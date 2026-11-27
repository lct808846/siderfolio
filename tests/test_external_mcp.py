"""V2.1 单元测试：受控外部 Streamable HTTP MCP 客户端、出站校验与参数/输出收敛。"""

from __future__ import annotations

import json
import socket

import httpx
import pytest

from astroagent.errors import ServiceError
from astroagent.external_mcp_client import (
    ExternalMcpHttpClient,
    validate_external_tool_arguments,
    validate_outbound_address,
)
from astroagent.external_mcp_schemas import ExternalMcpServerConfig


def _sample_config(**overrides) -> ExternalMcpServerConfig:
    base = {
        "id": "ext_astro",
        "title": "受控天文查询 MCP",
        "host": "mcp.example.org",
        "port": 443,
        "path": "/mcp",
        "protocol_version": "2026-07-28",
    }
    base.update(overrides)
    return ExternalMcpServerConfig(**base)


def test_external_mcp_server_config_validation_and_credential_ref(monkeypatch):
    cfg = _sample_config(auth_header="Authorization", auth_env_var="EXT_ASTRO_MCP_TOKEN")
    assert cfg.endpoint_url == "https://mcp.example.org/mcp"
    assert not cfg.auth_configured
    monkeypatch.setenv("EXT_ASTRO_MCP_TOKEN", "synthetic-ext-token-999")
    assert cfg.auth_configured
    assert cfg.resolve_auth_headers() == {"Authorization": "Bearer synthetic-ext-token-999"}
    # Credential value must never appear in serialized config
    assert "synthetic-ext-token-999" not in cfg.model_dump_json()

    # Forbidden internal credential env-var prefixes
    for forbidden in ("DEEPSEEK_API_KEY", "ASTROAGENT_DATABASE_URL", "SMTP_PASSWORD", "PGPASSWORD"):
        with pytest.raises(ValueError, match="internal platform credentials"):
            _sample_config(auth_header="Authorization", auth_env_var=forbidden)

    # Reserved server IDs and invalid path / scheme
    with pytest.raises(ValueError):
        _sample_config(id="builtin")
    with pytest.raises(ValueError):
        _sample_config(path="/mcp?token=leak")
    with pytest.raises(ValueError):
        _sample_config(scheme="http")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "sub.localhost",
        "metadata.google.internal",
        "127.0.0.1",
        "::1",
        "10.0.0.5",
        "172.16.0.9",
        "192.168.1.10",
        "169.254.169.254",
        "100.100.100.200",
        "::ffff:127.0.0.1",
    ],
)
def test_validate_outbound_address_blocks_private_loopback_and_metadata(host):
    with pytest.raises(ServiceError) as exc_info:
        validate_outbound_address(host, 443)
    assert exc_info.value.error.code == "mcp_egress_blocked"


def test_validate_outbound_address_checks_dns_resolution():
    def fake_private_dns(host, port, type=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.40", port))]

    with pytest.raises(ServiceError) as exc_info:
        validate_outbound_address("rebind.example.org", 443, resolver=fake_private_dns)
    assert exc_info.value.error.code == "mcp_egress_blocked"

    def fake_public_dns(host, port, type=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    assert validate_outbound_address("mcp.example.org", 443, resolver=fake_public_dns) == [
        "93.184.216.34"
    ]


def test_validate_external_tool_arguments_strict_allowlist():
    schema = {
        "type": "object",
        "properties": {
            "target": {"type": "string", "minLength": 1, "maxLength": 64},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["target"],
    }
    clean = validate_external_tool_arguments({"target": "M31", "limit": 5}, schema)
    assert clean == {"target": "M31", "limit": 5}

    # Unapproved extra field must fail
    with pytest.raises(ServiceError) as exc_info:
        validate_external_tool_arguments({"target": "M31", "conversation_dump": "secret"}, schema)
    assert exc_info.value.error.code == "mcp_unapproved_field"

    # Missing required field
    with pytest.raises(ServiceError) as exc_info:
        validate_external_tool_arguments({"limit": 5}, schema)
    assert exc_info.value.error.code == "mcp_invalid_arguments"

    # Wrong type or out of range
    with pytest.raises(ServiceError) as exc_info:
        validate_external_tool_arguments({"target": "M31", "limit": 999}, schema)
    assert exc_info.value.error.code == "mcp_invalid_arguments"

    # NUL injection
    with pytest.raises(ServiceError) as exc_info:
        validate_external_tool_arguments({"target": "M31\x00"}, schema)
    assert exc_info.value.error.code == "mcp_invalid_arguments"


def test_external_mcp_discover_pagination_sse_and_call_convergence(monkeypatch, capsys):
    monkeypatch.setenv("EXT_ASTRO_MCP_TOKEN", "secret-token-never-log")
    cfg = _sample_config(auth_header="Authorization", auth_env_var="EXT_ASTRO_MCP_TOKEN")
    seen_requests: list[tuple[str, dict, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_requests.append((body["method"], body.get("params", {}), dict(request.headers)))
        method = body["method"]
        if method == "initialize":
            assert request.headers.get("authorization") == "Bearer secret-token-never-log"
            return httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    "MCP-Session-Id": "sess-v21",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "protocolVersion": "2026-07-28",
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "mock-astro-mcp", "version": "1.0.0"},
                    },
                },
            )
        if method == "notifications/initialized":
            return httpx.Response(202, headers={"MCP-Session-Id": "sess-v21"})
        if method == "tools/list":
            cursor = body.get("params", {}).get("cursor")
            if cursor is None:
                return httpx.Response(
                    200,
                    headers={"Content-Type": "application/json"},
                    json={
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {
                            "tools": [
                                {
                                    "name": "lookup_target",
                                    "title": "只读目标检索",
                                    "description": "查询外部只读星表",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"target": {"type": "string"}},
                                        "required": ["target"],
                                    },
                                    "annotations": {
                                        "readOnlyHint": True,
                                        "destructiveHint": False,
                                    },
                                }
                            ],
                            "nextCursor": "page-2",
                        },
                    },
                )
            # Second page delivered over Streamable HTTP SSE
            sse_payload = (
                "event: message\n"
                + "data: "
                + json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {
                            "tools": [
                                {
                                    "name": "mutate_catalog",
                                    "description": "Write tool that must not be readonly-eligible",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"id": {"type": "string"}},
                                    },
                                    "annotations": {
                                        "readOnlyHint": False,
                                        "destructiveHint": True,
                                    },
                                }
                            ]
                        },
                    }
                )
                + "\n\n"
            )
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=sse_payload.encode("utf-8"),
            )
        if method == "tools/call":
            assert body["params"] == {"name": "lookup_target", "arguments": {"target": "M42"}}
            # Return > 50 items to verify convergence truncation
            items = [{"id": i, "ra": 83.82 + i * 0.001} for i in range(65)]
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "isError": False,
                        "structuredContent": {"items": items},
                        "content": [{"type": "text", "text": "Returned 65 external catalog rows."}],
                    },
                },
            )
        raise AssertionError(f"Unexpected method: {method}")

    client = ExternalMcpHttpClient(transport=httpx.MockTransport(handler))
    outcome = client.discover(cfg)
    assert outcome.protocol_version == "2026-07-28"
    assert outcome.server_name == "mock-astro-mcp"
    assert len(outcome.tools) == 2
    by_name = {item["remote_name"]: item for item in outcome.tools}
    assert by_name["lookup_target"]["eligible_readonly"] is True
    assert by_name["lookup_target"]["tool_id"] == "mcp__ext_astro__lookup_target"
    assert by_name["mutate_catalog"]["eligible_readonly"] is False

    result = client.call_tool(
        cfg,
        confirmation_id="conf-1",
        tool_id=by_name["lookup_target"]["tool_id"],
        remote_name="lookup_target",
        tool_title="只读目标检索",
        arguments={"target": "M42"},
        input_schema=by_name["lookup_target"]["input_schema"],
    )
    assert result.status == "success"
    assert result.truncated is True
    assert result.returned_count == 50
    assert isinstance(result.structured_data, dict)
    assert len(result.structured_data["items"]) == 50

    # Ensure secret token never leaks to structured stderr logs
    captured = capsys.readouterr()
    assert "secret-token-never-log" not in captured.err
    assert "secret-token-never-log" not in captured.out


def test_external_mcp_error_modes_protocol_redirect_timeout_and_oversized():
    cfg = _sample_config(max_response_bytes=16 * 1024)

    # Incompatible protocol version
    def wrong_proto(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "legacy"},
                },
            },
        )

    with pytest.raises(ServiceError) as exc_info:
        ExternalMcpHttpClient(transport=httpx.MockTransport(wrong_proto)).discover(cfg)
    assert exc_info.value.error.code == "mcp_incompatible_protocol"

    # Redirect must be blocked
    def redirect_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://169.254.169.254/latest"})

    with pytest.raises(ServiceError) as exc_info:
        ExternalMcpHttpClient(transport=httpx.MockTransport(redirect_handler)).discover(cfg)
    assert exc_info.value.error.code == "mcp_redirect_blocked"

    # Timeout
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")

    with pytest.raises(ServiceError) as exc_info:
        ExternalMcpHttpClient(transport=httpx.MockTransport(timeout_handler)).discover(cfg)
    assert exc_info.value.error.code == "mcp_timeout"

    # Oversized response
    def huge_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (20 * 1024))

    with pytest.raises(ServiceError) as exc_info:
        ExternalMcpHttpClient(transport=httpx.MockTransport(huge_handler)).discover(cfg)
    assert exc_info.value.error.code == "mcp_response_too_large"


def test_external_mcp_real_local_https_end_to_end(monkeypatch):
    """使用独立本地受控 HTTPS Streamable HTTP 端点验证真实 TLS 握手、分页、调用与故障边界。"""
    import http.client

    from scripts.mock_external_mcp_server import ControlledExternalMcpServer

    monkeypatch.setenv("EXT_LOCAL_TLS_TOKEN", "controlled-local-tls-token")

    class _LoopbackOnlyHttpsTransport(httpx.BaseTransport):
        def __init__(self, expected_port: int, ssl_context):
            self._expected_port = expected_port
            self._ssl_context = ssl_context

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            assert request.url.scheme == "https"
            assert request.url.host == "127.0.0.1"
            assert request.url.port == self._expected_port
            timeout_ext = (request.extensions or {}).get("timeout") or {}
            read_timeout = timeout_ext.get("read") or timeout_ext.get("connect") or 5.0
            conn = http.client.HTTPSConnection(
                "127.0.0.1",
                self._expected_port,
                timeout=float(read_timeout),
                context=self._ssl_context,
            )
            try:
                body = request.read()
                headers = dict(request.headers.items())
                conn.request(
                    request.method, request.url.raw_path.decode("ascii"), body=body, headers=headers
                )
                raw_resp = conn.getresponse()
                data = raw_resp.read()
                return httpx.Response(
                    status_code=raw_resp.status,
                    headers=list(raw_resp.getheaders()),
                    content=data,
                    request=request,
                )
            except TimeoutError as exc:
                raise httpx.ReadTimeout(str(exc), request=request) from exc
            finally:
                conn.close()

    with ControlledExternalMcpServer(auth_token="controlled-local-tls-token") as server:
        cfg = _sample_config(
            id="local_tls_mcp",
            host="127.0.0.1",
            port=server.port,
            path="/mcp",
            auth_header="Authorization",
            auth_env_var="EXT_LOCAL_TLS_TOKEN",
            call_timeout_seconds=1.5,
            max_response_bytes=32 * 1024,
        )
        # Verify production SSRF guard STILL blocks 127.0.0.1 by default
        with pytest.raises(ServiceError) as ssrf_exc:
            ExternalMcpHttpClient().discover(cfg)
        assert ssrf_exc.value.error.code == "mcp_egress_blocked"

        transport = _LoopbackOnlyHttpsTransport(server.port, server.client_ssl_context())
        client = ExternalMcpHttpClient(
            transport=transport,
            ssl_context=server.client_ssl_context(),
            allow_private_for_test=True,
        )

        # 1. Paginated discovery (JSON page 1 + SSE page 2)
        outcome = client.discover(cfg)
        assert outcome.protocol_version == "2026-07-28"
        assert outcome.server_name == "siderfolio-controlled-https-mcp"
        tools = {item["remote_name"]: item for item in outcome.tools}
        assert set(tools.keys()) == {"lookup_catalog_target", "mutate_catalog_record"}
        assert tools["lookup_catalog_target"]["eligible_readonly"] is True
        assert tools["mutate_catalog_record"]["eligible_readonly"] is False
        sha_v1 = tools["lookup_catalog_target"]["definition_sha256"]

        # 2. Normal read-only call + SSE call + bounded convergence (>50 rows)
        res = client.call_tool(
            cfg,
            confirmation_id="tls-conf-1",
            tool_id=tools["lookup_catalog_target"]["tool_id"],
            remote_name="lookup_catalog_target",
            tool_title="受控只读星表检索",
            arguments={"target": "M45", "limit": 3},
            input_schema=tools["lookup_catalog_target"]["input_schema"],
        )
        assert res.status == "success"
        assert res.returned_count == 3
        assert res.truncated is False

        server.state.sse_for_call = True
        conv_res = client.call_tool(
            cfg,
            confirmation_id="tls-conf-2",
            tool_id=tools["lookup_catalog_target"]["tool_id"],
            remote_name="lookup_catalog_target",
            tool_title="受控只读星表检索",
            arguments={"target": "CONVERGE_MANY"},
            input_schema=tools["lookup_catalog_target"]["input_schema"],
        )
        assert conv_res.status == "success"
        assert conv_res.truncated is True
        assert conv_res.returned_count == 50
        server.state.sse_for_call = False

        # 3. Definition change produces a distinct definition_sha256
        server.state.definition_version = 2
        outcome_v2 = client.discover(cfg)
        sha_v2 = next(
            item["definition_sha256"]
            for item in outcome_v2.tools
            if item["remote_name"] == "lookup_catalog_target"
        )
        assert sha_v2 != sha_v1

        # 4. Incompatible protocol version
        server.state.protocol_version = "2025-03-26"
        with pytest.raises(ServiceError) as proto_exc:
            client.discover(cfg)
        assert proto_exc.value.error.code == "mcp_incompatible_protocol"
        server.state.protocol_version = "2026-07-28"

        # 5. Redirect blocked
        server.state.force_redirect = True
        with pytest.raises(ServiceError) as redir_exc:
            client.discover(cfg)
        assert redir_exc.value.error.code == "mcp_redirect_blocked"
        server.state.force_redirect = False

        # 6. Oversized response blocked
        server.state.oversized_response = True
        with pytest.raises(ServiceError) as size_exc:
            client.discover(cfg)
        assert size_exc.value.error.code == "mcp_response_too_large"
        server.state.oversized_response = False

        # 7. Timeout enforced
        server.state.call_delay_seconds = 2.5
        with pytest.raises(ServiceError) as timeout_exc:
            client.call_tool(
                cfg,
                confirmation_id="tls-conf-timeout",
                tool_id=tools["lookup_catalog_target"]["tool_id"],
                remote_name="lookup_catalog_target",
                tool_title="受控只读星表检索",
                arguments={"target": "M31"},
                input_schema=tools["lookup_catalog_target"]["input_schema"],
            )
        assert timeout_exc.value.error.code == "mcp_timeout"
        server.state.call_delay_seconds = 0.0
        transport.close()
