"""独立运行的本地 Astronomy MCP Server（stdio，目标协议 2026-07-28）。"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from typing import Any

import anyio
import anyio.from_thread
import anyio.lowlevel
import mcp_types as types
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from astroagent import __version__
from astroagent.ads import AdsService
from astroagent.gaia import GaiaService
from astroagent.mcp_contract import (
    DEFAULT_MCP_CALL_TIMEOUT_SECONDS,
    DEFAULT_MCP_MAX_MESSAGE_BYTES,
    DEFAULT_MCP_MAX_REQUEST_BYTES,
    DEFAULT_MCP_SERVER_MAX_CONCURRENCY,
    DEFAULT_MCP_SERVER_MAX_QUEUE_WAIT_SECONDS,
    MCP_CORRELATION_META_KEY,
    MCP_SERVER_DESCRIPTION,
    MCP_SERVER_INSTRUCTIONS,
    MCP_SERVER_NAME,
    MCP_SERVER_TITLE,
    MCP_TOOL_NAMES,
    TOOL_CONTRACTS,
    AstronomyResult,
    build_envelope,
    emit_mcp_log,
    sanitize_correlation_id,
)
from astroagent.mcp_stdio import bounded_stdio_server
from astroagent.schemas import ErrorInfo, GaiaQuery, LiteratureQuery, ObjectQuery
from astroagent.simbad import SimbadService
from astroagent.table_schemas import VizierQuery
from astroagent.vizier import VizierService

_WIRE_ENVELOPE_OVERHEAD_BYTES = 1024


class McpServerConfig(BaseModel):
    """仅从进程环境读取的只读天文查询 MCP 配置，不读取 .env、数据库或模型密钥。"""

    model_config = ConfigDict(extra="forbid")

    simbad_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    ads_api_token: SecretStr = SecretStr("")
    ads_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    gaia_timeout_seconds: float = Field(default=45.0, gt=0, le=120)
    vizier_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    call_timeout_seconds: float = Field(default=DEFAULT_MCP_CALL_TIMEOUT_SECONDS, ge=1.0, le=180.0)
    max_message_bytes: int = Field(
        default=DEFAULT_MCP_MAX_MESSAGE_BYTES, ge=64 * 1024, le=16 * 1024 * 1024
    )
    max_request_bytes: int = Field(
        default=DEFAULT_MCP_MAX_REQUEST_BYTES, ge=4 * 1024, le=1024 * 1024
    )
    max_concurrency: int = Field(default=DEFAULT_MCP_SERVER_MAX_CONCURRENCY, ge=1, le=4)
    max_queue_wait_seconds: float = Field(
        default=DEFAULT_MCP_SERVER_MAX_QUEUE_WAIT_SECONDS, ge=0.1, le=60.0
    )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> McpServerConfig:
        source = os.environ if env is None else env
        mapping = {
            "SIMBAD_TIMEOUT_SECONDS": "simbad_timeout_seconds",
            "ADS_API_TOKEN": "ads_api_token",
            "ADS_TIMEOUT_SECONDS": "ads_timeout_seconds",
            "GAIA_TIMEOUT_SECONDS": "gaia_timeout_seconds",
            "VIZIER_TIMEOUT_SECONDS": "vizier_timeout_seconds",
            "ASTROAGENT_MCP_CALL_TIMEOUT_SECONDS": "call_timeout_seconds",
            "ASTROAGENT_MCP_MAX_MESSAGE_BYTES": "max_message_bytes",
            "ASTROAGENT_MCP_MAX_REQUEST_BYTES": "max_request_bytes",
            "ASTROAGENT_MCP_SERVER_MAX_CONCURRENCY": "max_concurrency",
            "ASTROAGENT_MCP_SERVER_MAX_QUEUE_WAIT_SECONDS": "max_queue_wait_seconds",
        }
        values: dict[str, Any] = {}
        for env_key, field_name in mapping.items():
            raw = source.get(env_key)
            if raw is not None and raw != "":
                values[field_name] = raw
        return cls.model_validate(values)


def build_mcp_tools() -> list[types.Tool]:
    """构建固定三项只读天文工具声明（含输入/输出 JSON Schema 与只读注解）。"""
    tools: list[types.Tool] = []
    for name in MCP_TOOL_NAMES:
        contract = TOOL_CONTRACTS[name]
        tools.append(
            types.Tool(
                name=contract.name,
                title=contract.title,
                description=contract.description,
                input_schema=contract.input_schema,
                output_schema=contract.output_schema,
                annotations=types.ToolAnnotations(
                    title=contract.title,
                    read_only_hint=True,
                    destructive_hint=False,
                    idempotent_hint=True,
                    open_world_hint=True,
                ),
            )
        )
    return tools


def _call_tool_result(
    tool_name: str,
    *,
    result: AstronomyResult | None = None,
    error: ErrorInfo | None = None,
    is_error: bool,
) -> types.CallToolResult:
    envelope = build_envelope(tool_name, result=result, error=error)
    payload = envelope.model_dump(mode="json")
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structured_content=payload,
        is_error=is_error,
    )


def _returned_count(tool_name: str, result: AstronomyResult) -> int:
    if tool_name == "query_simbad":
        return 1 if result.status == "success" else 0
    return int(getattr(result, "returned_count", 0))


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _correlation_from_meta(meta: Mapping[str, Any] | None) -> str:
    raw = meta.get(MCP_CORRELATION_META_KEY) if isinstance(meta, Mapping) else None
    return sanitize_correlation_id(raw)


def build_astronomy_mcp_server(
    *,
    config: McpServerConfig | None = None,
    simbad: SimbadService | None = None,
    ads: AdsService | None = None,
    gaia: GaiaService | None = None,
    vizier: VizierService | None = None,
) -> Server[Any]:
    """创建可复用现有四类查询服务的 MCP Server 实例。"""
    resolved_config = config if config is not None else McpServerConfig.from_env()
    simbad_service = (
        simbad if simbad is not None else SimbadService(resolved_config.simbad_timeout_seconds)
    )
    ads_service = (
        ads
        if ads is not None
        else AdsService(resolved_config.ads_api_token, resolved_config.ads_timeout_seconds)
    )
    gaia_service = gaia if gaia is not None else GaiaService(resolved_config.gaia_timeout_seconds)
    vizier_service = (
        vizier
        if vizier is not None
        else VizierService(resolved_config.vizier_timeout_seconds, simbad=simbad_service)
    )

    tools = build_mcp_tools()
    slots = anyio.lowlevel.RunVar[anyio.Semaphore]("astronomy-query-slots")

    def get_semaphore() -> anyio.Semaphore:
        semaphore = slots.get(None)
        if semaphore is None:
            semaphore = anyio.Semaphore(resolved_config.max_concurrency)
            slots.set(semaphore)
        return semaphore

    async def handle_list_tools(
        ctx: Any,
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        if params is not None and params.cursor is not None:
            raise MCPError(
                code=types.INVALID_PARAMS,
                message="Pagination cursor is not supported",
            )
        emit_mcp_log(
            component="mcp_server",
            event="mcp_tools_list",
            correlation_id=_correlation_from_meta(ctx.meta),
            protocol_version=ctx.protocol_version,
            result_status="success",
            returned_count=len(tools),
        )
        return types.ListToolsResult(tools=tools)

    async def handle_call_tool(
        ctx: Any,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        started = time.monotonic()
        tool_name = params.name
        protocol_version = ctx.protocol_version
        correlation_id = _correlation_from_meta(ctx.meta)

        contract = TOOL_CONTRACTS.get(tool_name)
        if contract is None:
            emit_mcp_log(
                component="mcp_server",
                event="mcp_tool_call",
                correlation_id=correlation_id,
                protocol_version=protocol_version,
                duration_ms=_elapsed_ms(started),
                result_status="protocol_error",
                error_code="unknown_tool",
            )
            raise MCPError(
                code=types.INVALID_PARAMS,
                message=f"Unknown tool: {tool_name}",
            )

        raw_arguments = {} if params.arguments is None else params.arguments
        if not isinstance(raw_arguments, dict):
            emit_mcp_log(
                component="mcp_server",
                event="mcp_tool_call",
                correlation_id=correlation_id,
                tool=tool_name,
                protocol_version=protocol_version,
                duration_ms=_elapsed_ms(started),
                result_status="mcp_error",
                error_code="invalid_tool_arguments",
            )
            return _call_tool_result(
                tool_name,
                error=ErrorInfo(
                    code="invalid_tool_arguments",
                    message="工具参数必须是 JSON 对象。",
                    retryable=False,
                ),
                is_error=True,
            )

        try:
            validated = contract.input_model.model_validate(raw_arguments)
        except (ValidationError, ValueError, TypeError):
            emit_mcp_log(
                component="mcp_server",
                event="mcp_tool_call",
                correlation_id=correlation_id,
                tool=tool_name,
                protocol_version=protocol_version,
                duration_ms=_elapsed_ms(started),
                result_status="mcp_error",
                error_code="invalid_tool_arguments",
            )
            return _call_tool_result(
                tool_name,
                error=ErrorInfo(
                    code="invalid_tool_arguments",
                    message="工具参数无效，请核对字段类型、范围与互斥条件。",
                    retryable=False,
                ),
                is_error=True,
            )

        token = anyio.lowlevel.current_token()
        semaphore = get_semaphore()
        acquired = False
        with anyio.move_on_after(resolved_config.max_queue_wait_seconds):
            await semaphore.acquire()
            acquired = True
        if not acquired:
            emit_mcp_log(
                component="mcp_server",
                event="mcp_tool_call",
                correlation_id=correlation_id,
                tool=tool_name,
                protocol_version=protocol_version,
                duration_ms=_elapsed_ms(started),
                result_status="mcp_error",
                error_code="mcp_server_busy",
            )
            return _call_tool_result(
                tool_name,
                error=ErrorInfo(
                    code="mcp_server_busy",
                    message="MCP 查询服务并发已满，请稍后重试。",
                    retryable=True,
                ),
                is_error=True,
            )

        def execute_query() -> AstronomyResult:
            if tool_name == "query_simbad":
                assert isinstance(validated, ObjectQuery)
                return simbad_service.query(validated.object_name)
            if tool_name == "search_ads":
                assert isinstance(validated, LiteratureQuery)
                return ads_service.search(validated)
            if tool_name == "query_vizier":
                assert isinstance(validated, VizierQuery)
                return vizier_service.query(validated)
            assert isinstance(validated, GaiaQuery)
            return gaia_service.query(validated)

        done = anyio.Event()
        outcome: list[tuple[str, Any]] = []

        def worker(fn: Callable[[], AstronomyResult] = execute_query) -> None:
            try:
                outcome.append(("ok", fn()))
            except BaseException as exc:
                outcome.append(("err", exc))
            finally:
                # 阻塞查询真正退出后才释放执行槽，避免超时或取消时叠加后台负载。
                with suppress(RuntimeError, anyio.ClosedResourceError):
                    anyio.from_thread.run_sync(done.set, token=token)
                with suppress(RuntimeError, anyio.ClosedResourceError):
                    anyio.from_thread.run_sync(semaphore.release, token=token)

        thread = threading.Thread(target=worker, name=f"astroagent-mcp-{tool_name}", daemon=True)
        started_thread = False
        try:
            thread.start()
            started_thread = True
        except BaseException:
            if not started_thread:
                semaphore.release()
            emit_mcp_log(
                component="mcp_server",
                event="mcp_tool_call",
                correlation_id=correlation_id,
                tool=tool_name,
                protocol_version=protocol_version,
                duration_ms=_elapsed_ms(started),
                result_status="mcp_error",
                error_code="mcp_server_error",
            )
            return _call_tool_result(
                tool_name,
                error=ErrorInfo(
                    code="mcp_server_error",
                    message="无法启动查询执行线程，请稍后重试。",
                    retryable=True,
                ),
                is_error=True,
            )

        timed_out = False
        try:
            with anyio.move_on_after(resolved_config.call_timeout_seconds) as scope:
                await done.wait()
            timed_out = scope.cancelled_caught
        except anyio.get_cancelled_exc_class():
            emit_mcp_log(
                component="mcp_server",
                event="mcp_tool_call",
                correlation_id=correlation_id,
                tool=tool_name,
                protocol_version=protocol_version,
                duration_ms=_elapsed_ms(started),
                result_status="mcp_error",
                error_code="mcp_cancelled",
            )
            raise

        if timed_out or not outcome:
            emit_mcp_log(
                component="mcp_server",
                event="mcp_tool_call",
                correlation_id=correlation_id,
                tool=tool_name,
                protocol_version=protocol_version,
                duration_ms=_elapsed_ms(started),
                result_status="mcp_error",
                error_code="mcp_tool_timeout",
            )
            return _call_tool_result(
                tool_name,
                error=ErrorInfo(
                    code="mcp_tool_timeout",
                    message="天文查询超过 MCP 单调用总时限，未返回结果。",
                    retryable=True,
                ),
                is_error=True,
            )

        kind, value = outcome[0]
        if kind != "ok":
            emit_mcp_log(
                component="mcp_server",
                event="mcp_tool_call",
                correlation_id=correlation_id,
                tool=tool_name,
                protocol_version=protocol_version,
                duration_ms=_elapsed_ms(started),
                result_status="mcp_error",
                error_code="mcp_server_error",
            )
            return _call_tool_result(
                tool_name,
                error=ErrorInfo(
                    code="mcp_server_error",
                    message="查询适配器内部异常，未返回原始堆栈。",
                    retryable=False,
                ),
                is_error=True,
            )

        service_result: AstronomyResult = value
        call_result = _call_tool_result(
            tool_name,
            result=service_result,
            is_error=service_result.status == "error",
        )
        wire_bytes = len(
            call_result.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")
        )
        if wire_bytes + _WIRE_ENVELOPE_OVERHEAD_BYTES > resolved_config.max_message_bytes:
            emit_mcp_log(
                component="mcp_server",
                event="mcp_tool_call",
                correlation_id=correlation_id,
                tool=tool_name,
                protocol_version=protocol_version,
                duration_ms=_elapsed_ms(started),
                result_status="mcp_error",
                error_code="mcp_response_too_large",
            )
            return _call_tool_result(
                tool_name,
                error=ErrorInfo(
                    code="mcp_response_too_large",
                    message="查询结果超过 MCP 消息大小上限，未截断返回。",
                    retryable=False,
                ),
                is_error=True,
            )

        emit_mcp_log(
            component="mcp_server",
            event="mcp_tool_call",
            correlation_id=correlation_id,
            tool=tool_name,
            protocol_version=protocol_version,
            duration_ms=_elapsed_ms(started),
            result_status=service_result.status,
            returned_count=_returned_count(tool_name, service_result),
            error_code=service_result.error.code if service_result.error is not None else None,
        )
        return call_result

    return Server(
        MCP_SERVER_NAME,
        version=__version__,
        title=MCP_SERVER_TITLE,
        description=MCP_SERVER_DESCRIPTION,
        instructions=MCP_SERVER_INSTRUCTIONS,
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )


def _configure_stderr_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.WARNING)


async def serve_stdio(config: McpServerConfig | None = None) -> None:
    resolved = config if config is not None else McpServerConfig.from_env()
    server = build_astronomy_mcp_server(config=resolved)
    emit_mcp_log(
        component="mcp_server",
        event="mcp_server_start",
        result_status="ready",
    )
    async with bounded_stdio_server(
        max_request_bytes=resolved.max_request_bytes,
        max_response_bytes=resolved.max_message_bytes,
    ) as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    _configure_stderr_logging()
    if args:
        sys.stderr.write(
            "astroagent.mcp_server does not accept CLI arguments; configure via environment.\n"
        )
        raise SystemExit(2)
    try:
        config = McpServerConfig.from_env()
    except ValidationError:
        sys.stderr.write(
            "Invalid Astronomy MCP Server environment configuration; check query limits.\n"
        )
        raise SystemExit(2) from None
    try:
        anyio.run(serve_stdio, config)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
