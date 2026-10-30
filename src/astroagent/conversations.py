"""SQLite 本机会话仓储：短事务、幂等预留、迁移与中断恢复。"""

import hashlib
import json
import multiprocessing
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from astroagent.conversation_schemas import ContextRecord, Turn
from astroagent.errors import ServiceError
from astroagent.schemas import ErrorInfo


def utc_now():
    return datetime.now(UTC).isoformat()


def encode(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def storage_error():
    return ServiceError(
        503, "conversation_storage_unavailable", "本地会话存储不可用，结果未确认保存。"
    )


def request_digest(request):
    return hashlib.sha256(encode(request.model_dump()).encode("utf-8")).hexdigest()


class ConversationRepository:
    def __init__(self, settings):
        self.settings = settings
        self.path = settings.data_dir.resolve() / "astroagent.sqlite3"
        self.lock_file = None
        self.mutex = threading.RLock()

    def initialize(self):
        if multiprocessing.parent_process() is not None or any(
            os.getenv(name, "1") != "1" for name in ("WEB_CONCURRENCY", "UVICORN_WORKERS")
        ):
            raise storage_error()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.lock_file = (self.path.parent / "service.lock").open("a+b")
            if self.lock_file.seek(0, 2) == 0:
                self.lock_file.write(b"1")
                self.lock_file.flush()
            self.lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.connection() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, 2, 3, 4):
                    raise storage_error()
                if version == 0:
                    tables = db.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                    if tables:
                        raise storage_error()
                    # Consistent SQLite backup, never a live copy of only the main file.
                    backup = self.path.with_name(
                        "migration-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".sqlite3"
                    )
                    with sqlite3.connect(backup) as target:
                        db.backup(target)
                    db.execute("BEGIN IMMEDIATE")
                    self._migrate_v1(db)
                    db.commit()
                if version < 2:
                    backup = self.path.with_name(
                        "migration-v2-"
                        + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                        + ".sqlite3"
                    )
                    with sqlite3.connect(backup) as target:
                        db.backup(target)
                    with self.transaction(db):
                        self._migrate_v2(db)
                if version < 3:
                    backup = self.path.with_name(
                        "migration-v3-"
                        + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                        + ".sqlite3"
                    )
                    with sqlite3.connect(backup) as target:
                        db.backup(target)
                    with self.transaction(db):
                        self._migrate_v3(db)
                if version < 4:
                    backup = self.path.with_name(
                        "migration-v4-"
                        + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                        + ".sqlite3"
                    )
                    with sqlite3.connect(backup) as target:
                        db.backup(target)
                    from astroagent.knowledge import migrate

                    with self.transaction(db):
                        migrate(db)
                db.execute("PRAGMA journal_mode=WAL")
                with self.transaction(db):
                    for row in db.execute(
                        "SELECT record FROM turns WHERE state='running'"
                    ).fetchall():
                        turn = Turn.model_validate_json(row[0])
                        turn.execution_status = "interrupted"
                        turn.completed_at = utc_now()
                        turn.error = ErrorInfo(
                            code="turn_interrupted",
                            message="服务重启中断了该轮，请确认后重新提问。",
                        )
                        self._save(db, turn)
                    from astroagent.projects import ProjectRepository

                    ProjectRepository.recover(db)
                    from astroagent.workflows import WorkflowRepository

                    WorkflowRepository.recover(db)
                    from astroagent.knowledge import KnowledgeRepository

                    KnowledgeRepository.recover(db)
        except (OSError, sqlite3.Error) as exc:
            self.close()
            raise storage_error() from exc
        except Exception:
            self.close()
            raise

    @staticmethod
    def _migrate_v1(db):
        db.execute("""CREATE TABLE conversations (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0)""")
        db.execute("""CREATE TABLE turns (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id)
            ON DELETE CASCADE, ordinal INTEGER NOT NULL, request_id TEXT NOT NULL,
            request_hash TEXT NOT NULL, state TEXT NOT NULL, record TEXT NOT NULL,
            size_bytes INTEGER NOT NULL, reserved_bytes INTEGER NOT NULL,
            UNIQUE(conversation_id, request_id), UNIQUE(conversation_id, ordinal))""")
        db.execute("CREATE INDEX turn_conversation ON turns(conversation_id, ordinal)")
        db.execute("PRAGMA user_version=1")

    def close(self):
        if self.lock_file is not None:
            self.lock_file.close()
            self.lock_file = None

    @staticmethod
    def _migrate_v2(db):
        db.execute(
            "ALTER TABLE conversations ADD COLUMN metadata_revision INTEGER NOT NULL DEFAULT 0"
        )
        db.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        db.execute("""CREATE TABLE project_conversations (
            conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE)""")
        db.execute("CREATE INDEX project_membership ON project_conversations(project_id)")
        db.execute("""CREATE TABLE snapshots (id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            record TEXT NOT NULL)""")
        db.execute("CREATE INDEX snapshot_project ON snapshots(project_id)")
        db.execute("""CREATE TABLE reruns (id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            request_id TEXT NOT NULL, request_hash TEXT NOT NULL, state TEXT NOT NULL,
            record TEXT NOT NULL, reserved_bytes INTEGER NOT NULL DEFAULT 0,
            UNIQUE(project_id,request_id))""")
        db.execute("CREATE INDEX rerun_project ON reruns(project_id)")
        db.execute("""CREATE TABLE imported_turn_origins (
            turn_id TEXT PRIMARY KEY REFERENCES turns(id) ON DELETE CASCADE,
            record TEXT NOT NULL)""")
        db.execute("PRAGMA user_version=2")

    @staticmethod
    def _migrate_v3(db):
        db.execute("""CREATE TABLE workflows (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            state TEXT NOT NULL, record TEXT NOT NULL,
            reserved_bytes INTEGER NOT NULL DEFAULT 0)""")
        db.execute("CREATE INDEX workflow_project ON workflows(project_id)")
        db.execute("""CREATE TABLE workflow_operations (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            request_id TEXT NOT NULL, request_hash TEXT NOT NULL, state TEXT NOT NULL,
            record TEXT NOT NULL, reserved_bytes INTEGER NOT NULL DEFAULT 0,
            UNIQUE(run_id, request_id))""")
        db.execute("""CREATE TABLE workflow_outputs (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            record TEXT NOT NULL, content BLOB NOT NULL)""")
        db.execute("""CREATE TABLE workflow_snapshot_refs (
            run_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE RESTRICT,
            PRIMARY KEY(run_id,snapshot_id))""")
        db.execute("PRAGMA user_version=3")

    @contextmanager
    def connection(self):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=0.5, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            yield db
        except (sqlite3.Error, OSError, ValueError) as exc:
            raise storage_error() from exc
        finally:
            if db is not None:
                db.close()

    @staticmethod
    @contextmanager
    def transaction(db):
        db.execute("BEGIN IMMEDIATE")
        try:
            yield
            db.commit()
        except BaseException:
            db.rollback()
            raise

    @staticmethod
    def _conversation(db, identifier):
        row = db.execute("SELECT * FROM conversations WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ServiceError(404, "conversation_not_found", "会话不存在。")
        return dict(row)

    @staticmethod
    def _idle(db, identifier):
        if db.execute(
            "SELECT 1 FROM turns WHERE conversation_id=? AND state='running'", (identifier,)
        ).fetchone():
            raise ServiceError(409, "conversation_busy", "该会话正在处理，请稍后再试。")

    @staticmethod
    def _touch_project(db, identifier):
        row = db.execute(
            "SELECT p.record FROM projects p JOIN project_conversations m "
            "ON p.id=m.project_id WHERE m.conversation_id=?",
            (identifier,),
        ).fetchone()
        if row:
            value = json.loads(row[0])
            value["revision"] += 1
            value["updated_at"] = utc_now()
            db.execute("UPDATE projects SET record=? WHERE id=?", (encode(value), value["id"]))

    @staticmethod
    def _used(db):
        from astroagent.knowledge import used_bytes

        turns = db.execute(
            "SELECT coalesce(sum(size_bytes+reserved_bytes),0) FROM turns"
        ).fetchone()[0]
        base = (
            used_bytes(db)
            + turns
            + sum(
                len(encode(dict(row)).encode()) for row in db.execute("SELECT * FROM conversations")
            )
        )
        for table in (
            "projects",
            "snapshots",
            "reruns",
            "imported_turn_origins",
            "workflows",
            "workflow_operations",
            "workflow_outputs",
        ):
            base += sum(len(row[0].encode()) for row in db.execute(f"SELECT record FROM {table}"))
        base += db.execute("SELECT coalesce(sum(reserved_bytes),0) FROM reruns").fetchone()[0]
        for table in ("workflows", "workflow_operations"):
            base += db.execute(f"SELECT coalesce(sum(reserved_bytes),0) FROM {table}").fetchone()[0]
        base += db.execute(
            "SELECT coalesce(sum(length(content)),0) FROM workflow_outputs"
        ).fetchone()[0]
        base += sum(
            len(encode(dict(row)).encode())
            for row in db.execute("SELECT * FROM workflow_snapshot_refs")
        )
        return base + sum(
            len(encode(dict(r)).encode()) for r in db.execute("SELECT * FROM project_conversations")
        )

    def create(self, title):
        with self.connection() as db, self.transaction(db):
            if (
                db.execute("SELECT count(*) FROM conversations").fetchone()[0]
                >= self.settings.max_conversations
            ):
                raise ServiceError(
                    409, "conversation_limit_reached", "会话已满，请整理历史后再新建。"
                )
            value = dict(
                id=str(uuid4()),
                title=title,
                created_at=utc_now(),
                updated_at=utc_now(),
                revision=0,
                metadata_revision=0,
            )
            if self._used(db) + len(encode(value).encode()) > self.settings.storage_bytes:
                raise ServiceError(
                    409, "conversation_storage_limit", "本地历史预算已满，请整理会话。"
                )
            db.execute(
                "INSERT INTO conversations VALUES "
                "(:id,:title,:created_at,:updated_at,:revision,:metadata_revision)",
                value,
            )
            return value

    def list(self):
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM conversations ORDER BY updated_at DESC,id")
            ]

    def detail(self, identifier):
        with self.connection() as db:
            value = self._conversation(db, identifier)
            turns = [
                Turn.model_validate_json(r[0])
                for r in db.execute(
                    "SELECT record FROM turns WHERE conversation_id=? ORDER BY ordinal",
                    (identifier,),
                )
            ]
            value["turns"] = [
                {
                    **t.model_dump(
                        include={
                            "turn_id",
                            "revision",
                            "message",
                            "execution_status",
                            "received_at",
                            "completed_at",
                        }
                    ),
                    "response_status": t.response.status if t.response else None,
                }
                for t in turns
            ]
            return value

    def rename(self, identifier, title, expected_metadata_revision=None):
        with self.connection() as db, self.transaction(db):
            previous = self._conversation(db, identifier)
            if (
                expected_metadata_revision is not None
                and previous["metadata_revision"] != expected_metadata_revision
            ):
                raise ServiceError(409, "conversation_revision_conflict", "会话已更新，请刷新。")
            self._idle(db, identifier)
            updated_at = utc_now()
            candidate = {
                **previous,
                "title": title,
                "updated_at": updated_at,
                "metadata_revision": previous["metadata_revision"] + 1,
            }
            if (
                self._used(db) - len(encode(previous).encode()) + len(encode(candidate).encode())
                > self.settings.storage_bytes
            ):
                raise ServiceError(
                    409, "conversation_storage_limit", "本地历史预算已满，请整理会话。"
                )
            db.execute(
                "UPDATE conversations SET title=?,updated_at=?,"
                "metadata_revision=metadata_revision+1 WHERE id=?",
                (title, updated_at, identifier),
            )
            self._touch_project(db, identifier)
            if self._used(db) > self.settings.storage_bytes:
                raise ServiceError(
                    409, "conversation_storage_limit", "项目历史预算已满，未保存改名。"
                )
            return self._conversation(db, identifier)

    def delete(self, identifier):
        with self.connection() as db, self.transaction(db):
            self._conversation(db, identifier)
            self._idle(db, identifier)
            from astroagent.projects import ProjectRepository

            owner = db.execute(
                "SELECT project_id FROM project_conversations WHERE conversation_id=?",
                (identifier,),
            ).fetchone()
            if owner:
                ProjectRepository._idle(db, owner[0])
            ProjectRepository.detach_conversation(db, identifier)
            db.execute("DELETE FROM conversations WHERE id=?", (identifier,))

    def turn(self, identifier, turn_id):
        with self.connection() as db:
            self._conversation(db, identifier)
            row = db.execute(
                "SELECT record FROM turns WHERE id=? AND conversation_id=?", (turn_id, identifier)
            ).fetchone()
            if row is None:
                raise ServiceError(404, "turn_not_found", "该会话中没有此轮记录。")
            return Turn.model_validate_json(row[0])

    def history(self, identifier):
        with self.connection() as db:
            return [
                Turn.model_validate_json(r[0])
                for r in db.execute(
                    "SELECT record FROM turns WHERE conversation_id=? ORDER BY ordinal",
                    (identifier,),
                )
            ]

    def existing(self, identifier, request):
        with self.connection() as db:
            self._conversation(db, identifier)
            row = db.execute(
                "SELECT request_hash,record FROM turns WHERE conversation_id=? AND request_id=?",
                (identifier, request.client_request_id),
            ).fetchone()
            if row is None:
                return None
            if row[0] != request_digest(request):
                raise ServiceError(409, "request_id_conflict", "这个请求编号已用于另一条问题。")
            return Turn.model_validate_json(row[1])

    def reserve(self, identifier, request):
        with self.connection() as db, self.transaction(db):
            conversation = self._conversation(db, identifier)
            self._idle(db, identifier)
            if conversation["revision"] != request.expected_revision:
                raise ServiceError(
                    409, "conversation_revision_conflict", "会话已更新，请刷新后再发送。"
                )
            if conversation["revision"] >= self.settings.max_turns:
                raise ServiceError(
                    409, "conversation_limit_reached", "该会话轮次已满，请新建会话。"
                )
            used = self._used(db)
            if used + self.settings.turn_bytes + 32768 > self.settings.storage_bytes:
                raise ServiceError(
                    409, "conversation_storage_limit", "本地历史预算已满，请整理会话后再提交。"
                )
            turn = Turn(
                conversation_id=identifier,
                turn_id=str(uuid4()),
                revision=conversation["revision"] + 1,
                client_request_id=request.client_request_id,
                message=request.message,
                execution_status="running",
                received_at=utc_now(),
            )
            text = turn.model_dump_json()
            db.execute(
                "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    turn.turn_id,
                    identifier,
                    turn.revision,
                    request.client_request_id,
                    request_digest(request),
                    "running",
                    text,
                    len(text.encode()),
                    max(0, self.settings.turn_bytes - len(text.encode())) + 32768,
                ),
            )
            db.execute(
                "UPDATE conversations SET revision=?,updated_at=? WHERE id=?",
                (turn.revision, utc_now(), identifier),
            )
            self._touch_project(db, identifier)
            if self._used(db) > self.settings.storage_bytes:
                raise ServiceError(
                    409, "conversation_storage_limit", "项目历史预算已满，未执行查询。"
                )
            return turn

    @staticmethod
    def _save(db, turn):
        text = turn.model_dump_json()
        db.execute(
            "UPDATE turns SET state=?,record=?,size_bytes=?,reserved_bytes=0 WHERE id=?",
            (turn.execution_status, text, len(text.encode()), turn.turn_id),
        )
        db.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?", (utc_now(), turn.conversation_id)
        )
        ConversationRepository._touch_project(db, turn.conversation_id)

    def finish(self, turn):
        text = turn.model_dump_json()
        if len(text.encode()) > self.settings.turn_bytes:
            turn.response = None
            turn.context = ContextRecord(warnings=["完整结果超出单轮存储上限，未裁剪保存。"])
            turn.execution_status = "failed"
            turn.error = ErrorInfo(
                code="turn_result_too_large", message="完整结果超出单轮存储上限，未保存数据。"
            )
        with self.connection() as db, self.transaction(db):
            self._save(db, turn)
        return turn
