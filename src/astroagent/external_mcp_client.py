"""V2.1 受控外部 Streamable HTTP MCP 客户端：出站地址校验、分页发现与有界只读调用。"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import socket
import ssl
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from astroagent import __version__
from astroagent.errors import ServiceError
from astroagent.external_mcp_schemas import ExternalMcpServerConfig
from astroagent.mcp_contract import emit_mcp_log
from astroagent.tool_catalog import (
    BUILTIN_TOOL_NAMES,
    canonical_json,
    compute_tool_definition_sha256,
    make_external_tool_id,
)
from astroagent.tool_schemas import ExternalMcpResult

EXTERNAL_MCP_CLIENT_NAME = "siderfolio-host"
MAX_DISCOVERY_PAGES = 10
MAX_TOOLS_PER_SERVER = 64
MAX_TEXT_EXCERPT_CHARS = 8000
MAX_STRUCTURED_JSON_BYTES = 64 * 1024
MAX_JSON_DEPTH = 6
MAX_ARRAY_ITEMS = 50
MAX_DICT_KEYS = 40
REMOTE_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)
_BLOCKED_METADATA_IPS = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("169.254.170.2"),
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)


def _is_forbidden_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped is not None:
        return _is_forbidden_ip(ip_obj.ipv4_mapped)
    return (
        ip_obj in _BLOCKED_METADATA_IPS
        or ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


def validate_outbound_address(
    host: str,
    port: int,
    *,
    resolver: Callable[..., list[Any]] = socket.getaddrinfo,
    allow_private_for_test: bool = False,
) -> list[str]:
    """校验最终解析地址，拒绝内网、环回、链路本地、保留与云元数据地址。"""
    lower = host.strip().lower().rstrip(".")
    if not lower:
        raise ServiceError(403, "mcp_egress_blocked", "外部 MCP 主机名为空，已拒绝出站连接。")
    if not allow_private_for_test and (
        lower in _BLOCKED_HOSTNAMES or lower.endswith((".localhost", ".local", ".internal"))
    ):
        raise ServiceError(
            403,
            "mcp_egress_blocked",
            "外部 MCP 目标主机属于禁止访问的本地或云元数据域名。",
        )

    try:
        literal = ipaddress.ip_address(lower)
    except ValueError:
        literal = None

    if literal is not None:
        if not allow_private_for_test and _is_forbidden_ip(literal):
            raise ServiceError(
                403,
                "mcp_egress_blocked",
                "外部 MCP 目标地址属于禁止访问的内网、环回或云元数据网段。",
            )
        return [str(literal)]

    try:
        infos = resolver(lower, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ServiceError(
            502,
            "mcp_dns_failed",
            "无法解析外部 MCP 服务主机地址。",
            retryable=True,
        ) from exc

    resolved: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        addr_str = str(sockaddr[0]).split("%", 1)[0]
        try:
            ip_obj = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        if not allow_private_for_test and _is_forbidden_ip(ip_obj):
            raise ServiceError(
                403,
                "mcp_egress_blocked",
                "外部 MCP 域名解析到禁止访问的内网、环回或云元数据地址，已中止连接。",
            )
        if addr_str not in resolved:
            resolved.append(addr_str)
    if not resolved:
        raise ServiceError(502, "mcp_dns_failed", "外部 MCP 主机未返回可用网络地址。")
    return resolved


def _check_no_nul(value: Any) -> None:
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("参数包含非法 NUL 字符")
    elif isinstance(value, list):
        for item in value:
            _check_no_nul(item)
    elif isinstance(value, dict):
        for k, v in value.items():
            _check_no_nul(k)
            _check_no_nul(v)


def _validate_schema_value(name: str, value: Any, schema: dict[str, Any], depth: int = 0) -> Any:
    if depth > 4:
        raise ValueError(f"字段 {name} 嵌套层数超过上限")
    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        types_allowed = [t for t in expected_type if isinstance(t, str)]
    elif isinstance(expected_type, str):
        types_allowed = [expected_type]
    else:
        types_allowed = []

    if value is None:
        if "null" in types_allowed:
            return None
        raise ValueError(f"字段 {name} 不能为空")

    if "enum" in schema and isinstance(schema["enum"], list):
        if value not in schema["enum"]:
            raise ValueError(f"字段 {name} 不在允许的枚举范围内")

    if "string" in types_allowed and isinstance(value, str):
        min_len = schema.get("minLength")
        max_len = schema.get("maxLength", 4000)
        if isinstance(min_len, int) and len(value) < min_len:
            raise ValueError(f"字段 {name} 长度不足")
        if isinstance(max_len, int) and len(value) > min(max_len, 4000):
            raise ValueError(f"字段 {name} 超过最大长度")
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                if not re.search(pattern, value):
                    raise ValueError(f"字段 {name} 不符合格式要求")
            except re.error:
                pass
        return value

    if "boolean" in types_allowed and isinstance(value, bool):
        return value

    if "integer" in types_allowed and isinstance(value, int) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            raise ValueError(f"字段 {name} 小于最小值")
        if isinstance(maximum, (int, float)) and value > maximum:
            raise ValueError(f"字段 {name} 超过最大值")
        return value

    if (
        "number" in types_allowed
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        num = float(value)
        if not math.isfinite(num):
            raise ValueError(f"字段 {name} 必须为有限数值")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and num < minimum:
            raise ValueError(f"字段 {name} 小于最小值")
        if isinstance(maximum, (int, float)) and num > maximum:
            raise ValueError(f"字段 {name} 超过最大值")
        return value

    if "array" in types_allowed and isinstance(value, list):
        max_items = min(int(schema.get("maxItems", 50)), 50)
        min_items = int(schema.get("minItems", 0))
        if len(value) < min_items or len(value) > max_items:
            raise ValueError(f"字段 {name} 数组元素数量超出范围")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            return [
                _validate_schema_value(f"{name}[{i}]", item, item_schema, depth + 1)
                for i, item in enumerate(value)
            ]
        return list(value)

    if "object" in types_allowed and isinstance(value, dict):
        props = schema.get("properties")
        if isinstance(props, dict):
            return validate_external_tool_arguments(
                value, schema, max_bytes=32 * 1024, _depth=depth + 1
            )
        if len(value) > 20:
            raise ValueError(f"字段 {name} 键数量超出限制")
        return dict(value)

    if not types_allowed:
        return value
    raise ValueError(f"字段 {name} 类型不符合工具契约")


def validate_external_tool_arguments(
    arguments: Any,
    input_schema: dict[str, Any],
    *,
    max_bytes: int = 64 * 1024,
    _depth: int = 0,
) -> dict[str, Any]:
    """严格按已批准的 inputSchema 白名单构造外发字段，拒绝未声明字段与非法类型。"""
    if not isinstance(arguments, dict):
        raise ServiceError(422, "mcp_invalid_arguments", "外部 MCP 工具参数必须为 JSON 对象。")
    if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
        raise ServiceError(502, "mcp_contract_invalid", "外部 MCP 工具输入契约无效。")
    try:
        _check_no_nul(arguments)
    except ValueError as exc:
        raise ServiceError(422, "mcp_invalid_arguments", str(exc)) from exc

    properties = input_schema.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    required = input_schema.get("required")
    required_set = {str(item) for item in required} if isinstance(required, list) else set()

    extra = sorted(set(arguments.keys()) - set(properties.keys()))
    if extra:
        raise ServiceError(
            422,
            "mcp_unapproved_field",
            f"外部查询包含未获批准的参数字段：{', '.join(extra[:5])}。",
        )

    missing = sorted(required_set - set(arguments.keys()))
    if missing:
        raise ServiceError(
            422,
            "mcp_invalid_arguments",
            f"外部查询缺少必填字段：{', '.join(missing[:5])}。",
        )

    sanitized: dict[str, Any] = {}
    for key, prop_schema in properties.items():
        if key not in arguments:
            continue
        raw_val = arguments[key]
        prop_dict = prop_schema if isinstance(prop_schema, dict) else {}
        try:
            sanitized[key] = _validate_schema_value(key, raw_val, prop_dict, _depth)
        except ValueError as exc:
            raise ServiceError(422, "mcp_invalid_arguments", str(exc)) from exc

    encoded = canonical_json(sanitized).encode("utf-8")
    if len(encoded) > max_bytes:
        raise ServiceError(422, "mcp_request_too_large", "外部 MCP 请求参数超过大小上限。")
    return sanitized


def arguments_digest(arguments: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(arguments).encode("utf-8")).hexdigest()


def _converge_value(value: Any, depth: int = 0) -> tuple[Any, bool]:
    """将远端返回 JSON 收敛到安全深度、键数和长度内，防止超大嵌套负载。"""
    if depth >= MAX_JSON_DEPTH:
        return "[已折叠深层数据]", True
    if value is None or isinstance(value, (bool, int)):
        return value, False
    if isinstance(value, float):
        return (value if math.isfinite(value) else str(value)), False
    if isinstance(value, str):
        if len(value) > 2000:
            return value[:2000] + "…", True
        return value, False
    if isinstance(value, list):
        truncated = len(value) > MAX_ARRAY_ITEMS
        out = []
        for item in value[:MAX_ARRAY_ITEMS]:
            conv, sub_trunc = _converge_value(item, depth + 1)
            out.append(conv)
            truncated = truncated or sub_trunc
        return out, truncated
    if isinstance(value, dict):
        items = list(value.items())
        truncated = len(items) > MAX_DICT_KEYS
        out_dict: dict[str, Any] = {}
        for k, v in items[:MAX_DICT_KEYS]:
            conv, sub_trunc = _converge_value(v, depth + 1)
            out_dict[str(k)[:120]] = conv
            truncated = truncated or sub_trunc
        return out_dict, truncated
    return str(value)[:500], True


@dataclass(frozen=True, slots=True)
class DiscoveryOutcome:
    protocol_version: str
    server_name: str
    server_version: str
    tools: list[dict[str, Any]]


class ExternalMcpHttpClient:
    """受控外部 Streamable HTTP MCP 客户端（固定端点、禁止重定向、严格字节与超时上限）。"""

    def __init__(
        self,
        *,
        resolver: Callable[..., list[Any]] = socket.getaddrinfo,
        transport: httpx.BaseTransport | None = None,
        ssl_context: ssl.SSLContext | bool = True,
        allow_private_for_test: bool = False,
    ):
        self._resolver = resolver
        self._transport = transport
        self._ssl_context = ssl_context
        self._allow_private_for_test = allow_private_for_test
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._sem_lock = threading.Lock()

    def _semaphore_for(self, config: ExternalMcpServerConfig) -> threading.BoundedSemaphore:
        with self._sem_lock:
            sem = self._semaphores.get(config.id)
            if sem is None:
                sem = threading.BoundedSemaphore(config.max_concurrency)
                self._semaphores[config.id] = sem
            return sem

    def _build_client(self, config: ExternalMcpServerConfig, timeout: float) -> httpx.Client:
        kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(
                timeout=timeout,
                connect=min(config.connect_timeout_seconds, timeout),
            ),
            "follow_redirects": False,
            "trust_env": False,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        else:
            kwargs["verify"] = self._ssl_context
        return httpx.Client(**kwargs)

    def _parse_streamable_http_payload(
        self,
        response: httpx.Response,
        *,
        max_bytes: int,
        expected_id: int | str | None,
    ) -> dict[str, Any] | None:
        if 300 <= response.status_code < 400:
            raise ServiceError(
                403,
                "mcp_redirect_blocked",
                "外部 MCP 服务端尝试重定向请求，已按出站安全策略拒绝。",
            )
        if response.status_code == 202 and expected_id is None:
            return None
        if response.status_code in (401, 403):
            raise ServiceError(
                502,
                "mcp_auth_failed",
                "外部 MCP 服务拒绝认证凭据，请核对服务端环境变量配置。",
            )
        if response.status_code == 429:
            raise ServiceError(
                503,
                "mcp_rate_limited",
                "外部 MCP 服务触发限流，请稍后再试。",
                retryable=True,
            )
        if response.status_code >= 400:
            raise ServiceError(
                502,
                "mcp_http_error",
                f"外部 MCP 服务返回 HTTP {response.status_code} 异常。",
                retryable=response.status_code >= 500,
            )

        content_type = (response.headers.get("content-type") or "").lower()
        buf = bytearray()
        for chunk in response.iter_bytes():
            buf.extend(chunk)
            if len(buf) > max_bytes:
                raise ServiceError(
                    502,
                    "mcp_response_too_large",
                    "外部 MCP 响应体积超过安全上限，已中止读取。",
                )
        if expected_id is None and not buf.strip():
            return None

        raw_text = buf.decode("utf-8", errors="replace")
        if "text/event-stream" in content_type:
            messages = self._extract_sse_json_messages(raw_text)
            if not messages:
                raise ServiceError(502, "mcp_protocol_error", "外部 MCP SSE 响应缺少有效消息。")
            for msg in messages:
                if expected_id is not None and msg.get("id") == expected_id:
                    return msg
            return messages[-1]

        try:
            parsed = json.loads(raw_text)
        except ValueError as exc:
            raise ServiceError(502, "mcp_protocol_error", "外部 MCP 返回了无效 JSON。") from exc
        if not isinstance(parsed, dict):
            raise ServiceError(502, "mcp_protocol_error", "外部 MCP JSON-RPC 响应结构无效。")
        return parsed

    @staticmethod
    def _extract_sse_json_messages(raw_text: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        data_lines: list[str] = []
        for raw_line in raw_text.splitlines():
            line = raw_line.rstrip("\r")
            if not line:
                if data_lines:
                    blob = "\n".join(data_lines).strip()
                    data_lines = []
                    if blob and blob != "[DONE]":
                        try:
                            parsed = json.loads(blob)
                            if isinstance(parsed, dict):
                                results.append(parsed)
                        except ValueError:
                            pass
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
        if data_lines:
            blob = "\n".join(data_lines).strip()
            if blob and blob != "[DONE]":
                try:
                    parsed = json.loads(blob)
                    if isinstance(parsed, dict):
                        results.append(parsed)
                except ValueError:
                    pass
        return results

    def _rpc(
        self,
        client: httpx.Client,
        config: ExternalMcpServerConfig,
        *,
        method: str,
        params: dict[str, Any] | None,
        rpc_id: int | None,
        session_id: str | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if rpc_id is not None:
            body["id"] = rpc_id
        if params is not None:
            body["params"] = params
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > config.max_request_bytes:
            raise ServiceError(422, "mcp_request_too_large", "外部 MCP 请求体超过大小上限。")

        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": config.protocol_version,
            **config.resolve_auth_headers(),
        }
        if session_id:
            headers["MCP-Session-Id"] = session_id

        try:
            with client.stream(
                "POST",
                config.endpoint_url,
                content=encoded,
                headers=headers,
            ) as response:
                next_session = response.headers.get("mcp-session-id") or session_id
                parsed = self._parse_streamable_http_payload(
                    response,
                    max_bytes=config.max_response_bytes,
                    expected_id=rpc_id,
                )
        except ServiceError:
            raise
        except httpx.TimeoutException as exc:
            raise ServiceError(
                504,
                "mcp_timeout",
                "外部 MCP 服务响应超时，未自动重试。",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ServiceError(
                502,
                "mcp_transport_error",
                "无法连接外部 MCP 服务端点，请检查网络与证书状态。",
                retryable=True,
            ) from exc

        if parsed is not None and "error" in parsed and parsed["error"] is not None:
            err = parsed["error"]
            err_code = err.get("code") if isinstance(err, dict) else None
            if err_code in (-32600, -32601, -32602):
                raise ServiceError(
                    502,
                    "mcp_protocol_error",
                    "外部 MCP 服务拒绝协议方法或参数。",
                )
            raise ServiceError(502, "mcp_upstream_error", "外部 MCP 服务返回协议错误。")

        return parsed, next_session

    def _handshake(
        self,
        client: httpx.Client,
        config: ExternalMcpServerConfig,
    ) -> tuple[str, str, str, str | None]:
        init_resp, session_id = self._rpc(
            client,
            config,
            method="initialize",
            params={
                "protocolVersion": config.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": EXTERNAL_MCP_CLIENT_NAME, "version": __version__},
            },
            rpc_id=1,
        )
        result = init_resp.get("result") if isinstance(init_resp, dict) else None
        if not isinstance(result, dict):
            raise ServiceError(
                502,
                "mcp_incompatible_protocol",
                "外部 MCP 握手响应缺少 result 结构。",
            )
        negotiated = str(result.get("protocolVersion") or "").strip()
        if negotiated != config.protocol_version:
            raise ServiceError(
                502,
                "mcp_incompatible_protocol",
                (
                    f"外部 MCP 协议版本不兼容：期望 {config.protocol_version}，"
                    f"远端声明 {negotiated or '未知'}。"
                ),
            )
        capabilities = result.get("capabilities")
        if not isinstance(capabilities, dict) or capabilities.get("tools") is None:
            raise ServiceError(
                502,
                "mcp_incompatible_protocol",
                "外部 MCP 服务未声明 tools 能力。",
            )
        server_info = result.get("serverInfo")
        server_name = (
            str(server_info.get("name") or "").strip() if isinstance(server_info, dict) else ""
        )
        server_version = (
            str(server_info.get("version") or "").strip() if isinstance(server_info, dict) else ""
        )
        if not server_name:
            raise ServiceError(
                502,
                "mcp_incompatible_protocol",
                "外部 MCP 握手响应缺少 serverInfo.name 身份标识。",
            )
        # Send initialized notification per Streamable HTTP spec.
        self._rpc(
            client,
            config,
            method="notifications/initialized",
            params={},
            rpc_id=None,
            session_id=session_id,
        )
        return negotiated, server_name, server_version, session_id

    def discover(self, config: ExternalMcpServerConfig) -> DiscoveryOutcome:
        started = time.monotonic()
        correlation_id = uuid.uuid4().hex
        if self._transport is None:
            validate_outbound_address(
                config.host,
                config.port,
                resolver=self._resolver,
                allow_private_for_test=self._allow_private_for_test,
            )
        sem = self._semaphore_for(config)
        if not sem.acquire(timeout=min(config.connect_timeout_seconds, 5.0)):
            raise ServiceError(
                503,
                "mcp_pool_exhausted",
                "外部 MCP 并发槽位已满，请稍后再试。",
                retryable=True,
            )
        try:
            with self._build_client(config, config.discover_timeout_seconds) as client:
                negotiated, server_name, server_version, session_id = self._handshake(
                    client, config
                )
                discovered: list[dict[str, Any]] = []
                seen_names: set[str] = set()
                seen_cursors: set[str] = set()
                cursor: str | None = None
                rpc_id = 2
                for _ in range(MAX_DISCOVERY_PAGES):
                    params = {"cursor": cursor} if cursor is not None else {}
                    resp, session_id = self._rpc(
                        client,
                        config,
                        method="tools/list",
                        params=params,
                        rpc_id=rpc_id,
                        session_id=session_id,
                    )
                    rpc_id += 1
                    result = resp.get("result") if isinstance(resp, dict) else None
                    if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                        raise ServiceError(
                            502,
                            "mcp_protocol_error",
                            "外部 MCP tools/list 返回格式无效。",
                        )
                    for raw_tool in result["tools"]:
                        if not isinstance(raw_tool, dict):
                            continue
                        remote_name = str(raw_tool.get("name") or "").strip()
                        if (
                            not REMOTE_TOOL_NAME_RE.fullmatch(remote_name)
                            or remote_name in seen_names
                        ):
                            continue
                        input_schema = raw_tool.get("inputSchema")
                        if (
                            not isinstance(input_schema, dict)
                            or input_schema.get("type") != "object"
                        ):
                            continue
                        seen_names.add(remote_name)
                        if len(discovered) >= MAX_TOOLS_PER_SERVER:
                            break
                        output_schema = raw_tool.get("outputSchema")
                        if not isinstance(output_schema, dict):
                            output_schema = None
                        annotations = raw_tool.get("annotations")
                        if not isinstance(annotations, dict):
                            annotations = {}
                        read_only_hint = (
                            annotations.get("readOnlyHint")
                            if isinstance(annotations.get("readOnlyHint"), bool)
                            else None
                        )
                        destructive_hint = (
                            annotations.get("destructiveHint")
                            if isinstance(annotations.get("destructiveHint"), bool)
                            else None
                        )
                        description = str(raw_tool.get("description") or "").strip()[:1000]
                        title = str(
                            raw_tool.get("title") or annotations.get("title") or remote_name
                        ).strip()[:120]
                        tool_id = make_external_tool_id(config.id, remote_name)
                        if tool_id in BUILTIN_TOOL_NAMES:
                            continue
                        definition_sha256 = compute_tool_definition_sha256(
                            name=remote_name,
                            description=description,
                            input_schema=input_schema,
                            output_schema=output_schema,
                            annotations={
                                "readOnlyHint": read_only_hint,
                                "destructiveHint": destructive_hint,
                            },
                        )
                        props = input_schema.get("properties")
                        param_names = (
                            [str(k) for k in props.keys()][:32] if isinstance(props, dict) else []
                        )
                        discovered.append(
                            {
                                "remote_name": remote_name,
                                "tool_id": tool_id,
                                "title": title,
                                "description": description,
                                "input_schema": input_schema,
                                "output_schema": output_schema,
                                "read_only_hint": read_only_hint,
                                "destructive_hint": destructive_hint,
                                "eligible_readonly": bool(
                                    read_only_hint is True and destructive_hint is not True
                                ),
                                "definition_sha256": definition_sha256,
                                "parameter_names": param_names,
                            }
                        )
                    next_cursor = result.get("nextCursor")
                    if not isinstance(next_cursor, str) or not next_cursor:
                        break
                    if next_cursor in seen_cursors:
                        raise ServiceError(
                            502,
                            "mcp_protocol_error",
                            "外部 MCP tools/list 分页游标出现循环，已停止发现。",
                        )
                    seen_cursors.add(next_cursor)
                    cursor = next_cursor
                else:
                    raise ServiceError(
                        502,
                        "mcp_protocol_error",
                        "外部 MCP tools/list 分页数量超过上限。",
                    )
            emit_mcp_log(
                component="external_mcp_client",
                event="external_mcp_discover",
                correlation_id=correlation_id,
                tool=config.id,
                protocol_version=negotiated,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                result_status="success",
                returned_count=len(discovered),
            )
            return DiscoveryOutcome(
                protocol_version=negotiated,
                server_name=server_name,
                server_version=server_version,
                tools=discovered,
            )
        except ServiceError as exc:
            emit_mcp_log(
                component="external_mcp_client",
                event="external_mcp_discover",
                correlation_id=correlation_id,
                tool=config.id,
                protocol_version=config.protocol_version,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                result_status="error",
                error_code=exc.error.code,
            )
            raise
        finally:
            sem.release()

    def call_tool(
        self,
        config: ExternalMcpServerConfig,
        *,
        confirmation_id: str,
        tool_id: str,
        remote_name: str,
        tool_title: str,
        arguments: dict[str, Any],
        input_schema: dict[str, Any],
    ) -> ExternalMcpResult:
        started = time.monotonic()
        correlation_id = uuid.uuid4().hex
        sanitized_args = validate_external_tool_arguments(
            arguments, input_schema, max_bytes=config.max_request_bytes
        )
        if self._transport is None:
            validate_outbound_address(
                config.host,
                config.port,
                resolver=self._resolver,
                allow_private_for_test=self._allow_private_for_test,
            )
        sem = self._semaphore_for(config)
        if not sem.acquire(timeout=min(config.connect_timeout_seconds, 5.0)):
            raise ServiceError(
                503,
                "mcp_pool_exhausted",
                "外部 MCP 并发槽位已满，请稍后再试。",
                retryable=True,
            )
        try:
            with self._build_client(config, config.call_timeout_seconds) as client:
                negotiated, _, _, session_id = self._handshake(client, config)
                resp, _ = self._rpc(
                    client,
                    config,
                    method="tools/call",
                    params={"name": remote_name, "arguments": sanitized_args},
                    rpc_id=2,
                    session_id=session_id,
                )
            result_obj = resp.get("result") if isinstance(resp, dict) else None
            if not isinstance(result_obj, dict):
                raise ServiceError(
                    502,
                    "mcp_contract_invalid",
                    "外部 MCP 工具调用未返回有效结果对象。",
                )
            is_error = bool(result_obj.get("isError", False))
            structured_raw = result_obj.get("structuredContent")
            content_blocks = result_obj.get("content")
            text_parts: list[str] = []
            if isinstance(content_blocks, list):
                for block in content_blocks[:20]:
                    if isinstance(block, dict) and block.get("type") == "text":
                        txt = block.get("text")
                        if isinstance(txt, str) and txt.strip():
                            text_parts.append(txt.strip())

            truncated = False
            structured_data = None
            if structured_raw is not None:
                conv, conv_trunc = _converge_value(structured_raw)
                truncated = truncated or conv_trunc
                encoded = canonical_json(conv).encode("utf-8")
                if len(encoded) > MAX_STRUCTURED_JSON_BYTES:
                    truncated = True
                    structured_data = {"note": "结构化数据超过显示上限，已收敛为文本摘要。"}
                else:
                    structured_data = conv

            raw_excerpt = "\n".join(text_parts).strip()
            if len(raw_excerpt) > MAX_TEXT_EXCERPT_CHARS:
                raw_excerpt = raw_excerpt[:MAX_TEXT_EXCERPT_CHARS] + "…"
                truncated = True
            if not raw_excerpt and structured_data is not None:
                preview = canonical_json(structured_data)
                if len(preview) > 1200:
                    raw_excerpt = preview[:1200] + "…"
                    truncated = True
                else:
                    raw_excerpt = preview

            returned_count = 0
            if isinstance(structured_data, list):
                returned_count = len(structured_data)
            elif isinstance(structured_data, dict):
                for key in ("items", "rows", "results", "records", "data"):
                    if isinstance(structured_data.get(key), list):
                        returned_count = len(structured_data[key])
                        break
                else:
                    returned_count = 1 if structured_data else 0
            elif raw_excerpt:
                returned_count = 1

            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            now_iso = datetime.now(UTC).isoformat()
            if is_error:
                emit_mcp_log(
                    component="external_mcp_client",
                    event="external_mcp_call",
                    correlation_id=correlation_id,
                    tool=tool_id,
                    protocol_version=negotiated,
                    duration_ms=duration_ms,
                    result_status="tool_error",
                    error_code="mcp_tool_returned_error",
                )
                return ExternalMcpResult(
                    confirmation_id=confirmation_id,
                    server_id=config.id,
                    server_title=config.title,
                    tool_id=tool_id,
                    remote_name=remote_name,
                    tool_title=tool_title,
                    protocol_version=negotiated,
                    status="error",
                    summary=raw_excerpt[:300] or "外部 MCP 工具返回执行失败。",
                    structured_data=structured_data,
                    text_excerpt=raw_excerpt,
                    returned_count=0,
                    truncated=truncated,
                    duration_ms=duration_ms,
                    executed_at=now_iso,
                    error_code="mcp_tool_returned_error",
                    error_message=raw_excerpt[:300] or "外部工具执行失败。",
                )

            summary = (
                raw_excerpt.splitlines()[0][:240]
                if raw_excerpt
                else f"外部只读查询完成，返回 {returned_count} 项数据。"
            )
            emit_mcp_log(
                component="external_mcp_client",
                event="external_mcp_call",
                correlation_id=correlation_id,
                tool=tool_id,
                protocol_version=negotiated,
                duration_ms=duration_ms,
                result_status="success",
                returned_count=returned_count,
            )
            return ExternalMcpResult(
                confirmation_id=confirmation_id,
                server_id=config.id,
                server_title=config.title,
                tool_id=tool_id,
                remote_name=remote_name,
                tool_title=tool_title,
                protocol_version=negotiated,
                status="success",
                summary=summary,
                structured_data=structured_data,
                text_excerpt=raw_excerpt,
                returned_count=returned_count,
                truncated=truncated,
                duration_ms=duration_ms,
                executed_at=now_iso,
            )
        except ServiceError as exc:
            emit_mcp_log(
                component="external_mcp_client",
                event="external_mcp_call",
                correlation_id=correlation_id,
                tool=tool_id,
                protocol_version=config.protocol_version,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                result_status="error",
                error_code=exc.error.code,
            )
            raise
        finally:
            sem.release()
