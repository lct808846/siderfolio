"""用户显式项目引用；不表示文献支持、证明或反驳科学结论。"""

from typing import Literal

from pydantic import Field, StrictBool, StrictInt

from astroagent.knowledge_schemas import EvidenceView, KnowledgeDocument
from astroagent.project_schemas import Contract, Digest, Identifier, Project, Revision

TargetKind = Literal["conversation_turn", "snapshot", "workflow_run"]
LinkState = Literal["active", "target_unavailable", "evidence_unavailable"]


class LinkCreate(Revision):
    client_request_id: Identifier
    target_type: TargetKind
    target_id: Identifier
    evidence_id: Identifier
    note: str = Field(default="", max_length=1000)
    confirmed: StrictBool


class LinkPatch(Revision):
    expected_link_revision: StrictInt = Field(ge=0)
    note: str = Field(max_length=1000)


class LinkDelete(Revision):
    expected_link_revision: StrictInt = Field(ge=0)
    confirmed: StrictBool


class ProjectLink(Contract):
    id: Identifier
    project_id: Identifier
    relationship: Literal["user_reference"] = "user_reference"
    record_version: Literal["1"] = "1"
    target_type: TargetKind
    target_id: Identifier
    target_conversation_id: Identifier | None = None
    target_fingerprint: Digest
    target_revision_at_link: StrictInt | None = Field(default=None, ge=0)
    evidence_id: Identifier
    evidence_version_id: Identifier
    evidence_text_sha256: Digest
    evidence_document_sha256: Digest
    created_at: str
    updated_at: str
    revision: StrictInt = Field(ge=0)
    note: str = Field(max_length=1000)
    state: LinkState = "active"
    target_invalidated: StrictBool = False
    evidence_invalidated: StrictBool = False
    invalidation_reason: str | None = Field(default=None, max_length=160)
    provenance: Literal["local", "imported_unverified"] = "local"
    original_id: Identifier | None = None
    original_target_id: Identifier | None = None
    original_evidence_id: Identifier | None = None
    archive_sha256: Digest | None = None


class SourceSummary(Contract):
    category: Literal[
        "database_measurement",
        "ads_abstract",
        "user_document",
        "saved_answer",
        "program_output",
        "user_note",
    ]
    provider: str
    url: str | None = None
    retrieved_at: str | None = None
    status: str


class LinkTarget(Contract):
    type: TargetKind
    id: Identifier
    conversation_id: Identifier | None = None
    label: str
    state: str
    response_status: str | None = None
    available: bool
    provenance: str
    created_at: str | None = None
    revision: int | None = None
    fingerprint: Digest | None = None
    template_version: str | None = None
    software: dict[str, str] = Field(default_factory=dict)
    sources: list[SourceSummary] = Field(default_factory=list)


class LinkDetail(Contract):
    link: ProjectLink
    present: bool
    latest_revision: int | None
    target: LinkTarget
    evidence: EvidenceView | None
    target_changed_since_link: bool
    warning: str


class LinkCreated(Contract):
    detail: LinkDetail
    replayed: bool
    duplicate: bool


class LinkPage(Contract):
    items: list[LinkDetail]
    total: int
    next_cursor: Identifier | None
    limit: int
    project_revision: int


class LinkRequestRecord(Contract):
    id: Identifier
    project_id: Identifier
    client_request_id: Identifier
    request_sha256: Digest
    link_id: Identifier
    created_at: str
    response: ProjectLink
    duplicate: StrictBool
    original_id: Identifier | None = None


class OverviewConversation(Contract):
    id: Identifier
    title: str
    updated_at: str
    turns: list[LinkTarget]


class ProjectOverview(Contract):
    project: Project
    conversations: list[OverviewConversation]
    snapshots: list[LinkTarget]
    workflows: list[LinkTarget]
    documents: list[KnowledgeDocument]
    evidence_count: int
    link_count: int
    link_request_count: int
    first_links: LinkPage
    warning: str
