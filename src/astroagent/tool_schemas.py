"""V2.1 服务端统一工具目录与外部 MCP 查询提案/结果数据结构。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ToolSource = Literal["builtin", "local_mcp", "external_mcp"]
ToolAccessScope = Literal[
    "account_readonly",
    "account_write",
    "project_draft",
    "external_readonly",
]
ToolSideEffectLevel = Literal[
    "readonly",
    "external_readonly",
    "internal_write",
    "draft_only",
]


class ToolCatalogItem(BaseModel):
    tool_id: str
    title: str
    description: str
    source: ToolSource
    server_id: str | None = None
    server_title: str | None = None
    remote_name: str | None = None
    protocol_version: str | None = None
    access_scope: ToolAccessScope
    side_effect_level: ToolSideEffectLevel
    requires_confirmation: bool = False
    availability_conditions: list[str] = Field(default_factory=list)
    available: bool = True
    unavailable_reason: str | None = None
    max_calls_per_turn: int = Field(default=6, ge=1, le=12)
    failure_categories: list[str] = Field(default_factory=list)
    definition_sha256: str


class UserToolCatalogResponse(BaseModel):
    tools: list[ToolCatalogItem] = Field(default_factory=list)
    tool_manifest_sha256: str


class ExternalMcpProposal(BaseModel):
    confirmation_id: str
    conversation_id: str
    turn_id: str
    project_id: str | None = None
    server_id: str
    server_title: str
    server_host: str = ""
    tool_id: str
    remote_name: str
    tool_title: str
    protocol_version: str
    definition_sha256: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    arguments_sha256: str
    outbound_fields: list[str] = Field(default_factory=list)
    status: Literal[
        "pending_confirmation",
        "executed",
        "failed",
        "cancelled",
        "expired",
    ] = "pending_confirmation"
    expires_at: str
    created_at: str


class ExternalMcpResult(BaseModel):
    confirmation_id: str
    server_id: str
    server_title: str
    tool_id: str
    remote_name: str
    tool_title: str
    protocol_version: str
    status: Literal["success", "error"]
    summary: str = ""
    structured_data: dict[str, Any] | list[Any] | None = None
    text_excerpt: str = ""
    returned_count: int = 0
    truncated: bool = False
    duration_ms: int | None = None
    executed_at: str
    error_code: str | None = None
    error_message: str | None = None


class ExternalMcpConfirmationRecord(BaseModel):
    proposal: ExternalMcpProposal
    result: ExternalMcpResult | None = None


class ExternalMcpConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_request_id: str = Field(min_length=1, max_length=64)
    expected_definition_sha256: str = Field(min_length=16, max_length=64)
    expected_arguments_sha256: str = Field(min_length=16, max_length=64)
