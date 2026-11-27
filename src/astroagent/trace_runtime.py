"""会话运行追踪采集器、错误归类与模型用量/估算费用聚合。"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from uuid import uuid4

from astroagent.trace_schemas import (
    ErrorCategory,
    ModelUsageSummary,
    RunSpan,
    RunTrace,
    SpanKind,
    SpanStatus,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


REFERENCE_PRICING: dict[str, dict] = {
    "gemini-4-hydrogen": {"input_per_1m": 1.50, "output_per_1m": 7.50, "currency": "USD"},
    "gemini-4-carbon": {"input_per_1m": 2.00, "output_per_1m": 10.0, "currency": "USD"},
    "gemini-4-argon": {"input_per_1m": 2.00, "output_per_1m": 10.0, "currency": "USD"},
    "gemini-4-neon": {"input_per_1m": 3.00, "output_per_1m": 15.0, "currency": "USD"},
    "gemini-3-pro": {"input_per_1m": 2.00, "output_per_1m": 12.0, "currency": "USD"},
    "gemini-3.0-pro": {"input_per_1m": 2.00, "output_per_1m": 12.0, "currency": "USD"},
    "gemini-3-flash": {"input_per_1m": 0.50, "output_per_1m": 3.00, "currency": "USD"},
    "gemini-2.5-pro": {"input_per_1m": 1.25, "output_per_1m": 10.0, "currency": "USD"},
    "gemini-2.5-flash": {"input_per_1m": 0.30, "output_per_1m": 2.50, "currency": "USD"},
    "gemini-2.5-flash-lite": {"input_per_1m": 0.10, "output_per_1m": 0.40, "currency": "USD"},
    "gemini-2.0-flash": {"input_per_1m": 0.10, "output_per_1m": 0.40, "currency": "USD"},
    "gemini-2.0-flash-lite": {"input_per_1m": 0.075, "output_per_1m": 0.30, "currency": "USD"},
    "deepseek-flash": {"input_per_1m": 0.30, "output_per_1m": 1.20, "currency": "USD"},
    "deepseek-v4-flash": {"input_per_1m": 0.30, "output_per_1m": 1.20, "currency": "USD"},
    "deepseek-v4.1-flash": {"input_per_1m": 0.30, "output_per_1m": 1.20, "currency": "USD"},
    "deepseek-v4-pro": {"input_per_1m": 1.32, "output_per_1m": 3.96, "currency": "USD"},
    "deepseek-chat": {"input_per_1m": 0.27, "output_per_1m": 1.10, "currency": "USD"},
    "deepseek-reasoner": {"input_per_1m": 0.55, "output_per_1m": 2.19, "currency": "USD"},
    "gpt-5": {"input_per_1m": 1.25, "output_per_1m": 10.0, "currency": "USD"},
    "gpt-5-mini": {"input_per_1m": 0.25, "output_per_1m": 2.00, "currency": "USD"},
    "gpt-4.1": {"input_per_1m": 2.00, "output_per_1m": 8.00, "currency": "USD"},
    "gpt-4.1-mini": {"input_per_1m": 0.40, "output_per_1m": 1.60, "currency": "USD"},
    "gpt-4.1-nano": {"input_per_1m": 0.10, "output_per_1m": 0.40, "currency": "USD"},
    "gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.0, "currency": "USD"},
    "gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60, "currency": "USD"},
    "o3": {"input_per_1m": 2.00, "output_per_1m": 8.00, "currency": "USD"},
    "o4-mini": {"input_per_1m": 1.10, "output_per_1m": 4.40, "currency": "USD"},
    "claude-opus-4": {"input_per_1m": 15.0, "output_per_1m": 75.0, "currency": "USD"},
    "claude-sonnet-4": {"input_per_1m": 3.00, "output_per_1m": 15.0, "currency": "USD"},
    "claude-3-7-sonnet": {"input_per_1m": 3.00, "output_per_1m": 15.0, "currency": "USD"},
    "claude-3-5-sonnet": {"input_per_1m": 3.00, "output_per_1m": 15.0, "currency": "USD"},
    "claude-3-5-haiku": {"input_per_1m": 0.80, "output_per_1m": 4.00, "currency": "USD"},
}


def _load_pricing_table() -> dict[str, dict]:
    raw = os.getenv("ASTROAGENT_MODEL_PRICING_JSON", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _normalize_model_key(name: str) -> str:
    cleaned = name.strip().lower()
    if "/" in cleaned:
        cleaned = cleaned.rsplit("/", 1)[-1]
    return re.sub(r"[\s_]+", "-", cleaned)


def lookup_reference_pricing(candidates: list[str]) -> dict | None:
    best_key = ""
    best_entry: dict | None = None
    for candidate in candidates:
        norm = _normalize_model_key(candidate)
        if not norm:
            continue
        if norm in REFERENCE_PRICING:
            return {**REFERENCE_PRICING[norm], "version": "官方参考价"}
        for key, entry in REFERENCE_PRICING.items():
            if norm.startswith(key + "-") or norm.startswith(key + "."):
                if len(key) > len(best_key):
                    best_key = key
                    best_entry = entry
    if best_entry is not None:
        return {**best_entry, "version": "官方参考价"}
    return None


def _lookup_pricing_entry(
    candidates: list[str],
    *,
    pricing_override: dict | None = None,
    configured_pricing: dict[str, dict] | None = None,
) -> dict | None:
    if isinstance(pricing_override, dict):
        return pricing_override
    env_table = _load_pricing_table()
    for candidate in candidates:
        if not candidate:
            continue
        entry = env_table.get(candidate) or env_table.get(candidate.split(":", 1)[-1])
        if isinstance(entry, dict):
            return entry
    if configured_pricing:
        for candidate in candidates:
            if not candidate:
                continue
            entry = configured_pricing.get(candidate) or configured_pricing.get(
                _normalize_model_key(candidate)
            )
            if isinstance(entry, dict):
                return entry
    return lookup_reference_pricing(candidates)


def estimate_usage_cost(
    *,
    provider: str | None,
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
    pricing_candidates: list[str] | None = None,
    pricing_override: dict | None = None,
    configured_pricing: dict[str, dict] | None = None,
) -> ModelUsageSummary:
    has_reported = input_tokens is not None or output_tokens is not None or total_tokens is not None
    if has_reported and total_tokens is None:
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
    summary = ModelUsageSummary(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        usage_source="reported" if has_reported else "unknown",
    )
    if not has_reported or input_tokens is None or output_tokens is None:
        return summary
    candidates: list[str] = []
    for item in [*(pricing_candidates or ()), model or ""]:
        if item and item not in candidates:
            candidates.append(item)
    if not candidates and pricing_override is None:
        return summary
    entry = _lookup_pricing_entry(
        candidates,
        pricing_override=pricing_override,
        configured_pricing=configured_pricing,
    )
    if not isinstance(entry, dict):
        return summary
    try:
        in_rate = float(entry["input_per_1m"])
        out_rate = float(entry["output_per_1m"])
        currency = str(entry.get("currency") or "USD")
        version = str(entry.get("version") or "已配置单价")
        if in_rate < 0 or out_rate < 0:
            return summary
        cost = round((input_tokens * in_rate + output_tokens * out_rate) / 1_000_000.0, 6)
        summary.estimated_cost = cost
        summary.currency = currency
        summary.pricing_version = version
        summary.cost_status = "estimated"
    except (KeyError, TypeError, ValueError):
        return summary
    return summary


def extract_message_usage(
    message,
    *,
    provider: str | None = None,
    model: str | None = None,
    pricing_candidates: list[str] | None = None,
    pricing_override: dict | None = None,
) -> ModelUsageSummary:
    meta = getattr(message, "response_metadata", None) or {}
    usage = getattr(message, "usage_metadata", None)
    if not isinstance(usage, dict):
        usage = meta.get("token_usage") or meta.get("usage")
    if not isinstance(usage, dict):
        return ModelUsageSummary(provider=provider, model=model, usage_source="unknown")
    in_tok = usage.get("input_tokens")
    if in_tok is None:
        in_tok = usage.get("prompt_tokens")
    out_tok = usage.get("output_tokens")
    if out_tok is None:
        out_tok = usage.get("completion_tokens")
    tot_tok = usage.get("total_tokens")
    in_val = int(in_tok) if isinstance(in_tok, int) and in_tok >= 0 else None
    out_val = int(out_tok) if isinstance(out_tok, int) and out_tok >= 0 else None
    tot_val = int(tot_tok) if isinstance(tot_tok, int) and tot_tok >= 0 else None
    if in_val == 0 and out_val == 0 and (tot_val is None or tot_val == 0):
        # Some streaming endpoints emit placeholder zeros when usage is not reported.
        return ModelUsageSummary(provider=provider, model=model, usage_source="unknown")
    candidates = list(pricing_candidates or ())
    resp_model = meta.get("model_name") or meta.get("model")
    if isinstance(resp_model, str) and resp_model and resp_model not in candidates:
        candidates.append(resp_model)
    return estimate_usage_cost(
        provider=provider,
        model=model,
        input_tokens=in_val,
        output_tokens=out_val,
        total_tokens=tot_val,
        pricing_candidates=candidates,
        pricing_override=pricing_override,
    )


def enrich_trace_cost(
    trace: RunTrace,
    *,
    configured_pricing: dict[str, dict] | None = None,
    model_aliases: dict[str, list[str]] | None = None,
) -> RunTrace:
    """Resolve cost dynamically on read when pricing was configured after the turn ran."""
    usage = trace.usage
    if (
        usage is None
        or usage.usage_source != "reported"
        or usage.cost_status == "estimated"
        or usage.input_tokens is None
        or usage.output_tokens is None
    ):
        return trace
    candidates: list[str] = []
    for raw in [usage.model, *(span.model for span in trace.spans if span.kind == "model")]:
        if not raw:
            continue
        if raw not in candidates:
            candidates.append(raw)
        for alias in (model_aliases or {}).get(raw, ()):
            if alias not in candidates:
                candidates.append(alias)
    recomputed = estimate_usage_cost(
        provider=usage.provider,
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        pricing_candidates=candidates,
        configured_pricing=configured_pricing,
    )
    if recomputed.cost_status != "estimated":
        return trace
    return trace.model_copy(update={"usage": recomputed})


def classify_error_code(code: str | None) -> ErrorCategory:
    if not code:
        return "none"
    lower = code.lower()
    if lower in {
        "mcp_process_exited",
        "mcp_startup_failed",
        "mcp_not_configured",
        "mcp_pool_busy",
        "mcp_acquire_timeout",
        "mcp_subprocess_failed",
    }:
        return "mcp_subprocess"
    if lower in {
        "mcp_invalid_wire",
        "mcp_contract_invalid",
        "mcp_response_too_large",
        "mcp_request_too_large",
        "mcp_protocol_mismatch",
        "mcp_incompatible_protocol",
        "mcp_protocol_error",
    }:
        return "mcp_protocol"
    if lower in {
        "mcp_transport_error",
        "mcp_dns_failed",
        "mcp_http_error",
        "mcp_redirect_blocked",
    }:
        return "mcp_transport"
    if "budget" in lower or lower == "agent_limit_reached":
        return "budget_exceeded"
    if "timeout" in lower:
        return "timeout"
    if "rate_limit" in lower:
        return "rate_limit"
    if "not_found" in lower:
        return "not_found"
    if (
        "auth" in lower
        or "permission" in lower
        or "scope" in lower
        or "consumed" in lower
        or "egress_blocked" in lower
        or "revoked" in lower
        or "definition_changed" in lower
    ):
        return "authorization"
    if "invalid" in lower or "validation" in lower or "ambiguous" in lower:
        return "validation"
    if "database" in lower or "storage" in lower:
        return "storage"
    if lower.startswith(("simbad_", "ads_", "gaia_", "model_")):
        return "upstream"
    return "internal"


class TraceRecorder:
    """单轮会话的结构化脱敏追踪记录器。"""

    def __init__(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        astronomy_transport: str | None = None,
    ):
        self.trace_id = str(uuid4())
        self.root_span_id = str(uuid4())
        self.conversation_id = conversation_id
        self.turn_id = turn_id
        self.astronomy_transport = (
            astronomy_transport if astronomy_transport in ("direct", "mcp") else None
        )
        self.started_at = _now_iso()
        self._started_mono = time.monotonic()
        self.spans: list[RunSpan] = []
        self.pricing_candidates: list[str] = []
        self.pricing_override: dict | None = None
        self.skill_id: str | None = None
        self.skill_title: str | None = None
        self.skill_version: str | None = None
        self.skill_mode: str | None = None
        self.tool_manifest_sha256: str | None = None
        self.memory_context = None

    def start_span(
        self,
        *,
        kind: SpanKind,
        name: str,
        transport: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> tuple[str, str, float]:
        return str(uuid4()), _now_iso(), time.monotonic()

    def record_span(
        self,
        *,
        span_id: str,
        started_at: str,
        started_mono: float,
        kind: SpanKind,
        name: str,
        status: SpanStatus,
        transport: str | None = None,
        tool_source: str | None = None,
        protocol_version: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        correlation_id: str | None = None,
        truncated: bool | None = None,
        result_count: int | None = None,
        error_code: str | None = None,
        error_category: ErrorCategory | None = None,
        result_ref: dict[str, str] | None = None,
        usage: ModelUsageSummary | None = None,
    ) -> RunSpan:
        ended_at = _now_iso()
        duration_ms = max(0, int((time.monotonic() - started_mono) * 1000))
        span = RunSpan(
            span_id=span_id,
            parent_span_id=self.root_span_id,
            kind=kind,
            name=name,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            transport=transport
            if transport in ("direct", "mcp", "external_mcp", "internal")
            else None,
            tool_source=tool_source
            if tool_source in ("builtin", "local_mcp", "external_mcp")
            else None,
            protocol_version=protocol_version,
            provider=provider,
            model=model,
            correlation_id=correlation_id,
            truncated=truncated,
            result_count=result_count,
            error_category=error_category
            or (classify_error_code(error_code) if error_code else None),
            error_code=error_code,
            result_ref=result_ref,
            usage=usage,
        )
        self.spans.append(span)
        return span

    def _aggregate_usage(self) -> ModelUsageSummary | None:
        model_spans = [s for s in self.spans if s.kind == "model" and s.usage is not None]
        if not model_spans:
            return None
        provider = next(
            (s.usage.provider for s in model_spans if s.usage and s.usage.provider), None
        )
        model = next((s.usage.model for s in model_spans if s.usage and s.usage.model), None)
        reported = [s.usage for s in model_spans if s.usage and s.usage.usage_source == "reported"]
        if not reported:
            return ModelUsageSummary(provider=provider, model=model, usage_source="unknown")
        in_total = sum(u.input_tokens or 0 for u in reported)
        out_total = sum(u.output_tokens or 0 for u in reported)
        tot_total = sum(
            u.total_tokens or ((u.input_tokens or 0) + (u.output_tokens or 0)) for u in reported
        )
        return estimate_usage_cost(
            provider=provider,
            model=model,
            input_tokens=in_total,
            output_tokens=out_total,
            total_tokens=tot_total,
            pricing_candidates=self.pricing_candidates,
            pricing_override=self.pricing_override,
        )

    def finalize(self, status: str, error_code: str | None = None) -> RunTrace:
        del error_code
        normalized = (
            status if status in ("ok", "partial", "error", "interrupted", "running") else "error"
        )
        return RunTrace(
            trace_id=self.trace_id,
            conversation_id=self.conversation_id,
            turn_id=self.turn_id,
            status=normalized,
            started_at=self.started_at,
            ended_at=_now_iso(),
            duration_ms=max(0, int((time.monotonic() - self._started_mono) * 1000)),
            astronomy_transport=self.astronomy_transport,
            skill_id=self.skill_id,
            skill_title=self.skill_title,
            skill_version=self.skill_version,
            skill_mode=self.skill_mode
            if self.skill_mode
            in ("explicit", "auto", "disabled", "none", "ambiguous", "auto_disabled")
            else None,
            tool_manifest_sha256=self.tool_manifest_sha256,
            memory_context=self.memory_context,
            spans=list(self.spans),
            usage=self._aggregate_usage(),
            available=True,
        )
