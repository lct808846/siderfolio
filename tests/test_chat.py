from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError

from astroagent.agent import AstroAgent
from astroagent.api.chat import get_agent
from astroagent.config import Settings
from astroagent.main import app
from astroagent.schemas import ErrorInfo, ObjectData, QueryResult, Source


class ScriptedModel:
    def __init__(self, *replies):
        self.replies = iter(replies)
        self.messages = []

    def invoke(self, messages):
        self.messages.append(list(messages))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


class StubSimbad:
    def __init__(self, *results):
        self.results = iter(results)
        self.names = []

    def query(self, object_name):
        self.names.append(object_name)
        return next(self.results)


def query_reply(*names):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "query_simbad", "args": {"object_name": name}, "id": f"call_{i}"}
            for i, name in enumerate(names)
        ],
    )


def result(name="test-star", status="success"):
    # Synthetic unit-test data; never used by the application or live acceptance.
    return QueryResult(
        object_name=name,
        status=status,
        source=Source(url=f"https://example.test/{name}", retrieved_at=datetime.now(UTC)),
        data=ObjectData(main_id=name, ra_deg=12, dec_deg=-34) if status == "success" else None,
        error=ErrorInfo(code="object_not_found", message="未找到") if status != "success" else None,
    )


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def install_agent(model, simbad, **settings):
    agent = AstroAgent(model, simbad, Settings(_env_file=None, **settings))
    app.dependency_overrides[get_agent] = lambda: agent
    return agent


def test_tool_call_round_trip_and_provenance(client):
    model = ScriptedModel(query_reply("test-star"), AIMessage(content="查询完成"))
    simbad = StubSimbad(result())
    install_agent(model, simbad)
    response = client.post("/api/v1/chat", json={"message": "查询 test-star"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["results"][0]["data"]["ra_deg"] == 12
    assert body["sources"][0]["url"] == "https://example.test/test-star"
    assert body["sources"][0]["retrieved_at"]
    assert simbad.names == ["test-star"]
    assert isinstance(model.messages[1][-1], ToolMessage)
    assert model.messages[1][-1].tool_call_id == "call_0"
    assert '"ra_deg": 12.0' in model.messages[1][-1].content


def test_concept_answer_does_not_query_database(client):
    install_agent(ScriptedModel(AIMessage(content="赤经是天球上的一个坐标。")), StubSimbad())
    body = client.post("/api/v1/chat", json={"message": "什么是赤经"}).json()
    assert body["status"] == "success"
    assert body["results"] == body["sources"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": ""},
        {"message": " \n "},
        {"message": "x" * 4001},
        {"message": None},
        {"message": 123},
        {"message": "hello", "extra": "unexpected"},
    ],
)
def test_invalid_request_rejected_before_model_creation(client, monkeypatch, payload):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    assert client.post("/api/v1/chat", json=payload).status_code == 422


def test_missing_key_does_not_break_health(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    response = client.post("/api/v1/chat", json={"message": "查询 Betelgeuse"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_not_configured"
    assert client.get("/health").json() == {"status": "ok"}


def test_invalid_configuration_is_sanitized(client, monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "secret-invalid-value")
    response = client.post("/api/v1/chat", json={"message": "hello"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "invalid_configuration"
    assert "secret-invalid-value" not in response.text


@pytest.mark.parametrize(
    "exc,status,code",
    [
        (
            APITimeoutError(request=httpx.Request("POST", "https://example.test")),
            504,
            "model_timeout",
        ),
        (
            APIConnectionError(request=httpx.Request("POST", "https://example.test")),
            502,
            "model_unavailable",
        ),
        (
            AuthenticationError(
                "secret",
                response=httpx.Response(401, request=httpx.Request("POST", "https://example.test")),
                body=None,
            ),
            503,
            "model_authentication_failed",
        ),
        (
            RateLimitError(
                "secret",
                response=httpx.Response(429, request=httpx.Request("POST", "https://example.test")),
                body=None,
            ),
            503,
            "model_rate_limited",
        ),
        (ValueError("secret"), 502, "model_invalid_response"),
    ],
)
def test_model_failures_have_stable_safe_errors(client, exc, status, code):
    install_agent(ScriptedModel(exc), StubSimbad())
    response = client.post("/api/v1/chat", json={"message": "hello"})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "secret" not in response.text


def test_database_failure_is_visible_to_model_and_client(client):
    model = ScriptedModel(query_reply("missing"), AIMessage(content="SIMBAD 未找到该名称。"))
    install_agent(model, StubSimbad(result("missing", "not_found")))
    body = client.post("/api/v1/chat", json={"message": "查询 missing"}).json()
    assert body["status"] == "error"
    assert body["sources"] == []
    assert body["results"][0]["error"]["code"] == "object_not_found"
    assert '"not_found"' in model.messages[1][-1].content


def test_multiple_objects_partial_success(client):
    install_agent(
        ScriptedModel(query_reply("test-star", "missing"), AIMessage(content="只有一个匹配。")),
        StubSimbad(result(), result("missing", "not_found")),
    )
    body = client.post("/api/v1/chat", json={"message": "查询两颗天体"}).json()
    assert body["status"] == "partial"
    assert len(body["results"]) == 2
    assert len(body["sources"]) == 1


def test_synthesis_timeout_keeps_database_results(client):
    install_agent(ScriptedModel(query_reply("test-star"), TimeoutError()), StubSimbad(result()))
    body = client.post("/api/v1/chat", json={"message": "查询 test-star"}).json()
    assert body["status"] == "partial"
    assert body["results"][0]["data"]["main_id"] == "test-star"
    assert body["warnings"][0]["code"] == "model_timeout"


@pytest.mark.parametrize(
    "call",
    [
        {"name": "run_shell", "args": {"command": "oops"}, "id": "1"},
        {"name": "query_simbad", "args": {"object_name": " "}, "id": "1"},
        {"name": "query_simbad", "args": {"object_name": "x", "sql": "bad"}, "id": "1"},
        {"name": "query_simbad", "args": {}, "id": "1"},
    ],
)
def test_unknown_tools_and_invalid_arguments_never_execute(client, call):
    simbad = StubSimbad()
    install_agent(ScriptedModel(AIMessage(content="", tool_calls=[call])), simbad)
    response = client.post("/api/v1/chat", json={"message": "test"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "model_invalid_tool_call"
    assert simbad.names == []


def test_call_limit_prevents_execution_of_oversized_batch(client):
    simbad = StubSimbad()
    install_agent(ScriptedModel(query_reply("a", "b")), simbad, agent_max_tool_calls=1)
    response = client.post("/api/v1/chat", json={"message": "test"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "agent_limit_reached"
    assert simbad.names == []


def test_round_limit_stops_repeated_calls_and_preserves_results(client):
    simbad = StubSimbad(result(), result())
    install_agent(
        ScriptedModel(query_reply("test-star"), query_reply("test-star")),
        simbad,
        agent_max_rounds=2,
    )
    body = client.post("/api/v1/chat", json={"message": "test"}).json()
    assert body["status"] == "partial"
    assert len(simbad.names) == 2
    assert len(body["sources"]) == 1
    assert body["warnings"][0]["code"] == "agent_limit_reached"


def test_empty_model_answer_is_reported(client):
    install_agent(ScriptedModel(AIMessage(content=" ")), StubSimbad())
    response = client.post("/api/v1/chat", json={"message": "test"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "model_empty_response"


def test_chat_is_documented(client):
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/chat"]["post"]
    assert {"200", "422", "502", "503", "504"} <= set(operation["responses"])
