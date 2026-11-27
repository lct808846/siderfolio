"""V2.2 PostgreSQL 与多账号/多项目隔离集成测试：长期记忆、候选冲突审核、跨会话检索与来源撤销。"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from psycopg import sql
from test_identity_postgres import ORIGIN, account, post

from astroagent.auth_config import AuthSettings
from astroagent.auth_store import AuthStore
from astroagent.config import LocalSettings
from astroagent.conversation_schemas import TurnRequest
from astroagent.schemas import ChatResponse

pytestmark = [pytest.mark.identity, pytest.mark.postgres]


@pytest.fixture
def v22_client(monkeypatch, tmp_path):
    if os.getenv("ASTROAGENT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("V2.2 PostgreSQL integration requires a disposable PostgreSQL environment")
    url = os.getenv("ASTROAGENT_TEST_DATABASE_URL", "")
    parsed = urlsplit(url)
    assert parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    assert parsed.path.startswith("/astroagent_test") and not parsed.query and not parsed.fragment
    name = "astroagent_test_v22_" + uuid4().hex
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
        monkeypatch.setenv("ASTROAGENT_RAG_MODEL_PATH", str(tmp_path / "missing-embedding"))
        monkeypatch.setenv("ASTROAGENT_RAG_MODEL_SHA256", "")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-key-not-valid")
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


class _StubAgent:
    def __init__(self, captured: list[dict]):
        self.captured = captured
        self.ads = None
        self.settings = type(
            "S",
            (),
            {"agent_max_tool_calls": 6, "selected_model_id": "stub", "deepseek_model": "stub"},
        )()

    def converse(self, message, context, skill_resolution=None, **kwargs):
        self.captured.append(
            {
                "message": message,
                "memory_block": context.render_memory_context(),
                "memory_trace": context.record.memory_context,
                "skill": skill_resolution,
            }
        )
        return ChatResponse(status="success", answer="已收到问题并按当前上下文处理。")


def test_memory_multi_account_multi_project_isolation_and_switches(v22_client):
    alice = v22_client
    account(alice, "alice-v22@example.org")
    bob = v22_client.fresh()
    account(bob, "bob-v22@example.org")

    # 1. Default memory toggle is ON, and raw memory listing/candidate endpoints are not exposed.
    prefs = alice.get("/api/v1/memories/preferences")
    assert prefs.status_code == 200
    assert prefs.json()["auto_extract"] is True
    assert prefs.json()["cross_session_injection"] is True
    assert prefs.json()["history_retrieval"] is True

    summary_initial = alice.get("/api/v1/memories/summary")
    assert summary_initial.status_code == 200
    assert summary_initial.json()["enabled"] is True
    assert summary_initial.json()["has_memory"] is False
    assert alice.get("/api/v1/memories").status_code == 405
    assert alice.get("/api/v1/memories/candidates").status_code == 404
    assert alice.get("/api/v1/memories/status").status_code == 404

    # 2. Alice creates two custom projects and adds global + project-A memories.
    proj_a = post(alice, "projects", {"name": "双星团潮汐项目 A"}).json()
    proj_b = post(alice, "projects", {"name": "白矮星测光项目 B"}).json()

    global_mem = post(
        alice,
        "memories",
        {
            "scope": "global",
            "summary": "我的研究方向是不同外部环境下的双星团动力学演化，主要使用 N 体模拟",
        },
    )
    assert global_mem.status_code == 201, global_mem.text

    proj_a_mem = post(
        alice,
        "memories",
        {
            "scope": "project",
            "project_id": proj_a["id"],
            "category": "experiment_condition",
            "summary": "项目 A 固定使用 PeTar 引擎，潮汐半径 15 pc，软化长度 0.01 pc",
        },
    )
    assert proj_a_mem.status_code == 201, proj_a_mem.text

    # Synthesized summary updates automatically without returning raw memory lists.
    alice_summary = alice.get("/api/v1/memories/summary").json()
    assert alice_summary["has_memory"] is True
    assert "双星团动力学演化" in alice_summary["summary_text"]
    assert "双星团潮汐项目 A" in alice_summary["summary_text"]
    assert "items" not in alice_summary

    # 3. Account isolation: Bob's summary is empty and Bob cannot target Alice's project.
    bob_summary = bob.get("/api/v1/memories/summary").json()
    assert bob_summary["has_memory"] is False
    cross_acct = post(
        bob,
        "memories",
        {
            "scope": "project",
            "project_id": proj_a["id"],
            "summary": "尝试越权写入他人项目",
        },
    )
    assert cross_acct.status_code == 404

    # 4. With default ON toggle, personal session sees global memory, NEVER project-A memory.
    alice_service = alice.identity.tenants.for_user(
        alice.store.authenticate(alice.cookies.get("astroagent_session"))
    )
    captured: list[dict] = []

    conv_personal = post(alice, "conversations", {"title": "个人新会话"}).json()
    alice_service.submit(
        conv_personal["id"],
        TurnRequest(
            message="找几篇和我研究方向相关的论文",
            client_request_id=str(uuid4()),
            expected_revision=0,
        ),
        lambda: _StubAgent(captured),
    )
    assert "双星团动力学演化" in captured[-1]["memory_block"]
    assert "潮汐半径 15 pc" not in captured[-1]["memory_block"]
    assert captured[-1]["skill"].skill_id == "astronomy-literature-curation"

    # 5. Project B session sees global memory but NEVER Project A memory.
    conv_b = post(alice, "conversations", {"title": "项目 B 会话"}).json()
    post(
        alice,
        f"projects/{proj_b['id']}/conversations/{conv_b['id']}",
        {
            "expected_revision": proj_b["revision"],
            "expected_conversation_revision": 0,
            "expected_metadata_revision": 0,
            "expected_source_project_id": None,
            "expected_source_revision": None,
        },
        method="PUT",
    )
    alice_service.submit(
        conv_b["id"],
        TurnRequest(
            message="请按 PeTar 和潮汐半径 15 pc 检查实验条件",
            client_request_id=str(uuid4()),
            expected_revision=0,
        ),
        lambda: _StubAgent(captured),
    )
    assert "潮汐半径 15 pc" not in captured[-1]["memory_block"]

    # 6. Turning memory toggle OFF stops injection immediately; stale revision returns 409.
    turn_off = post(
        alice,
        "memories/preferences",
        {
            "auto_extract": False,
            "cross_session_injection": False,
            "history_retrieval": False,
            "expected_revision": 0,
        },
        method="PUT",
    )
    assert turn_off.status_code == 200
    assert turn_off.json()["revision"] == 1

    stale = post(
        alice,
        "memories/preferences",
        {
            "auto_extract": True,
            "cross_session_injection": True,
            "history_retrieval": True,
            "expected_revision": 0,
        },
        method="PUT",
    )
    assert stale.status_code == 409

    alice_service.submit(
        conv_personal["id"],
        TurnRequest(
            message="再找几篇和我研究方向相关的论文",
            client_request_id=str(uuid4()),
            expected_revision=1,
        ),
        lambda: _StubAgent(captured),
    )
    assert captured[-1]["memory_block"] == ""

    # 7. Delete Project A -> project A memories are removed cleanly from summary.
    proj_a_detail = alice.get(f"/api/v1/projects/{proj_a['id']}").json()
    del_resp = post(
        alice,
        f"projects/{proj_a['id']}",
        {"expected_revision": proj_a_detail["revision"], "confirm": True},
        method="DELETE",
    )
    assert del_resp.status_code == 204
    summary_after_delete = alice.get("/api/v1/memories/summary").json()
    assert "潮汐半径 15 pc" not in summary_after_delete["summary_text"]


def test_direct_save_auto_extraction_and_source_revocation(v22_client):
    alice = v22_client
    account(alice, "alice-flow-v22@example.org")
    alice_service = alice.identity.tenants.for_user(
        alice.store.authenticate(alice.cookies.get("astroagent_session"))
    )
    captured: list[dict] = []

    # 1. Explicit direct-save saves immediately and updates memory summary.
    conv1 = post(alice, "conversations", {"title": "偏好记录会话"}).json()
    turn1, code1 = alice_service.submit(
        conv1["id"],
        TurnRequest(
            message="记住我主要用 Python 做数据分析",
            client_request_id=str(uuid4()),
            expected_revision=0,
        ),
        lambda: _StubAgent(captured),
    )
    assert code1 == 200
    assert len(turn1.memory_receipts) == 1
    assert turn1.memory_receipts[0].action == "saved"
    assert turn1.memory_receipts[0].memory_id is not None

    # 2. Automatic extraction (enabled by default) captures stated tool habit into summary.
    alice_service.submit(
        conv1["id"],
        TurnRequest(
            message="我平时主要使用 Julia 和 Gnuplot 做谱线拟合。",
            client_request_id=str(uuid4()),
            expected_revision=1,
        ),
        lambda: _StubAgent(captured),
    )
    summary = alice.get("/api/v1/memories/summary").json()
    assert summary["has_memory"] is True
    assert "Python" in summary["summary_text"]
    assert "Julia" in summary["summary_text"]

    # 3. Cross-session history search finds conv1 turn in a new personal session,
    # and deleting conv1 immediately revokes derived memory and stops history hits.
    conv2 = post(alice, "conversations", {"title": "跨会话检索测试"}).json()
    alice_service.submit(
        conv2["id"],
        TurnRequest(
            message="之前用 Julia 做谱线拟合是怎么说的",
            client_request_id=str(uuid4()),
            expected_revision=0,
        ),
        lambda: _StubAgent(captured),
    )
    assert "Julia" in captured[-1]["memory_block"]
    assert captured[-1]["memory_trace"].history_count >= 1

    # Delete conv1 -> derived memory is marked source_missing & paused.
    del_conv = post(alice, f"conversations/{conv1['id']}", None, method="DELETE")
    assert del_conv.status_code == 204

    summary_after_revoke = alice.get("/api/v1/memories/summary").json()
    assert "Julia" not in summary_after_revoke["summary_text"]

    alice_service.submit(
        conv2["id"],
        TurnRequest(
            message="再次询问之前 Julia 谱线拟合记录",
            client_request_id=str(uuid4()),
            expected_revision=1,
        ),
        lambda: _StubAgent(captured),
    )
    assert "Julia" not in captured[-1]["memory_block"]
    assert captured[-1]["memory_trace"].history_count == 0
