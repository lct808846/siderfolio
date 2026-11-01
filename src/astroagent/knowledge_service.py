"""本地文件处理、词法检索和摘录式回答；从不构造模型或外部工具。"""

import hashlib
import json
import sqlite3
import threading
import time
from uuid import uuid4

from astroagent.conversations import encode, utc_now
from astroagent.errors import ServiceError
from astroagent.knowledge import KnowledgeRepository, indexes_available
from astroagent.knowledge_parser import parse_document
from astroagent.knowledge_schemas import (
    DocumentVersion,
    EvidenceRecord,
    KnowledgeDocument,
    TextSource,
    TextUnit,
)
from astroagent.knowledge_text import (
    HAN,
    INDEX_VERSION,
    MAX_TEXT_BYTES,
    checksum,
    matches,
    normalize,
    query_terms,
)
from astroagent.schemas import ErrorInfo

PARSER_SLOT = threading.BoundedSemaphore(1)


def file_type(filename, data):
    if not data or len(data) > 20 * 1024**2:
        raise ServiceError(413, "knowledge_file_size", "文件必须非空且不超过20 MiB。")
    if (
        not filename
        or len(filename) > 200
        or any(c in filename for c in "\\/\x00\r\n")
        or any(ord(c) < 32 for c in filename)
    ):
        raise ServiceError(
            422, "knowledge_filename_invalid", "文件名无效；不能包含路径或控制字符。"
        )
    if filename.lower().endswith(".pdf") and data.startswith(b"%PDF-"):
        return "application/pdf"
    if filename.lower().endswith((".md", ".markdown")) and not data.startswith(b"%PDF-"):
        try:
            text = data.decode("utf-8-sig")
            if "\x00" in text:
                raise ValueError("Binary Markdown")
        except (UnicodeError, ValueError) as exc:
            raise ServiceError(
                422, "knowledge_markdown_invalid", "Markdown必须是UTF-8文本，允许UTF-8 BOM。"
            ) from exc
        return "text/markdown"
    raise ServiceError(
        415,
        "knowledge_media_unsupported",
        "仅支持具有PDF头的.pdf或UTF-8 .md/.markdown，不信任上传的媒体类型。",
    )


class KnowledgeService:
    def __init__(self, conversations):
        self.conversations = conversations
        self.repository = KnowledgeRepository(conversations.repository)

    def submit(
        self, project_id, options, *, filename=None, content=None, document_id=None, action=False
    ):
        media = None if action else file_type(filename, content)
        request_hash = checksum(
            encode(
                {
                    "kind": "reindex" if action else "upload",
                    "document_id": document_id,
                    "filename": filename,
                    "sha256": hashlib.sha256(content).hexdigest() if content is not None else None,
                    "options": options.model_dump(mode="json"),
                }
            )
        )
        repo, gate = self.repository, self.conversations.gate
        with gate:
            with repo.repo.connection() as db:
                existing = repo.existing(db, project_id, options.client_request_id, request_hash)
            if existing:
                return self.result(
                    existing
                ), 202 if existing.state == "parsing" else existing.http_status
            if not PARSER_SLOT.acquire(blocking=False):
                raise ServiceError(
                    503,
                    "knowledge_parser_busy",
                    "已有文档正在解析，请稍后使用原请求编号重试。",
                    retryable=True,
                )
            try:
                operation, needed, duplicate = repo.admit(
                    project_id, options, filename, media, content, request_hash, document_id, action
                )
            except Exception:
                PARSER_SLOT.release()
                raise
        if not needed:
            PARSER_SLOT.release()
            return self.result(operation, duplicate), 200
        product, error, status_code = None, None, 422
        try:
            version, data, saved = repo.extraction(
                project_id, operation.document_id, operation.version_id
            )
            product = saved if saved is not None else parse_document(data, version.media_type)
        except ServiceError as exc:
            error = exc.error
            status_code = exc.status_code
        except Exception:
            error = ErrorInfo(
                code="knowledge_extraction_failed",
                message="本地提取未完成，原文件保留；未执行自动重试。",
                retryable=True,
            )
        try:
            with gate:
                try:
                    operation = repo.finish(operation, product, error, status_code)
                except ServiceError as exc:
                    operation = repo.finish(operation, error=exc.error, status_code=exc.status_code)
        finally:
            PARSER_SLOT.release()
        return self.result(operation), operation.http_status

    def result(self, operation, duplicate=False):
        return {
            "operation": operation,
            "document": self.repository.detail(operation.project_id, operation.document_id),
            "duplicate": duplicate
            or bool(operation.message and operation.message.startswith("相同文件")),
        }

    def evidence_list(self, project_id):
        with self.repository.repo.connection() as db:
            self.repository.projects._project(db, project_id)
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT record FROM knowledge_evidence WHERE "
                    "project_id=? ORDER BY rowid DESC LIMIT 50",
                    (project_id,),
                )
            ]

    def evidence(self, project_id, evidence_id):
        with self.repository.repo.connection() as db:
            db.execute("BEGIN")
            self.repository.projects._project(db, project_id)
            row = db.execute(
                "SELECT record FROM knowledge_evidence WHERE id=? AND project_id=?",
                (evidence_id, project_id),
            ).fetchone()
            if not row:
                raise ServiceError(404, "knowledge_evidence_not_found", "该项目没有此引用。")
            return self.view(db, EvidenceRecord.model_validate_json(row[0]), {})

    @staticmethod
    def source_digest(source, cache):
        key = ("source_digest", source.version_id, source.position)
        if key not in cache:
            cache[key] = checksum(source.text)
        return cache[key]

    def view(self, db, evidence, cache):
        doc = db.execute(
            "SELECT record FROM knowledge_documents WHERE id=? AND project_id=?",
            (evidence.document_id, evidence.project_id),
        ).fetchone()
        version_key = (
            "evidence_version",
            evidence.project_id,
            evidence.document_id,
            evidence.version_id,
        )
        if version_key not in cache:
            cache[version_key] = db.execute(
                "SELECT record,content FROM knowledge_versions WHERE id=? AND document_id=?",
                (evidence.version_id, evidence.document_id),
            ).fetchone()
        version = cache[version_key]
        row = db.execute(
            "SELECT record FROM knowledge_units WHERE id=? AND version_id=? AND project_id=?",
            (evidence.unit_id, evidence.version_id, evidence.project_id),
        ).fetchone()
        text, path, url, historical = None, [], None, False
        validity = "deleted" if not doc else "original_unavailable"
        if doc and version:
            document = KnowledgeDocument.model_validate_json(doc[0])
            info = DocumentVersion.model_validate_json(version[0])
            historical = document.current_version_id != info.id
            if info.id not in cache:
                cache[info.id] = (
                    version[1] is not None
                    and len(version[1]) == info.bytes
                    and hashlib.sha256(version[1]).hexdigest() == info.sha256
                )
            if version[1] is not None and not cache[info.id]:
                validity = "corrupt"
            elif cache[info.id] and info.sha256 == evidence.document_sha256:
                url = (
                    f"/api/v1/projects/{evidence.project_id}/documents/"
                    f"{document.id}/versions/{info.id}/content"
                )
                if row:
                    unit = TextUnit.model_validate_json(row[0])
                    source = db.execute(
                        "SELECT record FROM knowledge_sources WHERE version_id=? AND position=?",
                        (info.id, unit.source_position),
                    ).fetchone()
                    original = TextSource.model_validate_json(source[0]) if source else None
                    if unit.text is not None and original is not None and original.text is not None:
                        if (
                            unit.sha256 == evidence.text_sha256 == checksum(unit.text)
                            and self.source_digest(original, cache) == original.sha256
                            and original.text[unit.char_start : unit.char_end] == unit.text
                            and unit.char_start == evidence.char_start
                            and unit.char_end == evidence.char_end
                            and unit.page == evidence.page
                            and unit.line_start == evidence.line_start
                            and unit.line_end == evidence.line_end
                        ):
                            validity, text, path = "available", unit.text, unit.heading_path
                        else:
                            validity = "corrupt"
        evidence = evidence.model_copy(update={"validity": validity})
        warning = {
            "available": (
                "用户文档提取原文；关键词命中不代表支持问题中的命题，PDF复杂排版可能缺漏。"
            ),
            "deleted": "原文已删除；仅保留最小定位元数据与哈希，不能恢复原文。",
            "original_unavailable": (
                "缺少原文或可核对的提取内容；需重新提供同哈希文件，不展示新版本冒充旧证据。"
            ),
            "corrupt": "原文、位置或摘要不一致，引用失效。",
        }[validity]
        return {
            "evidence": evidence,
            "text": text,
            "heading_path": path,
            "historical_version": historical,
            "content_url": url,
            "warning": warning,
        }

    def search(self, project_id, request):
        try:
            terms = query_terms(request.query)
        except ValueError as exc:
            raise ServiceError(422, "knowledge_query_invalid", str(exc)) from exc
        short = any(HAN.search(term) and len(term) < 3 for term in terms)
        with (
            self.conversations.gate,
            self.repository.repo.connection() as db,
            self.repository.repo.transaction(db),
        ):
            self.repository.projects._project(db, project_id)
            if not indexes_available(db):
                raise ServiceError(
                    503,
                    "knowledge_index_unavailable",
                    "当前SQLite缺少可用FTS5/trigram索引；旧项目和聊天不受影响。",
                )
            where = [
                "u.project_id=?",
                "json_extract(d.record,'$.current_version_id')=u.version_id",
                "json_extract(d.record,'$.state') IN ('ready','partial')",
                "json_extract(v.record,'$.indexed')=1",
            ]
            # Documents use their authoritative current version from JSON, never old versions.
            params = [project_id]
            if request.document_ids:
                where.append(
                    "u.document_id IN (" + ",".join("?" for _ in request.document_ids) + ")"
                )
                params.extend(request.document_ids)
                for doc_id in request.document_ids:
                    self.repository._document(db, project_id, doc_id)
            for term in terms:
                if HAN.search(term) and len(term) < 3:
                    continue
                table = "knowledge_trigrams" if HAN.search(term) else "knowledge_words"
                where.append(
                    f"u.id IN (SELECT unit_id FROM {table} WHERE {table} MATCH ? AND project_id=?)"
                )
                params.extend(['"' + term.replace('"', '""') + '"', project_id])
            base = (
                " FROM knowledge_units u JOIN knowledge_documents d ON d.id=u.document_id JOIN "
                "knowledge_versions v ON v.id=u.version_id WHERE " + " AND ".join(where)
            )
            deadline = time.monotonic() + 3
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            try:
                scan_bytes = db.execute(
                    "SELECT coalesce(sum(length(cast(u.normalized AS BLOB))),0)" + base, params
                ).fetchone()[0]
                if scan_bytes > MAX_TEXT_BYTES:
                    raise ServiceError(
                        422,
                        "knowledge_query_too_broad",
                        "候选文本超过20 MiB，请增加关键词或限定文档。",
                    )
                rows = db.execute(
                    "SELECT u.record,u.normalized" + base + " ORDER BY u.id LIMIT ?",
                    (*params, 50001 if short else 2001),
                ).fetchall()
            except sqlite3.Error as exc:
                raise ServiceError(
                    422, "knowledge_query_too_broad", "检索达到资源边界，请缩小关键词或文档范围。"
                ) from exc
            finally:
                db.set_progress_handler(None, 0)
            if len(rows) > (50000 if short else 2000):
                raise ServiceError(
                    422, "knowledge_query_too_broad", "候选段过多，请增加关键词或限定文档。"
                )
            found = []
            for row in rows:
                if time.monotonic() > deadline:
                    raise ServiceError(
                        422, "knowledge_query_too_broad", "检索达到时间边界，请缩小范围。"
                    )
                unit = TextUnit.model_validate_json(row[0])
                if (
                    unit.text is not None
                    and row[1] == normalize(unit.text)
                    and unit.sha256 == checksum(unit.text)
                    and matches(row[1], terms)
                ):
                    score = (100 if normalize(request.query) in row[1] else 0) + sum(
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
            selected = found[: request.limit]
            count = db.execute(
                "SELECT count(*) FROM knowledge_evidence WHERE project_id=?", (project_id,)
            ).fetchone()[0]
            if count + len(selected) > 1000:
                raise ServiceError(
                    409,
                    "knowledge_evidence_limit",
                    "项目最多保存1000条证据引用，请新建项目继续整理。",
                )
            hits, cache = [], {}
            for _, unit in selected:
                document = self.repository._document(db, project_id, unit.document_id)
                version, _ = self.repository._version(
                    db, project_id, unit.document_id, unit.version_id
                )
                record = EvidenceRecord(
                    id=str(uuid4()),
                    project_id=project_id,
                    document_id=document.id,
                    version_id=version.id,
                    unit_id=unit.id,
                    document_sha256=version.sha256,
                    text_sha256=unit.sha256,
                    query=request.query,
                    created_at=utc_now(),
                    validity="available",
                    filename=version.filename,
                    title=document.metadata.title,
                    page=unit.page,
                    line_start=unit.line_start,
                    line_end=unit.line_end,
                    char_start=unit.char_start,
                    char_end=unit.char_end,
                )
                view = self.view(db, record, cache)
                if view["evidence"].validity != "available":
                    raise ServiceError(
                        422, "knowledge_evidence_invalid", "命中原文已失效；没有以其他文本代替。"
                    )
                db.execute(
                    "INSERT INTO knowledge_evidence VALUES (?,?,?,?)",
                    (record.id, project_id, document.id, record.model_dump_json()),
                )
                hits.append(view)
            if hits:
                self.repository.projects._touch(db, project_id)
                self.repository.projects._budget(db)
            unavailable = db.execute(
                "SELECT count(*) FROM knowledge_documents WHERE project_id=? AND "
                "json_extract(record,'$.state') NOT IN ('ready')",
                (project_id,),
            ).fetchone()[0]
            return {
                "status": "evidence_found" if hits else "insufficient_evidence",
                "answer": "找到以下相关原文。这里只提供摘录和位置，不据关键词命中推断科学结论。"
                if hits
                else "未找到满足这些关键词的可用原文证据。请"
                "修改关键词或补充文档；不凭模型记忆补答。",
                "project_id": project_id,
                "query": request.query,
                "terms": terms,
                "mode": "fts5_and_bounded_short_cjk_scan" if short else "fts5_lexical",
                "index_version": INDEX_VERSION,
                "ranking": (
                    "all_terms_required; exact_normalized_query:+100; "
                    "term_occurrences_capped_at_10; ties:document/version/position"
                ),
                "returned_count": len(hits),
                "matched_units": len(found),
                "truncated": len(found) > len(hits),
                "searched_at": utc_now(),
                "hits": hits,
                "warnings": [
                    "仅检索当前版本的实际提取文本；不支持同义词、跨语言语义或图片。",
                    f"{unavailable}份文档存在解析/索引缺口或尚未就绪；旧版本不参与新检索。",
                ],
            }
