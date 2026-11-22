"""V1.8 AstroAgent MCP Client 连接池、隔离、故障回收与聊天链路测试（离线）。"""

from __future__ import annotations

import json
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from mcp.client.stdio import StdioServerParameters

from astroagent.agent import AstroAgent
from astroagent.api.chat import get_agent_for_model
from astroagent.config import LocalSettings, Settings
from astroagent.errors import ServiceError
from astroagent.mcp_client import (
    McpAdsAdapter,
    McpClientPool,
    McpGaiaAdapter,
    McpPoolConfig,
    McpSimbadAdapter,
    build_mcp_subprocess_env,
    close_mcp_runtime,
    effective_astronomy_transport,
    get_mcp_runtime_status,
    switch_astronomy_transport,
)


def _write_fake_server(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake_mcp_server.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return script


class ScriptedModel:
    def __init__(self, *replies):
        self.replies = iter(replies)
        self.messages = []

    def invoke(self, messages):
        self.messages.append(list(messages))
        return next(self.replies)


def test_subprocess_env_scrubs_host_secrets(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret-model")
    monkeypatch.setenv("ASTROAGENT_DATABASE_URL", "postgresql://u:pw@127.0.0.1:5432/db")
    monkeypatch.setenv("ASTROAGENT_AUTH_SECRET", "auth-secret")
    monkeypatch.setenv("ASTROAGENT_AUTH_SMTP_PASSWORD", "smtp-secret")
    monkeypatch.setenv("ASTROAGENT_PROXY_TOKEN", "0" * 64)
    monkeypatch.setenv("ASTROAGENT_PLOT_EXECUTOR_TOKEN", "1" * 64)

    settings = Settings(_env_file=None, ads_api_token="ads-token-only")
    env = build_mcp_subprocess_env(settings, McpPoolConfig())
    assert env["ADS_API_TOKEN"] == "ads-token-only"
    assert "DEEPSEEK_API_KEY" not in env
    assert "ASTROAGENT_DATABASE_URL" not in env
    assert "ASTROAGENT_AUTH_SECRET" not in env
    assert "ASTROAGENT_AUTH_SMTP_PASSWORD" not in env
    assert "ASTROAGENT_PROXY_TOKEN" not in env
    assert "ASTROAGENT_PLOT_EXECUTOR_TOKEN" not in env

    settings_no_ads = Settings(_env_file=None, ads_api_token="")
    env_no_ads = build_mcp_subprocess_env(settings_no_ads, McpPoolConfig())
    assert "ADS_API_TOKEN" not in env_no_ads


def test_default_direct_transport_does_not_initialize_mcp(monkeypatch):
    close_mcp_runtime()
    monkeypatch.delenv("ASTROAGENT_ASTRONOMY_TOOL_TRANSPORT", raising=False)
    local = LocalSettings(_env_file=None)
    assert local.astronomy_tool_transport == "direct"
    status = get_mcp_runtime_status(local)
    assert status["astronomy_tool_transport"] == "direct"
    assert status["mcp_status"] == "disabled"


def test_mcp_transport_wires_chat_factory_without_direct_fallback(monkeypatch):
    monkeypatch.setenv("ASTROAGENT_ASTRONOMY_TOOL_TRANSPORT", "mcp")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-key")
    try:
        agent = get_agent_for_model()
        assert isinstance(agent.simbad, McpSimbadAdapter)
        assert isinstance(agent.ads, McpAdsAdapter)
        assert isinstance(agent.gaia, McpGaiaAdapter)
    finally:
        close_mcp_runtime()


def test_runtime_transport_switch_verifies_mcp_and_recycles_on_direct():
    close_mcp_runtime()
    local = LocalSettings(_env_file=None)
    settings = Settings(_env_file=None)
    try:
        assert effective_astronomy_transport(local) == "direct"
        switch_astronomy_transport(local, settings, "mcp")
        assert effective_astronomy_transport(local) == "mcp"
        mcp_status = get_mcp_runtime_status(local)
        assert mcp_status["astronomy_tool_transport"] == "mcp"
        assert mcp_status["mcp_status"] == "ready"
        assert mcp_status["mcp_protocol_version"] == "2026-07-28"

        switch_astronomy_transport(local, settings, "direct")
        assert effective_astronomy_transport(local) == "direct"
        direct_status = get_mcp_runtime_status(local)
        assert direct_status["astronomy_tool_transport"] == "direct"
        assert direct_status["mcp_status"] == "disabled"
    finally:
        close_mcp_runtime()


def test_client_pool_round_trip_crash_recovery_and_partial_fallback(tmp_path):
    script = _write_fake_server(
        tmp_path,
        """
        import os
        from datetime import UTC, datetime
        import anyio
        from astroagent.mcp_server import McpServerConfig, build_astronomy_mcp_server
        from astroagent.mcp_stdio import bounded_stdio_server
        from astroagent.schemas import ErrorInfo, ObjectData, QueryResult, Source

        class CrashingSimbad:
            def query(self, object_name):
                if object_name == "CRASH":
                    os._exit(1)
                return QueryResult(
                    object_name=object_name,
                    status="success",
                    source=Source(
                        name="SIMBAD",
                        url=f"https://simbad.cds.unistra.fr/simbad/sim-id?Ident={object_name}",
                        retrieved_at=datetime(2026, 11, 21, 12, 0, tzinfo=UTC),
                    ),
                    data=ObjectData(main_id=object_name, ra_deg=56.75, dec_deg=24.12),
                )

        async def main():
            server = build_astronomy_mcp_server(
                config=McpServerConfig(),
                simbad=CrashingSimbad(),
            )
            async with bounded_stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())

        anyio.run(main)
        """,
    )
    pool = McpClientPool(
        McpPoolConfig(pool_size=1, startup_timeout_seconds=10, call_timeout_seconds=10),
        server_params_factory=lambda: StdioServerParameters(
            command=sys.executable, args=[str(script)]
        ),
    )
    try:
        model = ScriptedModel(
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "query_simbad", "args": {"object_name": "M45"}, "id": "call_1"},
                    {"name": "query_simbad", "args": {"object_name": "CRASH"}, "id": "call_2"},
                ],
            )
        )
        agent = AstroAgent(
            model,
            McpSimbadAdapter(pool),
            Settings(_env_file=None, deepseek_api_key="synthetic"),
            McpAdsAdapter(pool),
            McpGaiaAdapter(pool),
        )
        response = agent.chat("查询 M45 和 CRASH")
        assert response.status == "partial"
        assert len(response.results) == 1
        assert response.results[0].object_name == "M45"
        assert len(response.sources) == 1
        assert response.warnings[0].code == "mcp_process_exited"

        # 异常子进程回收后，后续新请求能够自动重建连接并成功返回。
        recovered = McpSimbadAdapter(pool).query("M31")
        assert recovered.status == "success"
        assert recovered.data is not None and recovered.data.main_id == "M31"
    finally:
        pool.close()


def test_client_rejects_incompatible_protocol_and_bad_contract_and_oversized(tmp_path):
    incompat = _write_fake_server(
        tmp_path,
        """
        import json, sys
        for line in sys.stdin:
            req = json.loads(line)
            resp = {
                "jsonrpc": "2.0",
                "id": req["id"],
                "result": {
                    "resultType": "complete",
                    "supportedVersions": ["2025-11-25"],
                    "capabilities": {"tools": {}},
                },
            }
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()
        """,
    )
    pool_bad = McpClientPool(
        McpPoolConfig(pool_size=1, startup_timeout_seconds=5, call_timeout_seconds=5),
        server_params_factory=lambda: StdioServerParameters(
            command=sys.executable, args=[str(incompat)]
        ),
    )
    try:
        with pytest.raises(ServiceError) as exc_info:
            pool_bad.verify_startup()
        assert exc_info.value.error.code == "mcp_incompatible_protocol"
    finally:
        pool_bad.close()

    oversized = _write_fake_server(
        tmp_path,
        """
        import json, sys
        from astroagent import __version__
        from astroagent.mcp_contract import TOOL_CONTRACTS
        meta = {"io.modelcontextprotocol/serverInfo": {
            "name": "astroagent-astronomy", "version": __version__,
        }}
        tools = [
            {
                "name": name,
                "description": c.description,
                "inputSchema": c.input_schema,
                "outputSchema": c.output_schema,
            }
            for name, c in TOOL_CONTRACTS.items()
        ]
        for line in sys.stdin:
            req = json.loads(line)
            if "id" not in req:
                continue
            method = req.get("method")
            if method == "server/discover":
                result = {
                    "resultType": "complete",
                    "supportedVersions": ["2026-07-28"],
                    "capabilities": {"tools": {}},
                }
            elif method == "tools/list":
                result = {"resultType": "complete", "tools": tools}
            elif method == "tools/call":
                arg = (req.get("params", {}).get("arguments") or {}).get("object_name")
                if arg == "OVERSIZED":
                    result = {
                        "resultType": "complete",
                        "content": [{"type": "text", "text": "A" * 90000}],
                        "structuredContent": {"schema_version": 1},
                        "isError": False,
                    }
                else:
                    result = {
                        "resultType": "complete",
                        "content": [{"type": "text", "text": "{}"}],
                        "structuredContent": {"schema_version": 999, "tool": "query_simbad"},
                        "isError": False,
                    }
            else:
                result = {"resultType": "complete"}
            result.update(cacheScope="private", ttlMs=0, _meta=meta)
            reply = {"jsonrpc": "2.0", "id": req["id"], "result": result}
            sys.stdout.write(json.dumps(reply) + "\\n")
            sys.stdout.flush()
        """,
    )
    pool_wire = McpClientPool(
        McpPoolConfig(
            pool_size=1,
            startup_timeout_seconds=5,
            call_timeout_seconds=5,
            max_message_bytes=64 * 1024,
        ),
        server_params_factory=lambda: StdioServerParameters(
            command=sys.executable, args=[str(oversized)]
        ),
    )
    try:
        pool_wire.verify_startup()
        with pytest.raises(ServiceError) as exc_info:
            McpSimbadAdapter(pool_wire).query("OVERSIZED")
        assert exc_info.value.error.code == "mcp_response_too_large"

        with pytest.raises(ServiceError) as exc_info:
            McpSimbadAdapter(pool_wire).query("BAD_CONTRACT")
        assert exc_info.value.error.code == "mcp_contract_invalid"
    finally:
        pool_wire.close()


def test_client_cancel_timeout_and_pool_saturation(tmp_path):
    slow = _write_fake_server(
        tmp_path,
        """
        import time
        import anyio
        from datetime import UTC, datetime
        from astroagent.mcp_server import McpServerConfig, build_astronomy_mcp_server
        from astroagent.mcp_stdio import bounded_stdio_server
        from astroagent.schemas import ObjectData, QueryResult, Source

        class SlowSimbad:
            def query(self, object_name):
                if object_name.startswith("SLEEP"):
                    time.sleep(2.0)
                return QueryResult(
                    object_name=object_name,
                    status="success",
                    source=Source(
                        name="SIMBAD",
                        url=f"https://simbad.cds.unistra.fr/simbad/sim-id?Ident={object_name}",
                        retrieved_at=datetime(2026, 11, 21, 12, 0, tzinfo=UTC),
                    ),
                    data=ObjectData(main_id=object_name, ra_deg=10.0, dec_deg=20.0),
                )

        async def main():
            server = build_astronomy_mcp_server(
                config=McpServerConfig(call_timeout_seconds=10.0),
                simbad=SlowSimbad(),
            )
            async with bounded_stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())

        anyio.run(main)
        """,
    )
    pool = McpClientPool(
        McpPoolConfig(
            pool_size=1,
            startup_timeout_seconds=5,
            call_timeout_seconds=1.5,
            acquire_timeout_seconds=0.2,
        ),
        server_params_factory=lambda: StdioServerParameters(
            command=sys.executable, args=[str(slow)]
        ),
    )
    try:
        errors: list[ServiceError] = []
        cancel_event = threading.Event()

        def first_call():
            try:
                pool.call_tool(
                    "query_simbad",
                    {"object_name": "SLEEP_1"},
                    cancel_event=cancel_event,
                )
            except ServiceError as exc:
                errors.append(exc)

        thread = threading.Thread(target=first_call)
        thread.start()
        time.sleep(0.3)

        with pytest.raises(ServiceError) as busy_exc:
            pool.call_tool("query_simbad", {"object_name": "FAST"})
        assert busy_exc.value.error.code == "mcp_pool_exhausted"

        cancel_event.set()
        thread.join(timeout=10.0)
        assert errors and errors[0].error.code == "mcp_cancelled"

        # 取消回收完成后，连接槽重新可用。
        ok = McpSimbadAdapter(pool).query("AFTER_CANCEL")
        assert ok.status == "success"
    finally:
        pool.close()
        _ = json.dumps({})
