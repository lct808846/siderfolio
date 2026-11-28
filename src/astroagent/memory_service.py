"""V2.2 长期记忆、跨会话历史检索与长对话摘要协调服务。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from uuid import uuid4

from astroagent.conversation_schemas import Turn
from astroagent.conversations import utc_now
from astroagent.embeddings import LocalEmbedder
from astroagent.errors import ServiceError
from astroagent.knowledge_text import checksum
from astroagent.memory_extractor import (
    build_local_conversation_summary,
    classify_memory_category,
    compute_omitted_turns_sha256,
    contains_policy_override,
    contains_sensitive_data,
    extract_rule_candidates,
    infer_query_category_boosts,
    memory_dedup_key,
    normalize_memory_text,
    parse_explicit_remember,
    score_lexical_relevance,
    select_summary_source_turns,
)
from astroagent.memory_schemas import (
    MAX_HISTORY_SNIPPETS,
    MAX_INJECTED_MEMORIES,
    MAX_MEMORIES_PER_ACCOUNT,
    MAX_SUMMARY_BYTES,
    PRESERVED_RECORD_CATEGORIES,
    ConversationSummaryRecord,
    HistorySnippet,
    MemoryCandidate,
    MemoryCandidateListResponse,
    MemoryCandidateReviewRequest,
    MemoryCandidateReviewResponse,
    MemoryContextTrace,
    MemoryCreateRequest,
    MemoryHistoryRef,
    MemoryItem,
    MemoryListResponse,
    MemoryPreferences,
    MemoryPreferencesUpdate,
    MemorySaveReceipt,
    MemoryScope,
    MemorySource,
    MemoryStatusResponse,
    MemorySummaryOverview,
    MemorySummarySection,
    MemoryUpdateRequest,
    MemoryVectorStatus,
    RetrievalMode,
)
from astroagent.memory_store import MemoryStore

LOGGER = logging.getLogger(__name__)
MAX_CROSS_SESSION_SCAN_TURNS = 200
HISTORY_MIN_RELEVANCE = 2.0
MEMORY_MIN_RELEVANCE = 2.0


@dataclass
class TurnMemoryBundle:
    memories: list[MemoryItem] = field(default_factory=list)
    history_snippets: list[HistorySnippet] = field(default_factory=list)
    summary: ConversationSummaryRecord | None = None
    trace: MemoryContextTrace = field(default_factory=MemoryContextTrace)
    memory_hint: str = ""


class MemoryService:
    def __init__(self, conversations, settings=None, *, store: MemoryStore | None = None):
        self.conversations = conversations
        self.repo = conversations.repository
        self.settings = settings if settings is not None else getattr(self.repo, "settings", None)
        self.store = store if store is not None else MemoryStore(self.repo)
        self.embedder = LocalEmbedder(self.settings) if self.settings is not None else None

    def initialize(self) -> None:
        self.store.initialize()

    def _resolve_custom_project_id(self, db, project_id: str | None) -> str | None:
        if not project_id:
            return None
        default_id = self.store.default_project_id(db)
        if default_id and project_id == default_id:
            return None
        return project_id

    def _verify_project_scope(self, db, scope: MemoryScope, project_id: str | None) -> str | None:
        if scope == "global":
            if project_id is not None:
                raise ServiceError(422, "memory_scope_invalid", "全局个人记忆不能绑定项目。")
            return None
        if not project_id:
            raise ServiceError(422, "memory_scope_invalid", "项目记忆必须指定有效的所属项目。")
        exists, name, is_default = self.store.project_exists(db, project_id)
        if not exists:
            raise ServiceError(404, "project_not_found", "所选项目不存在或无访问权限。")
        if is_default:
            raise ServiceError(
                422,
                "memory_scope_invalid",
                "个人空间（默认）请使用「全局个人」范围，项目记忆仅绑定具体科研项目。",
            )
        return name

    def get_preferences(self) -> MemoryPreferences:
        return self.store.get_preferences()

    def update_preferences(self, body: MemoryPreferencesUpdate) -> MemoryPreferences:
        return self.store.save_preferences(
            auto_extract=body.auto_extract,
            cross_session_injection=body.cross_session_injection,
            history_retrieval=body.history_retrieval,
            expected_revision=body.expected_revision,
        )

    def vector_status(self) -> MemoryVectorStatus:
        active_memories = self.store.list_memories(status="active")
        if self.settings is None or self.embedder is None:
            return MemoryVectorStatus(
                embedding_configured=False,
                semantic_ready=False,
                active_memory_count=len(active_memories),
                degraded_reason="embedding_not_configured",
            )
        configured = bool(self.settings.rag_model_path and self.settings.rag_model_sha256)
        if not configured:
            return MemoryVectorStatus(
                embedding_configured=False,
                semantic_ready=False,
                model_name=self.settings.rag_model_name,
                dimension=self.settings.rag_dimension,
                active_memory_count=len(active_memories),
                degraded_reason="embedding_not_configured",
            )
        if not getattr(self.settings, "rag_semantic_enabled", True):
            return MemoryVectorStatus(
                embedding_configured=True,
                semantic_ready=False,
                model_name=self.settings.rag_model_name,
                dimension=self.settings.rag_dimension,
                active_memory_count=len(active_memories),
                degraded_reason="semantic_disabled",
            )
        try:
            model_sha = self.embedder.identity()
        except ServiceError as exc:
            return MemoryVectorStatus(
                embedding_configured=True,
                semantic_ready=False,
                model_name=self.settings.rag_model_name,
                dimension=self.settings.rag_dimension,
                active_memory_count=len(active_memories),
                degraded_reason=exc.error.code,
            )
        indexed = self.store.vector_indexed_count(
            model_sha256=model_sha, dimension=self.settings.rag_dimension
        )
        return MemoryVectorStatus(
            embedding_configured=True,
            semantic_ready=True,
            model_name=self.settings.rag_model_name,
            dimension=self.settings.rag_dimension,
            indexed_count=indexed,
            active_memory_count=len(active_memories),
            degraded_reason=None if indexed >= len(active_memories) else "index_incomplete",
        )

    def rebuild_vectors(self) -> MemoryVectorStatus:
        status = self.vector_status()
        if not status.semantic_ready or self.embedder is None or self.settings is None:
            return status
        active = self.store.list_memories(status="active")
        if not active:
            return self.vector_status()
        try:
            model_sha = self.embedder.identity()
            vectors = self.embedder.encode([item.summary for item in active])
            for item, vec in zip(active, vectors, strict=True):
                self.store.upsert_vector(
                    item.id,
                    model_sha256=model_sha,
                    dimension=self.settings.rag_dimension,
                    text_sha256=checksum(item.summary),
                    vector=vec,
                )
        except ServiceError as exc:
            return status.model_copy(
                update={"semantic_ready": False, "degraded_reason": exc.error.code}
            )
        return self.vector_status()

    def summary_overview(self) -> MemorySummaryOverview:
        """Synthesize a high-level narrative memory summary without exposing raw item records."""
        prefs = self.store.get_preferences()
        enabled = bool(
            prefs.auto_extract or prefs.cross_session_injection or prefs.history_retrieval
        )
        active = self.store.list_memories(status="active")
        if not active:
            return MemorySummaryOverview(
                enabled=enabled,
                has_memory=False,
                summary_text="",
                sections=[],
                updated_at=prefs.updated_at,
                preferences=prefs,
            )

        def _join_clauses(items: list[MemoryItem], *, max_chars: int = 420) -> str:
            clauses: list[str] = []
            seen: set[str] = set()
            total = 0
            for item in items:
                text = item.summary.strip().rstrip("。！？!?;；")
                if not text:
                    continue
                if item.scope == "project" and item.project_name:
                    text = f"在「{item.project_name}」项目中，{text}"
                norm = normalize_memory_text(text)
                if norm in seen:
                    continue
                seen.add(norm)
                if total + len(text) > max_chars and clauses:
                    break
                clauses.append(text)
                total += len(text)
            if not clauses:
                return ""
            return "；".join(clauses) + "。"

        focus_items = [
            m
            for m in active
            if m.scope == "global" and m.category in ("research_focus", "background")
        ]
        habit_items = [
            m for m in active if m.scope == "global" and m.category in ("tool_habit", "preference")
        ]
        project_items = [m for m in active if m.scope == "project"]
        other_items = [
            m
            for m in active
            if m.scope == "global"
            and m.category not in ("research_focus", "background", "tool_habit", "preference")
        ]

        sections: list[MemorySummarySection] = []
        if focus_items:
            sections.append(
                MemorySummarySection(title="研究方向与背景", content=_join_clauses(focus_items))
            )
        if habit_items:
            sections.append(
                MemorySummarySection(title="常用工具与偏好", content=_join_clauses(habit_items))
            )
        if project_items:
            sections.append(
                MemorySummarySection(title="科研项目脉络", content=_join_clauses(project_items))
            )
        if other_items:
            sections.append(
                MemorySummarySection(title="补充信息", content=_join_clauses(other_items))
            )

        summary_text = "\n".join(f"{sec.title}：{sec.content}" for sec in sections if sec.content)
        latest_updated = max(
            (m.updated_at for m in active if m.updated_at), default=prefs.updated_at
        )
        return MemorySummaryOverview(
            enabled=enabled,
            has_memory=bool(sections),
            summary_text=summary_text,
            sections=sections,
            updated_at=latest_updated,
            preferences=prefs,
        )

    def status(self) -> MemoryStatusResponse:
        prefs = self.store.get_preferences()
        all_items = self.store.list_memories(include_superseded=False)
        pending = self.store.list_candidates(status="pending")
        return MemoryStatusResponse(
            preferences=prefs,
            active_global_count=sum(
                1 for item in all_items if item.status == "active" and item.scope == "global"
            ),
            active_project_count=sum(
                1 for item in all_items if item.status == "active" and item.scope == "project"
            ),
            paused_count=sum(1 for item in all_items if item.status == "paused"),
            pending_candidate_count=len(pending),
            summary_count=self.store.summary_count(),
            vector_status=self.vector_status(),
        )

    def list_memories(
        self,
        *,
        scope: str | None = None,
        project_id: str | None = None,
        category: str | None = None,
        status: str | None = None,
        q: str | None = None,
        include_superseded: bool = False,
    ) -> MemoryListResponse:
        if project_id:
            with self.repo.connection() as db:
                exists, _, _ = self.store.project_exists(db, project_id)
                if not exists:
                    raise ServiceError(404, "project_not_found", "项目不存在。")
        items = self.store.list_memories(
            scope=scope,
            project_id=project_id,
            category=category,
            status=status,
            include_superseded=include_superseded,
        )
        if q and q.strip():
            query = q.strip()
            norm_q = normalize_memory_text(query)
            scored: list[tuple[float, MemoryItem]] = []
            for item in items:
                norm_sum = normalize_memory_text(item.summary)
                if norm_q and norm_q in norm_sum:
                    scored.append((10.0, item))
                    continue
                s = score_lexical_relevance(query, norm_sum)
                if s > 0:
                    scored.append((s, item))
            scored.sort(key=lambda pair: (-pair[0], pair[1].updated_at), reverse=False)
            items = [pair[1] for pair in scored]
        return MemoryListResponse(
            items=items,
            total=len(items),
            preferences=self.store.get_preferences(),
        )

    @staticmethod
    def _find_scope_matches(
        db,
        *,
        scope: MemoryScope,
        project_id: str | None,
        category: str,
        normalized_key: str,
    ) -> tuple[MemoryItem | None, MemoryItem | None]:
        """Return (exact_duplicate, category_conflict) among active items in the same scope."""
        if project_id is None:
            rows = db.execute(
                "SELECT record FROM memories WHERE status='active' AND scope=? "
                "AND project_id IS NULL",
                (scope,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT record FROM memories WHERE status='active' AND scope=? AND project_id=?",
                (scope, project_id),
            ).fetchall()
        conflict = None
        for row in rows:
            item = MemoryItem.model_validate_json(row[0])
            if item.status != "active" or item.scope != scope or item.project_id != project_id:
                continue
            if item.category != category:
                continue
            if item.normalized_key == normalized_key:
                return item, conflict
            if conflict is None and category not in PRESERVED_RECORD_CATEGORIES:
                conflict = item
        return None, conflict

    @staticmethod
    def _require_memory_capacity(db) -> None:
        count = db.execute("SELECT COUNT(*) FROM memories WHERE status != 'superseded'").fetchone()[
            0
        ]
        if count >= MAX_MEMORIES_PER_ACCOUNT:
            raise ServiceError(
                409,
                "memory_limit_reached",
                f"单账号最多保存 {MAX_MEMORIES_PER_ACCOUNT} 条有效记忆，请先整理旧记录。",
            )

    def create_memory(self, body: MemoryCreateRequest) -> MemoryItem:
        sensitive = contains_sensitive_data(body.summary)
        if sensitive:
            raise ServiceError(
                422,
                "memory_sensitive_rejected",
                "记忆内容疑似包含密钥、密码或个人敏感联系方式，无法保存。",
            )
        override = contains_policy_override(body.summary)
        if override:
            raise ServiceError(
                422,
                "memory_policy_rejected",
                "记忆内容不能用于授权工具自动执行或覆盖系统安全规则。",
            )
        now = utc_now()
        resolved_category = body.category or classify_memory_category(
            body.summary, scope=body.scope
        )
        dedup = memory_dedup_key(resolved_category, body.summary)
        with self.repo.connection() as db, self.repo.transaction(db):
            self.store._ensure_ready(db)
            project_name = self._verify_project_scope(db, body.scope, body.project_id)
            exact, conflict = self._find_scope_matches(
                db,
                scope=body.scope,
                project_id=body.project_id,
                category=resolved_category,
                normalized_key=dedup,
            )
            if exact is not None:
                if project_name:
                    exact.project_name = project_name
                return exact

            supersedes_id = None
            if conflict is not None and body.conflict_resolution == "replace":
                conflict.status = "superseded"
                conflict.revision += 1
                conflict.updated_at = now
                self.store.save_memory_with_db(db, conflict)
                supersedes_id = conflict.id
            elif conflict is not None and body.conflict_resolution == "merge":
                conflict.summary = body.summary
                conflict.normalized_key = dedup
                conflict.revision += 1
                conflict.updated_at = now
                conflict.source = MemorySource(
                    source_type="manual",
                    source_label="用户手工录入",
                    project_id=body.project_id,
                    verification_status=body.verification_status,
                    validity="valid",
                )
                if project_name:
                    conflict.project_name = project_name
                self.store.save_memory_with_db(db, conflict)
                return conflict
            else:
                self._require_memory_capacity(db)

            item = MemoryItem(
                id=str(uuid4()),
                scope=body.scope,
                project_id=body.project_id,
                project_name=project_name,
                category=resolved_category,
                summary=body.summary,
                normalized_key=dedup,
                status="active",
                revision=1,
                supersedes_memory_id=supersedes_id,
                source=MemorySource(
                    source_type="manual",
                    source_label="用户手工录入",
                    project_id=body.project_id,
                    verification_status=body.verification_status,
                    validity="valid",
                ),
                created_at=now,
                updated_at=now,
            )
            self.store.save_memory_with_db(db, item)
            return item

    def update_memory(self, memory_id: str, body: MemoryUpdateRequest) -> MemoryItem:
        if body.summary is not None:
            if contains_sensitive_data(body.summary):
                raise ServiceError(
                    422,
                    "memory_sensitive_rejected",
                    "记忆内容疑似包含密钥、密码或个人敏感联系方式，未保存。",
                )
            if contains_policy_override(body.summary):
                raise ServiceError(
                    422,
                    "memory_policy_rejected",
                    "记忆内容不能用于授权工具自动执行或覆盖系统安全规则。",
                )
        now = utc_now()
        with self.repo.connection() as db, self.repo.transaction(db):
            self.store._ensure_ready(db)
            row = db.execute("SELECT record FROM memories WHERE id=?", (memory_id,)).fetchone()
            if row is None:
                raise ServiceError(404, "memory_not_found", "记忆条目不存在。")
            item = MemoryItem.model_validate_json(row[0])
            if item.status == "superseded":
                raise ServiceError(409, "memory_superseded", "该历史版本已被替代，无法直接编辑。")
            if item.revision != body.expected_revision:
                raise ServiceError(
                    409,
                    "memory_revision_conflict",
                    "记忆条目已更新，请重新读取最新修订号后再修改。",
                )
            summary_changed = body.summary is not None and body.summary != item.summary
            if body.summary is not None:
                item.summary = body.summary
                if item.source.source_type == "manual":
                    item.source.validity = "valid"
            if body.category is not None:
                item.category = body.category
            if body.promote_to_global:
                item.scope = "global"
                item.project_id = None
                item.project_name = None
            if body.status is not None:
                item.status = body.status
            item.normalized_key = memory_dedup_key(item.category, item.summary)
            item.revision += 1
            item.updated_at = now
            self.store.save_memory_with_db(db, item)
            if summary_changed or item.status != "active":
                # Drop stale embedding so outdated content is never semantically recalled.
                db.execute("DELETE FROM memory_vectors WHERE memory_id=?", (item.id,))
            if item.project_id:
                item.project_name = self.store.project_names_map(db).get(item.project_id)
            return item

    def delete_memory(self, memory_id: str, *, expected_revision: int | None = None) -> None:
        self.store.delete_memory(memory_id, expected_revision=expected_revision)

    def list_candidates(
        self,
        *,
        scope: str | None = None,
        project_id: str | None = None,
        status: str | None = "pending",
    ) -> MemoryCandidateListResponse:
        if project_id:
            with self.repo.connection() as db:
                exists, _, _ = self.store.project_exists(db, project_id)
                if not exists:
                    raise ServiceError(404, "project_not_found", "项目不存在。")
        items = self.store.list_candidates(scope=scope, project_id=project_id, status=status)
        return MemoryCandidateListResponse(items=items, total=len(items))

    def review_candidate(
        self, candidate_id: str, body: MemoryCandidateReviewRequest
    ) -> MemoryCandidateReviewResponse:
        now = utc_now()
        with self.repo.connection() as db, self.repo.transaction(db):
            self.store._ensure_ready(db)
            row = db.execute(
                "SELECT record FROM memory_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise ServiceError(404, "candidate_not_found", "候选记忆不存在。")
            candidate = MemoryCandidate.model_validate_json(row[0])

            # Idempotent replay if already reviewed with the exact same decision.
            target_status = {"accept": "accepted", "reject": "rejected", "skip": "skipped"}[
                body.action
            ]
            if candidate.status == target_status:
                existing_mem = None
                if candidate.accepted_memory_id:
                    mrow = db.execute(
                        "SELECT record FROM memories WHERE id=?", (candidate.accepted_memory_id,)
                    ).fetchone()
                    if mrow:
                        existing_mem = MemoryItem.model_validate_json(mrow[0])
                return MemoryCandidateReviewResponse(
                    candidate=candidate,
                    memory=existing_mem,
                    replayed=True,
                    message="该候选已按相同操作处理，返回原结果。",
                )
            if candidate.status != "pending":
                raise ServiceError(
                    409,
                    "candidate_already_reviewed",
                    "该候选记忆已被处理，无法重复变更为其他状态。",
                )

            if body.action in ("reject", "skip"):
                candidate.status = target_status
                candidate.reviewed_at = now
                self.store.save_candidate_with_db(db, candidate)
                return MemoryCandidateReviewResponse(
                    candidate=candidate,
                    memory=None,
                    replayed=False,
                    message="已拒绝该候选，同轮次同一内容不会再次提议。"
                    if body.action == "reject"
                    else "已跳过该候选。",
                )

            final_summary = body.summary if body.summary is not None else candidate.summary
            final_category = body.category if body.category is not None else candidate.category
            final_scope = body.scope if body.scope is not None else candidate.scope
            final_project_id = (
                body.project_id
                if body.scope is not None
                else (candidate.project_id if final_scope == "project" else None)
            )
            if contains_sensitive_data(final_summary):
                raise ServiceError(
                    422,
                    "memory_sensitive_rejected",
                    "候选内容疑似包含密钥或敏感联系方式，无法入库。",
                )
            if contains_policy_override(final_summary):
                raise ServiceError(
                    422,
                    "memory_policy_rejected",
                    "候选内容包含越权指令，无法保存为长期记忆。",
                )
            project_name = self._verify_project_scope(db, final_scope, final_project_id)
            dedup = memory_dedup_key(final_category, final_summary)

            exact, conflict = self._find_scope_matches(
                db,
                scope=final_scope,
                project_id=final_project_id,
                category=final_category,
                normalized_key=dedup,
            )
            if candidate.conflict_memory_id and conflict is None:
                crow = db.execute(
                    "SELECT record FROM memories WHERE id=? AND status='active'",
                    (candidate.conflict_memory_id,),
                ).fetchone()
                if crow:
                    conflict = MemoryItem.model_validate_json(crow[0])

            saved_memory: MemoryItem
            if exact is not None:
                saved_memory = exact
                msg = "同范围内已存在相同记忆，已复用原记录。"
            elif conflict is not None and body.resolution == "merge":
                conflict.summary = final_summary
                conflict.category = final_category
                conflict.normalized_key = dedup
                conflict.revision += 1
                conflict.updated_at = now
                conflict.source = candidate.source.model_copy(
                    update={"verification_status": "user_confirmed"}
                )
                self.store.save_memory_with_db(db, conflict)
                db.execute("DELETE FROM memory_vectors WHERE memory_id=?", (conflict.id,))
                saved_memory = conflict
                msg = "已与原有记忆合并并更新修订号。"
            else:
                supersedes_id = None
                if conflict is not None and body.resolution == "replace":
                    conflict.status = "superseded"
                    conflict.revision += 1
                    conflict.updated_at = now
                    self.store.save_memory_with_db(db, conflict)
                    supersedes_id = conflict.id
                else:
                    self._require_memory_capacity(db)
                saved_memory = MemoryItem(
                    id=str(uuid4()),
                    scope=final_scope,
                    project_id=final_project_id,
                    project_name=project_name,
                    category=final_category,
                    summary=final_summary,
                    normalized_key=dedup,
                    status="active",
                    revision=1,
                    supersedes_memory_id=supersedes_id,
                    source=candidate.source.model_copy(
                        update={"verification_status": "user_confirmed"}
                    ),
                    created_at=now,
                    updated_at=now,
                )
                self.store.save_memory_with_db(db, saved_memory)
                msg = (
                    "已替换旧版本记忆并撤回旧检索项。"
                    if supersedes_id
                    else "已确认并保存到长期记忆。"
                )

            candidate.status = "accepted"
            candidate.accepted_memory_id = saved_memory.id
            candidate.reviewed_at = now
            self.store.save_candidate_with_db(db, candidate)
            if saved_memory.project_id and project_name:
                saved_memory.project_name = project_name
            return MemoryCandidateReviewResponse(
                candidate=candidate,
                memory=saved_memory,
                replayed=False,
                message=msg,
            )

    def _retrieve_memories(
        self,
        message: str,
        *,
        custom_project_id: str | None,
    ) -> tuple[list[MemoryItem], RetrievalMode, list[str]]:
        candidates = self.store.list_active_for_turn(custom_project_id=custom_project_id)
        if not candidates:
            return [], "lexical", []

        category_boosts = infer_query_category_boosts(message)
        lexical_scores: dict[str, float] = {}
        for item in candidates:
            norm_text = normalize_memory_text(item.summary)
            lexical_scores[item.id] = score_lexical_relevance(
                message,
                norm_text,
                category=item.category,
                category_boosts=category_boosts,
            )

        semantic_scores: dict[str, float] = {}
        retrieval_mode: RetrievalMode = "lexical"
        degraded_reasons: list[str] = []

        if (
            self.settings is not None
            and self.embedder is not None
            and self.settings.rag_model_path is not None
            and bool(self.settings.rag_model_sha256)
            and getattr(self.settings, "rag_semantic_enabled", True)
        ):
            try:
                model_sha = self.embedder.identity()
                indexed = self.store.vector_indexed_count(
                    model_sha256=model_sha, dimension=self.settings.rag_dimension
                )
                if indexed > 0:
                    qvec = self.embedder.encode([message])[0]
                    raw_sem = self.store.semantic_scores(
                        memory_ids=[item.id for item in candidates],
                        model_sha256=model_sha,
                        dimension=self.settings.rag_dimension,
                        query_vector=qvec,
                        limit=20,
                    )
                    max_dist = float(getattr(self.settings, "rag_max_cosine_distance", 0.65))
                    min_sim = 1.0 - max_dist
                    semantic_scores = {mid: sim for mid, sim in raw_sem.items() if sim >= min_sim}
                    retrieval_mode = "hybrid"
                else:
                    retrieval_mode = "lexical_fallback"
                    degraded_reasons.append("memory_vector_index_empty")
            except ServiceError as exc:
                retrieval_mode = "lexical_fallback"
                degraded_reasons.append(exc.error.code)
            except Exception:
                retrieval_mode = "lexical_fallback"
                degraded_reasons.append("memory_semantic_unavailable")

        ranked: list[tuple[float, int, MemoryItem]] = []
        for item in candidates:
            lex = lexical_scores.get(item.id, 0.0)
            sem = semantic_scores.get(item.id, 0.0)
            combined = lex + (sem * 5.0 if sem > 0 else 0.0)
            # Project-scoped memory gets mild priority within its own project when already relevant.
            if combined >= MEMORY_MIN_RELEVANCE:
                if (
                    item.scope == "project"
                    and custom_project_id
                    and item.project_id == custom_project_id
                ):
                    combined += 0.6
                ranked.append((combined, 1 if item.scope == "project" else 0, item))

        ranked.sort(key=lambda entry: (-entry[0], -entry[1], entry[2].updated_at))
        selected = [entry[2] for entry in ranked[:MAX_INJECTED_MEMORIES]]
        return selected, retrieval_mode, degraded_reasons

    def _retrieve_history_snippets(
        self,
        message: str,
        *,
        current_conversation_id: str,
        custom_project_id: str | None,
    ) -> list[HistorySnippet]:
        with self.repo.connection() as db:
            default_id = self.store.default_project_id(db)
            if custom_project_id:
                rows = db.execute(
                    "SELECT t.conversation_id, c.title, t.id, t.ordinal, t.record, pc.project_id "
                    "FROM turns t "
                    "JOIN conversations c ON c.id=t.conversation_id "
                    "JOIN project_conversations pc ON pc.conversation_id=t.conversation_id "
                    "WHERE t.state='completed' AND t.conversation_id != ? AND pc.project_id=? "
                    "ORDER BY c.updated_at DESC, t.ordinal DESC LIMIT ?",
                    (current_conversation_id, custom_project_id, MAX_CROSS_SESSION_SCAN_TURNS),
                ).fetchall()
            else:
                if default_id:
                    rows = db.execute(
                        "SELECT t.conversation_id, c.title, t.id, t.ordinal, "
                        "t.record, pc.project_id "
                        "FROM turns t "
                        "JOIN conversations c ON c.id=t.conversation_id "
                        "LEFT JOIN project_conversations pc "
                        "ON pc.conversation_id=t.conversation_id "
                        "WHERE t.state='completed' AND t.conversation_id != ? "
                        "AND (pc.project_id IS NULL OR pc.project_id=?) "
                        "ORDER BY c.updated_at DESC, t.ordinal DESC LIMIT ?",
                        (current_conversation_id, default_id, MAX_CROSS_SESSION_SCAN_TURNS),
                    ).fetchall()
                else:
                    rows = db.execute(
                        "SELECT t.conversation_id, c.title, t.id, t.ordinal, "
                        "t.record, pc.project_id "
                        "FROM turns t "
                        "JOIN conversations c ON c.id=t.conversation_id "
                        "LEFT JOIN project_conversations pc "
                        "ON pc.conversation_id=t.conversation_id "
                        "WHERE t.state='completed' AND t.conversation_id != ? "
                        "AND pc.project_id IS NULL "
                        "ORDER BY c.updated_at DESC, t.ordinal DESC LIMIT ?",
                        (current_conversation_id, MAX_CROSS_SESSION_SCAN_TURNS),
                    ).fetchall()

        hits: list[HistorySnippet] = []
        seen_turn_ids: set[str] = set()
        for row in rows:
            try:
                turn = Turn.model_validate_json(row[4])
            except Exception:
                continue
            if turn.response is None or turn.turn_id in seen_turn_ids:
                continue
            user_msg = re.sub(r"\s+", " ", (turn.message or "").strip())
            answer_text = re.sub(r"\s+", " ", (turn.response.answer or "").strip())
            searchable = normalize_memory_text(f"{user_msg} {answer_text[:600]}")
            score = score_lexical_relevance(message, searchable)
            if score < HISTORY_MIN_RELEVANCE:
                continue
            seen_turn_ids.add(turn.turn_id)
            has_tools = bool(
                turn.response.results
                or turn.response.gaia_results
                or turn.response.literature_results
                or turn.response.nbody_proposals
                or turn.response.plot_proposals
            )
            excerpt = f"用户曾问：{user_msg[:180]}"
            if answer_text:
                excerpt += f"｜历史回答要点：{answer_text[:220]}"
            hits.append(
                HistorySnippet(
                    conversation_id=row[0],
                    conversation_title=str(row[1] or "历史会话"),
                    turn_id=turn.turn_id,
                    turn_revision=int(turn.revision),
                    project_id=row[5] if custom_project_id else None,
                    received_at=turn.received_at,
                    snippet=excerpt,
                    historical_label="历史",
                    score=score,
                    match_mode="lexical",
                    has_tools=has_tools,
                    source_url=f"/conversations/{row[0]}?turn={turn.turn_id}",
                )
            )
        hits.sort(key=lambda item: (-item.score, item.received_at))
        return hits[:MAX_HISTORY_SNIPPETS]

    def _get_or_build_summary(
        self,
        conversation_id: str,
        custom_project_id: str | None,
        omitted_completed: list,
    ) -> tuple[ConversationSummaryRecord | None, list[str]]:
        if not omitted_completed:
            return None, []
        degraded: list[str] = []
        covered = select_summary_source_turns(omitted_completed)
        expected_sha = compute_omitted_turns_sha256(covered)
        expected_ids = [t.turn_id for t in covered]
        expected_revs = {t.turn_id: int(t.revision) for t in covered}
        try:
            cached = self.store.get_summary(conversation_id)
            if (
                cached is not None
                and cached.status == "active"
                and cached.source_sha256 == expected_sha
                and cached.covered_turn_ids == expected_ids
                and cached.turn_revisions == expected_revs
                and cached.summary_bytes <= MAX_SUMMARY_BYTES
            ):
                return cached, degraded
        except Exception:
            degraded.append("summary_cache_read_failed")

        try:
            summary = build_local_conversation_summary(
                conversation_id,
                custom_project_id,
                omitted_completed,
                max_bytes=MAX_SUMMARY_BYTES,
            )
            try:
                self.store.save_summary(summary)
            except Exception:
                degraded.append("summary_cache_write_failed")
            return summary, degraded
        except Exception:
            degraded.append("summary_generation_failed")
            return None, degraded

    def prepare_turn_memory(
        self,
        *,
        conversation_id: str,
        project_id: str | None,
        message: str,
        omitted_completed: list,
    ) -> TurnMemoryBundle:
        bundle = TurnMemoryBundle()
        try:
            prefs = self.store.get_preferences()
        except Exception:
            bundle.trace.degraded_reasons.append("memory_preferences_unavailable")
            return bundle

        custom_project_id = None
        if project_id:
            try:
                with self.repo.connection() as db:
                    custom_project_id = self._resolve_custom_project_id(db, project_id)
            except Exception:
                custom_project_id = None

        degraded_reasons: list[str] = []
        retrieval_mode: RetrievalMode = "disabled"

        if prefs.cross_session_injection:
            try:
                selected, retrieval_mode, mem_degraded = self._retrieve_memories(
                    message, custom_project_id=custom_project_id
                )
                bundle.memories = selected
                degraded_reasons.extend(mem_degraded)
            except Exception:
                retrieval_mode = "lexical_fallback"
                degraded_reasons.append("memory_retrieval_failed")

        if prefs.history_retrieval:
            try:
                bundle.history_snippets = self._retrieve_history_snippets(
                    message,
                    current_conversation_id=conversation_id,
                    custom_project_id=custom_project_id,
                )
                if retrieval_mode == "disabled":
                    retrieval_mode = "lexical"
            except Exception:
                degraded_reasons.append("history_retrieval_failed")

        if omitted_completed:
            summary, sum_degraded = self._get_or_build_summary(
                conversation_id, custom_project_id, omitted_completed
            )
            bundle.summary = summary
            degraded_reasons.extend(sum_degraded)

        bundle.memory_hint = " ".join(item.summary for item in bundle.memories)
        bundle.trace = MemoryContextTrace(
            memory_ids=[item.id for item in bundle.memories],
            memory_scopes=[item.scope for item in bundle.memories],
            memory_count=len(bundle.memories),
            history_refs=[
                MemoryHistoryRef(
                    conversation_id=h.conversation_id,
                    conversation_title=h.conversation_title,
                    turn_id=h.turn_id,
                    turn_revision=h.turn_revision,
                    historical_label="历史",
                    match_mode=h.match_mode,
                )
                for h in bundle.history_snippets
            ],
            history_count=len(bundle.history_snippets),
            summary_id=bundle.summary.summary_id if bundle.summary else None,
            summary_first_turn_id=bundle.summary.first_turn_id if bundle.summary else None,
            summary_last_turn_id=bundle.summary.last_turn_id if bundle.summary else None,
            summary_covered_count=len(bundle.summary.covered_turn_ids) if bundle.summary else 0,
            summary_bytes=bundle.summary.summary_bytes if bundle.summary else 0,
            retrieval_mode=retrieval_mode,
            degraded_reasons=list(dict.fromkeys(degraded_reasons)),
            memory_context_bytes=0,
            skill_assisted_by_memory=False,
        )
        return bundle

    def process_completed_turn(
        self,
        *,
        conversation_id: str,
        project_id: str | None,
        turn: Turn,
        conversation_title: str = "",
    ) -> list[MemorySaveReceipt]:
        """Handle explicit direct save and optional automatic extraction after completion."""
        if turn.execution_status != "completed":
            return []
        receipts: list[MemorySaveReceipt] = []
        now = utc_now()
        try:
            with self.repo.connection() as db:
                custom_project_id = self._resolve_custom_project_id(db, project_id)
        except Exception:
            custom_project_id = None

        # 1. Explicit direct-save works even when auto_extract is OFF.
        explicit = parse_explicit_remember(turn.message, project_id=custom_project_id)
        if explicit is not None:
            if explicit.rejected_reason:
                receipts.append(
                    MemorySaveReceipt(
                        receipt_id=str(uuid4()),
                        action="needs_clarification",
                        scope="global",
                        category=explicit.category,
                        summary=explicit.summary,
                        message=explicit.rejected_reason,
                    )
                )
                return receipts
            if explicit.ambiguous_scope:
                receipts.append(
                    MemorySaveReceipt(
                        receipt_id=str(uuid4()),
                        action="needs_clarification",
                        scope=explicit.scope,
                        category=explicit.category,
                        summary=explicit.summary,
                        message="范围不够明确：请说明要保存为全局个人记忆，或在具体科研项目中再次确认。",
                    )
                )
                return receipts
            dedup = memory_dedup_key(explicit.category, explicit.summary)
            try:
                with self.repo.connection() as db, self.repo.transaction(db):
                    self.store._ensure_ready(db)
                    project_name = self._verify_project_scope(
                        db, explicit.scope, explicit.project_id
                    )
                    exact, conflict = self._find_scope_matches(
                        db,
                        scope=explicit.scope,
                        project_id=explicit.project_id,
                        category=explicit.category,
                        normalized_key=dedup,
                    )
                    title_label = conversation_title or "当前会话"
                    source = MemorySource(
                        source_type="conversation_turn",
                        source_label=f"对话直接保存（{title_label} · r{turn.revision}）",
                        conversation_id=conversation_id,
                        conversation_title=conversation_title or None,
                        turn_id=turn.turn_id,
                        turn_revision=turn.revision,
                        project_id=explicit.project_id,
                        quote=turn.message[:280],
                        verification_status="user_confirmed",
                        validity="valid",
                    )
                    if exact is not None:
                        receipts.append(
                            MemorySaveReceipt(
                                receipt_id=str(uuid4()),
                                action="already_saved",
                                memory_id=exact.id,
                                scope=exact.scope,
                                project_id=exact.project_id,
                                category=exact.category,
                                summary=exact.summary,
                                message="该记忆已保存，无需重复写入。",
                            )
                        )
                        return receipts
                    supersedes_id = None
                    if conflict is not None and explicit.explicit_replace:
                        conflict.status = "superseded"
                        conflict.revision += 1
                        conflict.updated_at = now
                        self.store.save_memory_with_db(db, conflict)
                        supersedes_id = conflict.id
                    else:
                        self._require_memory_capacity(db)
                    item = MemoryItem(
                        id=str(uuid4()),
                        scope=explicit.scope,
                        project_id=explicit.project_id,
                        project_name=project_name,
                        category=explicit.category,
                        summary=explicit.summary,
                        normalized_key=dedup,
                        status="active",
                        revision=1,
                        supersedes_memory_id=supersedes_id,
                        source=source,
                        created_at=now,
                        updated_at=now,
                    )
                    self.store.save_memory_with_db(db, item)
                    receipts.append(
                        MemorySaveReceipt(
                            receipt_id=str(uuid4()),
                            action="saved",
                            memory_id=item.id,
                            scope=item.scope,
                            project_id=item.project_id,
                            category=item.category,
                            summary=item.summary,
                            message="已保存到记忆，记忆摘要已更新。",
                        )
                    )
                    return receipts
            except Exception as exc:
                if isinstance(exc, ServiceError) and exc.error.code == "memory_limit_reached":
                    receipts.append(
                        MemorySaveReceipt(
                            receipt_id=str(uuid4()),
                            action="limit_reached",
                            scope=explicit.scope,
                            project_id=explicit.project_id,
                            category=explicit.category,
                            summary=explicit.summary,
                            message=exc.error.message,
                        )
                    )
                else:
                    LOGGER.warning(
                        "Direct memory save failed for turn %s: %s",
                        turn.turn_id,
                        type(exc).__name__,
                    )
                return receipts

        # 2. Automatic bounded extraction when memory is enabled: store directly into active
        # memories (passing sensitive & policy filters) so the narrative summary stays updated.
        try:
            prefs = self.store.get_preferences()
            if not prefs.auto_extract:
                return receipts
            extracted = extract_rule_candidates(turn.message, project_id=custom_project_id)
            if not extracted:
                return receipts
            with self.repo.connection() as db, self.repo.transaction(db):
                self.store._ensure_ready(db)
                names = self.store.project_names_map(db)
                for item in extracted:
                    dedup = memory_dedup_key(item.category, item.summary)
                    exact, _ = self._find_scope_matches(
                        db,
                        scope=item.scope,
                        project_id=item.project_id,
                        category=item.category,
                        normalized_key=dedup,
                    )
                    if exact is not None:
                        continue
                    try:
                        self._require_memory_capacity(db)
                    except ServiceError:
                        break
                    record = MemoryItem(
                        id=str(uuid4()),
                        scope=item.scope,
                        project_id=item.project_id,
                        project_name=names.get(item.project_id) if item.project_id else None,
                        category=item.category,
                        summary=item.summary,
                        normalized_key=dedup,
                        status="active",
                        revision=1,
                        source=MemorySource(
                            source_type="conversation_turn",
                            source_label=(
                                f"自动整理（{conversation_title or '会话'} · r{turn.revision}）"
                            ),
                            conversation_id=conversation_id,
                            conversation_title=conversation_title or None,
                            turn_id=turn.turn_id,
                            turn_revision=turn.revision,
                            project_id=item.project_id,
                            quote=item.quote,
                            verification_status="unverified",
                            validity="valid",
                        ),
                        created_at=now,
                        updated_at=now,
                    )
                    self.store.save_memory_with_db(db, record)
        except Exception as exc:
            LOGGER.warning("Automatic memory extraction failed: %s", type(exc).__name__)
        return receipts
