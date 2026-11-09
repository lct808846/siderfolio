"""V0.6 项目契约；完整响应严格复用既有科学快照校验。"""

import hashlib
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from astroagent.conversations import encode
from astroagent.export_schemas import ExportSnapshot, validate_snapshot
from astroagent.schemas import ChatResponse

Identifier = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ProjectCreate(Contract):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Empty name")
        return value.strip()


class Revision(Contract):
    expected_revision: StrictInt = Field(ge=0)


class ProjectUpdate(ProjectCreate, Revision):
    pass


class ProjectDelete(Revision):
    confirm: StrictBool

    @field_validator("confirm")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Confirmation required")
        return value


class Project(ProjectCreate):
    id: Identifier
    revision: StrictInt = Field(ge=0)
    created_at: str
    updated_at: str
    provenance: Literal["local", "imported_unverified"] = "local"
    original_id: Identifier | None = None
    import_map: dict[str, dict[str, str]] | None = None
    archive_sha256: Digest | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc(cls, value):
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.utcoffset() is None or date.utcoffset().total_seconds() != 0:
            raise ValueError("UTC time required")
        return value


class Membership(Revision):
    expected_source_project_id: Identifier | None = None
    expected_source_revision: StrictInt | None = Field(default=None, ge=0)
    expected_conversation_revision: StrictInt = Field(ge=0)
    expected_metadata_revision: StrictInt = Field(ge=0)


class SnapshotCreate(Revision):
    name: str = Field(min_length=1, max_length=100)
    conversation_id: Identifier
    turn_id: Identifier

    _nonblank = field_validator("name")(ProjectCreate.nonblank.__func__)


class SnapshotRename(Revision):
    name: str = Field(min_length=1, max_length=100)

    _nonblank = field_validator("name")(ProjectCreate.nonblank.__func__)


class SnapshotOrigin(Contract):
    conversation_id: Identifier
    turn_id: Identifier
    snapshot_id: Identifier | None = None
    archive_sha256: Digest | None = None


class Snapshot(Contract):
    id: Identifier
    project_id: Identifier
    name: str = Field(min_length=1, max_length=100)
    conversation_id: Identifier | None
    turn_id: Identifier | None
    origin: SnapshotOrigin
    response: ChatResponse
    sha256: Digest
    created_at: str
    software: dict[str, str]
    provenance: Literal["local", "imported_unverified"]
    rerun_of: Identifier | None = None
    rerun_origin_id: Identifier | None = None

    _nonblank = field_validator("name")(ProjectCreate.nonblank.__func__)

    @field_validator("response", mode="before")
    @classmethod
    def complete_response(cls, value):
        raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        result = ExportSnapshot.model_validate_json(encode(raw))
        validate_snapshot(result)
        return ChatResponse.model_validate_json(result.model_dump_json())

    def verify_digest(self):
        if (
            hashlib.sha256(encode(self.response.model_dump(mode="json")).encode()).hexdigest()
            != self.sha256
        ):
            raise ValueError("Snapshot digest differs")
        if (self.conversation_id is None) != (self.turn_id is None):
            raise ValueError("Incomplete turn reference")
        Project.utc(self.created_at)
        if len(self.software) > 20 or any(
            len(k) > 80 or len(v) > 200 for k, v in self.software.items()
        ):
            raise ValueError("Invalid software metadata")
        return self


class SnapshotSummary(Contract):
    id: Identifier
    project_id: Identifier
    name: str
    created_at: str
    sha256: Digest
    status: str
    provenance: str


class RerunRequest(Revision):
    family: Literal["simbad", "ads", "gaia"]
    result_index: StrictInt = Field(ge=0, le=11)
    client_request_id: Identifier
    confirmed: StrictBool

    @field_validator("client_request_id")
    @classmethod
    def uuid(cls, value):
        return str(UUID(value))


class Rerun(Contract):
    id: Identifier
    project_id: Identifier
    source_snapshot_id: Identifier | None
    source_origin_id: Identifier
    client_request_id: Identifier
    family: Literal["simbad", "ads", "gaia"]
    result_index: StrictInt = Field(ge=0, le=11)
    parameters: dict
    state: Literal["running", "completed", "failed", "interrupted"]
    created_at: str
    completed_at: str | None = None
    conversation_id: Identifier | None
    turn_id: Identifier | None
    snapshot_id: Identifier | None = None
    error: dict[str, str] | None = None
    software: dict[str, str]
    response_status: Literal["success", "partial", "error"] | None = None


class CompareRequest(Contract):
    left_id: Identifier
    right_id: Identifier
    match_identifiers: StrictBool = False


class ProjectDetail(Project):
    conversation_ids: list[str]
    snapshots: list[SnapshotSummary]
    reruns: list[Rerun]
    rag_answer_count: int = 0
    rag_request_count: int = 0
    link_count: int = 0
    link_request_count: int = 0
    workflow_count: int = 0
    running_workflow_count: int = 0
    document_count: int = 0
    document_version_count: int = 0
    document_bytes: int = 0
    knowledge_evidence_count: int = 0


class Comparison(Contract):
    left_id: str
    right_id: str
    left: dict
    right: dict
    differences: list[dict]
    identifiers: list[dict]
    warnings: list[str]


class ArchiveManifest(Contract):
    format: Literal["astroagent-project"]
    version: Literal[1, 2, 3, 4, 5, 6]
    exported_at: str
    application_version: str
    files: dict[str, dict]
    knowledge_mode: Literal["full", "metadata"] | None = None
    sources_complete: StrictBool | None = None


class ProjectArchiveRequest(Revision):
    format_version: StrictInt = Field(default=6, ge=1, le=6)
    knowledge_mode: Literal["full", "metadata"] = "metadata"
    confirmed_include_originals: StrictBool = False


class ImportResult(Contract):
    project: Project
    id_map: dict[str, dict[str, str]]
    archive_sha256: Digest
