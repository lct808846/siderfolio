"""租户隔离的脱敏运行追踪存储（有界容量与 30 天保留期）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from astroagent.trace_schemas import RunTrace

MAX_TRACES_PER_ACCOUNT = 300
RETENTION_DAYS = 30

DDL = (
    "CREATE TABLE IF NOT EXISTS run_trace_meta (version INTEGER PRIMARY KEY CHECK (version=1))",
    (
        "CREATE TABLE IF NOT EXISTS run_traces ("
        "turn_id TEXT PRIMARY KEY, "
        "conversation_id TEXT NOT NULL, "
        "trace_id TEXT NOT NULL, "
        "created_at TEXT NOT NULL, "
        "record TEXT NOT NULL)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_run_traces_conversation "
        "ON run_traces (conversation_id, created_at DESC)"
    ),
    "CREATE INDEX IF NOT EXISTS idx_run_traces_created ON run_traces (created_at DESC)",
    "INSERT INTO run_trace_meta(version) VALUES(1) ON CONFLICT (version) DO NOTHING",
)


def ready(db) -> bool:
    if getattr(db, "dialect", None) != "postgresql":
        return False
    if not db.execute("SELECT to_regclass('run_trace_meta')").fetchone()[0]:
        return False
    row = db.execute("SELECT version FROM run_trace_meta").fetchone()
    return bool(row and row[0] == 1)


def used(db) -> int:
    if not ready(db):
        return 0
    return int(
        db.execute(
            "SELECT COALESCE((SELECT SUM(octet_length(record)) FROM run_traces), 0)"
        ).fetchone()[0]
    )


class TraceStore:
    def __init__(self, repo):
        self.repo = repo

    def initialize(self) -> None:
        with self.repo.connection() as db, self.repo.transaction(db):
            for statement in DDL:
                db.execute(statement)

    def _ensure_ready(self, db) -> None:
        if not ready(db):
            for statement in DDL:
                db.execute(statement)

    def save(self, trace: RunTrace) -> None:
        payload = json.dumps(
            trace.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        cutoff = (datetime.now(UTC) - timedelta(days=RETENTION_DAYS)).isoformat()
        with self.repo.connection() as db, self.repo.transaction(db):
            self._ensure_ready(db)
            db.execute(
                "INSERT INTO run_traces (turn_id,conversation_id,trace_id,created_at,record) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT (turn_id) DO UPDATE SET "
                "trace_id=EXCLUDED.trace_id, created_at=EXCLUDED.created_at, record=EXCLUDED.record",
                (
                    trace.turn_id,
                    trace.conversation_id,
                    trace.trace_id,
                    trace.started_at,
                    payload,
                ),
            )
            db.execute("DELETE FROM run_traces WHERE created_at < ?", (cutoff,))
            stale = db.execute(
                "SELECT turn_id FROM run_traces ORDER BY created_at DESC OFFSET ?",
                (MAX_TRACES_PER_ACCOUNT,),
            ).fetchall()
            for row in stale:
                db.execute("DELETE FROM run_traces WHERE turn_id=?", (row[0],))

    @staticmethod
    def get_with_db(db, conversation_id: str, turn_id: str) -> RunTrace | None:
        if not ready(db):
            return None
        row = db.execute(
            "SELECT record FROM run_traces WHERE conversation_id=? AND turn_id=?",
            (conversation_id, turn_id),
        ).fetchone()
        if row is None:
            return None
        return RunTrace.model_validate_json(row[0])

    @staticmethod
    def get_for_conversation_with_db(db, conversation_id: str) -> dict[str, RunTrace]:
        if not ready(db):
            return {}
        rows = db.execute(
            "SELECT turn_id, record FROM run_traces WHERE conversation_id=?",
            (conversation_id,),
        ).fetchall()
        return {row[0]: RunTrace.model_validate_json(row[1]) for row in rows}

    def get(self, conversation_id: str, turn_id: str) -> RunTrace | None:
        with self.repo.connection() as db:
            return self.get_with_db(db, conversation_id, turn_id)

    def delete_conversation(self, conversation_id: str) -> None:
        with self.repo.connection() as db, self.repo.transaction(db):
            if ready(db):
                db.execute("DELETE FROM run_traces WHERE conversation_id=?", (conversation_id,))
