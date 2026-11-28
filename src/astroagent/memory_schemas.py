"""V2.2 长期记忆、自动候选、跨会话历史片段与长对话摘要的数据及权限契约。"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

MEMORY_SCHEMA_VERSION = 1
MAX_MEMORIES_PER_ACCOUNT = 500
MAX_CANDIDATES_PER_ACCOUNT = 200
MAX_INJECTED_MEMORIES = 5
MAX_HISTORY_SNIPPETS = 3
MAX_SUMMARY_BYTES = 4 * 1024
MAX_MEMORY_CONTEXT_BYTES = 16 * 1024
MAX_SUMMARY_SOURCE_BYTES = 64 * 1024

MemoryScope = Literal["global", "project"]

MemoryCategory = Literal[
    "research_focus",
    "preference",
    "tool_habit",
    "background",
    "project_goal",
    "experiment_condition",
    "progress",
    "failure_note",
    "next_step",
    "verified_finding",
]

MemoryStatus = Literal["active", "paused", "superseded"]

MemoryVerificationStatus = Literal["manual", "user_confirmed", "tool_verified", "unverified"]

MemorySourceType = Literal["manual", "conversation_turn", "project_note"]

MemorySourceValidity = Literal["valid", "source_missing", "source_moved"]

CandidateStatus = Literal["pending", "accepted", "rejected", "skipped"]

ConflictKind = Literal["none", "duplicate", "conflict"]

ConflictResolution = Literal["replace", "merge", "keep_both"]

RetrievalMode = Literal["disabled", "lexical", "hybrid", "lexical_fallback"]

# Categories that represent historical observations/experiments rather than mutable preferences;
# modifying parameters should not silently overwrite prior experimental findings.
PRESERVED_RECORD_CATEGORIES: frozenset[str] = frozenset(
    {"verified_finding", "failure_note", "experiment_condition"}
)

GLOBAL_ONLY_DEFAULT_CATEGORIES: frozenset[str] = frozenset(
    {"research_focus", "preference", "tool_habit", "background"}
)

PROJECT_ORIENTED_CATEGORIES: frozenset[str] = frozenset(
    {
        "project_goal",
        "experiment_condition",
        "progress",
        "failure_note",
        "next_step",
        "verified_finding",
    }
)


def _validate_optional_uuid(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return str(UUID(cleaned))


class MemoryPreferences(BaseModel):
    """个人长期记忆开关；默认开启。"""

    model_config = ConfigDict(extra="forbid")

    auto_extract: bool = True
    cross_session_injection: bool = True
    history_retrieval: bool = True
    revision: int = Field(default=0, ge=0)
    updated_at: str | None = None


class MemoryPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_extract: bool
    cross_session_injection: bool
    history_retrieval: bool
    expected_revision: StrictInt | None = Field(default=None, ge=0)


class MemorySource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_type: MemorySourceType = "manual"
    source_label: str = Field(default="用户手工录入", min_length=1, max_length=160)
    conversation_id: str | None = None
    conversation_title: str | None = Field(default=None, max_length=120)
    turn_id: str | None = None
    turn_revision: int | None = Field(default=None, ge=1)
    project_id: str | None = None
    quote: str | None = Field(default=None, max_length=320)
    verification_status: MemoryVerificationStatus = "manual"
    validity: MemorySourceValidity = "valid"

    @field_validator("conversation_id", "turn_id", "project_id")
    @classmethod
    def check_optional_uuids(cls, value: str | None) -> str | None:
        return _validate_optional_uuid(value)


class MemoryItem(BaseModel):
    id: str
    scope: MemoryScope
    project_id: str | None = None
    project_name: str | None = None
    category: MemoryCategory
    summary: str = Field(min_length=2, max_length=600)
    normalized_key: str = Field(min_length=1, max_length=128)
    status: MemoryStatus = "active"
    revision: int = Field(default=1, ge=1)
    supersedes_memory_id: str | None = None
    source: MemorySource = Field(default_factory=MemorySource)
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def validate_scope_binding(self) -> MemoryItem:
        if self.scope == "global" and self.project_id is not None:
            raise ValueError("全局个人记忆不得绑定项目 ID。")
        if self.scope == "project" and not self.project_id:
            raise ValueError("项目记忆必须绑定明确的项目 ID。")
        return self


class MemoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scope: MemoryScope = "global"
    project_id: str | None = None
    category: MemoryCategory | None = None
    summary: str = Field(min_length=2, max_length=600)
    verification_status: MemoryVerificationStatus = "manual"
    conflict_resolution: ConflictResolution = "keep_both"

    @field_validator("project_id")
    @classmethod
    def check_project_id(cls, value: str | None) -> str | None:
        return _validate_optional_uuid(value)

    @model_validator(mode="after")
    def validate_scope(self) -> MemoryCreateRequest:
        if self.scope == "global" and self.project_id is not None:
            raise ValueError("全局个人记忆不能指定项目 ID。")
        if self.scope == "project" and self.project_id is None:
            raise ValueError("项目记忆必须指定所属项目 ID。")
        return self


class MemoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str | None = Field(default=None, min_length=2, max_length=600)
    category: MemoryCategory | None = None
    status: Literal["active", "paused"] | None = None
    promote_to_global: bool = False
    expected_revision: StrictInt = Field(ge=1)

    @model_validator(mode="after")
    def ensure_has_change(self) -> MemoryUpdateRequest:
        if (
            self.summary is None
            and self.category is None
            and self.status is None
            and not self.promote_to_global
        ):
            raise ValueError("请提供至少一项需要修改的字段。")
        return self


class MemoryCandidate(BaseModel):
    id: str
    scope: MemoryScope
    project_id: str | None = None
    project_name: str | None = None
    category: MemoryCategory
    summary: str = Field(min_length=2, max_length=600)
    normalized_key: str = Field(min_length=1, max_length=128)
    status: CandidateStatus = "pending"
    extraction_method: Literal["local_rule", "local_model"] = "local_rule"
    conflict_kind: ConflictKind = "none"
    conflict_memory_id: str | None = None
    conflict_memory_summary: str | None = None
    accepted_memory_id: str | None = None
    source: MemorySource
    created_at: str
    reviewed_at: str | None = None


class MemoryCandidateReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal["accept", "reject", "skip"]
    resolution: ConflictResolution = "replace"
    summary: str | None = Field(default=None, min_length=2, max_length=600)
    category: MemoryCategory | None = None
    scope: MemoryScope | None = None
    project_id: str | None = None

    @field_validator("project_id")
    @classmethod
    def check_project_id(cls, value: str | None) -> str | None:
        return _validate_optional_uuid(value)

    @model_validator(mode="after")
    def validate_scope_override(self) -> MemoryCandidateReviewRequest:
        if self.scope == "global" and self.project_id is not None:
            raise ValueError("转为全局个人记忆时不得指定项目 ID。")
        if self.scope == "project" and self.project_id is None:
            raise ValueError("指定项目范围时必须提供所属项目 ID。")
        return self


class MemoryCandidateReviewResponse(BaseModel):
    candidate: MemoryCandidate
    memory: MemoryItem | None = None
    replayed: bool = False
    message: str


class MemorySaveReceipt(BaseModel):
    receipt_id: str
    action: Literal[
        "saved", "already_saved", "conflict_candidate", "needs_clarification", "limit_reached"
    ]
    memory_id: str | None = None
    candidate_id: str | None = None
    scope: MemoryScope = "global"
    project_id: str | None = None
    category: MemoryCategory = "preference"
    summary: str
    message: str


class ConversationSummaryRecord(BaseModel):
    summary_id: str
    conversation_id: str
    project_id: str | None = None
    first_turn_id: str
    last_turn_id: str
    covered_turn_ids: list[str] = Field(default_factory=list)
    turn_revisions: dict[str, int] = Field(default_factory=dict)
    source_sha256: str
    summary_text: str
    summary_bytes: int = Field(ge=0)
    generation_mode: Literal["local_rule", "local_model"] = "local_rule"
    status: Literal["active", "stale"] = "active"
    created_at: str
    updated_at: str


class HistorySnippet(BaseModel):
    conversation_id: str
    conversation_title: str
    turn_id: str
    turn_revision: int = Field(ge=1)
    project_id: str | None = None
    received_at: str
    snippet: str
    historical_label: Literal["历史"] = "历史"
    score: float = 0.0
    match_mode: Literal["lexical", "hybrid", "semantic"] = "lexical"
    has_tools: bool = False
    source_url: str


class MemoryHistoryRef(BaseModel):
    """脱敏历史引用定位，供运行追踪回查原会话轮次，不含原文正文。"""

    conversation_id: str
    conversation_title: str
    turn_id: str
    turn_revision: int = Field(ge=1)
    historical_label: Literal["历史"] = "历史"
    match_mode: Literal["lexical", "hybrid", "semantic"] = "lexical"


class MemoryContextTrace(BaseModel):
    """写入 ContextRecord 与 RunTrace 的脱敏记忆与压缩元数据（不含记忆/摘要/用户正文）。"""

    memory_ids: list[str] = Field(default_factory=list)
    memory_scopes: list[MemoryScope] = Field(default_factory=list)
    memory_count: int = Field(default=0, ge=0)
    history_refs: list[MemoryHistoryRef] = Field(default_factory=list)
    history_count: int = Field(default=0, ge=0)
    summary_id: str | None = None
    summary_first_turn_id: str | None = None
    summary_last_turn_id: str | None = None
    summary_covered_count: int = Field(default=0, ge=0)
    summary_bytes: int = Field(default=0, ge=0)
    retrieval_mode: RetrievalMode = "disabled"
    degraded_reasons: list[str] = Field(default_factory=list)
    memory_context_bytes: int = Field(default=0, ge=0)
    skill_assisted_by_memory: bool = False


class MemoryListResponse(BaseModel):
    items: list[MemoryItem] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    preferences: MemoryPreferences = Field(default_factory=MemoryPreferences)


class MemoryCandidateListResponse(BaseModel):
    items: list[MemoryCandidate] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)


class MemoryVectorStatus(BaseModel):
    embedding_configured: bool = False
    semantic_ready: bool = False
    model_name: str = ""
    dimension: int = 0
    indexed_count: int = Field(default=0, ge=0)
    active_memory_count: int = Field(default=0, ge=0)
    degraded_reason: str | None = None


class MemorySummarySection(BaseModel):
    title: str
    content: str


class MemorySummaryOverview(BaseModel):
    enabled: bool = True
    has_memory: bool = False
    summary_text: str = ""
    sections: list[MemorySummarySection] = Field(default_factory=list)
    updated_at: str | None = None
    preferences: MemoryPreferences = Field(default_factory=MemoryPreferences)


class MemoryStatusResponse(BaseModel):
    preferences: MemoryPreferences
    active_global_count: int = Field(default=0, ge=0)
    active_project_count: int = Field(default=0, ge=0)
    paused_count: int = Field(default=0, ge=0)
    pending_candidate_count: int = Field(default=0, ge=0)
    summary_count: int = Field(default=0, ge=0)
    vector_status: MemoryVectorStatus
