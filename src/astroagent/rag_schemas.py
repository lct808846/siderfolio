"""Separate evidence-consented RAG contracts. No change to ChatResponse."""

from typing import Literal

from pydantic import Field, StrictBool, field_validator

from astroagent.knowledge_schemas import EvidenceView
from astroagent.project_schemas import Contract, Digest, Identifier, Revision


class Confirm(Contract):
    confirmed: StrictBool


class IndexRequest(Revision):
    client_request_id: Identifier
    confirmed: StrictBool


class IndexStatus(Contract):
    id: Identifier
    project_id: Identifier
    client_request_id: Identifier
    state: Literal["pending", "running", "ready", "failed", "stale", "interrupted"]
    model_sha256: Digest
    model_name: str
    dimension: int
    normalized: Literal[True] = True
    algorithm: Literal["sentence-transformers-cpu-v1"] = "sentence-transformers-cpu-v1"
    source_sha256: Digest
    created_at: str
    completed_at: str | None = None
    total: int
    processed: int
    error: str | None = None


class RagQuery(Contract):
    question: str = Field(min_length=1, max_length=1000)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    document_ids: list[Identifier] = Field(default_factory=list, max_length=20)
    version_ids: list[Identifier] = Field(default_factory=list, max_length=20)
    history_ids: list[Identifier] = Field(default_factory=list, max_length=3)

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Question is empty")
        return value.strip()


class RagEvidence(Contract):
    label: str
    view: EvidenceView
    lexical_rank: int | None = None
    semantic_rank: int | None = None
    rrf_score: float


class HistoryText(Contract):
    id: Identifier
    question: str
    answer: str


class RetrievalTrace(Contract):
    version: Literal["pg-rrf-v1", "pg-rrf-v2"] = "pg-rrf-v1"
    lexical_algorithm: Literal["nfkc-pg-simple-cjk-substring-v1"] = (
        "nfkc-pg-simple-cjk-substring-v1"
    )
    rrf_k: Literal[60] = 60
    per_route_limit: Literal[20] = 20
    selected_limit: Literal[8] = 8
    embedding_model_name: str | None = None
    embedding_model_sha256: Digest | None = None
    embedding_dimension: int | None = None
    index_source_sha256: Digest | None = None
    max_cosine_distance: float
    embedding_cache_hit: bool | None = None


class Preview(Contract):
    id: Identifier
    project_id: Identifier
    question: str
    document_ids: list[Identifier]
    version_ids: list[Identifier]
    provider: str
    model: str
    model_fingerprint: Digest
    created_at: str
    expires_at: str
    status: Literal["evidence_found", "no_results"]
    evidence: list[RagEvidence]
    history: list[HistoryText]
    index_id: Identifier | None
    lexical_status: str
    semantic_status: str
    lexical_candidates: int
    semantic_candidates: int
    warnings: list[str]
    retrieval: RetrievalTrace
    confirmation_token: Digest


class GenerateRequest(Contract):
    client_request_id: Identifier
    preview_id: Identifier
    confirmation_token: Digest
    confirmed: StrictBool


class RagAnswer(Contract):
    id: Identifier
    project_id: Identifier
    client_request_id: Identifier
    preview_id: Identifier
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(default="", max_length=16000)
    state: Literal["running", "completed", "insufficient_evidence", "failed", "interrupted"]
    created_at: str
    completed_at: str | None = None
    provider: str = Field(max_length=500)
    model: str = Field(max_length=200)
    model_version: str | None = None
    evidence: list[RagEvidence] = Field(max_length=8)
    citation_labels: list[str] = Field(default_factory=list, max_length=8)
    history_ids: list[Identifier] = Field(max_length=3)
    document_ids: list[Identifier] = Field(default_factory=list, max_length=20)
    version_ids: list[Identifier] = Field(default_factory=list, max_length=20)
    index_id: Identifier | None
    retrieval: RetrievalTrace
    user_confirmed: StrictBool
    confirmation_sha256: Digest
    error: str | None = None
    provenance: Literal["local", "imported_unverified"] = "local"
    original_id: Identifier | None = None
    archive_sha256: Digest | None = None


class RagAnswerView(Contract):
    record: RagAnswer
    current_evidence: list[RagEvidence]
    warning: str


class RagPage(Contract):
    items: list[RagAnswerView]
    next_cursor: Identifier | None
    total: int


class RagRequestRecord(Contract):
    id: Identifier
    project_id: Identifier
    client_request_id: Identifier
    request_sha256: Digest
    answer_id: Identifier
    created_at: str
    original_id: Identifier | None = None


class RagStatus(Contract):
    project_id: Identifier
    indexes: list[IndexStatus]
    active_index_id: Identifier | None
    model_configured: bool
    semantic_enabled: bool
    vector_budget_bytes: int
    vector_used_bytes: int
    answer_count: int


class SetupStatus(Contract):
    runtime_database: Literal["postgresql"] = "postgresql"
    configured: bool
    ready: bool
    code: str
    message: str
    database_schema: int | None = None
    database_version: str | None = None
    vector_version: str | None = None
    database_used_bytes: int | None = None
    business_budget_bytes: int
    vector_budget_bytes: int
    embedding_configured: bool
    embedding_model: str
    embedding_dimension: int
    answering_configured: bool
    answering_provider: str
    answering_model: str
    credentials_location: Literal["server_environment_only"] = "server_environment_only"
