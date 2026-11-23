"""脱敏运行追踪与耗时/用量结构；不包含提示词、摘要原文、附件、笔记、密钥或原始异常。"""

from typing import Literal

from pydantic import BaseModel, Field


class ModelUsageSummary(BaseModel):
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    usage_source: Literal["reported", "unknown"] = "unknown"
    estimated_cost: float | None = Field(default=None, ge=0)
    currency: str | None = None
    pricing_version: str | None = None
    cost_status: Literal["estimated", "unknown"] = "unknown"


SpanKind = Literal[
    "turn",
    "rag_context",
    "model",
    "tool_simbad",
    "tool_ads",
    "tool_gaia",
    "tool_literature_save",
    "tool_nbody_proposal",
    "tool_plot_proposal",
    "compute_task",
    "plot_run",
]

SpanStatus = Literal[
    "ok",
    "partial",
    "not_found",
    "error",
    "skipped",
    "cancelled",
    "interrupted",
    "running",
    "queued",
]

ErrorCategory = Literal[
    "none",
    "validation",
    "authorization",
    "mcp_subprocess",
    "mcp_protocol",
    "upstream",
    "not_found",
    "timeout",
    "rate_limit",
    "storage",
    "internal",
]


class RunSpan(BaseModel):
    span_id: str
    parent_span_id: str | None = None
    kind: SpanKind
    name: str
    status: SpanStatus
    started_at: str
    ended_at: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    transport: Literal["direct", "mcp", "internal"] | None = None
    provider: str | None = None
    model: str | None = None
    correlation_id: str | None = None
    truncated: bool | None = None
    result_count: int | None = Field(default=None, ge=0)
    error_category: ErrorCategory | None = None
    error_code: str | None = None
    result_ref: dict[str, str] | None = None
    usage: ModelUsageSummary | None = None


class RunTrace(BaseModel):
    trace_id: str
    conversation_id: str
    turn_id: str
    status: Literal["ok", "partial", "error", "interrupted", "running"]
    started_at: str
    ended_at: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    astronomy_transport: Literal["direct", "mcp"] | None = None
    spans: list[RunSpan] = Field(default_factory=list)
    usage: ModelUsageSummary | None = None
    available: bool = True
    retention_days: int = 30
