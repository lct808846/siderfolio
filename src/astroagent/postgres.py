"""PostgreSQL runtime. The legacy repository methods retain their record contracts.

Only application-owned SQL is adapted here; request text is always a parameter.
SQLite is never opened by this runtime. Initial creation is an explicit setup action.
"""

import json
import multiprocessing
import os
import re
from contextlib import contextmanager

from astroagent.conversations import ConversationRepository, storage_error
from astroagent.errors import ServiceError

SCHEMA_VERSION = 6
LOCK_ID = 831047129
COLUMNS = {
    "conversations": "id,title,created_at,updated_at,revision,metadata_revision",
    ("turns"): (
        "id,conversation_id,ordinal,request_id,request_hash,state,record,size_bytes,reserved_bytes"
    ),
    "projects": "id,record",
    "project_conversations": "conversation_id,project_id",
    "snapshots": "id,project_id,record",
    "reruns": "id,project_id,request_id,request_hash,state,record,reserved_bytes",
    "imported_turn_origins": "turn_id,record",
    "workflows": "id,project_id,state,record,reserved_bytes",
    "workflow_operations": "id,run_id,request_id,request_hash,state,record,reserved_bytes",
    "workflow_outputs": "id,run_id,record,content",
    "workflow_snapshot_refs": "run_id,snapshot_id",
    "knowledge_meta": "key,value",
    "knowledge_documents": "id,project_id,record",
    "knowledge_versions": "id,document_id,project_id,record,content",
    "knowledge_sources": "version_id,position,record",
    "knowledge_units": "id,version_id,document_id,project_id,record,normalized",
    "knowledge_evidence": "id,project_id,document_id,record",
    "knowledge_operations": "id,project_id,request_id,request_hash,state,record,reserved_bytes",
    "project_links": "id,project_id,target_type,target_id,evidence_id,record",
    "project_link_requests": "id,project_id,request_id,request_sha256,record",
}


class Record(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def row_factory(cursor):
    names = [column.name for column in (cursor.description or ())]
    return lambda values: Record(
        (k, v) for k, v in zip(names, values, strict=True) if k != "_order"
    )


def adapt_sql(statement):
    """Finite compatibility rules for the pre-1.0 repository's private SQL dialect."""
    sql = statement.strip()
    if sql in ("BEGIN", "BEGIN IMMEDIATE"):
        return "BEGIN ISOLATION LEVEL REPEATABLE READ"
    if sql.startswith("PRAGMA user_version="):
        return None
    sql = sql.replace("BEGIN IMMEDIATE", "BEGIN")
    sql = re.sub(r"\bBLOB\b", "BYTEA", sql, flags=re.I)
    sql = re.sub(r"cast\(([^()]+) AS BYTEA\)", r"convert_to(\1,'UTF8')", sql, flags=re.I)
    sql = re.sub(r"\browid\b", "_order", sql)

    def json_field(match):
        expression, field = match.groups()
        value = f"({expression}::jsonb->>'{field}')"
        return f"({value})::integer" if field == "ordinal" else value

    sql = re.sub(r"json_extract\(([\w.]+),'\$\.([a-z_]+)'\)", json_field, sql)
    sql = sql.replace("(v.record::jsonb->>'indexed')=1", "(v.record::jsonb->>'indexed')='true'")
    if sql.startswith("CREATE TABLE "):
        table = re.match(r"CREATE TABLE (\w+)", sql).group(1)
        if table in COLUMNS:
            close = sql.rfind(")")
            sql = sql[:close] + ", _order BIGINT GENERATED ALWAYS AS IDENTITY" + sql[close:]
    match = re.match(r"INSERT INTO (\w+)\s+VALUES", sql)
    if match and match[1] in COLUMNS:
        table = match[1]
        # v1 DDL precedes the metadata_revision column added by v2.
        columns = COLUMNS[table]
        if table == "conversations" and sql.count("?") == 5:
            columns = columns.rsplit(",", 1)[0]
        sql = sql.replace(f"INSERT INTO {table}", f"INSERT INTO {table} ({columns})", 1)
    # Preserve literal percent signs while using psycopg's positional protocol.
    return sql.replace("%", "%%").replace("?", "%s")


class Connection:
    dialect = "postgresql"

    def __init__(self, raw, namespace="public", identity=None):
        self.raw = raw
        self.namespace = namespace
        self.identity = identity

    def execute(self, statement, parameters=()):
        def contains_nul(value):
            if isinstance(value, str):
                return "\x00" in value
            if isinstance(value, dict):
                return any(contains_nul(k) or contains_nul(v) for k, v in value.items())
            if isinstance(value, list):
                return any(contains_nul(v) for v in value)
            return False

        for value in parameters:
            if isinstance(value, str):
                invalid = "\x00" in value
                if not invalid and "\\u0000" in value and value.lstrip().startswith(("{", "[")):
                    try:
                        invalid = contains_nul(json.loads(value))
                    except (ValueError, RecursionError):
                        invalid = True
                if invalid:
                    raise ServiceError(
                        422,
                        "postgres_text_unsupported",
                        "文本包含PostgreSQL不支持的零字符；未静默清洗、替换或提交数据。",
                    )
        sql = adapt_sql(statement)
        if sql is None:
            return self.raw.execute("SELECT 1 WHERE false")
        if self.namespace != "public":
            # Extension types/functions are explicitly qualified; public relations
            # are never a fallback when a tenant table is absent.
            sql = re.sub(r"(?<![\w.])vector\b", "public.vector", sql)
            sql = sql.replace("<=>", "OPERATOR(public.<=>)")
            for name in ("vector_dims", "similarity", "word_similarity"):
                sql = re.sub(rf"(?<![\w.]){name}\(", f"public.{name}(", sql)
            sql = re.sub(r"(?<![\w.])gin_trgm_ops\b", "public.gin_trgm_ops", sql)
        return self.raw.execute(sql, parameters)

    def commit(self):
        if self.identity is not None:
            # Serialize final authorization with disable/reset/role changes.
            identifier, generation = self.identity
            current = self.raw.execute(
                "SELECT 1 FROM public.auth_users WHERE id=%s AND generation=%s "
                "AND active AND NOT disabled AND namespace=%s FOR SHARE",
                (identifier, generation, self.namespace),
            ).fetchone()
            if not current:
                raise ServiceError(403, "account_unavailable", "账号状态已改变，结果未提交。")
        self.raw.execute("COMMIT")

    def rollback(self):
        self.raw.execute("ROLLBACK")


class PostgresRepository(ConversationRepository):
    def __init__(self, settings, namespace="public", identity_guard=None, identity=None):
        super().__init__(settings)
        if namespace != "public" and not re.fullmatch(r"aa_[0-9a-f]{32}", namespace):
            raise ValueError("Invalid private namespace")
        self.namespace = namespace
        self.identity_guard = identity_guard
        self.identity = identity
        self.lock_id = LOCK_ID if namespace == "public" else int(namespace[3:18], 16)
        # pg_catalog is implicitly searched before this path. Keeping only the
        # private namespace also makes unqualified CREATE target that namespace.
        self.search_path = namespace
        self.path = None  # No runtime SQLite pathname, including error fallback.
        self.session = None
        self._session_required = False

    def connect(self):
        try:
            import psycopg

            if self.identity_guard is not None and not self.identity_guard():
                raise ServiceError(403, "account_unavailable", "账号暂不可用。")

            with self.mutex:
                if self._session_required:
                    try:
                        if self.session is None or self.session.closed:
                            raise RuntimeError("Lock session was lost")
                        self.session.execute("SELECT 1")
                    except Exception:
                        if self.session is not None:
                            self.session.close()
                        self.session = None
                        # Reconnect the lock only; never create tables, migrate or replay tasks.
                        replacement = psycopg.connect(
                            self.settings.database_url.get_secret_value(),
                            autocommit=True,
                            connect_timeout=5,
                            options=f"-c statement_timeout=5000 -c search_path={self.search_path}",
                        )
                        try:
                            if not replacement.execute(
                                "SELECT pg_try_advisory_lock(%s)", (self.lock_id,)
                            ).fetchone()[0]:
                                raise RuntimeError("Database acquired by another process")
                            row = replacement.execute(
                                "SELECT value FROM astroagent_meta WHERE key='schema_version'"
                            ).fetchone()
                            extensions = {
                                r[0]
                                for r in replacement.execute("SELECT extname FROM pg_extension")
                            }
                            if (
                                not row
                                or row[0] != str(SCHEMA_VERSION)
                                or not {"vector", "pg_trgm"} <= extensions
                            ):
                                raise RuntimeError("Database identity contract changed")
                            self.session = replacement
                        except BaseException:
                            replacement.close()
                            raise

            return psycopg.connect(
                self.settings.database_url.get_secret_value(),
                autocommit=True,
                connect_timeout=5,
                options=(
                    "-c statement_timeout=5000 -c lock_timeou"
                    "t=1000 -c idle_in_transaction_session_ti"
                    f"meout=15000 -c search_path={self.search_path}"
                ),
                row_factory=row_factory,
            )
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError(
                503,
                "database_unavailable",
                "无法连接本机PostgreSQL，请在设置中核对服务端连接配置。",
            ) from exc

    def initialize(self, *, create=False):
        if not self.settings.database_url.get_secret_value():
            raise ServiceError(
                503, "database_not_configured", "请先在服务端配置本机PostgreSQL，再打开设置。"
            )
        if multiprocessing.parent_process() is not None or any(
            os.getenv(name, "1") != "1" for name in ("WEB_CONCURRENCY", "UVICORN_WORKERS")
        ):
            raise storage_error()
        self.session = self.connect()
        try:
            locked = self.session.execute(
                "SELECT pg_try_advisory_lock(%s)", (self.lock_id,)
            ).fetchone()[0]
            if not locked:
                raise ServiceError(
                    503, "database_in_use", "此数据库已有AstroAgent进程，请只启动一个worker。"
                )
            self._session_required = True
            with self.connection() as db:
                meta = db.execute(
                    "SELECT to_regclass(?)", (f"{self.namespace}.astroagent_meta",)
                ).fetchone()[0]
                if not meta:
                    if not create:
                        raise ServiceError(
                            503,
                            "database_not_initialized",
                            "数据库尚未初始化；请在设置中明确确认创建。",
                        )
                    with self.transaction(db):
                        tables = db.execute(
                            "SELECT tablename FROM pg_tables WHERE schemaname=?", (self.namespace,)
                        ).fetchall()
                        if tables:
                            raise ServiceError(
                                409, "database_not_empty", "初始化需要空数据库，不覆盖已有表。"
                            )
                        if self.namespace == "public":
                            db.execute("CREATE EXTENSION IF NOT EXISTS vector")
                            db.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                        self._migrate_v1(db)
                        self._migrate_v2(db)
                        self._migrate_v3(db)
                        from astroagent.knowledge import migrate
                        from astroagent.project_links import migrate as links
                        from astroagent.rag_store import migrate as rag

                        migrate(db)
                        links(db)
                        rag(db)
                        db.execute(
                            "CREATE TABLE astroagent_meta (key TEXT P"
                            "RIMARY KEY,value TEXT NOT NULL)"
                        )
                        db.execute(
                            "INSERT INTO astroagent_meta VALUES ('schema_version',?)",
                            (str(SCHEMA_VERSION),),
                        )
                else:
                    version = db.execute(
                        "SELECT value FROM astroagent_meta WHERE key='schema_version'"
                    ).fetchone()
                    if not version or version[0] != str(SCHEMA_VERSION):
                        raise ServiceError(
                            503,
                            "database_schema_unsupported",
                            "数据库版本不匹配；请使用对应版本与迁移说明。",
                        )
                extensions = {r[0] for r in db.execute("SELECT extname FROM pg_extension")}
                if not {"vector", "pg_trgm"} <= extensions:
                    raise ServiceError(
                        503, "database_extension_missing", "数据库缺少pgvector或pg_trgm扩展。"
                    )
                with self.transaction(db):
                    from astroagent.knowledge import KnowledgeRepository
                    from astroagent.projects import ProjectRepository
                    from astroagent.rag_store import recover
                    from astroagent.workflows import WorkflowRepository

                    for row in db.execute(
                        "SELECT record FROM turns WHERE state='running'"
                    ).fetchall():
                        from astroagent.conversation_schemas import Turn
                        from astroagent.conversations import utc_now
                        from astroagent.schemas import ErrorInfo

                        turn = Turn.model_validate_json(row[0])
                        turn.execution_status, turn.completed_at = "interrupted", utc_now()
                        turn.error = ErrorInfo(
                            code="turn_interrupted", message="服务重启中断该轮；未自动重发。"
                        )
                        self._save(db, turn)
                    ProjectRepository.recover(db)
                    WorkflowRepository.recover(db)
                    KnowledgeRepository.recover(db)
                    recover(db)
        except BaseException:
            self.close()
            raise

    @contextmanager
    def connection(self):
        raw = self.connect()
        try:
            yield Connection(raw, self.namespace, self.identity)
        except ServiceError:
            raise
        except Exception as exc:
            raise storage_error() from exc
        finally:
            raw.close()

    @staticmethod
    @contextmanager
    def transaction(db):
        db.raw.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
        try:
            db.execute("SELECT pg_advisory_xact_lock(?)", (LOCK_ID + 1,))
            yield
            db.commit()
        except BaseException:
            db.rollback()
            raise

    @staticmethod
    def _used(db):
        from astroagent.local_model_store import used as local_used
        from astroagent.plot_store import used
        from astroagent.rag_store import used_bytes

        return ConversationRepository._used(db) + used_bytes(db) + used(db) + local_used(db)

    def close(self):
        self._session_required = False
        if self.session is not None:
            self.session.close()
            self.session = None
