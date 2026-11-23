"""AstroAgent 后端固定的本地 Astronomy MCP Client 连接池与工具适配器。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import threading
import time
import uuid
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
from pydantic import ValidationError

from astroagent import __version__
from astroagent.errors import ServiceError
from astroagent.mcp_contract import (
    DEFAULT_MCP_ACQUIRE_TIMEOUT_SECONDS,
    DEFAULT_MCP_CALL_TIMEOUT_SECONDS,
    DEFAULT_MCP_MAX_MESSAGE_BYTES,
    DEFAULT_MCP_MAX_REQUEST_BYTES,
    DEFAULT_MCP_POOL_SIZE,
    DEFAULT_MCP_STARTUP_TIMEOUT_SECONDS,
    MCP_CLIENT_NAME,
    MCP_CORRELATION_META_KEY,
    MCP_TARGET_PROTOCOL_VERSION,
    MCP_TOOL_NAMES,
    AstronomyResult,
    emit_mcp_log,
    map_adapter_error,
    parse_structured_tool_output,
    sanitize_correlation_id,
    verify_tool_manifest,
)
from astroagent.schemas import (
    GaiaQuery,
    GaiaQueryResult,
    LiteratureQuery,
    LiteratureSearchResult,
    ObjectQuery,
    QueryResult,
)

if TYPE_CHECKING:
    from astroagent.config import LocalSettings, Settings

TRANSPORT_META_KEY = "astronomy_tool_transport_v1"

_SAFE_RUNTIME_ENV_KEYS = (
    "HOME",
    "TMP",
    "TEMP",
    "XDG_CACHE_HOME",
    "ASTROPY_CACHE_DIR",
    "PYTHON_KEYRING_BACKEND",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)

_FORBIDDEN_SECRET_PREFIXES = (
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


@dataclass(frozen=True, slots=True)
class McpPoolConfig:
    startup_timeout_seconds: float = DEFAULT_MCP_STARTUP_TIMEOUT_SECONDS
    call_timeout_seconds: float = DEFAULT_MCP_CALL_TIMEOUT_SECONDS
    max_message_bytes: int = DEFAULT_MCP_MAX_MESSAGE_BYTES
    max_request_bytes: int = DEFAULT_MCP_MAX_REQUEST_BYTES
    pool_size: int = DEFAULT_MCP_POOL_SIZE
    acquire_timeout_seconds: float = DEFAULT_MCP_ACQUIRE_TIMEOUT_SECONDS

    @classmethod
    def from_local_settings(cls, local: LocalSettings) -> McpPoolConfig:
        return cls(
            startup_timeout_seconds=local.mcp_startup_timeout_seconds,
            call_timeout_seconds=local.mcp_call_timeout_seconds,
            max_message_bytes=local.mcp_max_message_bytes,
            max_request_bytes=local.mcp_max_request_bytes,
            pool_size=local.mcp_pool_size,
            acquire_timeout_seconds=local.mcp_acquire_timeout_seconds,
        )


def _import_mcp_sdk():
    try:
        import mcp_types as types
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, get_default_environment
        from mcp.shared.exceptions import MCPError

        from astroagent.mcp_stdio import (
            McpInvalidWireError,
            McpRequestTooLargeError,
            McpResponseTooLargeError,
            WireErrorSink,
            bounded_stdio_client,
        )
    except ImportError as exc:
        raise ServiceError(
            503,
            "mcp_not_configured",
            "已启用 MCP 天文查询通道，但服务端未安装 mcp 可选依赖；"
            "请安装 astroagent[mcp] 或将 ASTROAGENT_ASTRONOMY_TOOL_TRANSPORT 切回 direct。",
            retryable=False,
        ) from exc
    return (
        types,
        ClientSession,
        StdioServerParameters,
        get_default_environment,
        MCPError,
        McpInvalidWireError,
        McpRequestTooLargeError,
        McpResponseTooLargeError,
        WireErrorSink,
        bounded_stdio_client,
    )


def build_mcp_subprocess_env(
    settings: Settings,
    pool_config: McpPoolConfig,
) -> dict[str, str]:
    """仅为 MCP 子进程构造最小必需环境；排除模型、数据库、认证与代理凭据。"""
    _, _, _, get_default_environment, *_ = _import_mcp_sdk()
    env = dict(get_default_environment())
    for key in _SAFE_RUNTIME_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None and "\x00" not in value:
            env[key] = value
    for key in list(env):
        if key.upper().startswith(_FORBIDDEN_SECRET_PREFIXES):
            env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"
    src_root = Path(__file__).resolve().parents[1]
    if src_root.name == "src":
        existing_pythonpath = os.environ.get("PYTHONPATH", "")
        parts = [str(src_root)]
        if existing_pythonpath:
            parts.append(existing_pythonpath)
        env["PYTHONPATH"] = os.pathsep.join(parts)

    env["SIMBAD_TIMEOUT_SECONDS"] = str(settings.simbad_timeout_seconds)
    env["ADS_TIMEOUT_SECONDS"] = str(settings.ads_timeout_seconds)
    env["GAIA_TIMEOUT_SECONDS"] = str(settings.gaia_timeout_seconds)
    ads_token = settings.ads_api_token.get_secret_value().strip()
    if ads_token:
        env["ADS_API_TOKEN"] = ads_token
    else:
        env.pop("ADS_API_TOKEN", None)

    env["ASTROAGENT_MCP_CALL_TIMEOUT_SECONDS"] = str(pool_config.call_timeout_seconds)
    env["ASTROAGENT_MCP_MAX_MESSAGE_BYTES"] = str(pool_config.max_message_bytes)
    env["ASTROAGENT_MCP_MAX_REQUEST_BYTES"] = str(pool_config.max_request_bytes)
    env["ASTROAGENT_MCP_SERVER_MAX_CONCURRENCY"] = "1"
    env["ASTROAGENT_MCP_SERVER_MAX_QUEUE_WAIT_SECONDS"] = "1.0"
    return env


def _env_fingerprint(command: str, args: list[str], env: dict[str, str]) -> str:
    payload = json.dumps(
        {"command": command, "args": args, "env": sorted(env.items())},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _build_fixed_server_params(settings: Settings, pool_config: McpPoolConfig):
    _, _, StdioServerParameters, *_ = _import_mcp_sdk()
    env = build_mcp_subprocess_env(settings, pool_config)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "astroagent.mcp_server"],
        env=env,
    )
    return params, _env_fingerprint(params.command, params.args, env)


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _returned_count(tool_name: str, result: AstronomyResult) -> int:
    if tool_name == "query_simbad":
        return 1 if result.status == "success" else 0
    return int(getattr(result, "returned_count", 0))


class _McpConnection:
    """单条 MCP stdio 子进程连接，负责协议发现、清单核验、单调用执行与回收。"""

    def __init__(
        self,
        *,
        server_params: Any,
        fingerprint: str,
        pool_config: McpPoolConfig,
    ):
        self._server_params = server_params
        self.fingerprint = fingerprint
        self._pool_config = pool_config
        self._exit_stack: AsyncExitStack | None = None
        self.session: Any = None
        self.wire_errors: Any = None
        self.protocol_version: str | None = None
        self.server_version: str | None = None
        self.tool_names: list[str] = []
        self.closed = False

    async def open(self, correlation_id: str) -> None:
        (
            types,
            ClientSession,
            _,
            _,
            MCPError,
            McpInvalidWireError,
            McpRequestTooLargeError,
            McpResponseTooLargeError,
            WireErrorSink,
            bounded_stdio_client,
        ) = _import_mcp_sdk()
        started = time.monotonic()
        self.wire_errors = WireErrorSink()
        stack = AsyncExitStack()
        try:
            read_stream, write_stream = await stack.enter_async_context(
                bounded_stdio_client(
                    self._server_params,
                    max_message_bytes=self._pool_config.max_message_bytes,
                    max_request_bytes=self._pool_config.max_request_bytes,
                    errlog=sys.stderr,
                    error_sink=self.wire_errors,
                )
            )
            session = await stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                    client_info=types.Implementation(
                        name=MCP_CLIENT_NAME,
                        version=__version__,
                    ),
                )
            )
            with anyio.fail_after(self._pool_config.startup_timeout_seconds):
                raw_discover = await session.send_discover(MCP_TARGET_PROTOCOL_VERSION)
                discover = types.DiscoverResult.model_validate(raw_discover)
                if MCP_TARGET_PROTOCOL_VERSION not in discover.supported_versions:
                    raise ValueError("Server does not advertise required MCP protocol version")
                if discover.capabilities.tools is None:
                    raise ValueError("Server does not advertise tools capability")
                session.adopt(discover)
                tools: list[Any] = []
                cursor: str | None = None
                for _ in range(10):
                    params = (
                        types.PaginatedRequestParams(cursor=cursor) if cursor is not None else None
                    )
                    listed = await session.list_tools(params=params)
                    tools.extend(listed.tools)
                    cursor = listed.next_cursor
                    if cursor is None:
                        break
                else:
                    raise ValueError("Server tool listing pagination exceeded limit")
                verify_tool_manifest(tools)
            self._exit_stack = stack
            self.session = session
            self.protocol_version = session.protocol_version
            self.server_version = (
                session.server_info.version if session.server_info is not None else ""
            )
            self.tool_names = [tool.name for tool in tools]
            self.closed = False
            emit_mcp_log(
                component="mcp_client",
                event="mcp_client_connect",
                correlation_id=correlation_id,
                protocol_version=self.protocol_version,
                duration_ms=_elapsed_ms(started),
                result_status="success",
                returned_count=len(self.tool_names),
            )
        except BaseException as exc:
            with anyio.CancelScope(shield=True):
                with suppress(Exception):
                    await stack.aclose()
            self.closed = True
            self.session = None
            self._exit_stack = None
            if isinstance(exc, asyncio.CancelledError):
                raise
            mapped = self._map_connect_error(
                exc,
                MCPError=MCPError,
                types=types,
                McpInvalidWireError=McpInvalidWireError,
                McpRequestTooLargeError=McpRequestTooLargeError,
                McpResponseTooLargeError=McpResponseTooLargeError,
            )
            emit_mcp_log(
                component="mcp_client",
                event="mcp_client_connect",
                correlation_id=correlation_id,
                protocol_version=self.protocol_version,
                duration_ms=_elapsed_ms(started),
                result_status="mcp_error",
                error_code=mapped.error.code,
            )
            raise mapped from exc

    def _map_connect_error(
        self,
        exc: BaseException,
        *,
        MCPError: type[Exception],
        types: Any,
        McpInvalidWireError: type[Exception],
        McpRequestTooLargeError: type[Exception],
        McpResponseTooLargeError: type[Exception],
    ) -> ServiceError:
        wire_error = self.wire_errors.error if self.wire_errors is not None else None
        if isinstance(wire_error, McpResponseTooLargeError):
            return ServiceError(
                502,
                "mcp_response_too_large",
                "MCP 服务端握手响应超过消息大小上限，连接已终止。",
            )
        if isinstance(wire_error, McpRequestTooLargeError):
            return ServiceError(
                502,
                "mcp_request_too_large",
                "MCP 客户端握手请求超过消息大小上限。",
            )
        if isinstance(wire_error, McpInvalidWireError):
            return ServiceError(
                502,
                "mcp_contract_invalid",
                "MCP 服务端输出了不合法的协议帧，连接已终止。",
            )
        if isinstance(exc, TimeoutError):
            return ServiceError(
                504,
                "mcp_timeout",
                "本地 MCP 服务启动或协议核验超时，请稍后重试。",
                retryable=True,
            )
        if isinstance(exc, MCPError):
            code = getattr(exc, "code", None)
            if code in (
                types.UNSUPPORTED_PROTOCOL_VERSION,
                types.METHOD_NOT_FOUND,
                types.INVALID_REQUEST,
                types.INVALID_PARAMS,
            ):
                return ServiceError(
                    502,
                    "mcp_incompatible_protocol",
                    "MCP 服务协议版本或能力与 2026-07-28 契约不兼容，已停止调用。",
                )
            if code == types.REQUEST_TIMEOUT:
                return ServiceError(
                    504,
                    "mcp_timeout",
                    "本地 MCP 服务启动或协议核验超时，请稍后重试。",
                    retryable=True,
                )
            return ServiceError(
                502,
                "mcp_process_exited",
                "本地 MCP 服务进程异常退出或连接中断，请检查部署环境。",
                retryable=True,
            )
        if isinstance(exc, (ValidationError, ValueError)):
            return ServiceError(
                502,
                "mcp_incompatible_protocol",
                "MCP 服务声明的工具清单或契约不符合 AstroAgent 固定要求。",
            )
        return ServiceError(
            502,
            "mcp_process_exited",
            "无法启动或连接本地 MCP 服务进程，未切换回直连模式。",
            retryable=True,
        )

    async def close(self) -> None:
        self.closed = True
        stack = self._exit_stack
        self._exit_stack = None
        self.session = None
        if stack is not None:
            with anyio.CancelScope(shield=True):
                with suppress(Exception):
                    await stack.aclose()


class _McpSlot:
    """连接池槽位；同一时刻仅执行一个调用。"""

    def __init__(self, slot_id: int):
        self.slot_id = slot_id
        self.conn: _McpConnection | None = None

    async def close_connection(self) -> None:
        conn = self.conn
        self.conn = None
        if conn is not None:
            await conn.close()


class _AsyncMcpPool:
    """在专用事件循环中管理固定上限的 MCP 子进程槽位。"""

    def __init__(
        self,
        pool_config: McpPoolConfig,
        *,
        server_params_factory: Any = None,
    ):
        self._config = pool_config
        self._server_params_factory = server_params_factory
        self._slots = [_McpSlot(i) for i in range(pool_config.pool_size)]
        self._queue: asyncio.Queue[_McpSlot] = asyncio.Queue(maxsize=pool_config.pool_size)
        for slot in self._slots:
            self._queue.put_nowait(slot)
        self._closing = False
        self.last_protocol_version: str | None = None
        self.last_server_version: str | None = None
        self.last_tools: list[str] = []
        self.last_error_code: str | None = None

    def _resolve_params(self, settings: Settings | None):
        if self._server_params_factory is not None:
            params = self._server_params_factory()
            env = dict(params.env or {})
            return params, _env_fingerprint(params.command, list(params.args), env)
        assert settings is not None
        return _build_fixed_server_params(settings, self._config)

    async def verify_startup(self, settings: Settings | None) -> None:
        correlation_id = uuid.uuid4().hex
        slot = await self._acquire_slot(correlation_id, None)
        recycle = False
        try:
            params, fingerprint = self._resolve_params(settings)
            await self._ensure_connected(slot, params, fingerprint, correlation_id)
        except BaseException:
            recycle = True
            raise
        finally:
            if recycle:
                await slot.close_connection()
            self._queue.put_nowait(slot)

    async def _acquire_slot(
        self,
        correlation_id: str,
        tool_name: str | None,
    ) -> _McpSlot:
        if self._closing:
            raise ServiceError(
                503,
                "mcp_unavailable",
                "MCP 连接池正在关闭，请稍后重试。",
                retryable=True,
            )
        try:
            return await asyncio.wait_for(
                self._queue.get(),
                timeout=self._config.acquire_timeout_seconds,
            )
        except TimeoutError as exc:
            emit_mcp_log(
                component="mcp_client",
                event="mcp_client_call",
                correlation_id=correlation_id,
                tool=tool_name,
                protocol_version=self.last_protocol_version,
                result_status="mcp_error",
                error_code="mcp_pool_exhausted",
            )
            raise ServiceError(
                503,
                "mcp_pool_exhausted",
                "MCP 天文查询连接池已满，请稍后重试。",
                retryable=True,
            ) from exc

    async def _ensure_connected(
        self,
        slot: _McpSlot,
        params: Any,
        fingerprint: str,
        correlation_id: str,
    ) -> _McpConnection:
        if slot.conn is not None and not slot.conn.closed and slot.conn.fingerprint == fingerprint:
            return slot.conn
        if slot.conn is not None:
            await slot.close_connection()
        conn = _McpConnection(
            server_params=params,
            fingerprint=fingerprint,
            pool_config=self._config,
        )
        try:
            await conn.open(correlation_id)
        except ServiceError as exc:
            self.last_error_code = exc.error.code
            raise
        slot.conn = conn
        self.last_protocol_version = conn.protocol_version
        self.last_server_version = conn.server_version
        self.last_tools = list(conn.tool_names)
        self.last_error_code = None
        return conn

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        settings: Settings | None,
        correlation_id: str,
        cancel_event: threading.Event | None = None,
    ) -> AstronomyResult:
        (
            types,
            _,
            _,
            _,
            MCPError,
            McpInvalidWireError,
            McpRequestTooLargeError,
            McpResponseTooLargeError,
            _,
            _,
        ) = _import_mcp_sdk()
        started = time.monotonic()
        if cancel_event is not None and cancel_event.is_set():
            raise ServiceError(
                503,
                "mcp_cancelled",
                "MCP 查询在发起前已取消。",
                retryable=True,
            )
        slot = await self._acquire_slot(correlation_id, tool_name)
        recycle = False
        protocol_version = self.last_protocol_version
        try:
            params, fingerprint = self._resolve_params(settings)
            conn = await self._ensure_connected(slot, params, fingerprint, correlation_id)
            protocol_version = conn.protocol_version

            call_task = asyncio.create_task(
                conn.session.call_tool(
                    tool_name,
                    arguments,
                    meta={MCP_CORRELATION_META_KEY: correlation_id},
                )
            )
            wire_task = asyncio.create_task(conn.wire_errors.received.wait())
            cancelled_by_caller = False
            deadline = time.monotonic() + self._config.call_timeout_seconds
            try:
                while True:
                    if conn.wire_errors.error is not None:
                        raise conn.wire_errors.error
                    if call_task.done():
                        break
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled_by_caller = True
                        call_task.cancel()
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        call_task.cancel()
                        raise TimeoutError("MCP tool call exceeded deadline")
                    step = min(remaining, 0.05) if cancel_event is not None else remaining
                    await asyncio.wait(
                        (call_task, wire_task), timeout=step, return_when=asyncio.FIRST_COMPLETED
                    )
                if cancelled_by_caller:
                    with suppress(BaseException):
                        await call_task
                    recycle = True
                    raise ServiceError(
                        503,
                        "mcp_cancelled",
                        "MCP 天文查询已取消，迟到响应已丢弃并回收子进程。",
                        retryable=True,
                    )
                call_result = call_task.result()
            except ServiceError:
                raise
            except asyncio.CancelledError:
                call_task.cancel()
                with suppress(BaseException):
                    await call_task
                recycle = True
                raise ServiceError(
                    503,
                    "mcp_cancelled",
                    "MCP 天文查询已取消，迟到响应已丢弃并回收子进程。",
                    retryable=True,
                ) from None
            except TimeoutError as exc:
                call_task.cancel()
                with suppress(BaseException):
                    await call_task
                recycle = True
                raise ServiceError(
                    504,
                    "mcp_timeout",
                    "MCP 天文查询超过单调用时限，未自动重发；已回收异常子进程。",
                    retryable=True,
                ) from exc
            except BaseException as exc:
                wire_error = conn.wire_errors.error if conn.wire_errors is not None else None
                if wire_error is not None:
                    call_task.cancel()
                    with suppress(BaseException):
                        await call_task
                if isinstance(wire_error, McpResponseTooLargeError):
                    recycle = True
                    raise ServiceError(
                        502,
                        "mcp_response_too_large",
                        "MCP 工具响应超过消息大小上限，未截断返回；已回收连接。",
                    ) from exc
                if isinstance(wire_error, McpRequestTooLargeError):
                    recycle = True
                    raise ServiceError(
                        502,
                        "mcp_request_too_large",
                        "MCP 工具请求超过消息大小上限，已回收连接。",
                    ) from exc
                if isinstance(wire_error, McpInvalidWireError):
                    recycle = True
                    raise ServiceError(
                        502,
                        "mcp_contract_invalid",
                        "MCP 服务端返回了非法协议帧，已回收连接。",
                    ) from exc
                if isinstance(exc, MCPError):
                    code = getattr(exc, "code", None)
                    if code == types.REQUEST_TIMEOUT:
                        recycle = True
                        raise ServiceError(
                            504,
                            "mcp_timeout",
                            "MCP 天文查询超时，未自动重发；已回收连接。",
                            retryable=True,
                        ) from exc
                    if code == types.CONNECTION_CLOSED:
                        recycle = True
                        raise ServiceError(
                            502,
                            "mcp_process_exited",
                            "MCP 子进程意外退出，同次查询状态不明未重发；后续请求将重建连接。",
                            retryable=True,
                        ) from exc
                    if code in (
                        types.INVALID_PARAMS,
                        types.METHOD_NOT_FOUND,
                        types.INVALID_REQUEST,
                    ):
                        raise ServiceError(
                            502,
                            "mcp_protocol_error",
                            "MCP 协议调用被服务端拒绝，未切换至直连模式。",
                        ) from exc
                    recycle = True
                    raise ServiceError(
                        502,
                        "mcp_protocol_error",
                        "MCP 服务端返回内部协议错误，已回收连接。",
                        retryable=True,
                    ) from exc
                if isinstance(exc, (RuntimeError, ValidationError, ValueError)):
                    recycle = True
                    raise ServiceError(
                        502,
                        "mcp_contract_invalid",
                        "MCP 工具响应未通过契约校验，已回收连接。",
                    ) from exc
                recycle = True
                raise ServiceError(
                    502,
                    "mcp_process_exited",
                    "MCP 工具调用发生连接异常，未重发并已回收子进程。",
                    retryable=True,
                ) from exc
            finally:
                wire_task.cancel()
                with suppress(asyncio.CancelledError):
                    await wire_task

            try:
                kind, parsed = parse_structured_tool_output(
                    tool_name,
                    call_result.structured_content,
                    is_error=bool(call_result.is_error),
                )
            except ValueError as exc:
                recycle = True
                raise ServiceError(
                    502,
                    "mcp_contract_invalid",
                    "MCP 工具返回的结构化数据不符合契约，已回收连接。",
                ) from exc

            if kind == "error":
                raise map_adapter_error(parsed)

            assert not isinstance(parsed, ServiceError)
            result: AstronomyResult = parsed
            self.last_error_code = None
            emit_mcp_log(
                component="mcp_client",
                event="mcp_client_call",
                correlation_id=correlation_id,
                tool=tool_name,
                protocol_version=protocol_version,
                duration_ms=_elapsed_ms(started),
                result_status=result.status,
                returned_count=_returned_count(tool_name, result),
                error_code=result.error.code if result.error is not None else None,
            )
            return result
        except ServiceError as exc:
            self.last_error_code = exc.error.code
            emit_mcp_log(
                component="mcp_client",
                event="mcp_client_call",
                correlation_id=correlation_id,
                tool=tool_name,
                protocol_version=protocol_version,
                duration_ms=_elapsed_ms(started),
                result_status="mcp_error",
                error_code=exc.error.code,
            )
            raise
        finally:
            if recycle:
                # 阻塞调用/异常连接必须在确认子进程退出并回收后才释放执行槽。
                with anyio.CancelScope(shield=True):
                    await slot.close_connection()
                emit_mcp_log(
                    component="mcp_client",
                    event="mcp_client_recycle",
                    correlation_id=correlation_id,
                    tool=tool_name,
                    protocol_version=protocol_version,
                    result_status="recycled",
                )
            self._queue.put_nowait(slot)

    async def close(self) -> None:
        self._closing = True
        for slot in self._slots:
            await slot.close_connection()


class McpClientPool:
    """线程安全的 MCP Client 连接池封装，供同步聊天工作线程调用。"""

    def __init__(
        self,
        pool_config: McpPoolConfig | None = None,
        *,
        server_params_factory: Any = None,
    ):
        _import_mcp_sdk()
        self.config = pool_config if pool_config is not None else McpPoolConfig()
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._pool: _AsyncMcpPool | None = None
        self._closed = False
        self._lock = threading.Lock()
        self._server_params_factory = server_params_factory
        self._thread = threading.Thread(
            target=self._run_loop,
            name="astroagent-mcp-client-loop",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._pool = _AsyncMcpPool(
            self.config,
            server_params_factory=self._server_params_factory,
        )
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()

    def _submit(self, coro):
        with self._lock:
            if self._closed or self._pool is None or not self._loop.is_running():
                coro.close()
                raise ServiceError(
                    503,
                    "mcp_unavailable",
                    "MCP 客户端连接池未运行，请重启服务或检查配置。",
                    retryable=True,
                )
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def verify_startup(self, settings: Settings | None = None) -> None:
        assert self._pool is not None
        self._submit(self._pool.verify_startup(settings))

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        settings: Settings | None = None,
        correlation_id: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> AstronomyResult:
        assert self._pool is not None
        cid = sanitize_correlation_id(correlation_id)
        _LAST_MCP_CALL.meta = {"transport": "mcp", "tool": tool_name, "correlation_id": cid}
        return self._submit(
            self._pool.call_tool(
                tool_name,
                arguments,
                settings=settings,
                correlation_id=cid,
                cancel_event=cancel_event,
            )
        )

    def status(self) -> dict[str, Any]:
        pool = self._pool
        if self._closed or pool is None:
            return {
                "mcp_status": "error",
                "mcp_protocol_version": None,
                "mcp_server_version": None,
                "mcp_tools": [],
            }
        if pool.last_protocol_version and pool.last_error_code is None:
            state = "ready"
        elif pool.last_error_code is not None:
            state = "error"
        else:
            state = "configured"
        return {
            "mcp_status": state,
            "mcp_protocol_version": pool.last_protocol_version,
            "mcp_server_version": pool.last_server_version,
            "mcp_tools": list(pool.last_tools) if pool.last_tools else list(MCP_TOOL_NAMES),
        }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            pool = self._pool
            running = self._loop.is_running()
        if running and pool is not None:
            future = asyncio.run_coroutine_threadsafe(pool.close(), self._loop)
            with suppress(Exception):
                future.result(timeout=10.0)
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10.0)


_LAST_MCP_CALL = threading.local()


def clear_last_mcp_call_meta() -> None:
    _LAST_MCP_CALL.meta = None


def last_mcp_call_meta() -> dict[str, Any] | None:
    return getattr(_LAST_MCP_CALL, "meta", None)


class McpSimbadAdapter:
    """将 SimbadService.query 接口桥接到固定 MCP Client。"""

    def __init__(self, pool: McpClientPool, settings: Settings | None = None):
        self._pool = pool
        self._settings = settings

    def query(self, object_name: str) -> QueryResult:
        arguments = ObjectQuery(object_name=object_name).model_dump(mode="json")
        result = self._pool.call_tool("query_simbad", arguments, settings=self._settings)
        if not isinstance(result, QueryResult):
            raise ServiceError(
                502,
                "mcp_contract_invalid",
                "MCP query_simbad 返回结果类型不匹配。",
            )
        return result


class McpAdsAdapter:
    """将 AdsService.search 接口桥接到固定 MCP Client。"""

    def __init__(self, pool: McpClientPool, settings: Settings | None = None):
        self._pool = pool
        self._settings = settings

    def search(self, arguments: LiteratureQuery) -> LiteratureSearchResult:
        payload = arguments.model_dump(mode="json")
        result = self._pool.call_tool("search_ads", payload, settings=self._settings)
        if not isinstance(result, LiteratureSearchResult):
            raise ServiceError(
                502,
                "mcp_contract_invalid",
                "MCP search_ads 返回结果类型不匹配。",
            )
        return result


class McpGaiaAdapter:
    """将 GaiaService.query 接口桥接到固定 MCP Client，保留 mode 排他字段集。"""

    def __init__(self, pool: McpClientPool, settings: Settings | None = None):
        self._pool = pool
        self._settings = settings

    def query(self, arguments: GaiaQuery) -> GaiaQueryResult:
        # 仅传递显式设置字段，避免 source_id 模式混入圆锥默认值或 cone 模式混入 source_id。
        payload = arguments.model_dump(mode="json", exclude_unset=True)
        result = self._pool.call_tool("query_gaia", payload, settings=self._settings)
        if not isinstance(result, GaiaQueryResult):
            raise ServiceError(
                502,
                "mcp_contract_invalid",
                "MCP query_gaia 返回结果类型不匹配。",
            )
        return result


class _McpRuntimeManager:
    """进程级 MCP Client 生命周期管理器；仅在配置或管理员启用 mcp 时初始化。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._pool: McpClientPool | None = None
        self._config: McpPoolConfig | None = None
        self._startup_error: ServiceError | None = None
        self._persisted_transport: str | None = None

    def set_persisted_transport(self, transport: str | None) -> None:
        if transport not in (None, "direct", "mcp"):
            raise ValueError("Unsupported astronomy transport")
        with self._lock:
            self._persisted_transport = transport

    def effective_transport(self, local: LocalSettings) -> str:
        with self._lock:
            override = self._persisted_transport
        if override in ("direct", "mcp"):
            return override
        return local.astronomy_tool_transport

    def initialize(self, local: LocalSettings, settings: Settings) -> None:
        if self.effective_transport(local) != "mcp":
            return
        pool_config = McpPoolConfig.from_local_settings(local)
        with self._lock:
            if self._pool is not None and self._config == pool_config:
                pool = self._pool
            else:
                if self._pool is not None:
                    self._pool.close()
                    self._pool = None
                try:
                    pool = McpClientPool(pool_config)
                except ServiceError as exc:
                    self._startup_error = exc
                    self._config = pool_config
                    emit_mcp_log(
                        component="mcp_client",
                        event="mcp_runtime_init",
                        result_status="mcp_error",
                        error_code=exc.error.code,
                    )
                    return
                self._pool = pool
                self._config = pool_config
        try:
            pool.verify_startup(settings)
            with self._lock:
                self._startup_error = None
        except ServiceError as exc:
            with self._lock:
                self._startup_error = exc
            emit_mcp_log(
                component="mcp_client",
                event="mcp_runtime_init",
                result_status="mcp_error",
                error_code=exc.error.code,
            )

    def switch_transport(
        self,
        local: LocalSettings,
        settings: Settings,
        transport: str,
    ) -> None:
        if transport not in ("direct", "mcp"):
            raise ValueError("Unsupported astronomy transport")
        if transport == "direct":
            with self._lock:
                pool = self._pool
                self._pool = None
                self._config = None
                self._startup_error = None
                self._persisted_transport = "direct"
            if pool is not None:
                pool.close()
            return
        pool_config = McpPoolConfig.from_local_settings(local)
        candidate = McpClientPool(pool_config)
        try:
            candidate.verify_startup(settings)
        except Exception:
            candidate.close()
            raise
        with self._lock:
            previous = self._pool
            self._pool = candidate
            self._config = pool_config
            self._startup_error = None
            self._persisted_transport = "mcp"
        if previous is not None:
            previous.close()

    def acquire_pool(self, local: LocalSettings) -> McpClientPool:
        pool_config = McpPoolConfig.from_local_settings(local)
        with self._lock:
            if self._pool is not None and self._config == pool_config:
                return self._pool
            if self._pool is not None:
                self._pool.close()
                self._pool = None
            pool = McpClientPool(pool_config)
            self._pool = pool
            self._config = pool_config
            self._startup_error = None
            return pool

    def status(self, local: LocalSettings) -> dict[str, Any]:
        transport = self.effective_transport(local)
        if transport != "mcp":
            return {
                "astronomy_tool_transport": "direct",
                "mcp_status": "disabled",
                "mcp_protocol_version": None,
                "mcp_server_version": None,
                "mcp_tools": [],
            }
        with self._lock:
            pool = self._pool
            startup_error = self._startup_error
        if pool is None:
            return {
                "astronomy_tool_transport": "mcp",
                "mcp_status": "error" if startup_error is not None else "configured",
                "mcp_protocol_version": None,
                "mcp_server_version": None,
                "mcp_tools": [],
            }
        info = pool.status()
        if startup_error is not None and info["mcp_status"] != "ready":
            info["mcp_status"] = "error"
        return {"astronomy_tool_transport": "mcp", **info}

    def close(self) -> None:
        with self._lock:
            pool = self._pool
            self._pool = None
            self._config = None
            self._startup_error = None
            self._persisted_transport = None
        if pool is not None:
            pool.close()


_RUNTIME = _McpRuntimeManager()


def read_persisted_astronomy_transport(store) -> str | None:
    with store.connect() as db:
        row = db.execute(
            "SELECT value FROM public.auth_meta WHERE key=%s",
            (TRANSPORT_META_KEY,),
        ).fetchone()
    if not row:
        return None
    try:
        parsed = json.loads(row["value"])
    except Exception:
        return None
    transport = parsed.get("transport") if isinstance(parsed, dict) else None
    return transport if transport in ("direct", "mcp") else None


def write_persisted_astronomy_transport(db, transport: str) -> None:
    if transport not in ("direct", "mcp"):
        raise ValueError("Unsupported astronomy transport")
    payload = json.dumps({"transport": transport}, ensure_ascii=False)
    db.execute(
        "INSERT INTO public.auth_meta(key,value) VALUES (%s,%s) "
        "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
        (TRANSPORT_META_KEY, payload),
    )


def load_persisted_astronomy_transport(store) -> str | None:
    transport = read_persisted_astronomy_transport(store)
    _RUNTIME.set_persisted_transport(transport)
    return transport


def set_persisted_astronomy_transport(transport: str | None) -> None:
    _RUNTIME.set_persisted_transport(transport)


def effective_astronomy_transport(local: LocalSettings) -> str:
    return _RUNTIME.effective_transport(local)


def initialize_mcp_runtime(local: LocalSettings, settings: Settings) -> None:
    _RUNTIME.initialize(local, settings)


def switch_astronomy_transport(
    local: LocalSettings,
    settings: Settings,
    transport: str,
) -> None:
    _RUNTIME.switch_transport(local, settings, transport)


def get_mcp_pool(local: LocalSettings) -> McpClientPool:
    return _RUNTIME.acquire_pool(local)


def get_mcp_runtime_status(local: LocalSettings) -> dict[str, Any]:
    return _RUNTIME.status(local)


def close_mcp_runtime() -> None:
    _RUNTIME.close()
