"""PostgreSQL lexical candidates, with explicit short-CJK substring semantics."""

import time
from uuid import uuid4

from astroagent.conversations import utc_now
from astroagent.errors import ServiceError
from astroagent.knowledge_schemas import EvidenceRecord, TextUnit
from astroagent.knowledge_service import KnowledgeService
from astroagent.knowledge_text import HAN, MAX_TEXT_BYTES, checksum, matches, normalize, query_terms

INDEX_VERSION = "nfkc-pg-simple-cjk-substring-v1"


def candidates(db, project_id, query, document_ids=(), version_ids=(), limit=20):
    try:
        terms = query_terms(query)
    except ValueError as exc:
        raise ServiceError(422, "knowledge_query_invalid", str(exc)) from exc
    where = [
        "u.project_id=?",
        "(d.record::jsonb->>'state') IN ('ready','partial')",
        "(v.record::jsonb->>'indexed')='true'",
    ]
    values = [project_id]
    if version_ids:
        where.append("u.version_id IN (" + ",".join("?" for _ in version_ids) + ")")
        values.extend(version_ids)
    else:
        where.append("(d.record::jsonb->>'current_version_id')=u.version_id")
    if document_ids:
        where.append("u.document_id IN (" + ",".join("?" for _ in document_ids) + ")")
        values.extend(document_ids)
    for term in terms:
        if HAN.search(term):
            where.append("strpos(u.normalized,?)>0")
        else:
            where.append("to_tsvector('simple',u.normalized) @@ plainto_tsquery('simple',?)")
        values.append(term)
    base = (
        " FROM knowledge_units u JOIN knowledge_documents d ON d.id=u.document_id "
        "JOIN knowledge_versions v ON v.id=u.version_id WHERE " + " AND ".join(where)
    )
    size = db.execute(
        "SELECT coalesce(sum(octet_length(u.normalized)),0)" + base, values
    ).fetchone()[0]
    if size > MAX_TEXT_BYTES:
        raise ServiceError(
            422, "knowledge_query_too_broad", "候选文本超过20 MiB，请限定文档或增加关键词。"
        )
    rows = db.execute(
        "SELECT u.record,u.normalized" + base + " ORDER BY u.id LIMIT 50001", values
    ).fetchall()
    if len(rows) > 50000:
        raise ServiceError(422, "knowledge_query_too_broad", "候选段过多，请缩小范围。")
    deadline, found = time.monotonic() + 3, []
    for row in rows:
        if time.monotonic() > deadline:
            raise ServiceError(
                422, "knowledge_query_too_broad", "词法检索达到时间上限，请缩小范围。"
            )
        unit = TextUnit.model_validate_json(row[0])
        if (
            unit.text is not None
            and row[1] == normalize(unit.text)
            and checksum(unit.text) == unit.sha256
            and matches(row[1], terms)
        ):
            score = (100 if normalize(query) in row[1] else 0) + sum(
                min(row[1].count(term), 10) for term in terms
            )
            found.append((score, unit))
    found.sort(
        key=lambda item: (
            -item[0],
            item[1].document_id,
            item[1].version_id,
            item[1].source_position,
            item[1].char_start,
            item[1].id,
        )
    )
    return found[:limit], len(found), terms


def evidence_view(service, db, project_id, unit, query, cache, *, reuse=False):
    if reuse:
        rows = db.execute(
            "SELECT record FROM knowledge_evidence WHERE project_id=? AND document_id=?",
            (project_id, unit.document_id),
        )
        for row in rows:
            old = EvidenceRecord.model_validate_json(row[0])
            if old.unit_id == unit.id and old.text_sha256 == unit.sha256:
                view = service.view(db, old, cache)
                if view["evidence"].validity == "available":
                    return view
    count = db.execute(
        "SELECT count(*) FROM knowledge_evidence WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    if count >= 1000:
        raise ServiceError(409, "knowledge_evidence_limit", "项目最多保存1000条证据引用。")
    document = service.repository._document(db, project_id, unit.document_id)
    version, _ = service.repository._version(db, project_id, unit.document_id, unit.version_id)
    record = EvidenceRecord(
        id=str(uuid4()),
        project_id=project_id,
        document_id=document.id,
        version_id=version.id,
        unit_id=unit.id,
        document_sha256=version.sha256,
        text_sha256=unit.sha256,
        query=query,
        created_at=utc_now(),
        validity="available",
        filename=version.filename,
        title=document.metadata.title,
        page=unit.page,
        line_start=unit.line_start,
        line_end=unit.line_end,
        char_start=unit.char_start,
        char_end=unit.char_end,
        index_version=INDEX_VERSION,
    )
    view = service.view(db, record, cache)
    if view["evidence"].validity != "available":
        raise ServiceError(
            422, "knowledge_evidence_invalid", "固定原文或位置不符，未使用替代内容。"
        )
    db.execute(
        "INSERT INTO knowledge_evidence VALUES (?,?,?,?)",
        (record.id, project_id, document.id, record.model_dump_json()),
    )
    return view


class PostgresKnowledgeService(KnowledgeService):
    def search(self, project_id, request):
        repo = self.repository.repo
        with self.conversations.gate, repo.connection() as db, repo.transaction(db):
            self.repository.projects._project(db, project_id)
            for identifier in request.document_ids:
                self.repository._document(db, project_id, identifier)
            found, total, terms = candidates(
                db, project_id, request.query, request.document_ids, limit=request.limit
            )
            cache = {}
            hits = [
                evidence_view(self, db, project_id, unit, request.query, cache) for _, unit in found
            ]
            if hits:
                self.repository.projects._touch(db, project_id)
                self.repository.projects._budget(db)
            return {
                "status": "evidence_found" if hits else "insufficient_evidence",
                "answer": "找到以下相关原文。摘录与词法命中不证明科学结论。"
                if hits
                else "未找到满足全部关键词的可用原文；不凭模型记忆补答。",
                "project_id": project_id,
                "query": request.query,
                "terms": terms,
                "mode": "postgresql_simple_and_cjk_substring",
                "index_version": INDEX_VERSION,
                ("ranking"): (
                    "all_terms_required; exact_query:+100; oc"
                    "currences_capped_at_10; stable_location_"
                    "ties"
                ),
                "returned_count": len(hits),
                "matched_units": total,
                "truncated": total > len(hits),
                "searched_at": utc_now(),
                "hits": hits,
                "warnings": [
                    "仅检索当前版本；CJK按有界子串匹配，其他词用PostgreSQL simple后再核对词边界。",
                    "这不是旧SQLite FTS5算法的等价性或质量验证。",
                ],
            }
