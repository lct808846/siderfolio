"""Opt-in real PostgreSQL/pgvector integration; synthetic model, not RAG quality evidence.

ASTROAGENT_RUN_POSTGRES_TESTS=1 and ASTROAGENT_TEST_DATABASE_URL must identify
a dedicated local maintenance database whose name starts with astroagent_test.
Each test creates a new random database, and drops only that exact created database.
"""

import json
import math
import os
from io import BytesIO
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

pytestmark = pytest.mark.postgres


@pytest.fixture
def pg_client(monkeypatch, tmp_path):
    if os.getenv("ASTROAGENT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration is opt-in, not a passing runtime check")
    url = os.getenv("ASTROAGENT_TEST_DATABASE_URL", "")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("postgresql", "postgres")
        or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
        or not parsed.path.lstrip("/").startswith("astroagent_test")
        or parsed.query
        or parsed.fragment
    ):
        pytest.fail(
            "Configure an independent local astroagen"
            "t_test maintenance database; no personal"
            " DB allowed"
        )
    import psycopg
    from psycopg import sql

    import astroagent.main as main
    from astroagent.postgres import PostgresRepository

    name = "astroagent_test_" + uuid4().hex
    target = urlunsplit(parsed._replace(path="/" + name))
    created = False
    try:
        with psycopg.connect(url, autocommit=True, connect_timeout=5) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name))
            )
        created = True
        monkeypatch.setenv("ASTROAGENT_DATABASE_URL", target)
        monkeypatch.setenv("ASTROAGENT_RAG_MODEL_PATH", str(tmp_path / "synthetic-model"))
        monkeypatch.setenv("ASTROAGENT_RAG_MODEL_SHA256", "f" * 64)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-key-not-valid")

        class TestRepository(PostgresRepository):
            def initialize(self, *, create=True):
                return super().initialize(create=create)

        monkeypatch.setattr(main, "PostgresRepository", TestRepository)
        with TestClient(main.app) as client:
            service = main.app.state.conversation_service
            assert service is not None, "Isolated PostgreSQL/pgvector initialization must succeed"

            class Embedder:
                def identity(self):
                    return "f" * 64

                def encode(self, texts):
                    return [[1 / math.sqrt(384)] * 384 for _ in texts]

            service.rag.embedder = Embedder()
            client.rag_service = service.rag
            client.model_payloads = []

            class Model:
                def __init__(self, settings, **kwargs):
                    self.settings = settings

                def invoke(self, messages):
                    client.model_payloads.append(
                        {
                            "model": self.settings.deepseek_model,
                            "messages": [{"content": message.content} for message in messages],
                        }
                    )
                    value = (
                        '{"answer":"Synthetic explanation [E1]","'
                        'citations":["E1"],"insufficient_evidence'
                        '":false}'
                    )
                    return AIMessage(
                        content=value,
                        response_metadata={
                            "model_name": "synthetic-answer-v1",
                            "finish_reason": "stop",
                        },
                    )

            monkeypatch.setattr("astroagent.model_client.chat_model", Model)
            yield client
    finally:
        if created:
            # Only this fixture's exact random name is eligible. No source database is dropped.
            if not name.startswith("astroagent_test_") or len(name) != len("astroagent_test_") + 32:
                raise AssertionError("Unsafe test database cleanup target")
            with psycopg.connect(url, autocommit=True, connect_timeout=5) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_conversation_crud_uses_postgres_parameter_binding(pg_client):
    title = "新会话 · Gaia DR3 :id 100% ? '编号'"
    response = pg_client.post("/api/v1/conversations", json={"title": title})
    assert response.status_code == 201
    conversation = response.json()
    assert conversation["title"] == title
    assert conversation["revision"] == 0
    assert conversation["metadata_revision"] == 0
    root = f"/api/v1/conversations/{conversation['id']}"
    assert pg_client.get(root).json()["turns"] == []
    assert pg_client.get("/api/v1/conversations").json() == [conversation]
    renamed = pg_client.patch(
        root,
        json={"title": "更名后的会话", "expected_metadata_revision": 0},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "更名后的会话"
    assert pg_client.delete(root).status_code == 204
    assert pg_client.get("/api/v1/conversations").json() == []
    assert pg_client.model_payloads == []


def test_first_question_title_is_saved_with_postgres_turn_reservation(pg_client):
    from astroagent.conversation_schemas import TurnRequest
    from astroagent.conversations import conversation_title, utc_now
    from astroagent.main import app

    conversation = pg_client.post("/api/v1/conversations", json={}).json()
    question = "查询双星团的银河环境影响及相关文献"
    repository = app.state.repository
    turn = repository.reserve(
        conversation["id"],
        TurnRequest(message=question, client_request_id=str(uuid4()), expected_revision=0),
    )
    detail = pg_client.get(f"/api/v1/conversations/{conversation['id']}").json()
    assert detail["title"] == conversation_title(question)
    assert detail["metadata_revision"] == 1
    turn.execution_status = "interrupted"
    turn.completed_at = utc_now()
    repository.finish(turn)
    assert pg_client.model_payloads == []


def project_with_document(client):
    response = client.post("/api/v1/projects", json={"name": "RAG synthetic project"})
    assert response.status_code == 201
    project = response.json()
    root = f"/api/v1/projects/{project['id']}"
    response = client.post(
        root + "/documents",
        files={
            "file": (
                "fixture.md",
                b"# Reference\nBinary cluster environment synthetic fixture.\n",
                "text/markdown",
            )
        },
        data={
            "options": json.dumps(
                {"expected_revision": project["revision"], "client_request_id": str(uuid4())}
            )
        },
    )
    assert response.status_code in (200, 201)
    document = response.json()["document"]
    assert document["state"] == "ready"
    return root, document


def build(client, root):
    revision = client.get(root).json()["revision"]
    response = client.post(
        root + "/rag/indexes",
        json={"client_request_id": str(uuid4()), "expected_revision": revision, "confirmed": True},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "ready"
    return response.json()


def test_unmatched_literal_preview_cannot_send_nearest_neighbours(pg_client, monkeypatch):
    root, _ = project_with_document(pg_client)
    build(pg_client, root)

    def no_embedding(texts):
        raise AssertionError("Unanchored literal must not invoke the semantic model")

    monkeypatch.setattr(pg_client.rag_service.embedder, "encode", no_embedding)
    value = pg_client.post(root + "/rag/previews", json={"question": "unlistedcatalogueterm"})
    assert value.status_code == 200
    record = value.json()
    assert record["status"] == "no_results"
    assert record["evidence"] == []
    assert record["semantic_status"] == "literal_query_unmatched"
    assert record["retrieval"]["version"] == "pg-rrf-v2"
    rejected = pg_client.post(
        root + "/rag/answers",
        json={
            "client_request_id": str(uuid4()),
            "preview_id": record["id"],
            "confirmation_token": record["confirmation_token"],
            "confirmed": True,
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "rag_insufficient_evidence"
    assert pg_client.model_payloads == []


def preview(client, root):
    response = client.post(
        root + "/rag/previews",
        json={
            "question": "binary cluster",
            "document_ids": [],
            "version_ids": [],
            "history_ids": [],
        },
    )
    assert response.status_code == 200
    value = response.json()
    assert value["evidence"] and value["lexical_status"] == value["semantic_status"] == "ready"
    assert value["evidence"][0]["view"]["text"]
    return value


def test_confirmation_idempotency_and_deleted_request_never_resends(pg_client):
    client = pg_client
    root, _ = project_with_document(client)
    build(client, root)
    value = preview(client, root)
    assert not client.model_payloads
    body = {
        "client_request_id": str(uuid4()),
        "preview_id": value["id"],
        "confirmation_token": value["confirmation_token"],
        "confirmed": True,
    }
    assert (
        client.post(
            root + "/rag/answers", json={**body, "confirmation_token": "0" * 64}
        ).status_code
        == 409
    )
    assert client.post(root + "/rag/answers", json={**body, "confirmed": False}).status_code == 422
    assert not client.model_payloads
    response = client.post(root + "/rag/answers", json=body)
    assert response.status_code == 200 and response.json()["record"]["state"] == "completed"
    identifier = response.json()["record"]["id"]
    assert len(client.model_payloads) == 1
    assert client.post(root + "/rag/answers", json=body).json()["record"]["id"] == identifier
    assert len(client.model_payloads) == 1
    assert (
        client.request(
            "DELETE", root + "/rag/answers/" + identifier, json={"confirmed": True}
        ).status_code
        == 204
    )
    assert (
        client.post(root + "/rag/answers", json=body).json()["error"]["code"]
        == "rag_answer_deleted"
    )
    assert len(client.model_payloads) == 1


def test_selected_model_and_previewed_evidence_are_frozen_for_confirmation(pg_client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL", "model-a")
    monkeypatch.setenv(
        "CHAT_MODELS",
        json.dumps([{"id": "model-a", "label": "A"}, {"id": "model-b", "label": "B"}]),
    )
    root, _ = project_with_document(pg_client)
    build(pg_client, root)
    response = pg_client.post(
        root + "/rag/previews", json={"question": "binary cluster", "model": "model-b"}
    )
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["model"] == "model-b" and value["evidence"]
    assert not pg_client.model_payloads
    body = {
        "client_request_id": str(uuid4()),
        "preview_id": value["id"],
        "confirmation_token": value["confirmation_token"],
        "confirmed": True,
    }
    response = pg_client.post(root + "/rag/answers", json=body)
    assert response.status_code == 200, response.text
    assert len(pg_client.model_payloads) == 1
    sent = pg_client.model_payloads[0]
    assert sent["model"] == "model-b"
    payload = json.loads(sent["messages"][1]["content"])
    assert payload["question"] == "binary cluster"
    assert [item["text"] for item in payload["evidence"]] == [
        item["view"]["text"] for item in value["evidence"]
    ]


def test_scope_changed_original_never_sends(pg_client):
    client = pg_client
    root, document = project_with_document(client)
    build(client, root)
    value = preview(client, root)
    other = client.post("/api/v1/projects", json={"name": "Other project"}).json()
    body = {
        "client_request_id": str(uuid4()),
        "preview_id": value["id"],
        "confirmation_token": value["confirmation_token"],
        "confirmed": True,
    }
    assert client.post(f"/api/v1/projects/{other['id']}/rag/answers", json=body).status_code == 409
    revision = client.get(root).json()["revision"]
    assert (
        client.request(
            "DELETE",
            root + f"/documents/{document['id']}",
            json={"expected_revision": revision, "confirmed": True},
        ).status_code
        == 204
    )
    assert client.post(root + "/rag/answers", json=body).status_code == 409
    assert not client.model_payloads
    assert client.get(root + "/rag/status").json()["active_index_id"] is None


def test_format5_restores_fixed_citations_with_new_ids(pg_client):
    client = pg_client
    root, _ = project_with_document(client)
    build(client, root)
    value = preview(client, root)
    answer = client.post(
        root + "/rag/answers",
        json={
            "client_request_id": str(uuid4()),
            "preview_id": value["id"],
            "confirmation_token": value["confirmation_token"],
            "confirmed": True,
        },
    ).json()
    revision = client.get(root).json()["revision"]
    assert (
        client.post(
            root + "/archive", json={"expected_revision": revision, "format_version": 4}
        ).status_code
        == 409
    )
    archived = client.post(
        root + "/archive",
        json={
            "expected_revision": revision,
            "format_version": 5,
            "knowledge_mode": "full",
            "confirmed_include_originals": True,
        },
    )
    assert archived.status_code == 200
    with ZipFile(BytesIO(archived.content)) as archive:
        assert len(archive.namelist()) == 8 and "rag.json" in archive.namelist()
        assert (
            json.loads(archive.read("rag.json"))["answers"][0]["evidence"][0]["view"]["text"]
            is None
        )
    copied = client.post(
        "/api/v1/projects/import",
        content=archived.content,
        headers={"Content-Type": "application/zip"},
    )
    assert copied.status_code == 201
    restored = client.get(f"/api/v1/projects/{copied.json()['project']['id']}/rag/answers").json()[
        "items"
    ][0]
    assert restored["record"]["id"] != answer["record"]["id"]
    assert restored["record"]["provenance"] == "imported_unverified"
    assert restored["current_evidence"][0]["view"]["evidence"]["validity"] == "available"
    assert len(client.model_payloads) == 1
