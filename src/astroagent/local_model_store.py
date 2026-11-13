"""Optional extension: bounded task metadata, atomic compare-and-set title application."""

import json
import re

from astroagent.conversations import encode, utc_now
from astroagent.errors import ServiceError
from astroagent.local_model_schemas import LocalPreferences

DDL = (
    "CREATE TABLE local_assistant_meta (key TEXT PRIMARY KEY, record TEXT NOT NULL)",
    (
        "CREATE TABLE local_assistant_tasks (id TEXT P"
        "RIMARY KEY, kind TEXT NOT NULL, conversation_"
        "id TEXT REFERENCES conversations(id) ON DELET"
        "E CASCADE, state TEXT NOT NULL, record TEXT N"
        "OT NULL)"
    ),
    (
        "CREATE UNIQUE INDEX local_assistant_auto_titl"
        "e ON local_assistant_tasks(conversation_id) W"
        "HERE kind='automatic_title'"
    ),
)


def ready(db):
    if getattr(db, "dialect", None) != "postgresql":
        return False
    tables = db.execute(
        "SELECT to_regclass('local_assistant_meta') AS"
        " meta,to_regclass('local_assistant_tasks') AS"
        " tasks"
    ).fetchone()
    if not tables[0] or not tables[1]:
        return False
    version = db.execute("SELECT record FROM local_assistant_meta WHERE key='version'").fetchone()
    return bool(version and version[0] == "1")


def used(db):
    if not ready(db):
        return 0
    return db.execute(
        "SELECT COALESCE((SELECT SUM(octet_length(reco"
        "rd)) FROM local_assistant_meta),0)+COALESCE(("
        "SELECT SUM(octet_length(record)) FROM local_a"
        "ssistant_tasks),0)+COALESCE((SELECT SUM(CASE "
        "WHEN state IN ('queued','running') THEN 4096 "
        "ELSE 0 END) FROM local_assistant_tasks),0)"
    ).fetchone()[0]


def invalidate_title(db, conversation_id):
    if ready(db):
        for row in db.execute(
            (
                "SELECT record FROM local_assistant_tasks WHER"
                "E conversation_id=? AND kind='automatic_title"
                "' AND state IN ('queued','running')"
            ),
            (conversation_id,),
        ):
            value = json.loads(row[0])
            value.update(
                state="superseded",
                completed_at=utc_now(),
                error="用户手动改名或归属发生变化，保留人工选择。",
            )
            LocalModelStore.put(db, value)


class LocalModelStore:
    def __init__(self, repo):
        self.repo = repo

    def preferences(self, db):
        if not ready(db):
            return LocalPreferences().model_dump()
        row = db.execute(
            "SELECT record FROM local_assistant_meta WHERE key='preferences'"
        ).fetchone()
        if row is None:
            raise ServiceError(
                503, "local_assistant_schema_invalid", "本地助手扩展版本无效，请核对数据库。"
            )
        return LocalPreferences.model_validate_json(row[0]).model_dump()

    def initialize(self):
        with self.repo.connection() as db, self.repo.transaction(db):
            if not ready(db):
                if db.execute("SELECT to_regclass('local_assistant_meta')").fetchone()[0]:
                    raise ServiceError(
                        409, "local_assistant_schema_invalid", "现有本地助手扩展不兼容，不会覆盖。"
                    )
                for statement in DDL:
                    db.execute(statement)
                db.execute(
                    "INSERT INTO local_assistant_meta(key,record) VALUES(?,?)", ("version", "1")
                )
                db.execute(
                    "INSERT INTO local_assistant_meta(key,record) VALUES(?,?)",
                    ("preferences", encode(LocalPreferences().model_dump())),
                )
                self.budget(db)

    def update_preferences(self, request):
        with self.repo.connection() as db, self.repo.transaction(db):
            self.require(db)
            prefs = self.preferences(db)
            if prefs["revision"] != request.expected_revision:
                raise ServiceError(
                    409, "local_assistant_preferences_conflict", "设置已变化，请先刷新。"
                )
            value = LocalPreferences(
                revision=prefs["revision"] + 1,
                enabled=request.enabled,
                auto_titles=request.auto_titles and request.enabled,
            ).model_dump()
            db.execute(
                "UPDATE local_assistant_meta SET record=? WHERE key='preferences'", (encode(value),)
            )
            self.budget(db)
            return value

    @staticmethod
    def require(db):
        if not ready(db):
            raise ServiceError(
                409,
                "local_assistant_storage_unavailable",
                "请先在本机设置中确认准备本地助手记录表。",
            )

    def recover(self):
        with self.repo.connection() as db, self.repo.transaction(db):
            if ready(db):
                for row in db.execute(
                    "SELECT record FROM local_assistant_tasks WHERE state IN ('queued','running')"
                ):
                    value = json.loads(row[0])
                    value.update(
                        state="interrupted",
                        completed_at=utc_now(),
                        error="服务重启中断了任务，不自动重放本地推理。",
                    )
                    self.put(db, value)

    @staticmethod
    def put(db, value):
        # Raw text and manual results are never serialized here.
        saved = {**value, "output": None, "output_available": False}
        db.execute(
            "UPDATE local_assistant_tasks SET state=?,record=? WHERE id=?",
            (saved["state"], encode(saved), saved["id"]),
        )

    def get(self, identifier):
        with self.repo.connection() as db:
            self.require(db)
            row = db.execute(
                "SELECT record FROM local_assistant_tasks WHERE id=?", (identifier,)
            ).fetchone()
            if row is None:
                raise ServiceError(
                    404, "local_assistant_task_not_found", "本地助手任务不存在或已清理。"
                )
            return json.loads(row[0])

    def create(self, value):
        with self.repo.connection() as db, self.repo.transaction(db):
            self.require(db)
            row = db.execute(
                "SELECT record FROM local_assistant_tasks WHERE id=?", (value["id"],)
            ).fetchone()
            if row:
                old = json.loads(row[0])
                if old["request_sha256"] != value["request_sha256"]:
                    raise ServiceError(
                        409, "local_assistant_request_conflict", "同一请求编号不能用于不同输入。"
                    )
                return old, False
            if (
                value["automatic"]
                and db.execute(
                    (
                        "SELECT 1 FROM local_assistant_tasks WHERE kin"
                        "d='automatic_title' AND conversation_id=?"
                    ),
                    (value["conversation_id"],),
                ).fetchone()
            ):
                return None, False
            prefs = self.preferences(db)
            if not prefs["enabled"] or prefs["revision"] != value["preferences_revision"]:
                raise ServiceError(409, "local_assistant_disabled", "本地助手未启用或设置已变化。")
            if db.execute("SELECT count(*) FROM local_assistant_tasks").fetchone()[0] >= 500:
                raise ServiceError(
                    409,
                    "local_assistant_task_limit",
                    "本地任务记录已达500条，请在设置中清理已结束记录。",
                )
            if value["conversation_id"]:
                current = self.repo._conversation(db, value["conversation_id"])
                if current["metadata_revision"] != value["metadata_revision"]:
                    raise ServiceError(
                        409, "conversation_revision_conflict", "会话已改名，请刷新后再建议标题。"
                    )
            db.execute(
                (
                    "INSERT INTO local_assistant_tasks(id,kind,con"
                    "versation_id,state,record) VALUES(?,?,?,?,?)"
                ),
                (
                    value["id"],
                    "automatic_title" if value["automatic"] else value["action"],
                    value["conversation_id"],
                    value["state"],
                    encode(value),
                ),
            )
            self.budget(db)
            return value, True

    def finish(self, value, title=None):
        with self.repo.connection() as db, self.repo.transaction(db):
            row = db.execute(
                "SELECT record FROM local_assistant_tasks WHERE id=?", (value["id"],)
            ).fetchone()
            if row is None:
                return None
            old = json.loads(row[0])
            if old["state"] not in ("queued", "running"):
                return old
            prefs = self.preferences(db)
            if not prefs["enabled"] or prefs["revision"] != value["preferences_revision"]:
                value.update(state="superseded", error="本地助手设置已变化，任务结果已丢弃。")
            elif title is not None and value["automatic"]:
                conversation = db.execute(
                    "SELECT * FROM conversations WHERE id=?", (value["conversation_id"],)
                ).fetchone()
                first = db.execute(
                    "SELECT id FROM turns WHERE conversation_id=? ORDER BY ordinal LIMIT 1",
                    (value["conversation_id"],),
                ).fetchone()
                owner = db.execute(
                    "SELECT project_id FROM project_conversations WHERE conversation_id=?",
                    (value["conversation_id"],),
                ).fetchone()
                membership = owner[0] if owner else None
                if (
                    not prefs["auto_titles"]
                    or conversation is None
                    or first is None
                    or first[0] != value["turn_id"]
                    or conversation["title"] != value["baseline_title"]
                    or conversation["metadata_revision"] != value["metadata_revision"]
                    or membership != value["membership"]
                ):
                    value.update(
                        state="superseded", error="会话被修改、改名或重新归档，保留当前标题。"
                    )
                else:
                    db.execute(
                        (
                            "UPDATE conversations SET title=?,updated_at=?"
                            ",metadata_revision=metadata_revision+1 WHERE "
                            "id=? AND metadata_revision=? AND title=?"
                        ),
                        (
                            title,
                            utc_now(),
                            value["conversation_id"],
                            value["metadata_revision"],
                            value["baseline_title"],
                        ),
                    )
                    self.repo._touch_project(db, value["conversation_id"])
                    value["title_applied"] = True
            value["completed_at"] = utc_now() if value["state"] != "running" else None
            self.put(db, value)
            self.budget(db)
            return value

    def latest_title(self, conversation_id):
        with self.repo.connection() as db:
            self.repo._conversation(db, conversation_id)
            if not ready(db):
                return []
            return [
                json.loads(r[0])
                for r in db.execute(
                    (
                        "SELECT record FROM local_assistant_tasks WHER"
                        "E conversation_id=? AND kind='automatic_title"
                        "' ORDER BY id"
                    ),
                    (conversation_id,),
                )
            ]

    def clear(self):
        with self.repo.connection() as db, self.repo.transaction(db):
            self.require(db)
            db.execute("DELETE FROM local_assistant_tasks WHERE state NOT IN ('queued','running')")

    def budget(self, db):
        if self.repo._used(db) > self.repo.settings.storage_bytes:
            raise ServiceError(
                409, "local_assistant_storage_limit", "本地助手任务超过业务存储预算。"
            )

    def title_source(self, conversation_id):
        with self.repo.connection() as db:
            conversation = self.repo._conversation(db, conversation_id)
            first = db.execute(
                "SELECT id,record FROM turns WHERE conversation_id=? ORDER BY ordinal LIMIT 1",
                (conversation_id,),
            ).fetchone()
            if first is None:
                raise ServiceError(409, "local_assistant_no_message", "会话还没有用户消息。")
            turn = json.loads(first[1])
            owner = db.execute(
                "SELECT project_id FROM project_conversations WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            text = turn["message"][:2000].encode()[:4096].decode("utf-8", errors="ignore")
            if len(text) < len(turn["message"]) and re.match(
                r"[A-Za-z0-9_.:+/-]", turn["message"][len(text)]
            ):
                # Do not present a cut identifier/numeric token as a complete original value.
                text = re.sub(r"[A-Za-z0-9_.:+/-]+$", "", text)
            if not text.strip():
                raise ServiceError(
                    409,
                    "local_assistant_no_complete_prefix",
                    "首条问题的有限前缀没有完整文本，保留原名称。",
                )
            return (
                conversation,
                first[0],
                text,
                len(text) < len(turn["message"]),
                owner[0] if owner else None,
            )
