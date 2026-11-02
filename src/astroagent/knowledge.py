"""项目文献短事务与证据关系；解析器始终在事务外运行。"""

import hashlib
import json
import sqlite3
from uuid import uuid4

from astroagent.conversations import encode, utc_now
from astroagent.errors import ServiceError
from astroagent.knowledge_schemas import (
    DocumentVersion,
    EvidenceRecord,
    KnowledgeDocument,
    KnowledgeOperation,
    TextSource,
    TextUnit,
)
from astroagent.knowledge_text import MAX_TEXT_BYTES, checksum, normalize, segment
from astroagent.projects import ProjectRepository

FTS_TABLES = ("knowledge_words", "knowledge_trigrams")


def create_indexes(db):
    if getattr(db, "dialect", None) == "postgresql":
        db.execute(
            "CREATE INDEX IF NOT EXISTS knowledge_lex"
            "ical ON knowledge_units USING gin (to_ts"
            "vector('simple',normalized))"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS knowledge_sub"
            "string ON knowledge_units USING gin (nor"
            "malized gin_trgm_ops)"
        )
        db.execute(
            "INSERT INTO knowledge_meta (key,value) V"
            "ALUES ('fts_available','1') ON CONFLICT "
            "(key) DO UPDATE SET value='1'"
        )
        return True
    db.execute("SAVEPOINT knowledge_fts")
    try:
        db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_words USING "
            "fts5(unit_id UNINDEXED, project_id UNINDEXED, text, "
            "tokenize='unicode61 remove_diacritics 0')"
        )
        db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_trigrams USING "
            "fts5(unit_id UNINDEXED, project_id UNINDEXED, text, tokenize='trigram')"
        )
        db.execute("RELEASE knowledge_fts")
        available = "1"
    except sqlite3.Error:
        db.execute("ROLLBACK TO knowledge_fts")
        db.execute("RELEASE knowledge_fts")
        available = "0"
    db.execute("INSERT OR REPLACE INTO knowledge_meta VALUES ('fts_available',?)", (available,))
    return available == "1"


def indexes_available(db):
    return (
        db.execute("SELECT value FROM knowledge_meta WHERE key='fts_available'").fetchone()[0]
        == "1"
    )


def migrate(db):
    db.execute("CREATE TABLE knowledge_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute(
        "CREATE TABLE knowledge_documents (id TEXT PRIMARY KEY, project_id TEXT NOT NULL "
        "REFERENCES projects(id) ON DELETE CASCADE, record TEXT NOT NULL)"
    )
    db.execute("CREATE INDEX knowledge_project ON knowledge_documents(project_id)")
    db.execute(
        "CREATE TABLE knowledge_versions (id TEXT PRIMARY KEY, document_id TEXT NOT NULL "
        "REFERENCES knowledge_documents(id) ON DELETE CASCADE, project_id TEXT NOT NULL "
        "REFERENCES projects(id) ON DELETE CASCADE, record TEXT NOT NULL, content BLOB)"
    )
    db.execute(
        "CREATE TABLE knowledge_sources (version_id TEXT NOT NULL REFERENCES "
        "knowledge_versions(id) ON DELETE CASCADE, position INTEGER NOT NULL, "
        "record TEXT NOT NULL, PRIMARY KEY(version_id,position))"
    )
    db.execute(
        "CREATE TABLE knowledge_units (id TEXT PRIMARY KEY, version_id TEXT NOT NULL "
        "REFERENCES knowledge_versions(id) ON DELETE CASCADE, document_id TEXT NOT NULL, "
        "project_id TEXT NOT NULL, record TEXT NOT NULL, normalized TEXT NOT NULL)"
    )
    db.execute("CREATE INDEX knowledge_unit_version ON knowledge_units(version_id)")
    db.execute("CREATE INDEX knowledge_unit_project ON knowledge_units(project_id)")
    db.execute(
        "CREATE TABLE knowledge_evidence (id TEXT PRIMARY KEY, project_id TEXT NOT NULL "
        "REFERENCES projects(id) ON DELETE CASCADE, document_id TEXT "
        "NOT NULL, record TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE knowledge_operations (id TEXT PRIMARY KEY, project_id TEXT NOT NULL "
        "REFERENCES projects(id) ON DELETE CASCADE, request_id TEXT NOT "
        "NULL, request_hash TEXT NOT NULL, "
        "state TEXT NOT NULL, record TEXT NOT NULL, reserved_bytes INTEGER NOT NULL DEFAULT 0, "
        "UNIQUE(project_id, request_id))"
    )
    create_indexes(db)
    db.execute("PRAGMA user_version=4")


def used_bytes(db):
    size = 0
    for table in (
        "knowledge_documents",
        "knowledge_versions",
        "knowledge_sources",
        "knowledge_units",
        "knowledge_evidence",
        "knowledge_operations",
    ):
        size += db.execute(
            f"SELECT coalesce(sum(length(cast(record AS BLOB))),0) FROM {table}"
        ).fetchone()[0]
    size += db.execute(
        "SELECT coalesce(sum(length(content)),0) FROM knowledge_versions"
    ).fetchone()[0]
    size += db.execute(
        "SELECT coalesce(sum(length(cast(normalized AS BLOB))),0) FROM knowledge_units"
    ).fetchone()[0]
    size += db.execute(
        "SELECT coalesce(sum(reserved_bytes),0) FROM knowledge_operations"
    ).fetchone()[0]
    # FTS5's own persisted payloads, including the two normalized content copies.
    if getattr(db, "dialect", None) == "postgresql":
        size += db.execute(
            "SELECT pg_relation_size('knowledge_lexical')+pg_relation_size('knowledge_substring')"
        ).fetchone()[0]
    if indexes_available(db) and getattr(db, "dialect", None) != "postgresql":
        for name in FTS_TABLES:
            for suffix, columns in (
                ("data", ("block",)),
                ("idx", ("term",)),
                ("content", ("c0", "c1", "c2")),
                ("docsize", ("sz",)),
                ("config", ("k", "v")),
            ):
                expression = "+".join(f"length(cast({column} AS BLOB))" for column in columns)
                size += db.execute(
                    f"SELECT coalesce(sum({expression}),0) FROM {name}_{suffix}"
                ).fetchone()[0]
    return size


def clear_index(db, *, document_id=None, project_id=None):
    if getattr(db, "dialect", None) == "postgresql":
        if document_id:
            db.execute("DELETE FROM rag_vectors WHERE document_id=?", (document_id,))
            db.execute(
                (
                    "UPDATE rag_indexes SET state='stale',rec"
                    "ord=jsonb_set(record::jsonb,'{state}','\""
                    "stale\"')::text WHERE project_id IN (SELE"
                    "CT project_id FROM knowledge_documents W"
                    "HERE id=?) AND state='ready'"
                ),
                (document_id,),
            )
            db.execute(
                (
                    "DELETE FROM rag_previews WHERE project_i"
                    "d IN (SELECT project_id FROM knowledge_d"
                    "ocuments WHERE id=?)"
                ),
                (document_id,),
            )
        else:
            db.execute("DELETE FROM rag_vectors WHERE project_id=?", (project_id,))
            db.execute(
                (
                    "UPDATE rag_indexes SET state='stale',rec"
                    "ord=jsonb_set(record::jsonb,'{state}','\""
                    "stale\"')::text WHERE project_id=? AND st"
                    "ate='ready'"
                ),
                (project_id,),
            )
            db.execute("DELETE FROM rag_previews WHERE project_id=?", (project_id,))
        return
    if not indexes_available(db):
        return
    for table in FTS_TABLES:
        if document_id:
            db.execute(
                f"DELETE FROM {table} WHERE unit_id IN "
                "(SELECT id FROM knowledge_units WHERE document_id=?)",
                (document_id,),
            )
        else:
            db.execute(f"DELETE FROM {table} WHERE project_id=?", (project_id,))


class KnowledgeRepository:
    def __init__(self, repository):
        self.repo = repository
        self.projects = ProjectRepository(repository)

    @staticmethod
    def _put(db, table, model):
        db.execute(f"UPDATE {table} SET record=? WHERE id=?", (model.model_dump_json(), model.id))

    def _document(self, db, project_id, document_id):
        self.projects._project(db, project_id)
        row = db.execute(
            "SELECT record FROM knowledge_documents WHERE id=? AND project_id=?",
            (document_id, project_id),
        ).fetchone()
        if not row:
            raise ServiceError(404, "knowledge_document_not_found", "该项目没有此文档。")
        return KnowledgeDocument.model_validate_json(row[0])

    def _version(self, db, project_id, document_id, version_id):
        self._document(db, project_id, document_id)
        row = db.execute(
            "SELECT record,content FROM knowledge_versions WHERE id=? "
            "AND document_id=? AND project_id=?",
            (version_id, document_id, project_id),
        ).fetchone()
        if not row:
            raise ServiceError(404, "knowledge_version_not_found", "该文档没有此版本。")
        return DocumentVersion.model_validate_json(row[0]), row[1]

    def list(self, project_id):
        with self.repo.connection() as db:
            self.projects._project(db, project_id)
            return [
                KnowledgeDocument.model_validate_json(r[0])
                for r in db.execute(
                    "SELECT record FROM knowledge_documents WHERE project_id=? ORDER BY id",
                    (project_id,),
                )
            ]

    def detail(self, project_id, document_id):
        with self.repo.connection() as db:
            db.execute("BEGIN")
            document = self._document(db, project_id, document_id)
            value = document.model_dump(mode="json")
            value["versions"] = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT record FROM knowledge_versions WHERE document_id=? ORDER BY rowid",
                    (document_id,),
                )
            ]
            value["project_revision"] = self.projects._project(db, project_id)["revision"]
            return value

    def content(self, project_id, document_id, version_id):
        with self.repo.connection() as db:
            version, content = self._version(db, project_id, document_id, version_id)
            if content is None:
                raise ServiceError(
                    404,
                    "knowledge_original_unavailable",
                    "归档未包含原文或原文已删除；不能伪造空文件。",
                )
            if (
                len(content) != version.bytes
                or hashlib.sha256(content).hexdigest() != version.sha256
            ):
                raise ServiceError(
                    422, "knowledge_content_corrupt", "原文件哈希不一致，未交付内容。"
                )
            return version, content

    def existing(self, db, project_id, request_id, request_hash):
        self.projects._project(db, project_id)
        row = db.execute(
            "SELECT request_hash,record FROM knowledge_operations WHERE "
            "project_id=? AND request_id=?",
            (project_id, request_id),
        ).fetchone()
        if row and row[0] != request_hash:
            raise ServiceError(
                409, "knowledge_request_conflict", "此请求编号已用于另一份文件或参数。"
            )
        return KnowledgeOperation.model_validate_json(row[1]) if row else None

    def admit(
        self,
        project_id,
        options,
        filename,
        media,
        content,
        request_hash,
        document_id=None,
        action=False,
    ):
        with self.repo.connection() as db, self.repo.transaction(db):
            existing = self.existing(db, project_id, options.client_request_id, request_hash)
            if existing:
                return existing, False, False
            self.projects._project(db, project_id, options.expected_revision)
            self.projects._idle(db, project_id)
            if (
                db.execute(
                    "SELECT count(*) FROM knowledge_operations WHERE project_id=?", (project_id,)
                ).fetchone()[0]
                >= 500
            ):
                raise ServiceError(
                    409, "knowledge_operation_limit", "项目已保存500次文档操作，请整理项目后重试。"
                )
            now, duplicate = utc_now(), False
            document = self._document(db, project_id, document_id) if document_id else None
            restore_id = (
                (options.version_id or document.current_version_id)
                if action
                else options.restore_version_id
            )
            if restore_id:
                if document is None:
                    raise ServiceError(
                        422, "knowledge_invalid_restore", "恢复版本必须属于已有文档。"
                    )
                version, stored = self._version(db, project_id, document_id, restore_id)
                if action:
                    if not options.confirmed:
                        raise ServiceError(
                            422, "knowledge_confirmation_required", "请确认重建或恢复此版本的索引。"
                        )
                    if stored is None:
                        raise ServiceError(
                            422,
                            "knowledge_original_unavailable",
                            "需要先重新提供相同SHA-256原文件。",
                        )
                    content = stored
                elif (
                    hashlib.sha256(content).hexdigest() != version.sha256
                    or len(content) != version.bytes
                ):
                    raise ServiceError(
                        422,
                        "knowledge_restore_hash_mismatch",
                        "恢复文件与原始版本哈希不同，请作为新版本上传。",
                    )
                version.content_available = True
            else:
                digest = hashlib.sha256(content).hexdigest()
                if not options.allow_duplicate:
                    for row in db.execute(
                        "SELECT record FROM knowledge_versions WHERE project_id=?", (project_id,)
                    ):
                        candidate = DocumentVersion.model_validate_json(row[0])
                        if (
                            candidate.sha256 == digest
                            and candidate.content_available
                            and (document is None or candidate.document_id == document.id)
                        ):
                            version = candidate
                            document = self._document(db, project_id, candidate.document_id)
                            duplicate = True
                            break
                if not duplicate:
                    if not document:
                        if (
                            db.execute(
                                "SELECT count(*) FROM knowledge_documents WHERE project_id=?",
                                (project_id,),
                            ).fetchone()[0]
                            >= 100
                        ):
                            raise ServiceError(
                                409, "knowledge_document_limit", "每项目最多100份文档。"
                            )
                        doc_id, version_id = str(uuid4()), str(uuid4())
                        document = KnowledgeDocument(
                            id=doc_id,
                            project_id=project_id,
                            filename=filename,
                            metadata=options.metadata,
                            current_version_id=version_id,
                            state="parsing",
                            created_at=now,
                            updated_at=now,
                        )
                        db.execute(
                            "INSERT INTO knowledge_documents VALUES (?,?,?)",
                            (doc_id, project_id, document.model_dump_json()),
                        )
                    else:
                        version_id = str(uuid4())
                    if (
                        db.execute(
                            "SELECT count(*) FROM knowledge_versions WHERE project_id=?",
                            (project_id,),
                        ).fetchone()[0]
                        >= 200
                    ):
                        raise ServiceError(
                            409, "knowledge_version_limit", "每项目最多200个文件版本。"
                        )
                    version = DocumentVersion(
                        id=version_id,
                        project_id=project_id,
                        document_id=document.id,
                        filename=filename,
                        media_type=media,
                        sha256=digest,
                        bytes=len(content),
                        state="parsing",
                        content_available=True,
                        created_at=now,
                    )
                    db.execute(
                        "INSERT INTO knowledge_versions VALUES (?,?,?,?,?)",
                        (version.id, document.id, project_id, version.model_dump_json(), content),
                    )
            if not duplicate:
                clear_index(db, document_id=document.id)
                version.state, version.indexed, version.error = "parsing", False, None
                db.execute(
                    "UPDATE knowledge_versions SET record=?,content=? WHERE id=?",
                    (version.model_dump_json(), content, version.id),
                )
                document.current_version_id, document.filename = version.id, version.filename
                document.state, document.updated_at = "parsing", now
                self._put(db, "knowledge_documents", document)
            operation = KnowledgeOperation(
                id=str(uuid4()),
                project_id=project_id,
                document_id=document.id,
                version_id=version.id,
                client_request_id=options.client_request_id,
                state="completed" if duplicate else "parsing",
                created_at=now,
                completed_at=now if duplicate else None,
                message="相同文件已存在；未创建版本或再次解析。" if duplicate else None,
                http_status=200 if duplicate or action or document_id else 201,
            )
            reserve = 0 if duplicate else min(64 * 1024**2, max(8 * 1024**2, len(content) * 4))
            db.execute(
                "INSERT INTO knowledge_operations VALUES (?,?,?,?,?,?,?)",
                (
                    operation.id,
                    project_id,
                    operation.client_request_id,
                    request_hash,
                    operation.state,
                    operation.model_dump_json(),
                    reserve,
                ),
            )
            self.projects._touch(db, project_id)
            self.projects._budget(db)
            return operation, not duplicate, duplicate

    def extraction(self, project_id, document_id, version_id):
        with self.repo.connection() as db:
            version, content = self._version(db, project_id, document_id, version_id)
            if (
                content is None
                or len(content) != version.bytes
                or hashlib.sha256(content).hexdigest() != version.sha256
            ):
                raise ServiceError(422, "knowledge_content_corrupt", "原文件缺失或哈希不符。")
            sources = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT record FROM knowledge_sources WHERE version_id=? ORDER BY position",
                    (version_id,),
                )
            ]
            if sources and all(s["text"] is not None for s in sources):
                return (
                    version,
                    content,
                    {
                        "sources": sources,
                        "extractor": version.extractor,
                        "page_count": version.page_count,
                        "line_count": version.line_count,
                        "warnings": version.warnings,
                    },
                )
            return version, content, None

    def finish(self, operation, product=None, error=None, status_code=422):
        with self.repo.connection() as db, self.repo.transaction(db):
            document = self._document(db, operation.project_id, operation.document_id)
            version, _ = self._version(
                db, operation.project_id, operation.document_id, operation.version_id
            )
            if error:
                version.state, version.indexed = "failed", False
                version.error = {"code": error.code, "message": error.message}
                operation.state, operation.message = "failed", error.message
                operation.http_status = status_code
            else:
                sources = [
                    TextSource.model_validate({**s, "version_id": version.id}).model_dump(
                        mode="json"
                    )
                    for s in product["sources"]
                ]
                size = sum(len((s["text"] or "").encode("utf-8")) for s in sources)
                if (
                    size > MAX_TEXT_BYTES
                    or len(sources) > 500
                    or any(s["sha256"] != checksum(s["text"] or "") for s in sources)
                ):
                    raise ServiceError(
                        422, "knowledge_extraction_invalid", "提取内容超限或摘要不符。"
                    )
                signature = checksum(
                    encode(
                        [
                            {
                                key: s[key]
                                for key in ("position", "page", "state", "sha256", "error")
                            }
                            for s in sources
                        ]
                    )
                )
                if version.extraction_sha256 and signature != version.extraction_sha256:
                    raise ServiceError(
                        422,
                        "knowledge_extractor_changed",
                        "重新提取结果与历史不同，旧引用未重定向；请新建版本。",
                    )
                units = segment(sources, version.id, document.project_id, document.id)
                previous_units = [
                    json.loads(row[0])
                    for row in db.execute(
                        "SELECT record FROM knowledge_units WHERE version_id=? ORDER BY "
                        "json_extract(record,'$.ordinal')",
                        (version.id,),
                    )
                ]
                location_keys = (
                    "source_position",
                    "ordinal",
                    "char_start",
                    "char_end",
                    "sha256",
                    "page",
                    "line_start",
                    "line_end",
                    "heading_path",
                )
                if previous_units and [
                    {k: u[k] for k in location_keys} for u in previous_units
                ] != [{k: u[k] for k in location_keys} for u in units]:
                    raise ServiceError(
                        422,
                        "knowledge_segmentation_changed",
                        "分段或位置与历史不同，旧引用保留；请新建文件版本。",
                    )
                previous = {
                    (u["source_position"], u["char_start"], u["char_end"], u["sha256"]): u["id"]
                    for u in previous_units
                }
                clear_index(db, document_id=document.id)
                db.execute("DELETE FROM knowledge_units WHERE version_id=?", (version.id,))
                db.execute("DELETE FROM knowledge_sources WHERE version_id=?", (version.id,))
                for source in sources:
                    db.execute(
                        "INSERT INTO knowledge_sources VALUES (?,?,?)",
                        (version.id, source["position"], encode(source)),
                    )
                available = indexes_available(db) or create_indexes(db)
                for unit in units:
                    unit["id"] = previous.get(
                        (
                            unit["source_position"],
                            unit["char_start"],
                            unit["char_end"],
                            unit["sha256"],
                        ),
                        unit["id"],
                    )
                    unit = TextUnit.model_validate(unit).model_dump(mode="json")
                    normalized = normalize(unit["text"])
                    db.execute(
                        "INSERT INTO knowledge_units VALUES (?,?,?,?,?,?)",
                        (
                            unit["id"],
                            version.id,
                            document.id,
                            document.project_id,
                            encode(unit),
                            normalized,
                        ),
                    )
                    if available and getattr(db, "dialect", None) != "postgresql":
                        for table in FTS_TABLES:
                            db.execute(
                                f"INSERT INTO {table}(unit_id,project_id,text) VALUES (?,?,?)",
                                (unit["id"], document.project_id, normalized),
                            )
                version.state = (
                    "ready"
                    if units and all(s["state"] == "text" for s in sources) and available
                    else "partial"
                    if units
                    else "failed"
                )
                version.indexed = bool(units) and available
                version.extractor, version.extraction_sha256 = product["extractor"], signature
                version.parsed_at, version.text_bytes, version.unit_count = (
                    utc_now(),
                    size,
                    len(units),
                )
                version.page_count, version.line_count = (
                    product["page_count"],
                    product["line_count"],
                )
                version.warnings = list(dict.fromkeys(product["warnings"]))
                if not available:
                    version.warnings.append("FTS5或trigram索引不可用；提取文本保留，检索尚不可用。")
                if not units:
                    version.error = {
                        "code": "knowledge_no_text",
                        "message": "没有可检索文本；可能为扫描件，本版不执行OCR。",
                    }
                operation.state = "completed" if units else "failed"
                if not units:
                    operation.http_status = 422
                operation.message = (
                    "已保存实际提取内容；请核对解析范围和定位。"
                    if units
                    else version.error["message"]
                )
            document.state, document.updated_at = version.state, utc_now()
            self._put(db, "knowledge_versions", version)
            self._put(db, "knowledge_documents", document)
            operation.completed_at = utc_now()
            db.execute(
                "UPDATE knowledge_operations SET state=?,record=?,reserved_bytes=0 WHERE id=?",
                (operation.state, operation.model_dump_json(), operation.id),
            )
            self.projects._touch(db, operation.project_id)
            self.projects._budget(db)
            return operation

    def delete(self, project_id, document_id, request):
        with self.repo.connection() as db, self.repo.transaction(db):
            self.projects._project(db, project_id, request.expected_revision)
            self.projects._idle(db, project_id)
            self._document(db, project_id, document_id)
            if not request.confirmed:
                raise ServiceError(
                    422,
                    "knowledge_confirmation_required",
                    "请确认删除原文、所有版本和索引，并使历史引用失效。",
                )
            from astroagent.project_links import invalidate

            invalidate(db, project_id, document_id=document_id, reason="document_deleted")
            clear_index(db, document_id=document_id)
            for row in db.execute(
                "SELECT record FROM knowledge_evidence WHERE project_id=? AND document_id=?",
                (project_id, document_id),
            ).fetchall():
                evidence = EvidenceRecord.model_validate_json(row[0])
                evidence.validity = "deleted"
                self._put(db, "knowledge_evidence", evidence)
            db.execute("DELETE FROM knowledge_documents WHERE id=?", (document_id,))
            self.projects._touch(db, project_id)

    @staticmethod
    def recover(db):
        changed = set()
        for row in db.execute(
            "SELECT record FROM knowledge_operations WHERE state='parsing'"
        ).fetchall():
            operation = KnowledgeOperation.model_validate_json(row[0])
            operation.state, operation.completed_at = "interrupted", utc_now()
            operation.http_status = 409
            operation.message = "服务重启中断本地解析；未自动重试，需要明确确认。"
            db.execute(
                "UPDATE knowledge_operations SET "
                "state='interrupted',record=?,reserved_bytes=0 WHERE id=?",
                (operation.model_dump_json(), operation.id),
            )
            changed.add(operation.project_id)
        for table, model in (
            ("knowledge_versions", DocumentVersion),
            ("knowledge_documents", KnowledgeDocument),
        ):
            for row in db.execute(f"SELECT record FROM {table}").fetchall():
                value = model.model_validate_json(row[0])
                if value.state == "parsing":
                    value.state = "interrupted"
                    KnowledgeRepository._put(db, table, value)
        for project_id in changed:
            value = ProjectRepository._get(db, "projects", project_id)
            value["revision"] += 1
            value["updated_at"] = utc_now()
            ProjectRepository._put(db, "projects", value)
