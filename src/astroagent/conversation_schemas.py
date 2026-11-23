"""本机会话接口、持久轮次和历史引用；不改变原聊天协议。"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, StrictInt, field_validator

from astroagent.attachment_schemas import ChatAttachment
from astroagent.export_schemas import PlotSpec
from astroagent.literature_schemas import LiteratureSaveReceipt
from astroagent.schemas import ChatResponse, ErrorInfo
from astroagent.trace_schemas import RunTrace


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(default="新会话", min_length=1, max_length=80)


class ConversationRename(ConversationCreate):
    title: str = Field(min_length=1, max_length=80)
    expected_metadata_revision: StrictInt | None = Field(default=None, ge=0)


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=4000)
    client_request_id: str
    expected_revision: StrictInt = Field(ge=0)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=3)
    tool_mode: Literal["auto", "plot", "compute"] | None = Field(default=None)

    @field_validator("client_request_id")
    @classmethod
    def uuid_string(cls, value):
        return str(UUID(value))


class ResultReference(BaseModel):
    turn_id: str
    family: Literal["simbad", "ads", "gaia"]
    result_index: int


class ContextRecord(BaseModel):
    strategy_version: str = "1"
    included_turn_ids: list[str] = Field(default_factory=list)
    omitted_turn_ids: list[str] = Field(default_factory=list)
    omissions: list[dict[str, str]] = Field(default_factory=list)
    referenced_results: list[ResultReference] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    delivered_characters: int = 0
    delivered_bytes: int = 0


class Conversation(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    revision: int
    metadata_revision: int = 0


class ArchivedConversation(Conversation):
    archived_at: str


class Turn(BaseModel):
    _auto_title_eligible: bool = PrivateAttr(default=False)
    conversation_id: str
    turn_id: str
    revision: int
    client_request_id: str
    message: str
    model: str | None = None
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=3)
    execution_status: Literal["running", "completed", "failed", "interrupted"]
    received_at: str
    completed_at: str | None = None
    context: ContextRecord = Field(default_factory=ContextRecord)
    response: ChatResponse | None = None
    literature_receipts: list[LiteratureSaveReceipt] = Field(default_factory=list)
    run_trace: RunTrace | None = None
    trace_status: Literal["available", "unavailable", "not_recorded"] = "not_recorded"
    error: ErrorInfo | None = None


class TurnSummary(BaseModel):
    turn_id: str
    revision: int
    message: str
    model: str | None = None
    execution_status: str
    received_at: str
    completed_at: str | None
    response_status: str | None


class ConversationDetail(Conversation):
    turns: list[TurnSummary]


class ConversationBundle(BaseModel):
    conversation: ConversationDetail
    turns: list[Turn] = Field(default_factory=list)


class ArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plots: list[PlotSpec] = Field(default_factory=list, max_length=3)


class ArtifactInfo(BaseModel):
    artifact_id: str
    conversation_id: str
    turn_id: str
    snapshot_sha256: str
    exporter_version: str
    export_status: Literal["success", "partial"]
    created_at: str
    expires_at: str
    manifest_url: str
    download_url: str
    figures: list[dict[str, str]]


class TurnFailureResponse(BaseModel):
    error: ErrorInfo
    conversation_id: str | None = None
    turn_id: str | None = None
