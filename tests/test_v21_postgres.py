"""V2.1 PostgreSQL 与多账号隔离集成测试：技能偏好、外部 MCP 审批生命周期与确认边界。"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from psycopg import sql
from test_identity_postgres import ORIGIN, account, post, synthetic_admin

from astroagent.auth_config import AuthSettings
from astroagent.auth_store import AuthStore
from astroagent.config import LocalSettings
from astroagent.conversation_schemas import TurnRequest
from astroagent.external_mcp_client import ExternalMcpHttpClient, arguments_digest
from astroagent.tool_schemas import ExternalMcpProposal

pytestmark = [pytest.mark.identity, pytest.mark.postgres]


@pytest.fixture
def v21_client(monkeypatch, tmp_path):
    if os.getenv("ASTROAGENT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("V2.1 PostgreSQL integration requires a disposable PostgreSQL environment")
    url = os.getenv("ASTROAGENT_TEST_DATABASE_URL", "")
    parsed = urlsplit(url)
    assert parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    assert parsed.path.startswith("/astroagent_test") and not parsed.query and not parsed.fragment
    name = "astroagent_test_v21_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as db:
        db.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
    target = urlunsplit(parsed._replace(path="/" + name))
    try:
        with psycopg.connect(target, autocommit=True) as db:
            db.execute("CREATE EXTENSION vector")
            db.execute("CREATE EXTENSION pg_trgm")
        monkeypatch.setenv("ASTROAGENT_DATABASE_URL", target)
        monkeypatch.setenv("ASTROAGENT_AUTH_ORIGIN", ORIGIN)
        monkeypatch.setenv("ASTROAGENT_AUTH_LOCAL_HTTP", "true")
        monkeypatch.setenv("ASTROAGENT_AUTH_SECRET", Fernet.generate_key().decode())
        monkeypatch.setenv("ASTROAGENT_RAG_MODEL_PATH", str(tmp_path / "synthetic-embedding"))
        monkeypatch.setenv("ASTROAGENT_RAG_MODEL_SHA256", "f" * 64)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-key-not-valid")
        monkeypatch.setenv("ASTROAGENT_EXTERNAL_MCP_ENABLED", "true")
        monkeypatch.setenv(
            "ASTROAGENT_EXTERNAL_MCP_SERVERS_JSON",
            json.dumps(
                [
                    {
                        "id": "mock_cds",
                        "title": "可控只读星表 MCP",
                        "host": "cds-mock.example.org",
                        "port": 443,
                        "path": "/mcp",
                        "protocol_version": "2026-07-28",
                    }
                ]
            ),
        )
        for key, value in {
            "HOST": "smtp.example.org",
            "USER": "fixture@example.org",
            "PASSWORD": "synthetic-not-a-credential",
            "FROM": "fixture@example.org",
        }.items():
            monkeypatch.setenv("ASTROAGENT_AUTH_SMTP_" + key, value)
        from astroagent.auth_mail import MailWorker
        from astroagent.main import app

        monkeypatch.setattr(MailWorker, "start", lambda self: None)
        monkeypatch.setattr(MailWorker, "close", lambda self: None)
        store = AuthStore(LocalSettings(), AuthSettings())
        store.install()
        with TestClient(app, base_url=ORIGIN) as client:
            assert app.state.identity is not None, app.state.storage_code
            client.identity = app.state.identity
            client.store = store

            def _fresh():
                other = TestClient(app, base_url=ORIGIN)
                other.identity = app.state.identity
                other.store = store
                return other

            client.fresh = _fresh
            yield client
    finally:
        with psycopg.connect(url, autocommit=True) as db:
            db.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_skill_preferences_are_isolated_between_accounts(v21_client):
    alice = v21_client
    account(alice, "alice-v21@example.org")
    bob = v21_client.fresh()
    account(bob, "bob-v21@example.org")

    resp = post(
        alice,
        "skills/preferences",
        {
            "auto_match": False,
            "disabled_skill_ids": ["astronomy-literature-curation"],
        },
        method="PUT",
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["preferences"]["auto_match"] is False
    assert resp.json()["preferences"]["disabled_skill_ids"] == ["astronomy-literature-curation"]

    # Bob's preferences remain untouched
    bob_skills = bob.get("/api/v1/skills")
    assert bob_skills.status_code == 200
    assert bob_skills.json()["preferences"]["auto_match"] is True
    assert bob_skills.json()["preferences"]["disabled_skill_ids"] == []

    # Regular user cannot access admin MCP management routes
    assert bob.get("/api/v1/admin/mcp/servers").status_code == 403


def test_admin_external_mcp_lifecycle_definition_change_and_confirmation_isolation(v21_client):
    admin = v21_client
    synthetic_admin(admin)
    # Re-authenticate recent MFA window via totp reauth not needed immediately after confirm,
    # ensure session has recent auth.
    tool_version = {"desc": "查询只读恒星参数 v1"}
    upstream_calls = {"count": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        method = body["method"]
        if method == "initialize":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "protocolVersion": "2026-07-28",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "mock-cds-server", "version": "1.0"},
                    },
                },
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "tools": [
                            {
                                "name": "query_star",
                                "title": "只读恒星查询",
                                "description": tool_version["desc"],
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"star": {"type": "string"}},
                                    "required": ["star"],
                                },
                                "annotations": {
                                    "readOnlyHint": True,
                                    "destructiveHint": False,
                                },
                            },
                            {
                                "name": "drop_table",
                                "title": "危险写入工具",
                                "description": "不可批准的写入工具",
                                "inputSchema": {"type": "object", "properties": {}},
                                "annotations": {
                                    "readOnlyHint": False,
                                    "destructiveHint": True,
                                },
                            },
                        ]
                    },
                },
            )
        if method == "tools/call":
            upstream_calls["count"] += 1
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "isError": False,
                        "structuredContent": {
                            "items": [{"star": body["params"]["arguments"]["star"], "mag": 0.03}]
                        },
                        "content": [{"type": "text", "text": "Vega V=0.03"}],
                    },
                },
            )
        raise AssertionError(method)

    admin.identity.external_mcp.client = ExternalMcpHttpClient(
        transport=httpx.MockTransport(mock_handler)
    )

    # 1. Discover & enable server
    discovered = post(admin, "admin/mcp/servers/mock_cds/discover", {})
    assert discovered.status_code == 200, discovered.text
    tools = {t["remote_name"]: t for t in discovered.json()["tools"]}
    assert tools["query_star"]["eligible_readonly"] is True
    assert tools["drop_table"]["eligible_readonly"] is False

    # Reject approving non-readonly tool
    bad_approve = post(
        admin,
        "admin/mcp/servers/mock_cds/tools/drop_table/approve",
        {"expected_definition_sha256": tools["drop_table"]["definition_sha256"]},
    )
    assert bad_approve.status_code == 409
    assert bad_approve.json()["error"]["code"] == "mcp_tool_not_readonly"

    # Enable server and approve readonly tool
    toggled = post(admin, "admin/mcp/servers/mock_cds/toggle", {"enabled": True})
    assert toggled.status_code == 200 and toggled.json()["enabled"] is True

    approved = post(
        admin,
        "admin/mcp/servers/mock_cds/tools/query_star/approve",
        {"expected_definition_sha256": tools["query_star"]["definition_sha256"]},
    )
    assert approved.status_code == 200, approved.text
    star_tool = next(t for t in approved.json()["tools"] if t["remote_name"] == "query_star")
    assert star_tool["approved"] is True

    # User tool catalog now exposes approved external tool
    user_tools = admin.get("/api/v1/skills/tools")
    assert user_tools.status_code == 200
    assert any(t["tool_id"] == star_tool["tool_id"] for t in user_tools.json()["tools"])

    # 2. Save a confirmation proposal and test confirmation binding, replay & cross-user isolation
    conv = post(admin, "conversations", {}).json()
    session_user = admin.get("/api/v1/auth/session").json()["user"]
    svc = admin.identity.tenants.for_user(
        admin.store.authenticate(admin.cookies.get("astroagent_session"))
    )
    turn = svc.repository.reserve(
        conv["id"],
        TurnRequest(
            message="查询 Vega 外部星表",
            expected_revision=0,
            client_request_id=str(uuid4()),
        ),
    )
    turn_id = turn.turn_id
    confirmation_id = str(uuid4())
    args = {"star": "Vega"}
    args_sha = arguments_digest(args)
    now = datetime.now(UTC)
    proposal = ExternalMcpProposal(
        confirmation_id=confirmation_id,
        conversation_id=conv["id"],
        turn_id=turn_id,
        server_id="mock_cds",
        server_title="可控只读星表 MCP",
        server_host="cds-mock.example.org",
        tool_id=star_tool["tool_id"],
        remote_name="query_star",
        tool_title="只读恒星查询",
        protocol_version="2026-07-28",
        definition_sha256=star_tool["definition_sha256"],
        arguments=args,
        arguments_sha256=args_sha,
        outbound_fields=["star"],
        expires_at=(now + timedelta(minutes=15)).isoformat(),
        created_at=now.isoformat(),
    )
    svc.skills.save_proposal(proposal)

    # Another user cannot confirm admin's proposal
    other = v21_client.fresh()
    account(other, "outsider-v21@example.org")
    cross = post(
        other,
        f"conversations/{conv['id']}/turns/{turn_id}/external-mcp/{confirmation_id}/confirm",
        {
            "client_request_id": "req-other",
            "expected_definition_sha256": star_tool["definition_sha256"],
            "expected_arguments_sha256": args_sha,
        },
    )
    assert cross.status_code == 404

    # Tampered argument digest rejected before upstream call
    tampered = post(
        admin,
        f"conversations/{conv['id']}/turns/{turn_id}/external-mcp/{confirmation_id}/confirm",
        {
            "client_request_id": "req-tamper",
            "expected_definition_sha256": star_tool["definition_sha256"],
            "expected_arguments_sha256": "0" * 64,
        },
    )
    assert tampered.status_code == 409
    assert upstream_calls["count"] == 0

    # Valid confirmation executes upstream once
    ok = post(
        admin,
        f"conversations/{conv['id']}/turns/{turn_id}/external-mcp/{confirmation_id}/confirm",
        {
            "client_request_id": "req-idempotent-1",
            "expected_definition_sha256": star_tool["definition_sha256"],
            "expected_arguments_sha256": args_sha,
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["proposal"]["status"] == "executed"
    assert ok.json()["result"]["status"] == "success"
    assert upstream_calls["count"] == 1

    # Idempotent replay with same client_request_id does NOT call upstream again
    replay = post(
        admin,
        f"conversations/{conv['id']}/turns/{turn_id}/external-mcp/{confirmation_id}/confirm",
        {
            "client_request_id": "req-idempotent-1",
            "expected_definition_sha256": star_tool["definition_sha256"],
            "expected_arguments_sha256": args_sha,
        },
    )
    assert replay.status_code == 200
    assert upstream_calls["count"] == 1

    # 3. Definition change invalidates approval automatically
    tool_version["desc"] = "查询只读恒星参数 v2（定义已变）"
    rediscovered = post(admin, "admin/mcp/servers/mock_cds/discover", {})
    assert rediscovered.status_code == 200
    changed_tool = next(t for t in rediscovered.json()["tools"] if t["remote_name"] == "query_star")
    assert changed_tool["definition_changed"] is True
    assert changed_tool["approved"] is False

    # No longer visible in user active catalog until re-approved
    user_tools_after = admin.get("/api/v1/skills/tools")
    assert not any(t["tool_id"] == star_tool["tool_id"] for t in user_tools_after.json()["tools"])
    # Audit log recorded admin actions
    with admin.store.connect() as db:
        events = {
            row["event"]
            for row in db.execute(
                "SELECT event FROM public.auth_audit WHERE actor=%s", (session_user["id"],)
            ).fetchall()
        }
    assert {"mcp_server_discovered", "mcp_server_toggled", "mcp_tool_approved"}.issubset(events)
