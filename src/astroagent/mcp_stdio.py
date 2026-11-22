"""有界消息长度的 MCP stdio 传输包装（服务端与客户端），确保标准输出仅承载合法 JSON-RPC。"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import BinaryIO, TextIO

import anyio
import anyio.lowlevel
import anyio.to_thread
import mcp_types as types
from mcp.client.stdio import (
    _WRITER_FLUSH_TIMEOUT,
    StdioServerParameters,
    _aclose_all,
    _create_platform_compatible_process,
    _drain_stdout,
    _get_executable_command,
    _stop_server_process,
    get_default_environment,
)
from mcp.server.stdio import (
    _claim_fd,
    _open_stdin_diversion,
    _open_stdout_diversion,
)
from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import SessionMessage

from astroagent.mcp_contract import (
    DEFAULT_MCP_MAX_MESSAGE_BYTES,
    DEFAULT_MCP_MAX_REQUEST_BYTES,
    emit_mcp_log,
)


class McpWireError(Exception):
    """MCP stdio 线协议层错误。"""


class McpResponseTooLargeError(McpWireError):
    """服务端输出的单个 JSON-RPC 帧超过允许字节上限。"""


class McpRequestTooLargeError(McpWireError):
    """客户端发送的单个 JSON-RPC 帧超过允许字节上限。"""


class McpInvalidWireError(McpWireError):
    """服务端输出的帧不是有效的 UTF-8 或 JSON-RPC 消息。"""


@dataclass
class WireErrorSink:
    error: McpWireError | None = None
    received: anyio.Event = field(default_factory=anyio.Event)

    def record(self, exc: McpWireError) -> None:
        if self.error is None:
            self.error = exc
            self.received.set()


def _read_bounded_line(stream: BinaryIO, max_bytes: int) -> tuple[str, bytes]:
    """从阻塞二进制流读取单行，超限时丢弃剩余字节以避免无界内存占用。"""
    raw = stream.readline(max_bytes + 1)
    if not raw:
        return "eof", b""
    if len(raw) > max_bytes:
        if not raw.endswith(b"\n"):
            while True:
                discarded = stream.readline(65536)
                if not discarded or discarded.endswith(b"\n"):
                    break
        return "too_large", b""
    return "line", raw


def _write_bytes(stream: BinaryIO, data: bytes) -> None:
    stream.write(data)
    stream.flush()


def _extract_request_id(parsed: object) -> str | int | None:
    if not isinstance(parsed, dict):
        return None
    req_id = parsed.get("id")
    if type(req_id) in (int, str):
        return req_id
    return None


@asynccontextmanager
async def bounded_stdio_server(
    *,
    max_request_bytes: int = DEFAULT_MCP_MAX_REQUEST_BYTES,
    max_response_bytes: int = DEFAULT_MCP_MAX_MESSAGE_BYTES,
):
    """在隔离标准流描述符上运行有界字节限制的 MCP stdio 服务端传输。"""
    restore_stdin = None
    restore_stdout = None
    try:
        stdin_buffer, restore_stdin = _claim_fd(0, sys.stdin, "rb", _open_stdin_diversion)
        stdout_buffer, restore_stdout = _claim_fd(1, sys.stdout, "wb", _open_stdout_diversion)

        read_stream_writer, read_stream = create_context_streams[SessionMessage | Exception](0)
        write_stream, write_stream_reader = create_context_streams[SessionMessage](0)

        async def send_rpc_error(
            req_id: str | int | None,
            code: int,
            message: str,
        ) -> None:
            err = types.JSONRPCError(
                jsonrpc="2.0",
                id=req_id,
                error=types.ErrorData(code=code, message=message),
            )
            with suppress(anyio.ClosedResourceError, anyio.BrokenResourceError):
                await write_stream.send(SessionMessage(err))

        async def stdin_reader() -> None:
            try:
                async with read_stream_writer:
                    while True:
                        kind, raw = await anyio.to_thread.run_sync(
                            _read_bounded_line,
                            stdin_buffer,
                            max_request_bytes,
                            abandon_on_cancel=True,
                        )
                        if kind == "eof":
                            break
                        if kind == "too_large":
                            emit_mcp_log(
                                component="mcp_server",
                                event="mcp_request_rejected",
                                result_status="protocol_error",
                                error_code="mcp_request_too_large",
                            )
                            await send_rpc_error(
                                None,
                                types.INVALID_REQUEST,
                                "MCP request exceeds maximum byte size",
                            )
                            continue
                        stripped = raw.strip()
                        if not stripped:
                            continue
                        try:
                            text = stripped.decode("utf-8", errors="strict")
                            parsed = json.loads(text)
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            emit_mcp_log(
                                component="mcp_server",
                                event="mcp_request_rejected",
                                result_status="protocol_error",
                                error_code="json_rpc_parse_error",
                            )
                            await send_rpc_error(None, types.PARSE_ERROR, "Parse error")
                            continue
                        try:
                            message = types.jsonrpc_message_adapter.validate_python(
                                parsed, by_name=False
                            )
                        except Exception:
                            emit_mcp_log(
                                component="mcp_server",
                                event="mcp_request_rejected",
                                result_status="protocol_error",
                                error_code="json_rpc_invalid_request",
                            )
                            await send_rpc_error(
                                _extract_request_id(parsed),
                                types.INVALID_REQUEST,
                                "Invalid Request",
                            )
                            continue
                        await read_stream_writer.send(SessionMessage(message))
            except (anyio.ClosedResourceError, OSError):
                await anyio.lowlevel.checkpoint()

        async def stdout_writer() -> None:
            try:
                async with write_stream_reader:
                    async for session_message in write_stream_reader:
                        payload = session_message.message.model_dump_json(
                            by_alias=True, exclude_unset=True
                        )
                        encoded = (payload + "\n").encode("utf-8")
                        if len(encoded) > max_response_bytes:
                            emit_mcp_log(
                                component="mcp_server",
                                event="mcp_response_rejected",
                                result_status="mcp_error",
                                error_code="mcp_response_too_large",
                            )
                            if isinstance(session_message.message, types.JSONRPCResponse):
                                fallback = types.JSONRPCError(
                                    jsonrpc="2.0",
                                    id=session_message.message.id,
                                    error=types.ErrorData(
                                        code=types.INTERNAL_ERROR,
                                        message="MCP response exceeds maximum byte size",
                                    ),
                                )
                                encoded = (
                                    fallback.model_dump_json(by_alias=True, exclude_unset=True)
                                    + "\n"
                                ).encode("utf-8")
                            else:
                                continue
                        await anyio.to_thread.run_sync(
                            _write_bytes, stdout_buffer, encoded, abandon_on_cancel=True
                        )
            except (anyio.ClosedResourceError, OSError):
                await anyio.lowlevel.checkpoint()

        async with anyio.create_task_group() as tg:
            tg.start_soon(stdin_reader)
            tg.start_soon(stdout_writer)
            yield read_stream, write_stream
    finally:
        if restore_stdout is not None:
            restore_stdout()
        if restore_stdin is not None:
            restore_stdin()


@asynccontextmanager
async def bounded_stdio_client(
    server: StdioServerParameters,
    *,
    max_message_bytes: int = DEFAULT_MCP_MAX_MESSAGE_BYTES,
    max_request_bytes: int = DEFAULT_MCP_MAX_REQUEST_BYTES,
    errlog: TextIO = sys.stderr,
    error_sink: WireErrorSink | None = None,
) -> AsyncGenerator[tuple, None]:
    """启动本地 MCP stdio 子进程并强制单帧字节上限，退出时确保整个进程树回收。"""
    command = await _get_executable_command(server.command)
    env = dict(server.env) if server.env is not None else get_default_environment()
    process = await _create_platform_compatible_process(
        command=command,
        args=server.args,
        env=env,
        errlog=errlog,
        cwd=server.cwd,
    )

    read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](
        0
    )
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)

    shutting_down = False
    writer_done = anyio.Event()
    sink = error_sink if error_sink is not None else WireErrorSink()

    async def stdout_reader() -> None:
        assert process.stdout, "Opened process is missing stdout"
        buf = bytearray()
        try:
            async with read_stream_writer:
                try:
                    async for chunk in process.stdout:
                        if not chunk:
                            continue
                        buf.extend(chunk)
                        while True:
                            newline = buf.find(b"\n")
                            if newline == -1:
                                if len(buf) > max_message_bytes:
                                    sink.record(
                                        McpResponseTooLargeError(
                                            "MCP response line exceeds maximum byte size"
                                        )
                                    )
                                    return
                                break
                            line_bytes = bytes(buf[:newline])
                            del buf[: newline + 1]
                            if len(line_bytes) + 1 > max_message_bytes:
                                sink.record(
                                    McpResponseTooLargeError(
                                        "MCP response line exceeds maximum byte size"
                                    )
                                )
                                return
                            stripped = line_bytes.strip()
                            if not stripped:
                                continue
                            try:
                                text = stripped.decode(
                                    server.encoding, errors=server.encoding_error_handler
                                )
                                message = types.jsonrpc_message_adapter.validate_json(
                                    text, by_name=False
                                )
                            except Exception as exc:
                                sink.record(
                                    McpInvalidWireError(
                                        "MCP server emitted malformed JSON-RPC frame"
                                    )
                                )
                                _ = exc
                                return
                            try:
                                await read_stream_writer.send(SessionMessage(message))
                            except (anyio.ClosedResourceError, anyio.BrokenResourceError):
                                return
                    if buf.strip():
                        if len(buf) > max_message_bytes:
                            sink.record(
                                McpResponseTooLargeError(
                                    "MCP response line exceeds maximum byte size"
                                )
                            )
                        else:
                            sink.record(
                                McpInvalidWireError(
                                    "MCP server closed stdout with incomplete frame"
                                )
                            )
                finally:
                    await _drain_stdout(process)
        except anyio.ClosedResourceError:
            pass
        except (anyio.BrokenResourceError, ConnectionError, OSError):
            if not shutting_down:
                emit_mcp_log(
                    component="mcp_client",
                    event="mcp_stdout_broken",
                    result_status="mcp_error",
                    error_code="mcp_process_exited",
                )

    async def stdin_writer() -> None:
        assert process.stdin, "Opened process is missing stdin"
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    payload = session_message.message.model_dump_json(
                        by_alias=True, exclude_unset=True
                    )
                    data = (payload + "\n").encode(
                        encoding=server.encoding, errors=server.encoding_error_handler
                    )
                    if len(data) > max_request_bytes:
                        sink.record(
                            McpRequestTooLargeError("MCP request exceeds maximum byte size")
                        )
                        await read_stream_writer.aclose()
                        return
                    await process.stdin.send(data)
        except (anyio.ClosedResourceError, anyio.BrokenResourceError, OSError):
            await read_stream_writer.aclose()
        finally:
            writer_done.set()

    async def shutdown() -> None:
        read_stream.close()
        write_stream.close()
        with anyio.move_on_after(_WRITER_FLUSH_TIMEOUT) as flush_scope:
            await writer_done.wait()
        if flush_scope.cancelled_caught:
            await anyio.lowlevel.cancel_shielded_checkpoint()
        await _stop_server_process(process)
        await _aclose_all(read_stream, write_stream, read_stream_writer, write_stream_reader)
        await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            shutting_down = True
            with anyio.CancelScope(shield=True):
                await shutdown()
            tg.cancel_scope.cancel()
    await anyio.lowlevel.cancel_shielded_checkpoint()
