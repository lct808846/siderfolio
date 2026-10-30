"""项目本地文献、不可变文件版本和原文证据契约。"""

from typing import Literal

from pydantic import Field, StrictBool, StrictInt, field_validator

from astroagent.project_schemas import Contract, Digest, Identifier, Revision

DocumentState = Literal["parsing", "ready", "partial", "failed", "interrupted", "unavailable"]


class DocumentMetadata(Contract):
    title: str | None = Field(default=None, max_length=500)
    authors: list[str] = Field(default_factory=list, max_length=50)
    year: StrictInt | None = Field(default=None, ge=1, le=9999)
    doi: str | None = Field(default=None, max_length=300)

    @field_validator("authors")
    @classmethod
    def author_lengths(cls, values):
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("Invalid author")
        return values


class DocumentUpload(Revision):
    client_request_id: Identifier
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    allow_duplicate: StrictBool = False
    restore_version_id: Identifier | None = None


class DocumentAction(Revision):
    client_request_id: Identifier
    confirmed: StrictBool
    version_id: Identifier | None = None


class DocumentDelete(Revision):
    confirmed: StrictBool


class KnowledgeDocument(Contract):
    id: Identifier
    project_id: Identifier
    filename: str = Field(min_length=1, max_length=200)
    metadata: DocumentMetadata
    current_version_id: Identifier
    state: DocumentState
    created_at: str
    updated_at: str
    provenance: Literal["local", "imported_unverified"] = "local"
    original_id: Identifier | None = None


class DocumentVersion(Contract):
    id: Identifier
    project_id: Identifier
    document_id: Identifier
    filename: str = Field(min_length=1, max_length=200)
    media_type: Literal["application/pdf", "text/markdown"]
    sha256: Digest
    bytes: StrictInt = Field(ge=1, le=20 * 1024**2)
    state: DocumentState
    content_available: StrictBool
    indexed: StrictBool = False
    created_at: str
    parsed_at: str | None = None
    extractor: str | None = None
    segmentation_version: str = "1"
    extraction_sha256: Digest | None = None
    page_count: StrictInt | None = Field(default=None, ge=0, le=500)
    line_count: StrictInt | None = Field(default=None, ge=0, le=200000)
    text_bytes: StrictInt = Field(default=0, ge=0, le=20 * 1024**2)
    unit_count: StrictInt = Field(default=0, ge=0, le=25000)
    warnings: list[str] = Field(default_factory=list, max_length=510)
    error: dict[str, str] | None = None
    original_id: Identifier | None = None


class TextSource(Contract):
    version_id: Identifier
    position: StrictInt = Field(ge=1, le=500)
    page: StrictInt | None = Field(default=None, ge=1, le=500)
    state: Literal["text", "no_text", "failed", "unavailable"]
    text: str | None
    sha256: Digest
    error: str | None = None


class TextUnit(Contract):
    id: Identifier
    project_id: Identifier
    document_id: Identifier
    version_id: Identifier
    source_position: StrictInt = Field(ge=1, le=500)
    ordinal: StrictInt = Field(ge=0, le=25000)
    text: str | None = Field(max_length=1200)
    sha256: Digest
    char_start: StrictInt = Field(ge=0)
    char_end: StrictInt = Field(ge=1)
    page: StrictInt | None = Field(default=None, ge=1, le=500)
    line_start: StrictInt | None = Field(default=None, ge=1, le=200000)
    line_end: StrictInt | None = Field(default=None, ge=1, le=200000)
    heading_path: list[str] = Field(default_factory=list, max_length=6)


class EvidenceRecord(Contract):
    id: Identifier
    project_id: Identifier
    document_id: Identifier
    version_id: Identifier
    unit_id: Identifier
    document_sha256: Digest
    text_sha256: Digest
    query: str = Field(min_length=1, max_length=1000)
    created_at: str
    index_version: str = "nfkc-casefold-fts5-v1"
    source_label: Literal["user_document"] = "user_document"
    validity: Literal["available", "original_unavailable", "deleted", "corrupt"]
    filename: str
    title: str | None = None
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    char_start: int
    char_end: int
    original_id: Identifier | None = None


class EvidenceView(Contract):
    evidence: EvidenceRecord
    text: str | None
    heading_path: list[str]
    historical_version: bool
    content_url: str | None
    warning: str


class KnowledgeQuery(Contract):
    query: str = Field(min_length=1, max_length=1000)
    limit: StrictInt = Field(default=10, ge=1, le=20)
    document_ids: list[Identifier] = Field(default_factory=list, max_length=20)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Empty query")
        return value.strip()


class KnowledgeResult(Contract):
    status: Literal["evidence_found", "insufficient_evidence"]
    answer: str
    project_id: Identifier
    query: str
    terms: list[str]
    mode: str
    index_version: str
    ranking: str
    returned_count: int
    matched_units: int
    truncated: bool
    searched_at: str
    hits: list[EvidenceView]
    warnings: list[str]


class DocumentDetail(KnowledgeDocument):
    versions: list[DocumentVersion]
    project_revision: int


class TextPreview(Contract):
    version_id: Identifier
    source_position: int
    page: int | None
    state: str
    text: str
    sha256: Digest
    original_characters: int
    truncated: bool
    error: str | None


class KnowledgeOperation(Contract):
    id: Identifier
    project_id: Identifier
    document_id: Identifier
    version_id: Identifier
    client_request_id: Identifier
    state: Literal["parsing", "completed", "failed", "interrupted"]
    created_at: str
    completed_at: str | None = None
    message: str | None = None
    http_status: StrictInt = Field(default=200, ge=200, le=599)


class DocumentResult(Contract):
    operation: KnowledgeOperation
    document: DocumentDetail
    duplicate: bool = False
