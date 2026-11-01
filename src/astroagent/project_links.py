"""关联短事务、来源解析与失效；不调用模型、检索或外部科研服务。"""

from uuid import uuid4

from astroagent.conversation_schemas import Turn
from astroagent.conversations import encode, utc_now
from astroagent.errors import ServiceError
from astroagent.knowledge_schemas import EvidenceRecord, KnowledgeDocument
from astroagent.link_schemas import LinkRequestRecord, LinkTarget, ProjectLink
from astroagent.project_schemas import Snapshot
from astroagent.projects import ProjectRepository
from astroagent.workflow_schemas import WorkflowRun
from astroagent.workflow_templates import digest


def migrate(db):
    db.execute(
        "CREATE TABLE project_links (id TEXT PRIMARY KEY, project_id TEXT NOT NULL "
        "REFERENCES projects(id) ON DELETE CASCADE, target_type TEXT NOT NULL, "
        "target_id TEXT NOT NULL, evidence_id TEXT NOT NULL, record TEXT NOT NULL)"
    )
    db.execute(
        "CREATE INDEX project_link_target ON "
        "project_links(project_id,target_type,target_id,evidence_id,id)"
    )
    db.execute(
        "CREATE TABLE project_link_requests (id TEXT PRIMARY KEY, project_id TEXT NOT NULL "
        "REFERENCES projects(id) ON DELETE CASCADE, request_id TEXT NOT NULL, "
        "request_sha256 TEXT NOT NULL, record TEXT NOT NULL, UNIQUE(project_id,request_id))"
    )
    db.execute("PRAGMA user_version=5")


def invalidate(db, project_id, *, target_type=None, target_ids=(), document_id=None, reason):
    sql, values = "SELECT record FROM project_links WHERE project_id=?", [project_id]
    if document_id:
        sql += (
            " AND evidence_id IN (SELECT id FROM knowledge_evidence "
            "WHERE project_id=? AND document_id=?)"
        )
        values.extend([project_id, document_id])
    else:
        if not target_ids:
            return
        sql += " AND target_type=? AND target_id IN (" + ",".join("?" for _ in target_ids) + ")"
        values.extend([target_type, *target_ids])
    for row in db.execute(sql, values).fetchall():
        link = ProjectLink.model_validate_json(row[0])
        flag = "evidence_invalidated" if document_id else "target_invalidated"
        if getattr(link, flag):
            continue
        setattr(link, flag, True)
        link.state = "target_unavailable" if link.target_invalidated else "evidence_unavailable"
        link.invalidation_reason, link.updated_at = reason, utc_now()
        link.revision += 1
        db.execute(
            "UPDATE project_links SET record=? WHERE id=?", (link.model_dump_json(), link.id)
        )


def invalidate_conversation(db, project_id, conversation_id, reason):
    turn_ids = [
        r[0] for r in db.execute("SELECT id FROM turns WHERE conversation_id=?", (conversation_id,))
    ]
    invalidate(db, project_id, target_type="conversation_turn", target_ids=turn_ids, reason=reason)


def sources(response):
    values, seen = [], set()
    for field in ("results", "gaia_results", "literature_results"):
        for result in response.get(field, []):
            candidates = [result["source"]]
            if field == "literature_results":
                candidates += [p["source"] for p in result.get("papers", [])]
            for source in candidates:
                key = (source["name"], source["url"], source["retrieved_at"], result["status"])
                if key in seen:
                    continue
                seen.add(key)
                values.append(
                    {
                        "category": "ads_abstract"
                        if field == "literature_results"
                        else "database_measurement",
                        "provider": source["name"],
                        "url": source["url"],
                        "retrieved_at": source["retrieved_at"],
                        "status": result["status"],
                    }
                )
    if response.get("answer"):
        values.append(
            {
                "category": "saved_answer",
                "provider": "保存的回答或程序说明（不新增引用）",
                "url": None,
                "retrieved_at": None,
                "status": response["status"],
            }
        )
    return values


def workflow_fingerprint(run):
    return digest(
        {
            "template_id": run.template_id,
            "template_version": run.template_version,
            "parameters": run.parameters,
            "state": run.state,
            "steps": [
                {
                    "id": s.id,
                    "version": s.version,
                    "state": s.state,
                    "attempts": [
                        {
                            "input_sha256": a.input_sha256,
                            "output_sha256": a.output_sha256,
                            "state": a.state,
                            "query_status": a.query_status,
                            "export_status": a.export_status,
                        }
                        for a in s.attempts
                    ],
                }
                for s in run.steps
            ],
        }
    )


def turn_fingerprint(turn):
    return digest(
        {
            "response": turn.response.model_dump(mode="json") if turn.response else None,
            "execution_status": turn.execution_status,
            "received_at": turn.received_at,
        }
    )


class ProjectLinks:
    def __init__(self, conversations):
        self.conversations = conversations
        self.repo = conversations.repository
        self.projects = ProjectRepository(self.repo)

    @staticmethod
    def missing(kind, identifier, reason="来源结果不可用"):
        return LinkTarget(
            type=kind,
            id=identifier,
            label=reason,
            state="unavailable",
            available=False,
            provenance="unknown",
        )

    def target(self, db, project_id, kind, identifier, cache):
        key = ("project_target", project_id, kind, identifier)
        if key in cache:
            return cache[key]
        value = self.missing(kind, identifier)
        if kind == "conversation_turn":
            row = db.execute(
                "SELECT t.record,c.title FROM turns t JOIN project_conversations m "
                "ON m.conversation_id=t.conversation_id JOIN conversations c "
                "ON c.id=t.conversation_id WHERE t.id=? AND m.project_id=?",
                (identifier, project_id),
            ).fetchone()
            if row:
                turn = Turn.model_validate_json(row[0])
                provenance = (
                    "imported_unverified"
                    if db.execute(
                        "SELECT 1 FROM imported_turn_origins WHERE turn_id=?", (identifier,)
                    ).fetchone()
                    else "local"
                )
                value = LinkTarget(
                    type=kind,
                    id=identifier,
                    conversation_id=turn.conversation_id,
                    label=f"{row[1]} · 第{turn.revision}轮",
                    state=turn.execution_status,
                    response_status=turn.response.status if turn.response else None,
                    available=turn.response is not None and turn.execution_status != "running",
                    provenance=provenance,
                    created_at=turn.received_at,
                    revision=turn.revision,
                    fingerprint=turn_fingerprint(turn),
                    sources=sources(turn.response.model_dump(mode="json")) if turn.response else [],
                )
        elif kind == "snapshot":
            row = db.execute(
                "SELECT record FROM snapshots WHERE id=? AND project_id=?", (identifier, project_id)
            ).fetchone()
            if row:
                try:
                    snapshot = Snapshot.model_validate_json(row[0]).verify_digest()
                except ValueError:
                    value = self.missing(kind, identifier, "快照哈希或完整内容不符")
                else:
                    value = LinkTarget(
                        type=kind,
                        id=identifier,
                        label=snapshot.name,
                        state="saved",
                        response_status=snapshot.response.status,
                        available=True,
                        provenance=snapshot.provenance,
                        created_at=snapshot.created_at,
                        fingerprint=snapshot.sha256,
                        software=snapshot.software,
                        sources=sources(snapshot.response.model_dump(mode="json")),
                    )
        elif kind == "workflow_run":
            row = db.execute(
                "SELECT record FROM workflows WHERE id=? AND project_id=?", (identifier, project_id)
            ).fetchone()
            if row:
                run = WorkflowRun.model_validate_json(row[0])
                origin, seen = [], set()
                for step in run.steps:
                    for attempt in step.attempts:
                        output = attempt.output or {}
                        collected = (
                            sources(output["response"])
                            if "response" in output
                            else sources({"results": [output["result"]]})
                            if "result" in output
                            else []
                        )
                        for item in collected:
                            marker = encode(item)
                            if marker not in seen:
                                origin.append(item)
                                seen.add(marker)
                origin.append(
                    {
                        "category": "program_output",
                        "provider": "固定科研流程（无模型）",
                        "url": None,
                        "retrieved_at": run.updated_at,
                        "status": run.state,
                    }
                )
                value = LinkTarget(
                    type=kind,
                    id=identifier,
                    label=run.name,
                    state=run.state,
                    available=run.state in ("succeeded", "failed", "interrupted"),
                    provenance=run.provenance,
                    created_at=run.created_at,
                    revision=run.revision,
                    fingerprint=workflow_fingerprint(run),
                    template_version=f"{run.template_id}@{run.template_version}",
                    software=run.software,
                    sources=origin,
                )
        cache[key] = value
        return value

    def resolve(
        self, db, link, cache, *, present=True, latest_revision=None, include_evidence=True
    ):
        target = (
            self.missing(link.target_type, link.target_id, "结果已删除或会话已移出项目；不自动恢复")
            if link.target_invalidated
            else self.target(db, link.project_id, link.target_type, link.target_id, cache)
        )
        changed = target.fingerprint is not None and target.fingerprint != link.target_fingerprint
        if changed and link.target_type != "workflow_run":
            target = self.missing(link.target_type, link.target_id, "不可变结果与关联时的摘要不符")
        row = db.execute(
            "SELECT record FROM knowledge_evidence WHERE id=? AND project_id=?",
            (link.evidence_id, link.project_id),
        ).fetchone()
        view, valid = None, False
        if row and not link.evidence_invalidated:
            record = EvidenceRecord.model_validate_json(row[0])
            exact = (
                record.version_id == link.evidence_version_id
                and record.text_sha256 == link.evidence_text_sha256
                and record.document_sha256 == link.evidence_document_sha256
            )
            if exact:
                view = self.conversations.knowledge.view(db, record, cache)
                valid = view["evidence"].validity == "available"
        state = (
            "target_unavailable"
            if not target.available
            else "evidence_unavailable"
            if not valid
            else "active"
        )
        record = link.model_copy(update={"state": state})
        if not include_evidence:
            view = None
        return {
            "link": record,
            "present": present,
            "latest_revision": latest_revision
            if latest_revision is not None
            else link.revision
            if present
            else None,
            "target": target,
            "evidence": view,
            "target_changed_since_link": changed,
            "warning": "user_reference只表示用户建立的引用关系，不构成支持、反驳或科学证明。"
            + (
                "流程在关联后更新；请查看原尝试和当前状态。"
                if changed and link.target_type == "workflow_run"
                else ""
            )
            + ("此关联已解绑，以下仅为原请求记录。" if not present else ""),
        }

    def _link(self, db, project_id, identifier):
        self.projects._project(db, project_id)
        row = db.execute(
            "SELECT record FROM project_links WHERE id=? AND project_id=?", (identifier, project_id)
        ).fetchone()
        if not row:
            raise ServiceError(404, "project_link_not_found", "该项目没有此关联。")
        return ProjectLink.model_validate_json(row[0])

    def detail(self, project_id, identifier):
        with self.repo.connection() as db:
            db.execute("BEGIN")
            return self.resolve(db, self._link(db, project_id, identifier), {})

    def create(self, project_id, request):
        request_hash = digest({"project_id": project_id, **request.model_dump(mode="json")})
        with self.conversations.gate, self.repo.connection() as db, self.repo.transaction(db):
            self.projects._project(db, project_id)
            previous = db.execute(
                "SELECT request_sha256,record FROM project_link_requests "
                "WHERE project_id=? AND request_id=?",
                (project_id, request.client_request_id),
            ).fetchone()
            if previous:
                if previous[0] != request_hash:
                    raise ServiceError(
                        409, "project_link_request_conflict", "此请求编号已用于不同关联或参数。"
                    )
                history = LinkRequestRecord.model_validate_json(previous[1])
                current = db.execute(
                    "SELECT record FROM project_links WHERE id=? AND project_id=?",
                    (history.link_id, project_id),
                ).fetchone()
                latest = ProjectLink.model_validate_json(current[0]) if current else None
                response = (
                    history.response.model_copy(
                        update={
                            "target_invalidated": latest.target_invalidated,
                            "evidence_invalidated": latest.evidence_invalidated,
                            "invalidation_reason": latest.invalidation_reason,
                        }
                    )
                    if latest
                    else history.response
                )
                return {
                    "detail": self.resolve(
                        db,
                        response,
                        {},
                        present=bool(current),
                        latest_revision=latest.revision if latest else None,
                    ),
                    "replayed": True,
                    "duplicate": history.duplicate,
                }, 200
            self.projects._project(db, project_id, request.expected_revision)
            self.projects._idle(db, project_id)
            if not request.confirmed:
                raise ServiceError(
                    422,
                    "project_link_confirmation_required",
                    "请核对项目结果、原始证据与备注后确认建立关联。",
                )
            if (
                db.execute(
                    "SELECT count(*) FROM project_link_requests WHERE project_id=?", (project_id,)
                ).fetchone()[0]
                >= 3000
            ):
                raise ServiceError(
                    409,
                    "project_link_request_limit",
                    "项目关联操作记录已满（3000），请保留历史并整理项目。",
                )
            cache = {}
            target = self.target(db, project_id, request.target_type, request.target_id, cache)
            if target.provenance == "unknown":
                raise ServiceError(404, "project_link_target_not_found", "项目中不存在此结果。")
            if not target.available:
                raise ServiceError(
                    422, "project_link_target_unavailable", "该结果尚不可关联，请先核对执行状态。"
                )
            evidence_row = db.execute(
                "SELECT record FROM knowledge_evidence WHERE id=? AND project_id=?",
                (request.evidence_id, project_id),
            ).fetchone()
            if not evidence_row:
                raise ServiceError(404, "project_link_evidence_not_found", "项目中不存在此证据。")
            evidence = EvidenceRecord.model_validate_json(evidence_row[0])
            view = self.conversations.knowledge.view(db, evidence, cache)
            if view["evidence"].validity != "available":
                raise ServiceError(
                    422,
                    "project_link_evidence_unavailable",
                    "证据原文、固定版本或位置不可用，未创建关联。",
                )
            duplicate, link = False, None
            for row in db.execute(
                "SELECT record FROM project_links WHERE project_id=? AND target_type=? "
                "AND target_id=? AND evidence_id=? ORDER BY id",
                (project_id, request.target_type, request.target_id, request.evidence_id),
            ):
                candidate = ProjectLink.model_validate_json(row[0])
                if not candidate.target_invalidated and not candidate.evidence_invalidated:
                    if (
                        candidate.evidence_text_sha256 != evidence.text_sha256
                        or candidate.evidence_document_sha256 != evidence.document_sha256
                        or candidate.evidence_version_id != evidence.version_id
                    ):
                        raise ServiceError(
                            422,
                            "project_link_evidence_changed",
                            "历史关联的固定证据身份不符，不能静默替换。",
                        )
                    link, duplicate = candidate, True
                    break
            now = utc_now()
            if link is None:
                if (
                    db.execute(
                        "SELECT count(*) FROM project_links WHERE project_id=?", (project_id,)
                    ).fetchone()[0]
                    >= 1000
                ):
                    raise ServiceError(
                        409, "project_link_limit", "每项目最多1000个关联；不会自动清除旧数据。"
                    )
                link = ProjectLink(
                    id=str(uuid4()),
                    project_id=project_id,
                    target_type=request.target_type,
                    target_id=request.target_id,
                    target_conversation_id=target.conversation_id,
                    target_fingerprint=target.fingerprint,
                    target_revision_at_link=target.revision,
                    evidence_id=evidence.id,
                    evidence_version_id=evidence.version_id,
                    evidence_text_sha256=evidence.text_sha256,
                    evidence_document_sha256=evidence.document_sha256,
                    created_at=now,
                    updated_at=now,
                    revision=0,
                    note=request.note,
                )
                db.execute(
                    "INSERT INTO project_links VALUES (?,?,?,?,?,?)",
                    (
                        link.id,
                        project_id,
                        link.target_type,
                        link.target_id,
                        link.evidence_id,
                        link.model_dump_json(),
                    ),
                )
            history = LinkRequestRecord(
                id=str(uuid4()),
                project_id=project_id,
                client_request_id=request.client_request_id,
                request_sha256=request_hash,
                link_id=link.id,
                created_at=now,
                response=link,
                duplicate=duplicate,
            )
            db.execute(
                "INSERT INTO project_link_requests VALUES (?,?,?,?,?)",
                (
                    history.id,
                    project_id,
                    history.client_request_id,
                    request_hash,
                    history.model_dump_json(),
                ),
            )
            self.projects._touch(db, project_id)
            self.projects._budget(db)
            return {
                "detail": self.resolve(db, link, cache),
                "replayed": False,
                "duplicate": duplicate,
            }, 200 if duplicate else 201

    def change(self, project_id, identifier, request, *, remove=False):
        with self.conversations.gate, self.repo.connection() as db, self.repo.transaction(db):
            self.projects._project(db, project_id, request.expected_revision)
            self.projects._idle(db, project_id)
            link = self._link(db, project_id, identifier)
            if link.revision != request.expected_link_revision:
                raise ServiceError(
                    409, "project_link_revision_conflict", "关联已经更新，请刷新后再修改。"
                )
            if remove:
                if not request.confirmed:
                    raise ServiceError(
                        422,
                        "project_link_confirmation_required",
                        "请确认只解除关联，不删除两端原始数据。",
                    )
                db.execute("DELETE FROM project_links WHERE id=?", (link.id,))
            else:
                link.note, link.updated_at, link.revision = (
                    request.note,
                    utc_now(),
                    link.revision + 1,
                )
                db.execute(
                    "UPDATE project_links SET record=? WHERE id=?",
                    (link.model_dump_json(), link.id),
                )
            self.projects._touch(db, project_id)
            self.projects._budget(db)
            return self.resolve(db, link, {}) if not remove else None

    def _page(
        self, db, project_id, limit, after=None, target_type=None, target_id=None, evidence_id=None
    ):
        where, values = ["project_id=?"], [project_id]
        for column, value in (
            ("target_type", target_type),
            ("target_id", target_id),
            ("evidence_id", evidence_id),
        ):
            if value is not None:
                where.append(f"{column}=?")
                values.append(value)
        expression = " AND ".join(where)
        total = db.execute(
            "SELECT count(*) FROM project_links WHERE " + expression, values
        ).fetchone()[0]
        if after:
            expression += " AND id>?"
            values.append(after)
        rows = db.execute(
            "SELECT record FROM project_links WHERE " + expression + " ORDER BY id LIMIT ?",
            (*values, limit + 1),
        ).fetchall()
        cache, items = {}, []
        for row in rows[:limit]:
            items.append(
                self.resolve(
                    db, ProjectLink.model_validate_json(row[0]), cache, include_evidence=False
                )
            )
        return {
            "items": items,
            "total": total,
            "next_cursor": items[-1]["link"].id if len(rows) > limit and items else None,
            "limit": limit,
            "project_revision": self.projects._project(db, project_id)["revision"],
        }

    def page(self, project_id, limit, **filters):
        with self.repo.connection() as db:
            db.execute("BEGIN")
            self.projects._project(db, project_id)
            return self._page(db, project_id, limit, **filters)

    def overview(self, project_id):
        with self.repo.connection() as db:
            db.execute("BEGIN")
            project, cache = self.projects._project(db, project_id), {}
            conversations = []
            for row in db.execute(
                "SELECT c.id,c.title,c.updated_at FROM conversations c "
                "JOIN project_conversations m ON m.conversation_id=c.id "
                "WHERE m.project_id=? ORDER BY c.id",
                (project_id,),
            ):
                turns = [
                    self.target(db, project_id, "conversation_turn", turn[0], cache)
                    for turn in db.execute(
                        "SELECT id FROM turns WHERE conversation_id=? ORDER BY ordinal", (row[0],)
                    )
                ]
                conversations.append(
                    {"id": row[0], "title": row[1], "updated_at": row[2], "turns": turns}
                )
            snapshots = [
                self.target(db, project_id, "snapshot", row[0], cache)
                for row in db.execute(
                    "SELECT id FROM snapshots WHERE project_id=? ORDER BY id", (project_id,)
                )
            ]
            workflows = [
                self.target(db, project_id, "workflow_run", row[0], cache)
                for row in db.execute(
                    "SELECT id FROM workflows WHERE project_id=? ORDER BY id", (project_id,)
                )
            ]
            return {
                "project": project,
                "conversations": conversations,
                "snapshots": snapshots,
                "workflows": workflows,
                "documents": [
                    KnowledgeDocument.model_validate_json(row[0])
                    for row in db.execute(
                        "SELECT record FROM knowledge_documents WHERE project_id=? ORDER BY id",
                        (project_id,),
                    )
                ],
                "evidence_count": db.execute(
                    "SELECT count(*) FROM knowledge_evidence WHERE project_id=?", (project_id,)
                ).fetchone()[0],
                "link_count": db.execute(
                    "SELECT count(*) FROM project_links WHERE project_id=?", (project_id,)
                ).fetchone()[0],
                "link_request_count": db.execute(
                    "SELECT count(*) FROM project_link_requests WHERE project_id=?", (project_id,)
                ).fetchone()[0],
                "first_links": self._page(db, project_id, 25),
                "warning": (
                    "总览只读取保存的记录，不查询外部服务、不检索全文、不调用模型。"
                    "用户备注和手动关联不改写原回答或科研统计。"
                ),
            }
