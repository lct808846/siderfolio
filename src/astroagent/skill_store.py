"""租户隔离的 V2.1 个人技能偏好与外部 MCP 查询确认存储。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from astroagent.errors import ServiceError
from astroagent.skill_schemas import SkillPreferences
from astroagent.tool_schemas import (
    ExternalMcpConfirmationRecord,
    ExternalMcpProposal,
    ExternalMcpResult,
)

PREFERENCES_KEY = "user_skill_preferences_v1"

DDL = (
    "CREATE TABLE IF NOT EXISTS skill_meta (version INTEGER PRIMARY KEY CHECK (version=1))",
    (
        "CREATE TABLE IF NOT EXISTS skill_preferences ("
        "key TEXT PRIMARY KEY, "
        "record TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    ),
    (
        "CREATE TABLE IF NOT EXISTS external_mcp_confirmations ("
        "confirmation_id TEXT PRIMARY KEY, "
        "conversation_id TEXT NOT NULL, "
        "turn_id TEXT NOT NULL, "
        "project_id TEXT, "
        "server_id TEXT NOT NULL, "
        "tool_id TEXT NOT NULL, "
        "definition_sha256 TEXT NOT NULL, "
        "arguments_sha256 TEXT NOT NULL, "
        "status TEXT NOT NULL, "
        "client_request_id TEXT, "
        "expires_at TEXT NOT NULL, "
        "created_at TEXT NOT NULL, "
        "record TEXT NOT NULL)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_ext_mcp_confirm_turn "
        "ON external_mcp_confirmations (conversation_id, turn_id, created_at)"
    ),
    "INSERT INTO skill_meta(version) VALUES(1) ON CONFLICT (version) DO NOTHING",
)


def ready(db) -> bool:
    if getattr(db, "dialect", None) != "postgresql":
        return False
    if not db.execute("SELECT to_regclass('skill_meta')").fetchone()[0]:
        return False
    row = db.execute("SELECT version FROM skill_meta").fetchone()
    return bool(row and row[0] == 1)


class SkillStore:
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

    def get_preferences(self) -> SkillPreferences:
        with self.repo.connection() as db:
            if not ready(db):
                return SkillPreferences()
            row = db.execute(
                "SELECT record FROM skill_preferences WHERE key=?",
                (PREFERENCES_KEY,),
            ).fetchone()
            if row is None:
                return SkillPreferences()
            parsed = SkillPreferences.model_validate_json(row[0])
            return SkillPreferences(auto_match=True, disabled_skill_ids=parsed.disabled_skill_ids)

    def save_preferences(self, prefs: SkillPreferences) -> SkillPreferences:
        enforced = SkillPreferences(auto_match=True, disabled_skill_ids=prefs.disabled_skill_ids)
        now = datetime.now(UTC).isoformat()
        payload = enforced.model_dump_json()
        with self.repo.connection() as db, self.repo.transaction(db):
            self._ensure_ready(db)
            db.execute(
                "INSERT INTO skill_preferences (key, record, updated_at) VALUES (?,?,?) "
                "ON CONFLICT (key) DO UPDATE SET "
                "record=EXCLUDED.record, updated_at=EXCLUDED.updated_at",
                (PREFERENCES_KEY, payload, now),
            )
        return enforced

    def save_proposal(self, proposal: ExternalMcpProposal) -> ExternalMcpConfirmationRecord:
        record = ExternalMcpConfirmationRecord(proposal=proposal, result=None)
        payload = json.dumps(
            record.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
        )
        with self.repo.connection() as db, self.repo.transaction(db):
            self._ensure_ready(db)
            db.execute(
                "INSERT INTO external_mcp_confirmations "
                "(confirmation_id, conversation_id, turn_id, project_id, server_id, tool_id, "
                "definition_sha256, arguments_sha256, status, client_request_id, expires_at, "
                "created_at, record) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT (confirmation_id) DO UPDATE SET "
                "status=EXCLUDED.status, record=EXCLUDED.record",
                (
                    proposal.confirmation_id,
                    proposal.conversation_id,
                    proposal.turn_id,
                    proposal.project_id,
                    proposal.server_id,
                    proposal.tool_id,
                    proposal.definition_sha256,
                    proposal.arguments_sha256,
                    proposal.status,
                    None,
                    proposal.expires_at,
                    proposal.created_at,
                    payload,
                ),
            )
        return record

    def get_confirmation(
        self, conversation_id: str, turn_id: str, confirmation_id: str
    ) -> tuple[ExternalMcpConfirmationRecord, str | None]:
        with self.repo.connection() as db:
            if not ready(db):
                raise ServiceError(404, "confirmation_not_found", "外部查询确认记录不存在。")
            row = db.execute(
                "SELECT record, client_request_id FROM external_mcp_confirmations "
                "WHERE confirmation_id=? AND conversation_id=? AND turn_id=?",
                (confirmation_id, conversation_id, turn_id),
            ).fetchone()
            if row is None:
                raise ServiceError(404, "confirmation_not_found", "外部查询确认记录不存在。")
            return ExternalMcpConfirmationRecord.model_validate_json(row[0]), row[1]

    def update_confirmation(
        self,
        record: ExternalMcpConfirmationRecord,
        *,
        client_request_id: str | None = None,
    ) -> ExternalMcpConfirmationRecord:
        payload = json.dumps(
            record.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
        )
        with self.repo.connection() as db, self.repo.transaction(db):
            self._ensure_ready(db)
            db.execute(
                "UPDATE external_mcp_confirmations SET status=?, client_request_id=?, record=? "
                "WHERE confirmation_id=?",
                (
                    record.proposal.status,
                    client_request_id,
                    payload,
                    record.proposal.confirmation_id,
                ),
            )
        return record

    def records_for_turn_with_db(
        self, db, conversation_id: str, turn_id: str
    ) -> list[ExternalMcpConfirmationRecord]:
        if not ready(db):
            return []
        rows = db.execute(
            "SELECT record FROM external_mcp_confirmations "
            "WHERE conversation_id=? AND turn_id=? ORDER BY created_at",
            (conversation_id, turn_id),
        ).fetchall()
        return [ExternalMcpConfirmationRecord.model_validate_json(row[0]) for row in rows]

    def records_for_conversation_with_db(
        self, db, conversation_id: str
    ) -> dict[str, list[ExternalMcpConfirmationRecord]]:
        if not ready(db):
            return {}
        rows = db.execute(
            "SELECT turn_id, record FROM external_mcp_confirmations "
            "WHERE conversation_id=? ORDER BY created_at",
            (conversation_id,),
        ).fetchall()
        grouped: dict[str, list[ExternalMcpConfirmationRecord]] = {}
        for row in rows:
            grouped.setdefault(row[0], []).append(
                ExternalMcpConfirmationRecord.model_validate_json(row[1])
            )
        return grouped

    def delete_conversation(self, conversation_id: str) -> None:
        with self.repo.connection() as db, self.repo.transaction(db):
            if ready(db):
                db.execute(
                    "DELETE FROM external_mcp_confirmations WHERE conversation_id=?",
                    (conversation_id,),
                )


def merge_confirmations_into_turn(turn, records: list[ExternalMcpConfirmationRecord]) -> None:
    """Sync live confirmation statuses & results onto Turn and ChatResponse."""
    if not records:
        return
    proposals_by_id: dict[str, ExternalMcpProposal] = {}
    results_by_id: dict[str, ExternalMcpResult] = {}
    for rec in records:
        proposals_by_id[rec.proposal.confirmation_id] = rec.proposal
        if rec.result is not None:
            results_by_id[rec.proposal.confirmation_id] = rec.result
    if turn.response is not None:
        existing_props = list(turn.response.external_mcp_proposals or [])
        merged_props: list[ExternalMcpProposal] = []
        seen_ids: set[str] = set()
        for prop in existing_props:
            merged_props.append(proposals_by_id.get(prop.confirmation_id, prop))
            seen_ids.add(prop.confirmation_id)
        for cid, prop in proposals_by_id.items():
            if cid not in seen_ids:
                merged_props.append(prop)
        turn.response.external_mcp_proposals = merged_props

        existing_res = list(turn.response.external_mcp_results or [])
        merged_res: list[ExternalMcpResult] = []
        seen_res: set[str] = set()
        for res in existing_res:
            merged_res.append(results_by_id.get(res.confirmation_id, res))
            seen_res.add(res.confirmation_id)
        for cid, res in results_by_id.items():
            if cid not in seen_res:
                merged_res.append(res)
        turn.response.external_mcp_results = merged_res
