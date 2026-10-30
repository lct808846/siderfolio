"""项目、不可变响应副本与短事务；不在数据库事务内访问外部服务。"""

import hashlib
import importlib.metadata
import json
from uuid import uuid4

from astroagent import __version__
from astroagent.conversation_schemas import Turn
from astroagent.conversations import encode, utc_now
from astroagent.errors import ServiceError
from astroagent.project_schemas import Project, Rerun, Snapshot
from astroagent.schemas import ErrorInfo


def software_versions():
    values = {"astroagent": __version__}
    for name in ("astroquery", "astropy", "numpy", "matplotlib"):
        try:
            values[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            values[name] = "unavailable"
    return values


def conflict(text="项目已更新，请刷新后重试。"):
    return ServiceError(409, "project_revision_conflict", text)


class ProjectRepository:
    def __init__(self, repository):
        self.repo = repository
        self.settings = repository.settings

    @staticmethod
    def _get(db, table, identifier, project_id=None):
        row = db.execute(f"SELECT record FROM {table} WHERE id=?", (identifier,)).fetchone()
        value = json.loads(row[0]) if row else None
        if value is None or (project_id is not None and value["project_id"] != project_id):
            raise ServiceError(404, "project_record_not_found", "项目或该项目中的记录不存在。")
        return value

    @staticmethod
    def _put(db, table, value):
        db.execute(f"UPDATE {table} SET record=? WHERE id=?", (encode(value), value["id"]))

    def _project(self, db, identifier, revision=None):
        value = self._get(db, "projects", identifier)
        if revision is not None and value["revision"] != revision:
            raise conflict()
        return value

    def _touch(self, db, identifier):
        value = self._project(db, identifier)
        value["revision"] += 1
        value["updated_at"] = utc_now()
        self._put(db, "projects", value)
        return value

    def _budget(self, db):
        if self.repo._used(db) > self.settings.storage_bytes:
            raise ServiceError(
                409, "project_storage_limit", "完整项目超出本地存储预算，未裁剪或覆盖历史。"
            )

    @staticmethod
    def _idle(db, project_id):
        if db.execute(
            "SELECT 1 FROM knowledge_operations WHERE project_id=? AND state='parsing'",
            (project_id,),
        ).fetchone():
            raise ServiceError(409, "project_busy", "项目正在解析文档，请先核对状态。")
        if db.execute(
            "SELECT 1 FROM workflows WHERE project_id=? AND state='running'", (project_id,)
        ).fetchone():
            raise ServiceError(409, "project_busy", "项目中有运行中的科研流程，请先读取其状态。")
        if db.execute(
            "SELECT 1 FROM reruns WHERE project_id=? AND state='running'", (project_id,)
        ).fetchone():
            raise ServiceError(409, "project_busy", "项目正在重跑查询，请等待完成或恢复状态。")
        if db.execute(
            """SELECT 1 FROM turns t JOIN project_conversations m
            ON t.conversation_id=m.conversation_id WHERE m.project_id=? AND t.state='running'""",
            (project_id,),
        ).fetchone():
            raise ServiceError(409, "project_busy", "项目中有运行中的会话，请稍后重试。")

    def list(self):
        with self.repo.connection() as db:
            values = [json.loads(r[0]) for r in db.execute("SELECT record FROM projects")]
            return sorted(values, key=lambda x: (x["updated_at"], x["id"]), reverse=True)

    def create(self, request):
        with self.repo.connection() as db, self.repo.transaction(db):
            if db.execute("SELECT count(*) FROM projects").fetchone()[0] >= 20:
                raise ServiceError(409, "project_limit", "最多保存20个项目。")
            value = Project(
                id=str(uuid4()),
                **request.model_dump(),
                revision=0,
                created_at=utc_now(),
                updated_at=utc_now(),
            ).model_dump()
            db.execute("INSERT INTO projects VALUES (?,?)", (value["id"], encode(value)))
            self._budget(db)
            return value

    def detail(self, identifier):
        with self.repo.connection() as db:
            # One read transaction across all related rows.
            db.execute("BEGIN")
            value = self._project(db, identifier)
            value["conversation_ids"] = [
                r[0]
                for r in db.execute(
                    "SELECT conversation_id FROM project_conversations "
                    "WHERE project_id=? ORDER BY conversation_id",
                    (identifier,),
                )
            ]
            value["snapshots"] = [
                self.summary(json.loads(r[0]))
                for r in db.execute(
                    "SELECT record FROM snapshots WHERE project_id=? ORDER BY rowid", (identifier,)
                )
            ]
            value["reruns"] = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT record FROM reruns WHERE project_id=? ORDER BY rowid", (identifier,)
                )
            ]
            value["workflow_count"] = db.execute(
                "SELECT count(*) FROM workflows WHERE project_id=?", (identifier,)
            ).fetchone()[0]
            value["document_count"] = db.execute(
                "SELECT count(*) FROM knowledge_documents WHERE project_id=?", (identifier,)
            ).fetchone()[0]
            value["document_version_count"] = db.execute(
                "SELECT count(*) FROM knowledge_versions WHERE project_id=?", (identifier,)
            ).fetchone()[0]
            value["document_bytes"] = db.execute(
                "SELECT coalesce(sum(length(content)),0) FROM "
                "knowledge_versions WHERE project_id=?",
                (identifier,),
            ).fetchone()[0]
            value["knowledge_evidence_count"] = db.execute(
                "SELECT count(*) FROM knowledge_evidence WHERE project_id=?", (identifier,)
            ).fetchone()[0]
            value["running_workflow_count"] = db.execute(
                "SELECT count(*) FROM workflows WHERE project_id=? AND state='running'",
                (identifier,),
            ).fetchone()[0]
            return value

    def update(self, identifier, request):
        with self.repo.connection() as db, self.repo.transaction(db):
            value = self._project(db, identifier, request.expected_revision)
            value.update(name=request.name, description=request.description)
            self._put(db, "projects", value)
            result = self._touch(db, identifier)
            self._budget(db)
            return result

    def delete(self, identifier, revision):
        with self.repo.connection() as db, self.repo.transaction(db):
            self._project(db, identifier, revision)
            self._idle(db, identifier)
            for row in db.execute(
                "SELECT conversation_id FROM project_conversations WHERE project_id=?",
                (identifier,),
            ):
                db.execute(
                    "UPDATE conversations SET metadata_revision=metadata_revision+1 WHERE id=?",
                    (row[0],),
                )
            db.execute("DELETE FROM workflows WHERE project_id=?", (identifier,))
            from astroagent.knowledge import clear_index

            clear_index(db, project_id=identifier)
            db.execute("DELETE FROM projects WHERE id=?", (identifier,))

    def membership(self, identifier, conversation_id, request, *, remove=False):
        with self.repo.connection() as db, self.repo.transaction(db):
            self._project(db, identifier, request.expected_revision)
            conversation = self.repo._conversation(db, conversation_id)
            self.repo._idle(db, conversation_id)
            if (
                conversation["revision"] != request.expected_conversation_revision
                or conversation["metadata_revision"] != request.expected_metadata_revision
            ):
                raise conflict("会话已更新，请刷新后移动。")
            row = db.execute(
                "SELECT project_id FROM project_conversations WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            source = row[0] if row else None
            if source != request.expected_source_project_id or (remove and source != identifier):
                raise conflict("会话归属已变化，请刷新。")
            if source and source != identifier:
                self._project(db, source, request.expected_source_revision)
                if request.expected_source_revision is None:
                    raise conflict("移动会话需要原项目修订号。")
            if source:
                self._idle(db, source)
            self._idle(db, identifier)
            db.execute(
                "DELETE FROM project_conversations WHERE conversation_id=?", (conversation_id,)
            )
            if not remove:
                if (
                    db.execute(
                        "SELECT count(*) FROM project_conversations WHERE project_id=?",
                        (identifier,),
                    ).fetchone()[0]
                    >= 20
                ):
                    raise ServiceError(409, "project_conversation_limit", "每个项目最多20个会话。")
                db.execute(
                    "INSERT INTO project_conversations VALUES (?,?)", (conversation_id, identifier)
                )
            db.execute(
                "UPDATE conversations SET metadata_revision=metadata_revision+1 WHERE id=?",
                (conversation_id,),
            )
            if source and source != identifier:
                self._touch(db, source)
            self._touch(db, identifier)
            self._budget(db)
        return self.detail(identifier)

    @staticmethod
    def summary(value):
        return {
            **{
                k: value[k]
                for k in ("id", "project_id", "name", "created_at", "sha256", "provenance")
            },
            "status": value["response"]["status"],
        }

    def snapshot(self, project_id, identifier):
        with self.repo.connection() as db:
            self._project(db, project_id)
            return self._get(db, "snapshots", identifier, project_id)

    @staticmethod
    def make_snapshot(project_id, name, turn, *, rerun_of=None):
        response = turn.response.model_dump(mode="json")
        value = Snapshot(
            id=str(uuid4()),
            project_id=project_id,
            name=name,
            conversation_id=turn.conversation_id,
            turn_id=turn.turn_id,
            origin={"conversation_id": turn.conversation_id, "turn_id": turn.turn_id},
            response=response,
            sha256=hashlib.sha256(encode(response).encode()).hexdigest(),
            created_at=utc_now(),
            software=software_versions(),
            provenance="local",
            rerun_of=rerun_of,
            rerun_origin_id=rerun_of,
        )
        return value.verify_digest().model_dump(mode="json")

    def _insert_snapshot(self, db, value):
        if (
            db.execute(
                "SELECT count(*) FROM snapshots WHERE project_id=?", (value["project_id"],)
            ).fetchone()[0]
            >= 100
        ):
            raise ServiceError(409, "snapshot_limit", "每个项目最多100个命名快照。")
        db.execute(
            "INSERT INTO snapshots VALUES (?,?,?)",
            (value["id"], value["project_id"], encode(value)),
        )

    def save_snapshot(self, identifier, request):
        with self.repo.connection() as db, self.repo.transaction(db):
            self._project(db, identifier, request.expected_revision)
            self._idle(db, identifier)
            row = db.execute(
                "SELECT project_id FROM project_conversations WHERE conversation_id=?",
                (request.conversation_id,),
            ).fetchone()
            if row is None or row[0] != identifier:
                raise ServiceError(404, "project_conversation_not_found", "该会话不属于此项目。")
            row = db.execute(
                "SELECT record FROM turns WHERE id=? AND conversation_id=?",
                (request.turn_id, request.conversation_id),
            ).fetchone()
            turn = Turn.model_validate_json(row[0]) if row else None
            if turn is None or turn.response is None:
                raise ServiceError(422, "snapshot_unavailable", "该轮没有可交付的完整响应。")
            value = self.make_snapshot(identifier, request.name, turn)
            imported = db.execute(
                "SELECT record FROM imported_turn_origins WHERE turn_id=?", (turn.turn_id,)
            ).fetchone()
            if imported:
                value["provenance"] = "imported_unverified"
                value["origin"] = json.loads(imported[0])
            self._insert_snapshot(db, value)
            self._touch(db, identifier)
            self._budget(db)
            return value

    def change_snapshot(self, project_id, identifier, revision, name=None):
        with self.repo.connection() as db, self.repo.transaction(db):
            self._project(db, project_id, revision)
            self._idle(db, project_id)
            value = self._get(db, "snapshots", identifier, project_id)
            if name is not None:
                value["name"] = name
                self._put(db, "snapshots", value)
            else:
                if db.execute(
                    "SELECT 1 FROM workflow_snapshot_refs WHERE snapshot_id=?", (identifier,)
                ).fetchone():
                    raise ServiceError(
                        409,
                        "snapshot_used_by_workflow",
                        "快照被科研流程引用；请先明确删除相关流程。",
                    )
                db.execute("DELETE FROM snapshots WHERE id=?", (identifier,))
                for row in db.execute(
                    "SELECT record FROM snapshots WHERE project_id=?", (project_id,)
                ).fetchall():
                    child = json.loads(row[0])
                    if child["rerun_of"] == identifier:
                        child["rerun_of"] = None
                        self._put(db, "snapshots", child)
                for row in db.execute(
                    "SELECT record FROM reruns WHERE project_id=?", (project_id,)
                ).fetchall():
                    r = json.loads(row[0])
                    for key in ("source_snapshot_id", "snapshot_id"):
                        if r[key] == identifier:
                            r[key] = None
                    self._put(db, "reruns", r)
            self._touch(db, project_id)
            self._budget(db)
            return value

    @staticmethod
    def detach_conversation(db, identifier):
        rows = db.execute(
            "SELECT project_id FROM project_conversations WHERE conversation_id=?", (identifier,)
        ).fetchall()
        for table in ("snapshots", "reruns"):
            for row in db.execute(f"SELECT record FROM {table}").fetchall():
                value = json.loads(row[0])
                if value["conversation_id"] == identifier:
                    value["conversation_id"] = value["turn_id"] = None
                    ProjectRepository._put(db, table, value)
        for row in rows:
            value = ProjectRepository._get(db, "projects", row[0])
            value["revision"] += 1
            value["updated_at"] = utc_now()
            ProjectRepository._put(db, "projects", value)

    def rerun(self, project_id, identifier):
        with self.repo.connection() as db:
            self._project(db, project_id)
            return self._get(db, "reruns", identifier, project_id)

    def existing_rerun(self, project_id, snapshot_id, request):
        digest = hashlib.sha256(
            encode({"snapshot_id": snapshot_id, **request.model_dump()}).encode()
        ).hexdigest()
        with self.repo.connection() as db:
            self._project(db, project_id)
            row = db.execute(
                "SELECT request_hash,record FROM reruns WHERE project_id=? AND request_id=?",
                (project_id, request.client_request_id),
            ).fetchone()
            if row and row[0] != digest:
                raise ServiceError(409, "request_id_conflict", "此请求编号已用于不同重跑条件。")
            return (json.loads(row[1]) if row else None), digest

    def reserve_rerun(self, project_id, snapshot_id, request, parameters, digest):
        with self.repo.connection() as db, self.repo.transaction(db):
            self._project(db, project_id, request.expected_revision)
            self._get(db, "snapshots", snapshot_id, project_id)
            self._idle(db, project_id)
            if (
                db.execute(
                    "SELECT count(*) FROM reruns WHERE project_id=?", (project_id,)
                ).fetchone()[0]
                >= 100
            ):
                raise ServiceError(409, "rerun_limit", "每项目最多100条重跑记录，请新建项目。")
            if (
                db.execute("SELECT count(*) FROM conversations").fetchone()[0]
                >= self.settings.max_conversations
            ):
                raise ServiceError(
                    409, "conversation_limit_reached", "会话已满，无法保存独立重跑轮次。"
                )
            if (
                db.execute(
                    "SELECT count(*) FROM snapshots WHERE project_id=?", (project_id,)
                ).fetchone()[0]
                >= 100
            ):
                raise ServiceError(409, "snapshot_limit", "快照已满，无法保存重跑结果。")
            conv_id, turn_id, rerun_id = str(uuid4()), str(uuid4()), str(uuid4())
            now = utc_now()
            db.execute(
                "INSERT INTO conversations VALUES (?,?,?,?,?,?)",
                (conv_id, "直接重跑 · " + request.family, now, now, 1, 0),
            )
            db.execute("INSERT INTO project_conversations VALUES (?,?)", (conv_id, project_id))
            turn = Turn(
                conversation_id=conv_id,
                turn_id=turn_id,
                revision=1,
                client_request_id=request.client_request_id,
                message="程序直接重跑（无模型调用）：" + encode(parameters),
                execution_status="running",
                received_at=now,
            )
            text = turn.model_dump_json()
            db.execute(
                "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    turn_id,
                    conv_id,
                    1,
                    request.client_request_id,
                    digest,
                    "running",
                    text,
                    len(text.encode()),
                    self.settings.turn_bytes + 32768,
                ),
            )
            record = Rerun(
                id=rerun_id,
                project_id=project_id,
                source_snapshot_id=snapshot_id,
                source_origin_id=snapshot_id,
                client_request_id=request.client_request_id,
                family=request.family,
                result_index=request.result_index,
                parameters=parameters,
                state="running",
                created_at=now,
                conversation_id=conv_id,
                turn_id=turn_id,
                software=software_versions(),
            ).model_dump()
            db.execute(
                "INSERT INTO reruns VALUES (?,?,?,?,?,?,?)",
                (
                    rerun_id,
                    project_id,
                    request.client_request_id,
                    digest,
                    "running",
                    encode(record),
                    self.settings.turn_bytes + 65536,
                ),
            )
            self._touch(db, project_id)
            self._budget(db)
            return record, turn

    def finish_rerun(self, record, turn):
        with self.repo.connection() as db, self.repo.transaction(db):
            value = None
            if len(turn.model_dump_json().encode()) > self.settings.turn_bytes:
                turn.response = None
                turn.execution_status = "failed"
                turn.error = ErrorInfo(
                    code="turn_result_too_large", message="完整重跑结果超出上限，未裁剪保存。"
                )
            if turn.response is not None:
                value = self.make_snapshot(
                    record["project_id"],
                    "重跑 · " + record["family"],
                    turn,
                    rerun_of=record["source_origin_id"],
                )
                self._insert_snapshot(db, value)
            self.repo._save(db, turn)
            record.update(
                state=turn.execution_status,
                response_status=turn.response.status if turn.response else None,
                completed_at=turn.completed_at,
                snapshot_id=value["id"] if value else None,
                error={"code": turn.error.code, "message": turn.error.message}
                if turn.error
                else None,
            )
            self._put(db, "reruns", record)
            db.execute(
                "UPDATE reruns SET state=?,reserved_bytes=0 WHERE id=?",
                (record["state"], record["id"]),
            )
            self._budget(db)
            return record

    @staticmethod
    def recover(db):
        for row in db.execute("SELECT record FROM reruns WHERE state='running'").fetchall():
            value = json.loads(row[0])
            value.update(
                state="interrupted",
                completed_at=utc_now(),
                error={"code": "rerun_interrupted", "message": "服务重启中断了重跑，未自动重放。"},
            )
            ProjectRepository._put(db, "reruns", value)
            db.execute(
                "UPDATE reruns SET state='interrupted',reserved_bytes=0 WHERE id=?", (value["id"],)
            )
