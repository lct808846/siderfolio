"""V2.1 受控外部 MCP 配置、发现清单与管理状态模型。"""

from __future__ import annotations

import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from astroagent.mcp_contract import MCP_TARGET_PROTOCOL_VERSION

SERVER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
ENV_VAR_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
HEADER_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{1,63}$")
RESERVED_SERVER_IDS = frozenset({"builtin", "local", "astronomy", "siderfolio", "astroagent"})
FORBIDDEN_CREDENTIAL_ENV_PREFIXES = (
    "DEEPSEEK_",
    "OPENAI_",
    "ANTHROPIC_",
    "GEMINI_",
    "ASTROAGENT_DATABASE_",
    "ASTROAGENT_AUTH_",
    "ASTROAGENT_PROXY_",
    "ASTROAGENT_PLOT_",
    "PG",
    "SMTP_",
)


class ExternalMcpServerConfig(BaseModel):
    """运营者在服务端私有配置中预配的受控外部 MCP 服务（固定主机、端口、路径）。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=400)
    scheme: Literal["https"] = "https"
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=443, ge=1, le=65535)
    path: str = Field(default="/mcp", min_length=1, max_length=200)
    protocol_version: str = Field(default=MCP_TARGET_PROTOCOL_VERSION, min_length=4, max_length=32)
    auth_header: str | None = Field(default=None, max_length=64)
    auth_env_var: str | None = Field(default=None, max_length=64)
    auth_scheme: str | None = Field(default="Bearer", max_length=32)
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30.0)
    discover_timeout_seconds: float = Field(default=10.0, gt=0, le=30.0)
    call_timeout_seconds: float = Field(default=15.0, gt=0, le=60.0)
    max_request_bytes: int = Field(default=64 * 1024, ge=4 * 1024, le=256 * 1024)
    max_response_bytes: int = Field(default=256 * 1024, ge=16 * 1024, le=2 * 1024 * 1024)
    max_concurrency: int = Field(default=2, ge=1, le=4)
    cache_ttl_seconds: int = Field(default=300, ge=30, le=3600)

    @field_validator("id")
    @classmethod
    def valid_server_id(cls, value: str) -> str:
        if not SERVER_ID_RE.fullmatch(value) or value in RESERVED_SERVER_IDS:
            raise ValueError("Invalid or reserved external MCP server ID")
        return value

    @field_validator("host")
    @classmethod
    def valid_host(cls, value: str) -> str:
        lower = value.lower().rstrip(".")
        if (
            not lower
            or any(ch in lower for ch in ("/", "?", "#", "@", ":", " ", "\t", "\r", "\n", "\\"))
            or ".." in lower
        ):
            raise ValueError("External MCP host must be a plain hostname or IP literal")
        return lower

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or "?" in value
            or "#" in value
            or "\\" in value
            or ".." in value
            or any(ord(ch) <= 0x20 for ch in value)
        ):
            raise ValueError("External MCP path must be a fixed clean path without query/fragment")
        return value

    @field_validator("auth_header")
    @classmethod
    def valid_auth_header(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not HEADER_NAME_RE.fullmatch(value):
            raise ValueError("Invalid auth_header name")
        return value

    @field_validator("auth_env_var")
    @classmethod
    def valid_auth_env_var(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not ENV_VAR_RE.fullmatch(value):
            raise ValueError("Invalid auth_env_var name")
        if value.upper().startswith(FORBIDDEN_CREDENTIAL_ENV_PREFIXES):
            raise ValueError("External MCP server cannot reference internal platform credentials")
        return value

    @property
    def endpoint_url(self) -> str:
        default_port = self.scheme == "https" and self.port == 443
        netloc = self.host if default_port else f"{self.host}:{self.port}"
        return f"{self.scheme}://{netloc}{self.path}"

    @property
    def endpoint_display(self) -> str:
        return self.endpoint_url

    def resolve_auth_headers(self) -> dict[str, str]:
        if not self.auth_header or not self.auth_env_var:
            return {}
        secret = os.environ.get(self.auth_env_var, "").strip()
        if not secret or "\r" in secret or "\n" in secret or "\x00" in secret:
            return {}
        value = f"{self.auth_scheme} {secret}" if self.auth_scheme else secret
        return {self.auth_header: value}

    @property
    def auth_configured(self) -> bool:
        if not self.auth_header or not self.auth_env_var:
            return False
        return bool(os.environ.get(self.auth_env_var, "").strip())


class DiscoveredExternalTool(BaseModel):
    remote_name: str
    tool_id: str
    title: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    read_only_hint: bool | None = None
    destructive_hint: bool | None = None
    eligible_readonly: bool = False
    definition_sha256: str
    approved: bool = False
    definition_changed: bool = False
    approved_definition_sha256: str = ""
    approved_at: str | None = None
    revoked_at: str | None = None
    parameter_names: list[str] = Field(default_factory=list)


class ExternalMcpServerStatus(BaseModel):
    server_id: str
    title: str
    description: str = ""
    endpoint_display: str
    protocol_version: str
    negotiated_protocol_version: str = ""
    server_name: str = ""
    server_version: str = ""
    enabled: bool = False
    auth_env_ref: str | None = None
    auth_configured: bool = False
    last_discovered_at: str | None = None
    last_sync_status: Literal["never", "ok", "error", "incompatible"] = "never"
    last_error_code: str = ""
    last_error_message: str = ""
    cache_stale: bool = True
    tools: list[DiscoveredExternalTool] = Field(default_factory=list)


class AdminMcpServersResponse(BaseModel):
    feature_enabled: bool = False
    servers: list[ExternalMcpServerStatus] = Field(default_factory=list)


class ServerToggleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class ToolApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_definition_sha256: str = Field(min_length=16, max_length=64)
