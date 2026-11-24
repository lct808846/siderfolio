"""持久化、幂等、故障恢复、上下文边界与同包产物的行为测试。"""

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from astroagent.agent import AstroAgent
from astroagent.api import conversations as routes
from astroagent.config import LocalSettings, Settings
from astroagent.context import MAX_HISTORY_BYTES, MAX_HISTORY_TURNS, PreparedContext
from astroagent.conversation_schemas import ArtifactRequest, Turn, TurnRequest
from astroagent.conversation_service import ConversationService
from astroagent.conversations import ConversationRepository, conversation_title
from astroagent.errors import ServiceError
from astroagent.main import app
from astroagent.postgres import PostgresRepository
from astroagent.schemas import ChatResponse
from scripts.export_samples import synthetic_request


class RecordingAgent:
    def __init__(self, response=None):
        self.response = response or ChatResponse.model_validate(synthetic_request()["snapshot"])
        self.calls = []

    def converse(self, message, context):
        self.calls.append((message, context))
        return self.response


@pytest.fixture
def client(monkeypatch):
    agent = RecordingAgent()
    monkeypatch.setattr(routes, "get_agent", lambda: agent)
    with TestClient(app) as client:
        client.agent = agent
        yield client


def create(client, title="合成会话"):
    response = client.post("/api/v1/conversations", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def submit(client, conversation, message="合成查询", request_id=None, revision=None):
    return client.post(
        f"/api/v1/conversations/{conversation['id']}/turns",
        json={
            "message": message,
            "client_request_id": request_id or str(uuid4()),
            "expected_revision": conversation["revision"] if revision is None else revision,
        },
    )


def test_first_question_names_default_conversation_once_and_survives_follow_up(client):
    conversation = create(client, "新会话")
    question = "查询 Gaia DR3 source_id 5853498713190525696 的测量信息并说明限制。"
    assert submit(client, conversation, question).status_code == 200
    detail = client.get(f"/api/v1/conversations/{conversation['id']}").json()
    assert detail["title"] == conversation_title(question)
    assert len(detail["title"]) <= 36
    assert detail["metadata_revision"] == 1
    assert submit(client, conversation, "后续问题", revision=1).status_code == 200
    refreshed = client.get(f"/api/v1/conversations/{conversation['id']}").json()
    assert refreshed["title"] == detail["title"]


def test_automatic_title_preserves_custom_title_and_explicit_default_rename(client):
    custom = create(client, "我的研究项目")
    assert submit(client, custom, "合成问题").status_code == 200
    assert client.get(f"/api/v1/conversations/{custom['id']}").json()["title"] == "我的研究项目"
    manual = create(client, "新会话")
    path = f"/api/v1/conversations/{manual['id']}"
    renamed = client.patch(path, json={"title": "新会话", "expected_metadata_revision": 0})
    assert renamed.status_code == 200
    assert submit(client, manual, "合成问题").status_code == 200
    assert client.get(path).json()["title"] == "新会话"


def test_crud_complete_data_and_idempotency(client):
    conversation = create(client)
    key = str(uuid4())
    first = submit(client, conversation, request_id=key)
    assert first.status_code == 200, first.text
    turn = first.json()
    assert turn["execution_status"] == "completed"
    assert len(turn["response"]["gaia_results"][0]["data"]) == 100
    assert turn["response"]["gaia_results"][0]["data"][0]["source_id"] == "5853498713190525696"
    repeated = submit(client, conversation, request_id=key)
    assert repeated.status_code == 200 and repeated.json() == turn
    assert len(client.agent.calls) == 1
    assert submit(client, conversation, "不同问题", key).status_code == 409
    assert submit(client, conversation).json()["error"]["code"] == "conversation_revision_conflict"
    detail = client.get(f"/api/v1/conversations/{conversation['id']}").json()
    assert detail["revision"] == 1 and detail["turns"][0]["turn_id"] == turn["turn_id"]
    assert "response" not in detail["turns"][0]
    fetched = client.get(
        f"/api/v1/conversations/{conversation['id']}/turns/{turn['turn_id']}"
    ).json()
    assert fetched == turn
    renamed = client.patch(
        f"/api/v1/conversations/{conversation['id']}", json={"title": "  后续查询  "}
    )
    assert renamed.json()["title"] == "后续查询"
    assert client.get("/api/v1/conversations").json()[0]["revision"] == 1
    assert client.delete(f"/api/v1/conversations/{conversation['id']}").status_code == 204
    assert client.get(f"/api/v1/conversations/{conversation['id']}").status_code == 404


def test_history_context_does_not_copy_new_results(client):
    conversation = create(client)
    first = submit(client, conversation).json()
    client.agent.response = ChatResponse(status="success", answer="根据历史第1轮解释，不是新查询。")
    second = submit(client, conversation, "解释刚才的视差统计", revision=1).json()
    assert second["context"]["included_turn_ids"] == [first["turn_id"]]
    assert len(second["context"]["referenced_results"]) == 3
    assert second["response"]["gaia_results"] == []
    view = client.agent.calls[-1][1].payload[0]["historical_response"]
    assert len(view["gaia_results"][0]["data"]) == 10
    assert view["gaia_results"][0]["analysis"]["sample_size"] == 100
    assert first["response"]["gaia_results"][0]["returned_count"] == 100


def test_context_whole_turn_window_and_bytes():
    response = ChatResponse.model_validate(synthetic_request()["snapshot"])
    history = [
        Turn(
            conversation_id=str(uuid4()),
            turn_id=str(uuid4()),
            revision=i + 1,
            client_request_id=str(uuid4()),
            message="问题",
            execution_status="completed",
            received_at="2026-10-28T00:00:00Z",
            response=response,
        )
        for i in range(MAX_HISTORY_TURNS + 2)
    ]
    context = PreparedContext(history, "新问题")
    assert 0 < len(context.payload) <= MAX_HISTORY_TURNS
    assert context.record.delivered_bytes <= MAX_HISTORY_BYTES
    assert history[0].turn_id in context.record.omitted_turn_ids
    assert all(
        len(item["historical_response"]["gaia_results"][0]["data"]) == 10
        for item in context.payload
    )
    history[-1].response = ChatResponse(
        status="success", answer="大" * (MAX_HISTORY_BYTES // 3 + 1)
    )
    context = PreparedContext(history, "新问题")
    assert history[-1].turn_id in context.record.omitted_turn_ids
    assert context.record.warnings
    assert context.render().startswith("[") and isinstance(json.loads(context.render()), list)


def test_same_agent_loop_and_historical_data_not_tool_messages():
    from test_chat import ScriptedModel, StubSimbad

    history = [
        Turn(
            conversation_id=str(uuid4()),
            turn_id=str(uuid4()),
            revision=1,
            client_request_id=str(uuid4()),
            message="合成查询",
            execution_status="completed",
            received_at="2026-10-28T00:00:00Z",
            response=ChatResponse.model_validate(synthetic_request()["snapshot"]),
        )
    ]
    model = ScriptedModel(AIMessage(content="历史解释"))
    agent = AstroAgent(model, StubSimbad(), Settings())
    context = PreparedContext(history, "解释上一轮")
    assert agent.converse("解释上一轮", context).gaia_results == []
    # ScriptedModel keeps actual messages supplied to the common invocation loop.
    messages = model.messages[0] if hasattr(model, "messages") else model.calls[0]
    assert any("历史数据" in str(message.content) for message in messages)
    assert all(message.type != "tool" for message in messages)
    assert "每次请求无状态，下一次需包含完整条件。" not in messages[0].content


def test_restart_persistence_and_running_interrupted(tmp_path):
    settings = LocalSettings(data_dir=tmp_path / "db")
    repository = ConversationRepository(settings)
    repository.initialize()
    conversation = repository.create("重启测试")
    request = TurnRequest(message="不要重放", client_request_id=str(uuid4()), expected_revision=0)
    reserved = repository.reserve(conversation["id"], request)
    repository.close()
    second = ConversationRepository(settings)
    second.initialize()
    try:
        turn = second.turn(conversation["id"], reserved.turn_id)
        assert turn.execution_status == "interrupted" and turn.error.code == "turn_interrupted"
        assert second.existing(conversation["id"], request).turn_id == reserved.turn_id
        with second.connection() as db:
            assert db.execute("SELECT sum(reserved_bytes) FROM turns").fetchone()[0] == 0
        assert list(settings.data_dir.glob("migration-*.sqlite3"))
    finally:
        second.close()


def test_unknown_schema_rejected_without_overwrite(tmp_path):
    settings = LocalSettings(data_dir=tmp_path / "future")
    settings.data_dir.mkdir()
    path = settings.data_dir / "astroagent.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
        db.execute("CREATE TABLE valuable(value TEXT)")
        db.execute("INSERT INTO valuable VALUES ('preserve')")
    repository = ConversationRepository(settings)
    with pytest.raises(ServiceError):
        repository.initialize()
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99
        assert db.execute("SELECT value FROM valuable").fetchone()[0] == "preserve"


def test_migration_failure_rolls_back(tmp_path, monkeypatch):
    settings = LocalSettings(data_dir=tmp_path / "rollback")

    def fail(db):
        db.execute("CREATE TABLE accidental(value TEXT)")
        raise sqlite3.OperationalError("sensitive path")

    repository = ConversationRepository(settings)
    monkeypatch.setattr(repository, "_migrate_v1", fail)
    with pytest.raises(ServiceError) as error:
        repository.initialize()
    assert "sensitive" not in str(error.value)
    with sqlite3.connect(repository.path) as db:
        assert (
            db.execute("SELECT name FROM sqlite_master WHERE name='accidental'").fetchone() is None
        )
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
    assert list(settings.data_dir.glob("migration-*.sqlite3"))


def test_duplicate_process_and_multiworker_not_enabled(tmp_path, monkeypatch):
    settings = LocalSettings(data_dir=tmp_path / "single")
    first = ConversationRepository(settings)
    first.initialize()
    try:
        with pytest.raises(ServiceError):
            ConversationRepository(settings).initialize()
    finally:
        first.close()
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(ServiceError):
        ConversationRepository(settings).initialize()


@pytest.mark.parametrize(
    ("stack", "web_concurrency", "uvicorn_workers", "expected_code"),
    [
        ("", "1", "1", "conversation_storage_unavailable"),
        ("astroagent-dev", "1", "1", "database_unavailable"),
        ("astroagent-dev", "2", "1", "conversation_storage_unavailable"),
        ("astroagent-dev", "1", "2", "conversation_storage_unavailable"),
    ],
)
def test_postgres_reload_child_respects_single_worker_guard(
    tmp_path, monkeypatch, stack, web_concurrency, uvicorn_workers, expected_code
):
    monkeypatch.setenv("ASTROAGENT_DEV_STACK", stack)
    monkeypatch.setenv("WEB_CONCURRENCY", web_concurrency)
    monkeypatch.setenv("UVICORN_WORKERS", uvicorn_workers)
    monkeypatch.setattr("astroagent.postgres.multiprocessing.parent_process", lambda: object())
    repository = PostgresRepository(
        LocalSettings(
            _env_file=None,
            data_dir=tmp_path,
            database_url="postgresql://127.0.0.1/astroagent_test",
        )
    )

    def connect():
        raise ServiceError(503, "database_unavailable", "Fixture reached the database connection.")

    monkeypatch.setattr(repository, "connect", connect)
    with pytest.raises(ServiceError) as error:
        repository.initialize()
    assert error.value.error.code == expected_code


def test_concurrency_idempotent_running_and_global_slots(tmp_path):
    repository = ConversationRepository(LocalSettings(data_dir=tmp_path / "parallel"))
    repository.initialize()
    service = ConversationService(repository)
    conversations = [repository.create(str(i)) for i in range(3)]
    entered = threading.Barrier(3)
    release = threading.Event()

    class Blocking:
        def converse(self, message, context):
            entered.wait(timeout=10)
            assert release.wait(10)
            return ChatResponse(status="success", answer="done")

    requests = [
        TurnRequest(message="问题", client_request_id=str(uuid4()), expected_revision=0)
        for _ in conversations
    ]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(service.submit, conversations[i]["id"], requests[i], Blocking)
                for i in (0, 1)
            ]
            entered.wait(timeout=10)
            repeated, status = service.submit(conversations[0]["id"], requests[0], Blocking)
            assert status == 202 and repeated.execution_status == "running"
            with pytest.raises(ServiceError) as error:
                service.submit(conversations[2]["id"], requests[2], Blocking)
            assert error.value.error.code == "conversation_service_busy"
            with pytest.raises(ServiceError) as error:
                repository.delete(conversations[0]["id"])
            assert error.value.error.code == "conversation_busy"
            renamed = repository.rename(conversations[0]["id"], "manual title")
            assert renamed["title"] == "manual title"
            release.set()
            assert all(f.result(timeout=10)[0].execution_status == "completed" for f in futures)
            assert repository.detail(conversations[0]["id"])["title"] == "manual title"
    finally:
        release.set()
        repository.close()


def test_model_failure_saved_and_retries_not_charged(client, monkeypatch):
    class Failing:
        calls = 0

        def converse(self, *args):
            self.calls += 1
            raise ServiceError(504, "model_timeout", "模型超时。")

    agent = Failing()
    monkeypatch.setattr(routes, "get_agent", lambda: agent)
    conversation = create(client)
    key = str(uuid4())
    first = submit(client, conversation, request_id=key)
    assert first.status_code == 504 and first.json()["turn_id"]
    repeat = submit(client, conversation, request_id=key)
    assert repeat.status_code == 200 and repeat.json()["execution_status"] == "failed"
    assert agent.calls == 1
    assert submit(client, conversation, revision=1).status_code == 504
    assert agent.calls == 2


def test_limits_and_large_results_are_not_silently_truncated(client):
    service = app.state.conversation_service
    conversation = create(client)
    service.repository.settings.turn_bytes = 1500
    result = submit(client, conversation)
    assert result.status_code == 503 and result.json()["error"]["code"] == "turn_result_too_large"
    turn = client.get(
        f"/api/v1/conversations/{conversation['id']}/turns/{result.json()['turn_id']}"
    ).json()
    assert turn["response"] is None and turn["execution_status"] == "failed"
    service.repository.settings.max_turns = 1
    assert (
        submit(client, conversation, revision=1).json()["error"]["code"]
        == "conversation_limit_reached"
    )


def test_storage_budget_and_commit_fault(client, monkeypatch):
    repository = app.state.conversation_service.repository
    conversation = create(client)
    repository.settings.storage_bytes = 1024
    assert submit(client, conversation).json()["error"]["code"] == "conversation_storage_limit"
    assert client.agent.calls == []
    repository.settings.storage_bytes = 256 * 1024**2

    def fail(turn):
        raise ServiceError(503, "conversation_storage_unavailable", "未确认保存。")

    monkeypatch.setattr(repository, "finish", fail)
    response = submit(client, conversation)
    assert response.status_code == 503 and response.json()["turn_id"]
    assert (
        client.get(
            f"/api/v1/conversations/{conversation['id']}/turns/{response.json()['turn_id']}"
        ).json()["execution_status"]
        == "running"
    )


def test_artifact_preview_same_zip_cache_and_delete(client):
    conversation = create(client)
    turn = submit(client, conversation).json()
    path = f"/api/v1/conversations/{conversation['id']}/turns/{turn['turn_id']}/artifacts"
    payload = {
        "plots": [
            {"gaia_result_index": 0, "kind": kind}
            for kind in ("proper_motion", "parallax_histogram", "observed_cmd")
        ]
    }
    response = client.post(path, json=payload)
    assert response.status_code == 201, response.text
    info = response.json()
    assert (
        client.post(path, json={"plots": list(reversed(payload["plots"]))}).json()["artifact_id"]
        == info["artifact_id"]
    )
    downloaded = client.get(info["download_url"])
    assert downloaded.headers["cache-control"] == "no-store"
    with ZipFile(BytesIO(downloaded.content)) as archive:
        manifest = client.get(info["manifest_url"]).json()
        assert manifest == json.loads(archive.read("manifest.json"))
        assert manifest["source_authenticity_verified"] is False
        for figure in info["figures"]:
            picture = client.get(figure["url"])
            assert picture.status_code == 200 and picture.headers["content-type"] == "image/png"
            assert hashlib.sha256(picture.content).hexdigest() == figure["sha256"]
            assert any(
                archive.read(name) == picture.content
                for name in archive.namelist()
                if name.endswith(".png")
            )
    client.delete(f"/api/v1/conversations/{conversation['id']}")
    assert client.get(info["download_url"]).status_code == 404


def test_artifact_expiry_capacity_and_snapshot_limit(client):
    conversation = create(client)
    turn = submit(client, conversation).json()
    cache = app.state.conversation_service.artifacts
    clock = [0.0]
    cache.clock = lambda: clock[0]
    info = cache.generate(conversation["id"], turn["turn_id"], ArtifactRequest())
    cache.settings.artifact_count = 1
    with pytest.raises(ServiceError) as error:
        cache.generate(
            conversation["id"],
            turn["turn_id"],
            ArtifactRequest(plots=[{"gaia_result_index": 0, "kind": "proper_motion"}]),
        )
    assert error.value.error.code == "artifact_cache_full"
    clock[0] = 1000
    assert client.get(info.download_url).status_code == 410
    assert client.get(f"/api/v1/artifacts/{uuid4()}/download").status_code == 404
    rebuilt = cache.generate(conversation["id"], turn["turn_id"], ArtifactRequest())
    assert rebuilt.artifact_id != info.artifact_id
    stored = app.state.conversation_service.repository.turn(conversation["id"], turn["turn_id"])
    stored.response.answer = "大" * 800000
    app.state.conversation_service.repository.finish(stored)
    with pytest.raises(ServiceError) as error:
        cache.generate(conversation["id"], turn["turn_id"], ArtifactRequest())
    assert error.value.status_code == 413


@pytest.mark.parametrize("body", [{"title": " "}, {"title": "x", "extra": 1}, {"title": 1}])
def test_new_input_contracts(client, body):
    assert client.post("/api/v1/conversations", json=body).status_code == 422


def test_host_origin_cors_json_stream_and_ownership(client):
    assert (
        client.post(
            "/api/v1/conversations", json={}, headers={"Origin": "https://untrusted.invalid"}
        ).status_code
        == 403
    )
    assert client.get("/health", headers={"Host": "untrusted.invalid"}).status_code == 400
    preflight = client.options(
        "/api/v1/conversations",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert (
        preflight.status_code == 200
        and preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    )
    assert (
        client.post(
            "/api/v1/conversations",
            content=iter([b" " * 16384] * 3),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    for body in (b"{", b"[" * 100 + b"]" * 100, b'{"title":"a","title":"b"}', b"NaN"):
        assert (
            client.post(
                "/api/v1/conversations", content=body, headers={"Content-Type": "application/json"}
            ).status_code
            == 422
        )
    conversation = create(client)
    another = create(client)
    turn = submit(client, conversation).json()
    assert (
        client.get(f"/api/v1/conversations/{another['id']}/turns/{turn['turn_id']}").status_code
        == 404
    )


def test_storage_unavailable_does_not_break_old_routes(tmp_path, monkeypatch):
    bad = tmp_path / "file"
    bad.write_text("not a directory")
    monkeypatch.setenv("ASTROAGENT_DATA_DIR", str(bad))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/api/v1/conversations").status_code == 503


def test_legacy_chat_shares_global_model_slots(client):
    from astroagent.execution import MODEL_TASK_SLOTS

    assert MODEL_TASK_SLOTS.acquire(blocking=False)
    assert MODEL_TASK_SLOTS.acquire(blocking=False)
    try:
        response = client.post("/api/v1/chat", json={"message": "普通问题"})
        assert (
            response.status_code == 503
            and response.json()["error"]["code"] == "conversation_service_busy"
        )
    finally:
        MODEL_TASK_SLOTS.release()
        MODEL_TASK_SLOTS.release()


def test_corrupted_preview_is_not_served_as_png(client):
    conversation = create(client)
    turn = submit(client, conversation).json()
    cache = app.state.conversation_service.artifacts
    info = cache.generate(
        conversation["id"],
        turn["turn_id"],
        ArtifactRequest(plots=[{"gaia_result_index": 0, "kind": "proper_motion"}]),
    )
    cache.items[info.artifact_id]["package"] = b"invalid zip"
    response = client.get(info.figures[0]["url"])
    assert response.status_code == 500 and response.json()["error"]["code"] == "export_failed"


def test_invalid_local_settings_keep_health_and_refuse_network_directory(monkeypatch):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LocalSettings(data_dir="//server/share")
    with pytest.raises(ValidationError):
        LocalSettings(allowed_origins=["*"])
    monkeypatch.setenv("ASTROAGENT_ALLOWED_ORIGINS", "broken JSON")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/conversations").status_code == 503


def test_rename_cannot_bypass_business_content_budget(client):
    conversation = create(client, "a")
    repository = app.state.conversation_service.repository
    with repository.connection() as db:
        repository.settings.storage_bytes = repository._used(db)
    response = client.patch(
        f"/api/v1/conversations/{conversation['id']}", json={"title": "很长的标题" * 10}
    )
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "conversation_storage_limit"
    )
    assert client.get(f"/api/v1/conversations/{conversation['id']}").json()["title"] == "a"
