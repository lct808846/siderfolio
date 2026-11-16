"""Typed schemas for user profile, avatar management, and usage summaries."""

from pydantic import BaseModel


class ModelUsageEntry(BaseModel):
    model: str
    label: str
    calls: int
    succeeded: int
    failed: int
    chat_calls: int = 0
    plot_calls: int = 0
    rag_calls: int = 0
    local_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    last_used_at: str | None = None


class WorkspaceUsageStats(BaseModel):
    conversations_count: int
    turns_count: int
    completed_turns: int
    failed_turns: int
    projects_count: int
    snapshots_count: int
    workflows_count: int
    knowledge_documents_count: int
    plot_datasets_count: int
    plot_operations_count: int
    rag_answers_count: int
    local_tasks_count: int
    simbad_queries: int
    ads_queries: int
    gaia_queries: int
    used_bytes: int
    budget_bytes: int
    storage_ready: bool


class ProfileAccountInfo(BaseModel):
    id: str
    email: str
    username: str
    avatar_url: str
    admin: bool
    totp_enabled: bool
    mfa_verified: bool
    created_at: str
    last_login: str | None = None
    active_sessions: int


class ProfileSummary(BaseModel):
    account: ProfileAccountInfo
    total_model_calls: int
    distinct_models_count: int
    known_total_tokens: int | None = None
    models: list[ModelUsageEntry]
    workspace: WorkspaceUsageStats


class AvatarResponse(BaseModel):
    message: str
    avatar_url: str
