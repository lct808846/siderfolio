"""租户隔离（aa_<32-hex>）的 V2.2 长期记忆、候选队列、向量索引与长对话摘要持久化存储。"""

from __future__ import annotations

import json

from astroagent.conversations import utc_now
from astroagent.embeddings import vector_literal
from astroagent.errors import ServiceError
from astroagent.memory_extractor import normalize_memory_text
from astroagent.memory_schemas import (
    MEMORY_SCHEMA_VERSION,
    ConversationSummaryRecord,
    MemoryCandidate,
    MemoryItem,
    MemoryPreferences,
)

PREFERENCES_KEY = "user_memory_preferences_v1"

DDL = (
    "CREATE TABLE IF NOT EXISTS memory_meta (version INTEGER PRIMARY KEY CHECK (version=1))",
    (
        "CREATE TABLE IF NOT EXISTS memory_preferences ("
        "key TEXT PRIMARY KEY, "
        "record TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    ),
    (
        "CREATE TABLE IF NOT EXISTS memories ("
        "id TEXT PRIMARY KEY, "
        "scope TEXT NOT NULL, "
        "project_id TEXT, "
        "category TEXT NOT NULL, "
        "status TEXT NOT NULL, "
        "normalized_key TEXT NOT NULL, "
        "revision INTEGER NOT NULL, "
        "source_conversation_id TEXT, "
        "source_turn_id TEXT, "
        "source_project_id TEXT, "
        "normalized_text TEXT NOT NULL, "
        "record TEXT NOT NULL, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_memories_scope_status "
        "ON memories (scope, project_id, status, updated_at DESC)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_memories_dedup "
        "ON memories (scope, project_id, category, normalized_key)"
    ),
    ("CREATE INDEX IF NOT EXISTS idx_memories_source_conv ON memories (source_conversation_id)"),
    ("CREATE INDEX IF NOT EXISTS idx_memories_source_proj ON memories (source_project_id)"),
    (
        "CREATE TABLE IF NOT EXISTS memory_candidates ("
        "id TEXT PRIMARY KEY, "
        "scope TEXT NOT NULL, "
        "project_id TEXT, "
        "category TEXT NOT NULL, "
        "status TEXT NOT NULL, "
        "normalized_key TEXT NOT NULL, "
        "source_conversation_id TEXT, "
        "source_turn_id TEXT, "
        "record TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_memory_candidates_status "
        "ON memory_candidates (status, scope, project_id, created_at DESC)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_memory_candidates_turn "
        "ON memory_candidates (source_conversation_id, source_turn_id, normalized_key)"
    ),
    (
        "CREATE TABLE IF NOT EXISTS memory_vectors ("
        "memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE, "
        "model_sha256 TEXT NOT NULL, "
        "dimension INTEGER NOT NULL, "
        "text_sha256 TEXT NOT NULL, "
        "embedding vector NOT NULL, "
        "updated_at TEXT NOT NULL)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_memory_vectors_model "
        "ON memory_vectors (model_sha256, dimension)"
    ),
    (
        "CREATE TABLE IF NOT EXISTS conversation_summaries ("
        "conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE, "
        "source_sha256 TEXT NOT NULL, "
        "status TEXT NOT NULL, "
        "record TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    ),
    f"INSERT INTO memory_meta(version) VALUES({MEMORY_SCHEMA_VERSION}) "
    "ON CONFLICT (version) DO NOTHING",
)


def ready(db) -> bool:
    if getattr(db, "dialect", None) != "postgresql":
        return False
    if not db.execute("SELECT to_regclass('memory_meta')").fetchone()[0]:
        return False
    row = db.execute("SELECT version FROM memory_meta").fetchone()
    return bool(row and row[0] == MEMORY_SCHEMA_VERSION)


def used(db) -> int:
    if not ready(db):
        return 0
    total = 0
    for table in ("memory_preferences", "memories", "memory_candidates", "conversation_summaries"):
        total += int(
            db.execute(f"SELECT COALESCE(SUM(octet_length(record)), 0) FROM {table}").fetchone()[0]
        )
    return total


def _encode(model) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))


class MemoryStore:
    def __init__(self, repo):
        self.repo = repo

    def initialize(self) -> None:
        with self.repo.connection() as db, self.repo.transaction(db):
            if getattr(db, "dialect", None) != "postgresql":
                return
            for statement in DDL:
                db.execute(statement)

    def _ensure_ready(self, db) -> None:
        if getattr(db, "dialect", None) != "postgresql":
            raise ServiceError(
                503,
                "memory_storage_unavailable",
                "长期记忆存储仅支持已就绪的 PostgreSQL/pgvector 数据库。",
            )
        if not ready(db):
            for statement in DDL:
                db.execute(statement)

    def get_preferences(self) -> MemoryPreferences:
        with self.repo.connection() as db:
            if not ready(db):
                return MemoryPreferences()
            row = db.execute(
                "SELECT record FROM memory_preferences WHERE key=?",
                (PREFERENCES_KEY,),
            ).fetchone()
            if row is None:
                return MemoryPreferences()
            return MemoryPreferences.model_validate_json(row[0])

    def save_preferences(
        self,
        *,
        auto_extract: bool,
        cross_session_injection: bool,
        history_retrieval: bool,
        expected_revision: int | None = None,
    ) -> MemoryPreferences:
        now = utc_now()
        with self.repo.connection() as db, self.repo.transaction(db):
            self._ensure_ready(db)
            row = db.execute(
                "SELECT record FROM memory_preferences WHERE key=?",
                (PREFERENCES_KEY,),
            ).fetchone()
            current = (
                MemoryPreferences.model_validate_json(row[0])
                if row is not None
                else MemoryPreferences()
            )
            if expected_revision is not None and current.revision != expected_revision:
                raise ServiceError(
                    409,
                    "memory_preferences_conflict",
                    "记忆设置已更新，请重新读取后再保存。",
                )
            updated = MemoryPreferences(
                auto_extract=auto_extract,
                cross_session_injection=cross_session_injection,
                history_retrieval=history_retrieval,
                revision=current.revision + 1,
                updated_at=now,
            )
            db.execute(
                "INSERT INTO memory_preferences (key, record, updated_at) VALUES (?,?,?) "
                "ON CONFLICT (key) DO UPDATE SET record=EXCLUDED.record, "
                "updated_at=EXCLUDED.updated_at",
                (PREFERENCES_KEY, _encode(updated), now),
            )
            return updated

    def project_exists(self, db, project_id: str) -> tuple[bool, str | None, bool]:
        """Return (exists, project_name, is_default_personal_space)."""
        row = db.execute("SELECT record FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            return False, None, False
        data = json.loads(row[0])
        default_row = db.execute(
            "SELECT value FROM astroagent_meta WHERE key='default_workspace_project_id'"
        ).fetchone()
        is_default = bool(default_row and default_row[0] == project_id)
        return True, str(data.get("name") or ""), is_default

    def default_project_id(self, db) -> str | None:
        if not db.execute("SELECT to_regclass('astroagent_meta')").fetchone()[0]:
            return None
        row = db.execute(
            "SELECT value FROM astroagent_meta WHERE key='default_workspace_project_id'"
        ).fetchone()
        return row[0] if row else None

    def project_names_map(self, db) -> dict[str, str]:
        rows = db.execute("SELECT id, record FROM projects").fetchall()
        names: dict[str, str] = {}
        for row in rows:
            try:
                names[row[0]] = str(json.loads(row[1]).get("name") or "")
            except Exception:
                names[row[0]] = ""
        return names

    def list_memories(
        self,
        *,
        scope: str | None = None,
        project_id: str | None = None,
        category: str | None = None,
        status: str | None = None,
        include_superseded: bool = False,
    ) -> list[MemoryItem]:
        with self.repo.connection() as db:
            if not ready(db):
                return []
            where: list[str] = []
            params: list[object] = []
            if scope:
                where.append("scope=?")
                params.append(scope)
            if project_id:
                where.append("project_id=?")
                params.append(project_id)
            if category:
                where.append("category=?")
                params.append(category)
            if status:
                where.append("status=?")
                params.append(status)
            elif not include_superseded:
                where.append("status != 'superseded'")
            sql = "SELECT record FROM memories"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY updated_at DESC, id DESC"
            names = self.project_names_map(db)
            items: list[MemoryItem] = []
            for row in db.execute(sql, params).fetchall():
                item = MemoryItem.model_validate_json(row[0])
                if item.project_id:
                    item.project_name = names.get(item.project_id) or item.project_name
                items.append(item)
            return items

    def list_active_for_turn(self, *, custom_project_id: str | None) -> list[MemoryItem]:
        with self.repo.connection() as db:
            if not ready(db):
                return []
            if custom_project_id:
                rows = db.execute(
                    "SELECT record FROM memories WHERE status='active' "
                    "AND (scope='global' OR (scope='project' AND project_id=?)) "
                    "ORDER BY updated_at DESC, id DESC",
                    (custom_project_id,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT record FROM memories WHERE status='active' AND scope='global' "
                    "ORDER BY updated_at DESC, id DESC"
                ).fetchall()
            return [MemoryItem.model_validate_json(row[0]) for row in rows]

    def get_memory(self, memory_id: str) -> MemoryItem | None:
        with self.repo.connection() as db:
            if not ready(db):
                return None
            row = db.execute("SELECT record FROM memories WHERE id=?", (memory_id,)).fetchone()
            if row is None:
                return None
            item = MemoryItem.model_validate_json(row[0])
            if item.project_id:
                item.project_name = self.project_names_map(db).get(item.project_id)
            return item

    def save_memory_with_db(self, db, item: MemoryItem) -> MemoryItem:
        self._ensure_ready(db)
        norm_text = normalize_memory_text(item.summary)
        db.execute(
            "INSERT INTO memories "
            "(id, scope, project_id, category, status, normalized_key, revision, "
            "source_conversation_id, source_turn_id, source_project_id, normalized_text, "
            "record, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (id) DO UPDATE SET "
            "scope=EXCLUDED.scope, project_id=EXCLUDED.project_id, category=EXCLUDED.category, "
            "status=EXCLUDED.status, normalized_key=EXCLUDED.normalized_key, "
            "revision=EXCLUDED.revision, source_conversation_id=EXCLUDED.source_conversation_id, "
            "source_turn_id=EXCLUDED.source_turn_id, source_project_id=EXCLUDED.source_project_id, "
            "normalized_text=EXCLUDED.normalized_text, record=EXCLUDED.record, "
            "updated_at=EXCLUDED.updated_at",
            (
                item.id,
                item.scope,
                item.project_id,
                item.category,
                item.status,
                item.normalized_key,
                item.revision,
                item.source.conversation_id,
                item.source.turn_id,
                item.source.project_id,
                norm_text,
                _encode(item),
                item.created_at,
                item.updated_at,
            ),
        )
        if item.status != "active":
            db.execute("DELETE FROM memory_vectors WHERE memory_id=?", (item.id,))
        return item

    def delete_memory(self, memory_id: str, *, expected_revision: int | None = None) -> None:
        with self.repo.connection() as db, self.repo.transaction(db):
            self._ensure_ready(db)
            row = db.execute("SELECT record FROM memories WHERE id=?", (memory_id,)).fetchone()
            if row is None:
                raise ServiceError(404, "memory_not_found", "记忆条目不存在。")
            current = MemoryItem.model_validate_json(row[0])
            if expected_revision is not None and current.revision != expected_revision:
                raise ServiceError(
                    409,
                    "memory_revision_conflict",
                    "记忆条目已变更，请重新读取后再删除。",
                )
            db.execute("DELETE FROM memory_vectors WHERE memory_id=?", (memory_id,))
            db.execute("DELETE FROM memories WHERE id=?", (memory_id,))

    def list_candidates(
        self,
        *,
        scope: str | None = None,
        project_id: str | None = None,
        status: str | None = "pending",
    ) -> list[MemoryCandidate]:
        with self.repo.connection() as db:
            if not ready(db):
                return []
            where: list[str] = []
            params: list[object] = []
            if status:
                where.append("status=?")
                params.append(status)
            if scope:
                where.append("scope=?")
                params.append(scope)
            if project_id:
                where.append("project_id=?")
                params.append(project_id)
            sql = "SELECT record FROM memory_candidates"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY created_at DESC, id DESC"
            names = self.project_names_map(db)
            items: list[MemoryCandidate] = []
            for row in db.execute(sql, params).fetchall():
                item = MemoryCandidate.model_validate_json(row[0])
                if item.project_id:
                    item.project_name = names.get(item.project_id) or item.project_name
                items.append(item)
            return items

    def save_candidate_with_db(self, db, candidate: MemoryCandidate) -> MemoryCandidate:
        self._ensure_ready(db)
        db.execute(
            "INSERT INTO memory_candidates "
            "(id, scope, project_id, category, status, normalized_key, "
            "source_conversation_id, source_turn_id, record, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (id) DO UPDATE SET "
            "scope=EXCLUDED.scope, project_id=EXCLUDED.project_id, category=EXCLUDED.category, "
            "status=EXCLUDED.status, normalized_key=EXCLUDED.normalized_key, "
            "record=EXCLUDED.record",
            (
                candidate.id,
                candidate.scope,
                candidate.project_id,
                candidate.category,
                candidate.status,
                candidate.normalized_key,
                candidate.source.conversation_id,
                candidate.source.turn_id,
                _encode(candidate),
                candidate.created_at,
            ),
        )
        return candidate

    def candidate_exists_for_turn_with_db(
        self, db, conversation_id: str, turn_id: str, normalized_key: str
    ) -> bool:
        if not ready(db):
            return False
        row = db.execute(
            "SELECT 1 FROM memory_candidates "
            "WHERE source_conversation_id=? AND source_turn_id=? AND normalized_key=?",
            (conversation_id, turn_id, normalized_key),
        ).fetchone()
        return row is not None

    def upsert_vector(
        self,
        memory_id: str,
        *,
        model_sha256: str,
        dimension: int,
        text_sha256: str,
        vector: list[float],
    ) -> None:
        now = utc_now()
        with self.repo.connection() as db, self.repo.transaction(db):
            self._ensure_ready(db)
            db.execute(
                "INSERT INTO memory_vectors "
                "(memory_id, model_sha256, dimension, text_sha256, embedding, updated_at) "
                "VALUES (?,?,?,?,?::vector,?) "
                "ON CONFLICT (memory_id) DO UPDATE SET "
                "model_sha256=EXCLUDED.model_sha256, dimension=EXCLUDED.dimension, "
                "text_sha256=EXCLUDED.text_sha256, embedding=EXCLUDED.embedding, "
                "updated_at=EXCLUDED.updated_at",
                (
                    memory_id,
                    model_sha256,
                    dimension,
                    text_sha256,
                    vector_literal(vector),
                    now,
                ),
            )

    def delete_vector(self, memory_id: str) -> None:
        with self.repo.connection() as db, self.repo.transaction(db):
            if ready(db):
                db.execute("DELETE FROM memory_vectors WHERE memory_id=?", (memory_id,))

    def semantic_scores(
        self,
        *,
        memory_ids: list[str],
        model_sha256: str,
        dimension: int,
        query_vector: list[float],
        limit: int = 20,
    ) -> dict[str, float]:
        if not memory_ids:
            return {}
        with self.repo.connection() as db:
            if not ready(db):
                return {}
            placeholders = ",".join("?" for _ in memory_ids)
            vec = vector_literal(query_vector)
            rows = db.execute(
                "SELECT memory_id, 1.0 - (embedding <=> ?::vector) AS similarity "
                f"FROM memory_vectors WHERE model_sha256=? AND dimension=? "
                f"AND memory_id IN ({placeholders}) "
                "ORDER BY embedding <=> ?::vector LIMIT ?",
                [vec, model_sha256, dimension, *memory_ids, vec, limit],
            ).fetchall()
            return {row[0]: float(row[1]) for row in rows if row[1] is not None}

    def vector_indexed_count(self, *, model_sha256: str, dimension: int) -> int:
        if not model_sha256 or dimension <= 0:
            return 0
        with self.repo.connection() as db:
            if not ready(db):
                return 0
            row = db.execute(
                "SELECT COUNT(*) FROM memory_vectors v JOIN memories m ON m.id=v.memory_id "
                "WHERE m.status='active' AND v.model_sha256=? AND v.dimension=?",
                (model_sha256, dimension),
            ).fetchone()
            return int(row[0]) if row else 0

    def get_summary(self, conversation_id: str) -> ConversationSummaryRecord | None:
        with self.repo.connection() as db:
            if not ready(db):
                return None
            row = db.execute(
                "SELECT record FROM conversation_summaries WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            if row is None:
                return None
            return ConversationSummaryRecord.model_validate_json(row[0])

    def save_summary(self, summary: ConversationSummaryRecord) -> ConversationSummaryRecord:
        with self.repo.connection() as db, self.repo.transaction(db):
            self._ensure_ready(db)
            db.execute(
                "INSERT INTO conversation_summaries "
                "(conversation_id, source_sha256, status, record, updated_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT (conversation_id) DO UPDATE SET "
                "source_sha256=EXCLUDED.source_sha256, status=EXCLUDED.status, "
                "record=EXCLUDED.record, updated_at=EXCLUDED.updated_at",
                (
                    summary.conversation_id,
                    summary.source_sha256,
                    summary.status,
                    _encode(summary),
                    summary.updated_at,
                ),
            )
            return summary

    def invalidate_summary(self, conversation_id: str) -> None:
        with self.repo.connection() as db, self.repo.transaction(db):
            if ready(db):
                db.execute(
                    "DELETE FROM conversation_summaries WHERE conversation_id=?",
                    (conversation_id,),
                )

    def summary_count(self) -> int:
        with self.repo.connection() as db:
            if not ready(db):
                return 0
            row = db.execute(
                "SELECT COUNT(*) FROM conversation_summaries WHERE status='active'"
            ).fetchone()
            return int(row[0]) if row else 0

    def on_conversation_deleted(self, conversation_id: str) -> None:
        with self.repo.connection() as db, self.repo.transaction(db):
            self.on_conversation_deleted_with_db(db, conversation_id)

    def on_conversation_deleted_with_db(self, db, conversation_id: str) -> None:
        if not ready(db):
            return
        db.execute(
            "DELETE FROM conversation_summaries WHERE conversation_id=?",
            (conversation_id,),
        )
        db.execute(
            "DELETE FROM memory_candidates WHERE source_conversation_id=? AND status='pending'",
            (conversation_id,),
        )
        now = utc_now()
        rows = db.execute(
            "SELECT record FROM memories WHERE source_conversation_id=?",
            (conversation_id,),
        ).fetchall()
        for row in rows:
            item = MemoryItem.model_validate_json(row[0])
            item.source.validity = "source_missing"
            item.source.quote = None
            if item.source.source_type == "conversation_turn" and item.status == "active":
                item.status = "paused"
            item.revision += 1
            item.updated_at = now
            self.save_memory_with_db(db, item)

    def on_conversation_moved_with_db(
        self, db, source_project_id: str, conversation_id: str
    ) -> None:
        if not ready(db):
            return
        db.execute(
            "DELETE FROM conversation_summaries WHERE conversation_id=?",
            (conversation_id,),
        )
        db.execute(
            "DELETE FROM memory_candidates "
            "WHERE source_conversation_id=? AND project_id=? AND status='pending'",
            (conversation_id, source_project_id),
        )
        now = utc_now()
        rows = db.execute(
            "SELECT record FROM memories "
            "WHERE scope='project' AND project_id=? AND source_conversation_id=?",
            (source_project_id, conversation_id),
        ).fetchall()
        for row in rows:
            item = MemoryItem.model_validate_json(row[0])
            item.source.validity = "source_moved"
            item.source.quote = None
            if item.status == "active":
                item.status = "paused"
            item.revision += 1
            item.updated_at = now
            self.save_memory_with_db(db, item)

    def on_project_deleted_with_db(self, db, project_id: str) -> None:
        if not ready(db):
            return
        db.execute(
            "DELETE FROM memory_vectors WHERE memory_id IN "
            "(SELECT id FROM memories WHERE scope='project' AND project_id=?)",
            (project_id,),
        )
        db.execute("DELETE FROM memories WHERE scope='project' AND project_id=?", (project_id,))
        db.execute("DELETE FROM memory_candidates WHERE project_id=?", (project_id,))
        now = utc_now()
        rows = db.execute(
            "SELECT record FROM memories WHERE scope='global' AND source_project_id=?",
            (project_id,),
        ).fetchall()
        for row in rows:
            item = MemoryItem.model_validate_json(row[0])
            item.source.validity = "source_missing"
            item.source.quote = None
            if item.source.source_type != "manual" and item.status == "active":
                item.status = "paused"
            item.revision += 1
            item.updated_at = now
            self.save_memory_with_db(db, item)
