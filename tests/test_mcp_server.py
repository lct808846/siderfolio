"""V1.8 独立 Astronomy MCP Server 离线契约与边界测试（不访问外部网络）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime

import anyio
import mcp_types as types
import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError

from astroagent import __version__
from astroagent.ads import AdsService
from astroagent.gaia import GaiaService
from astroagent.mcp_contract import (
    MCP_SCHEMA_VERSION,
    MCP_SERVER_NAME,
    MCP_TARGET_PROTOCOL_VERSION,
    MCP_TOOL_NAMES,
    parse_structured_tool_output,
    verify_tool_manifest,
)
from astroagent.mcp_server import McpServerConfig, build_astronomy_mcp_server
from astroagent.schemas import (
    ErrorInfo,
    GaiaQuery,
    LiteratureQuery,
    ObjectData,
    QueryResult,
    Source,
)
from tests.gaia_fixtures import source_row, votable


class FakeResponse:
    def __init__(self, status_code: int = 200, *, payload=None, content: bytes = b""):
        self.status_code = status_code
        self._payload = payload
        self._content = content
        self.closed = False

    def json(self):
        return self._payload

    def iter_content(self, chunk_size: int = 65536):
        for offset in range(0, len(self._content), chunk_size):
            yield self._content[offset : offset + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response: FakeResponse | Exception):
        self.response = response

    def get(self, *args, **kwargs):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def post(self, *args, **kwargs):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def close(self):
        pass


class StubSimbad:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[str] = []

    def query(self, object_name: str) -> QueryResult:
        self.calls.append(object_name)
        return self.handler(object_name)


def _simbad_ok(name: str) -> QueryResult:
    return QueryResult(
        object_name=name,
        status="success",
        source=Source(
            name="SIMBAD",
            url=f"https://simbad.cds.unistra.fr/simbad/sim-id?Ident={name}&output.format=HTML",
            retrieved_at=datetime(2026, 11, 21, 12, 0, tzinfo=UTC),
        ),
        data=ObjectData(
            main_id=f"* {name}",
            ra_deg=56.75,
            dec_deg=24.12,
            object_type="OpC",
            spectral_type=None,
            coordinate_bibcode="2020yCat.1350....0G",
        ),
    )


def _simbad_not_found(name: str) -> QueryResult:
    return QueryResult(
        object_name=name,
        status="not_found",
        source=Source(
            name="SIMBAD",
            url=f"https://simbad.cds.unistra.fr/simbad/sim-id?Ident={name}&output.format=HTML",
            retrieved_at=datetime(2026, 11, 21, 12, 0, tzinfo=UTC),
        ),
        error=ErrorInfo(code="object_not_found", message="SIMBAD 未找到该天体名称。"),
    )


def _simbad_timeout(name: str) -> QueryResult:
    return QueryResult(
        object_name=name,
        status="error",
        source=Source(
            name="SIMBAD",
            url=f"https://simbad.cds.unistra.fr/simbad/sim-id?Ident={name}&output.format=HTML",
            retrieved_at=datetime(2026, 11, 21, 12, 0, tzinfo=UTC),
        ),
        error=ErrorInfo(
            code="simbad_timeout",
            message="SIMBAD 查询超时，请稍后重试。",
            retryable=True,
        ),
    )


def _ads_ok_service() -> AdsService:
    payload = {
        "responseHeader": {"status": 0},
        "response": {
            "numFound": 12,
            "start": 0,
            "docs": [
                {
                    "bibcode": "2024ApJ...900....1A",
                    "title": ["Open Clusters in Gaia DR3"],
                    "author": ["Author, A.", "Author, B."],
                    "year": "2024",
                    "pub": "ApJ",
                    "doi": ["10.3847/example"],
                    "abstract": "Sample abstract text.",
                    "citation_count": 7,
                }
            ],
        },
    }
    return AdsService(
        token="synthetic-token",
        timeout=5,
        session=FakeSession(FakeResponse(200, payload=payload)),
    )


def _gaia_cone_service(*, overflow: bool = False, extra_rows: int = 2) -> GaiaService:
    rows = [
        source_row(
            source_id=6672947260672947200 + i,
            ra=56.75 + i * 0.001,
            dec=24.12,
            parallax=7.3 if i == 0 else None,
            parallax_error=0.1 if i == 0 else None,
            separation_deg=0.001 * i,
        )
        for i in range(extra_rows)
    ]
    content = votable(rows, cone=True, after="OVERFLOW" if overflow else None)
    return GaiaService(timeout=5, session=FakeSession(FakeResponse(200, content=content)))


def test_discover_and_tools_manifest():
    server = build_astronomy_mcp_server(
        config=McpServerConfig(),
        simbad=StubSimbad(_simbad_ok),
        ads=_ads_ok_service(),
        gaia=_gaia_cone_service(),
    )

    async def run():
        async with Client(server, mode="auto") as client:
            assert client.protocol_version == MCP_TARGET_PROTOCOL_VERSION
            assert client.server_info is not None
            assert client.server_info.name == MCP_SERVER_NAME
            assert client.server_info.version == __version__
            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == list(MCP_TOOL_NAMES)
            verify_tool_manifest(listed.tools)
            for tool in listed.tools:
                assert tool.annotations is not None
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.destructive_hint is False
            with pytest.raises(MCPError) as exc_info:
                await client.list_tools(cursor="unsupported")
            assert exc_info.value.code == types.INVALID_PARAMS

    anyio.run(run)


def test_direct_and_mcp_scientific_parity():
    simbad = StubSimbad(_simbad_ok)
    ads = _ads_ok_service()
    gaia = _gaia_cone_service(overflow=True, extra_rows=2)
    server = build_astronomy_mcp_server(
        config=McpServerConfig(),
        simbad=simbad,
        ads=ads,
        gaia=gaia,
    )

    direct_simbad = simbad.query("M45")
    direct_ads = ads.search(LiteratureQuery(query='abs:"open clusters"', rows=1, start=0))
    gaia_args = GaiaQuery(
        mode="cone",
        ra_deg=56.75,
        dec_deg=24.12,
        radius_arcmin=5,
        limit=1,
        estimate_distance=True,
    )
    direct_gaia = gaia.query(gaia_args)

    async def run():
        async with Client(server, mode="auto") as client:
            s_call = await client.call_tool("query_simbad", {"object_name": "M45"})
            assert not s_call.is_error
            assert s_call.structured_content["schema_version"] == MCP_SCHEMA_VERSION
            assert json.loads(s_call.content[0].text) == s_call.structured_content
            kind, s_res = parse_structured_tool_output(
                "query_simbad", s_call.structured_content, is_error=bool(s_call.is_error)
            )
            assert kind == "result"
            assert s_res.data == direct_simbad.data
            assert s_res.status == direct_simbad.status == "success"

            a_call = await client.call_tool(
                "search_ads", {"query": 'abs:"open clusters"', "rows": 1, "start": 0}
            )
            assert not a_call.is_error
            kind, a_res = parse_structured_tool_output(
                "search_ads", a_call.structured_content, is_error=bool(a_call.is_error)
            )
            assert kind == "result"
            assert a_res.total_found == direct_ads.total_found == 12
            assert a_res.has_more is True
            assert [p.bibcode for p in a_res.papers] == [p.bibcode for p in direct_ads.papers]

            g_call = await client.call_tool(
                "query_gaia", gaia_args.model_dump(mode="json", exclude_unset=True)
            )
            assert not g_call.is_error
            kind, g_res = parse_structured_tool_output(
                "query_gaia", g_call.structured_content, is_error=bool(g_call.is_error)
            )
            assert kind == "result"
            assert g_res.data == direct_gaia.data
            assert isinstance(g_res.data[0].source_id, str)
            assert g_res.data[0].source_id == "6672947260672947200"
            assert g_res.truncated is True
            assert g_res.archive_overflow is True
            assert g_res.analysis == direct_gaia.analysis
            assert g_res.adql == direct_gaia.adql

    anyio.run(run)


def test_not_found_upstream_errors_invalid_args_and_unknown_tool():
    simbad_nf = StubSimbad(_simbad_not_found)
    ads_unconfigured = AdsService(token="", timeout=5)
    gaia_limited = GaiaService(timeout=5, session=FakeSession(FakeResponse(429)))
    server = build_astronomy_mcp_server(
        config=McpServerConfig(),
        simbad=simbad_nf,
        ads=ads_unconfigured,
        gaia=gaia_limited,
    )

    async def run():
        async with Client(server, mode="auto") as client:
            nf = await client.call_tool("query_simbad", {"object_name": "NO_SUCH_OBJECT"})
            assert not nf.is_error
            assert nf.structured_content["result"]["status"] == "not_found"
            assert nf.structured_content["error"] is None

            ads_err = await client.call_tool("search_ads", {"query": "betelgeuse"})
            assert ads_err.is_error is True
            assert ads_err.structured_content["error"] is None
            assert ads_err.structured_content["result"]["status"] == "error"
            assert ads_err.structured_content["result"]["error"]["code"] == "ads_not_configured"

            gaia_err = await client.call_tool(
                "query_gaia", {"mode": "source_id", "source_id": "5853498713190525696"}
            )
            assert gaia_err.is_error is True
            assert gaia_err.structured_content["result"]["error"]["code"] == "gaia_rate_limited"

            bad_ads = await client.call_tool(
                "search_ads", {"query": "stars", "rows": 10, "start": 91}
            )
            assert bad_ads.is_error is True
            assert bad_ads.structured_content["result"] is None
            assert bad_ads.structured_content["error"]["code"] == "invalid_tool_arguments"

            bad_gaia = await client.call_tool(
                "query_gaia",
                {"mode": "source_id", "source_id": "5853498713190525696", "limit": 5},
            )
            assert bad_gaia.is_error is True
            assert bad_gaia.structured_content["result"] is None
            assert bad_gaia.structured_content["error"]["code"] == "invalid_tool_arguments"

            with pytest.raises(MCPError) as exc_info:
                await client.call_tool("run_shell", {"cmd": "id"})
            assert exc_info.value.code == types.INVALID_PARAMS

    anyio.run(run)


def test_response_size_limit_and_server_concurrency_and_timeout():
    gate = threading.Event()

    def slow_simbad(name: str) -> QueryResult:
        gate.wait(timeout=8.0)
        return _simbad_timeout(name)

    huge_ads_payload = {
        "responseHeader": {"status": 0},
        "response": {
            "numFound": 1,
            "start": 0,
            "docs": [
                {
                    "bibcode": "2024ApJ...900....1A",
                    "title": ["Big Abstract"],
                    "author": ["Author, A."],
                    "year": "2024",
                    "pub": "ApJ",
                    "doi": [],
                    "abstract": "X" * 40000,
                    "citation_count": 0,
                }
            ],
        },
    }
    server = build_astronomy_mcp_server(
        config=McpServerConfig(
            call_timeout_seconds=1.0,
            max_message_bytes=64 * 1024,
            max_concurrency=1,
            max_queue_wait_seconds=0.1,
        ),
        simbad=StubSimbad(slow_simbad),
        ads=AdsService(
            token="synthetic",
            timeout=5,
            session=FakeSession(FakeResponse(200, payload=huge_ads_payload)),
        ),
        gaia=_gaia_cone_service(),
    )

    async def run():
        async with Client(server, mode="auto") as client:
            too_big = await client.call_tool("search_ads", {"query": "big", "rows": 1})
            assert too_big.is_error is True
            assert too_big.structured_content["result"] is None
            assert too_big.structured_content["error"]["code"] == "mcp_response_too_large"

            try:
                timed_out = await client.call_tool("query_simbad", {"object_name": "SLOW"})
                assert timed_out.is_error is True
                assert timed_out.structured_content["error"]["code"] == "mcp_tool_timeout"

                busy = await client.call_tool("query_simbad", {"object_name": "BUSY"})
                assert busy.is_error is True
                assert busy.structured_content["error"]["code"] == "mcp_server_busy"
            finally:
                gate.set()
            await anyio.sleep(0.05)

    anyio.run(run)


def test_standalone_stdio_process_stdout_purity_and_rpc_errors():
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        in {
            "PATH",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "PATHEXT",
        }
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"
    env["ADS_API_TOKEN"] = ""

    messages = [
        "{not-valid-json",
        json.dumps({"jsonrpc": "2.0", "id": "bad-rpc"}),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "disc-1",
                "method": "server/discover",
                "params": {
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": MCP_TARGET_PROTOCOL_VERSION,
                        "io.modelcontextprotocol/clientCapabilities": {},
                    }
                },
            }
        ),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "ads-1",
                "method": "tools/call",
                "params": {
                    "name": "search_ads",
                    "arguments": {"query": "secret-query-text-never-log"},
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": MCP_TARGET_PROTOCOL_VERSION,
                        "io.modelcontextprotocol/clientCapabilities": {},
                    },
                },
            }
        ),
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "astroagent.mcp_server"],
        input=("\n".join(messages) + "\n").encode("utf-8"),
        capture_output=True,
        env=env,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0
    stdout_lines = [line for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]
    parsed = [json.loads(line) for line in stdout_lines]
    by_id = {item.get("id"): item for item in parsed}
    assert any(item.get("error", {}).get("code") == types.PARSE_ERROR for item in parsed)
    assert by_id["bad-rpc"]["error"]["code"] == types.INVALID_REQUEST
    assert MCP_TARGET_PROTOCOL_VERSION in by_id["disc-1"]["result"]["supportedVersions"]
    assert by_id["ads-1"]["result"]["isError"] is True
    assert by_id["ads-1"]["result"]["structuredContent"]["result"]["error"]["code"] == (
        "ads_not_configured"
    )
    stderr_text = proc.stderr.decode("utf-8")
    assert "secret-query-text-never-log" not in stderr_text
    assert "mcp_tool_call" in stderr_text
    _ = time.monotonic()
