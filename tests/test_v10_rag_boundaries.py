"""PostgreSQL RAG safety checks with synthetic evidence and a model double."""

import hashlib
import json
import os
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from test_rag_postgres import build, preview, project_with_document

pytest_plugins = ("test_rag_postgres",)
pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "response",
    [
        '{"answer":"unsupported [E99]","citations":["E99"],"insufficient_evidence":false}',
        '{"answer":"unsupported [E1]","citations":[],"insufficient_evidence":false}',
        '{"answer":"<script>alert(1)</script> [E1]","citations":["E1"],'
        '"insufficient_evidence":false}',
        '{"answer":"untrusted https://example.invalid [E1]","citations":["E1"],'
        '"insufficient_evidence":false}',
        '{"answer":"false claim [E1]","citations":["E1"],"insufficient_evidence":true}',
    ],
)
def test_unverified_model_output_is_not_exposed(pg_client, monkeypatch, response):
    client = pg_client
    root, _ = project_with_document(client)
    build(client, root)
    view = preview(client, root)

    class Model:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def create(self, **kwargs):
            return SimpleNamespace(
                model="synthetic",
                choices=[
                    SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=response))
                ],
            )

    monkeypatch.setattr("openai.OpenAI", Model)
    answer = client.post(
        root + "/rag/answers",
        json={
            "client_request_id": str(uuid4()),
            "preview_id": view["id"],
            "confirmation_token": view["confirmation_token"],
            "confirmed": True,
        },
    )
    assert answer.status_code == 200
    record = answer.json()["record"]
    assert record["state"] == "insufficient_evidence"
    assert record["citation_labels"] == []
    assert "unsupported" not in record["answer"]
    assert "<script>" not in record["answer"]
    assert "https://" not in record["answer"]


def test_no_results_and_cross_project_scope_do_not_send(pg_client):
    client = pg_client
    root, document = project_with_document(client)
    empty = client.post(root + "/rag/previews", json={"question": "unlikelynosuchevidencetoken"})
    assert empty.status_code == 200
    assert empty.json()["status"] == "no_results" and not empty.json()["evidence"]
    denied = client.post(
        root + "/rag/answers",
        json={
            "client_request_id": str(uuid4()),
            "preview_id": empty.json()["id"],
            "confirmation_token": empty.json()["confirmation_token"],
            "confirmed": True,
        },
    )
    assert denied.status_code in (409, 422)
    other = client.post("/api/v1/projects", json={"name": "Another isolated project"}).json()
    isolated = client.post(
        f"/api/v1/projects/{other['id']}/rag/previews",
        json={"question": "binary cluster", "document_ids": [document["id"]]},
    )
    assert isolated.status_code in (404, 422)
    assert not client.model_payloads


@pytest.mark.parametrize("failure", ["invalid_json", "truncated", "timeout"])
def test_model_failures_do_not_expose_unverified_text(pg_client, monkeypatch, failure):
    client = pg_client
    root, _ = project_with_document(client)
    build(client, root)
    view = preview(client, root)

    class Model:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def create(self, **kwargs):
            if failure == "timeout":
                raise TimeoutError("synthetic timeout")
            value = (
                "NOT_VERIFIED_PRIVATE_TEXT"
                if failure == "invalid_json"
                else (
                    '{"answer":"NOT_VERIFIED_PRIVATE_TEXT [E1]",'
                    '"citations":["E1"],"insufficient_evidence":false}'
                )
            )
            return SimpleNamespace(
                model="synthetic",
                choices=[
                    SimpleNamespace(
                        finish_reason="length" if failure == "truncated" else "stop",
                        message=SimpleNamespace(content=value),
                    )
                ],
            )

    monkeypatch.setattr("openai.OpenAI", Model)
    answer = client.post(
        root + "/rag/answers",
        json={
            "client_request_id": str(uuid4()),
            "preview_id": view["id"],
            "confirmation_token": view["confirmation_token"],
            "confirmed": True,
        },
    )
    assert answer.status_code in (200, 503)
    assert "NOT_VERIFIED_PRIVATE_TEXT" not in answer.text
    if answer.status_code == 200:
        assert answer.json()["record"]["state"] in ("failed", "insufficient_evidence")


@pytest.mark.parametrize(
    "case", ["unknown_member", "duplicate_answer", "invalid_label", "bad_hash"]
)
def test_corrupt_format5_archive_is_rejected_atomically(pg_client, case):
    client = pg_client
    root, _ = project_with_document(client)
    build(client, root)
    view = preview(client, root)
    answer = client.post(
        root + "/rag/answers",
        json={
            "client_request_id": str(uuid4()),
            "preview_id": view["id"],
            "confirmation_token": view["confirmation_token"],
            "confirmed": True,
        },
    )
    assert answer.status_code == 200 and answer.json()["record"]["state"] == "completed"
    revision = client.get(root).json()["revision"]
    exported = client.post(
        root + "/archive",
        json={
            "expected_revision": revision,
            "format_version": 5,
            "knowledge_mode": "full",
            "confirmed_include_originals": True,
        },
    )
    assert exported.status_code == 200
    with ZipFile(BytesIO(exported.content)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    rag = json.loads(files["rag.json"])
    if case == "unknown_member":
        files["unexpected.json"] = b"{}"
    elif case == "duplicate_answer":
        rag["answers"].append(rag["answers"][0])
    elif case == "invalid_label":
        rag["answers"][0]["citation_labels"] = ["E99"]
    else:
        rag["answers"][0]["evidence"][0]["view"]["evidence"]["text_sha256"] = "0" * 64
    if case != "unknown_member":
        files["rag.json"] = json.dumps(rag, ensure_ascii=False).encode()
        manifest = json.loads(files["manifest.json"])
        manifest["files"]["rag.json"] = {
            "bytes": len(files["rag.json"]),
            "sha256": hashlib.sha256(files["rag.json"]).hexdigest(),
        }
        files["manifest.json"] = json.dumps(manifest).encode()
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    before = len(client.get("/api/v1/projects").json())
    imported = client.post(
        "/api/v1/projects/import",
        content=stream.getvalue(),
        headers={"Content-Type": "application/zip"},
    )
    assert imported.status_code == 422
    assert len(client.get("/api/v1/projects").json()) == before


def test_index_request_is_idempotent_and_changed_body_conflicts(pg_client):
    client = pg_client
    root, _ = project_with_document(client)
    revision = client.get(root).json()["revision"]
    request = {"expected_revision": revision, "client_request_id": str(uuid4()), "confirmed": True}
    first = client.post(root + "/rag/indexes", json=request)
    assert first.status_code == 200 and first.json()["state"] == "ready"
    replay = client.post(root + "/rag/indexes", json=request)
    assert replay.status_code == 200 and replay.json()["id"] == first.json()["id"]
    changed = client.post(root + "/rag/indexes", json={**request, "confirmed": False})
    assert changed.status_code in (409, 422)
    assert len(client.get(root + "/rag/status").json()["indexes"]) == 1


def test_expired_preview_never_calls_model(pg_client):
    client = pg_client
    root, _ = project_with_document(client)
    build(client, root)
    view = preview(client, root)
    repo = client.rag_service.repo
    with repo.connection() as db, repo.transaction(db):
        db.execute(
            "UPDATE rag_previews SET record=jsonb_set(record::jsonb,"
            "'{expires_at}',?::jsonb)::text WHERE id=?",
            ('"2000-01-01T00:00:00+00:00"', view["id"]),
        )
    response = client.post(
        root + "/rag/answers",
        json={
            "client_request_id": str(uuid4()),
            "preview_id": view["id"],
            "confirmation_token": view["confirmation_token"],
            "confirmed": True,
        },
    )
    assert response.status_code == 409
    assert not client.model_payloads


@pytest.mark.parametrize("content_type", ["json", "bodyless"])
def test_cancel_preview_deletes_it_and_prevents_send(pg_client, content_type):
    client = pg_client
    root, _ = project_with_document(client)
    build(client, root)
    view = preview(client, root)
    path = root + "/rag/previews/" + view["id"]
    invalid = client.request("DELETE", path, content=b"unexpected")
    assert invalid.status_code == 415
    result = client.request("DELETE", path, **({"json": {}} if content_type == "json" else {}))
    assert result.status_code == 204
    response = client.post(
        root + "/rag/answers",
        json={
            "client_request_id": str(uuid4()),
            "preview_id": view["id"],
            "confirmation_token": view["confirmation_token"],
            "confirmed": True,
        },
    )
    assert response.status_code == 409
    assert not client.model_payloads


@pytest.mark.skipif(
    os.getenv("ASTROAGENT_RUN_LARGE_ACCEPTANCE") != "1",
    reason="explicit opt-in for a 256 MiB logical PostgreSQL payload",
)
def test_postgres_logical_storage_limit_preserves_original(pg_client):
    client = pg_client
    root, document = project_with_document(client)
    original = document["current_version_id"]
    revision = client.get(root).json()["revision"]
    repo = client.rag_service.repo
    with repo.connection() as db, repo.transaction(db):
        db.execute("SET LOCAL statement_timeout='120s'")
        db.execute(
            "INSERT INTO knowledge_versions (id,document_id,project_id,record,content) "
            "SELECT ?,document_id,project_id,record,convert_to(repeat('x',?), 'UTF8') "
            "FROM knowledge_versions WHERE id=?",
            (str(uuid4()), 256 * 1024**2, original),
        )
        assert repo._used(db) >= 256 * 1024**2
    response = client.post(
        root + f"/documents/{document['id']}/versions",
        files={"file": ("replacement.md", b"# replacement", "text/markdown")},
        data={
            "options": json.dumps(
                {"expected_revision": revision, "client_request_id": str(uuid4())}
            )
        },
    )
    assert response.status_code == 409
    assert client.get(root).json()["revision"] == revision
    preserved = client.get(root + f"/documents/{document['id']}/versions/{original}/content")
    assert preserved.content == b"# Reference\nBinary cluster environment synthetic fixture.\n"


def test_metadata_archive_preserves_history_without_original_or_model_calls(pg_client):
    client = pg_client
    root, _ = project_with_document(client)
    build(client, root)
    view = preview(client, root)
    answer = client.post(
        root + "/rag/answers",
        json={
            "client_request_id": str(uuid4()),
            "preview_id": view["id"],
            "confirmation_token": view["confirmation_token"],
            "confirmed": True,
        },
    )
    assert answer.status_code == 200 and answer.json()["record"]["state"] == "completed"
    revision = client.get(root).json()["revision"]
    exported = client.post(
        root + "/archive",
        json={"expected_revision": revision, "format_version": 5, "knowledge_mode": "metadata"},
    )
    assert exported.status_code == 200
    restored = client.post(
        "/api/v1/projects/import",
        content=exported.content,
        headers={"Content-Type": "application/zip"},
    )
    assert restored.status_code == 201
    new_root = "/api/v1/projects/" + restored.json()["project"]["id"]
    history = client.get(new_root + "/rag/answers").json()["items"]
    assert len(history) == 1 and history[0]["record"]["provenance"] == "imported_unverified"
    assert history[0]["current_evidence"][0]["view"]["text"] is None
    assert history[0]["current_evidence"][0]["view"]["evidence"]["validity"] != "available"
    assert client.get(new_root + "/rag/status").json()["active_index_id"] is None
    assert len(client.model_payloads) == 1


def test_deleted_answer_history_still_blocks_old_format_export(pg_client):
    client = pg_client
    root, _ = project_with_document(client)
    build(client, root)
    view = preview(client, root)
    body = {
        "client_request_id": str(uuid4()),
        "preview_id": view["id"],
        "confirmation_token": view["confirmation_token"],
        "confirmed": True,
    }
    answer = client.post(root + "/rag/answers", json=body)
    assert answer.status_code == 200
    identifier = answer.json()["record"]["id"]
    assert (
        client.request(
            "DELETE", root + "/rag/answers/" + identifier, json={"confirmed": True}
        ).status_code
        == 204
    )
    revision = client.get(root).json()["revision"]
    for version in (1, 2, 3, 4):
        response = client.post(
            root + "/archive", json={"expected_revision": revision, "format_version": version}
        )
        assert response.status_code == 409
    assert client.post(root + "/rag/answers", json=body).status_code == 409
    assert len(client.model_payloads) == 1


def test_second_process_lock_is_rejected_without_disturbing_first(pg_client):
    from astroagent.errors import ServiceError
    from astroagent.postgres import PostgresRepository

    client = pg_client
    root, _ = project_with_document(client)
    second = PostgresRepository(client.rag_service.repo.settings)
    with pytest.raises(ServiceError) as caught:
        second.initialize()
    assert caught.value.error.code == "database_in_use"
    assert client.get(root).status_code == 200


def test_lost_lock_session_reacquires_lock_before_business_access(pg_client):
    client = pg_client
    root, _ = project_with_document(client)
    client.rag_service.repo.session.close()
    response = client.get(root)
    assert response.status_code == 200
    assert not client.rag_service.repo.session.closed


def test_lost_lock_session_refuses_access_while_another_process_holds_lock(pg_client):
    from astroagent.postgres import PostgresRepository

    client = pg_client
    root, _ = project_with_document(client)
    client.rag_service.repo.session.close()
    second = PostgresRepository(client.rag_service.repo.settings)
    second.initialize()
    try:
        response = client.get(root)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "database_unavailable"
    finally:
        second.close()
    assert client.get(root).status_code == 200


def test_unknown_database_schema_is_refused_without_change(pg_client):
    from astroagent.errors import ServiceError
    from astroagent.postgres import PostgresRepository

    repo = pg_client.rag_service.repo
    repo.close()
    with repo.connection() as db, repo.transaction(db):
        db.execute("UPDATE astroagent_meta SET value=? WHERE key='schema_version'", ("999",))
    other = PostgresRepository(repo.settings)
    with pytest.raises(ServiceError) as caught:
        other.initialize()
    assert caught.value.error.code == "database_schema_unsupported"
    with repo.connection() as db:
        assert (
            db.execute("SELECT value FROM astroagent_meta WHERE key='schema_version'").fetchone()[0]
            == "999"
        )
