"""V2.1 受控只读 Streamable HTTP (HTTPS) 外部 MCP 测试服务端。

用于离线本机 TLS 端到端验收：支持 2026-07-28 握手、分页 tools/list（含 SSE 响应）、
Bearer 凭据校验、工具定义变更模拟、协议不兼容、重定向、超时、超大响应与只读调用。
仅限开发与隔离测试环境使用，切勿作为生产数据源部署。
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import ssl
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def generate_self_signed_tls(directory: Path, host: str = "127.0.0.1") -> tuple[Path, Path]:
    """Generate a short-lived self-signed TLS certificate for local HTTPS testing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    san_entries: list[x509.GeneralName] = [x509.DNSName("localhost")]
    try:
        san_entries.append(x509.IPAddress(ipaddress.ip_address(host)))
    except ValueError:
        san_entries.append(x509.DNSName(host))

    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=7))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_path = directory / "controlled-mcp-cert.pem"
    key_path = directory / "controlled-mcp-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@dataclass
class ControlledMcpState:
    path: str = "/mcp"
    auth_token: str | None = None
    protocol_version: str = "2026-07-28"
    definition_version: int = 1
    force_redirect: bool = False
    call_delay_seconds: float = 0.0
    sse_for_call: bool = False
    oversized_response: bool = False
    return_tool_error: bool = False
    session_id: str = "controlled-https-session-v21"
    lock: threading.Lock = field(default_factory=threading.Lock)
    requests_log: list[dict[str, Any]] = field(default_factory=list)

    def record(self, method: str, params: dict[str, Any]) -> None:
        with self.lock:
            self.requests_log.append({"method": method, "params": params})


def _make_handler(state: ControlledMcpState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_bytes(
            self,
            status: int,
            body: bytes,
            *,
            content_type: str = "application/json",
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("MCP-Session-Id", state.session_id)
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send_bytes(status, raw, content_type="application/json")

        def _send_sse(self, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            frame = f"event: message\ndata: {encoded}\n\n".encode()
            self._send_bytes(200, frame, content_type="text/event-stream")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != state.path:
                self._send_json(404, {"error": "not_found"})
                return
            if state.force_redirect:
                self._send_bytes(
                    302,
                    b"",
                    extra_headers={"Location": "https://169.254.169.254/latest/meta-data/"},
                )
                return
            if state.auth_token:
                expected = f"Bearer {state.auth_token}"
                if self.headers.get("Authorization") != expected:
                    self._send_json(401, {"error": "unauthorized"})
                    return

            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except ValueError:
                self._send_json(
                    400,
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse"}},
                )
                return

            method = str(body.get("method") or "")
            rpc_id = body.get("id")
            params = body.get("params") if isinstance(body.get("params"), dict) else {}
            state.record(method, params)

            if state.oversized_response and method in ("tools/list", "tools/call"):
                self._send_bytes(200, b"x" * (128 * 1024), content_type="application/json")
                return

            if method == "initialize":
                self._send_json(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "result": {
                            "protocolVersion": state.protocol_version,
                            "capabilities": {"tools": {"listChanged": False}},
                            "serverInfo": {
                                "name": "siderfolio-controlled-https-mcp",
                                "version": f"1.{state.definition_version}.0",
                            },
                        },
                    },
                )
                return

            if method == "notifications/initialized":
                self._send_bytes(202, b"")
                return

            if method == "tools/list":
                cursor = params.get("cursor")
                if cursor is None:
                    self._send_json(
                        200,
                        {
                            "jsonrpc": "2.0",
                            "id": rpc_id,
                            "result": {
                                "tools": [
                                    {
                                        "name": "lookup_catalog_target",
                                        "title": "受控只读星表检索",
                                        "description": (
                                            "按天体标识符检索合成天文星表记录"
                                            f"（契约 v{state.definition_version}）。"
                                        ),
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {
                                                "target": {
                                                    "type": "string",
                                                    "minLength": 1,
                                                    "maxLength": 64,
                                                },
                                                "limit": {
                                                    "type": "integer",
                                                    "minimum": 1,
                                                    "maximum": 20,
                                                },
                                            },
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
                    return
                if cursor == "page-2":
                    self._send_sse(
                        {
                            "jsonrpc": "2.0",
                            "id": rpc_id,
                            "result": {
                                "tools": [
                                    {
                                        "name": "mutate_catalog_record",
                                        "title": "非只读写入测试工具",
                                        "description": "用于验证服务端拒绝批准非只读工具。",
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {"target": {"type": "string"}},
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
                    return
                self._send_json(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {"code": -32602, "message": "unknown cursor"},
                    },
                )
                return

            if method == "tools/call":
                if state.call_delay_seconds > 0:
                    time.sleep(state.call_delay_seconds)
                name = params.get("name")
                arguments = params.get("arguments")
                if name != "lookup_catalog_target" or not isinstance(arguments, dict):
                    self._send_json(
                        200,
                        {
                            "jsonrpc": "2.0",
                            "id": rpc_id,
                            "error": {"code": -32602, "message": "unknown tool"},
                        },
                    )
                    return
                if state.return_tool_error:
                    payload = {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "result": {
                            "isError": True,
                            "content": [{"type": "text", "text": "合成外部源返回业务错误"}],
                        },
                    }
                    self._send_sse(payload) if state.sse_for_call else self._send_json(200, payload)
                    return

                target = str(arguments.get("target") or "")
                count = 65 if target == "CONVERGE_MANY" else int(arguments.get("limit") or 2)
                items = [
                    {
                        "target": target,
                        "index": i + 1,
                        "ra_deg": round(56.75 + i * 0.001, 6),
                        "dec_deg": round(24.12 + i * 0.001, 6),
                        "g_mag": round(8.5 + i * 0.1, 2),
                    }
                    for i in range(count)
                ]
                payload = {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "isError": False,
                        "structuredContent": {"items": items, "source": "controlled-https-mock"},
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"受控 HTTPS MCP 返回 {target} 的 {len(items)} 条合成星表记录。"
                                ),
                            }
                        ],
                    },
                }
                self._send_sse(payload) if state.sse_for_call else self._send_json(200, payload)
                return

            self._send_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                },
            )

    return Handler


class ControlledExternalMcpServer:
    """Context manager running a real TLS Streamable HTTP MCP endpoint on 127.0.0.1."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        path: str = "/mcp",
        auth_token: str | None = None,
    ):
        self.host = host
        self.requested_port = port
        self.state = ControlledMcpState(path=path, auth_token=auth_token)
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.cert_path: Path | None = None
        self.port: int = 0

    def __enter__(self) -> ControlledExternalMcpServer:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="siderfolio-ext-mcp-")
        cert_path, key_path = generate_self_signed_tls(Path(self._tmpdir.name), host=self.host)
        self.cert_path = cert_path
        server_ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ssl.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))

        httpd = ThreadingHTTPServer((self.host, self.requested_port), _make_handler(self.state))
        httpd.socket = server_ssl.wrap_socket(httpd.socket, server_side=True)
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def client_ssl_context(self) -> ssl.SSLContext:
        assert self.cert_path is not None
        return ssl.create_default_context(cafile=str(self.cert_path))

    @property
    def url(self) -> str:
        return f"https://{self.host}:{self.port}{self.state.path}"

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None


def main() -> None:
    parser = argparse.ArgumentParser(description="Siderfolio V2.1 受控只读 HTTPS MCP 测试服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--path", default="/mcp")
    parser.add_argument("--token", default=None, help="可选 Bearer 鉴权令牌")
    args = parser.parse_args()

    with ControlledExternalMcpServer(
        host=args.host,
        port=args.port,
        path=args.path,
        auth_token=args.token,
    ) as server:
        print(f"Controlled HTTPS MCP listening at {server.url}")
        print(f"Self-signed CA cert: {server.cert_path}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
