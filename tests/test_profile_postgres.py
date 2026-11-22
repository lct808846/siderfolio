"""Profile APIs through real authentication and disposable tenant databases."""

import io
import json
from uuid import uuid4

import pytest
from PIL import Image
from test_identity_postgres import ORIGIN, account, post
from test_identity_postgres import identity_client as identity_client

pytestmark = [pytest.mark.identity, pytest.mark.postgres]


def png(color="green"):
    output = io.BytesIO()
    Image.new("RGB", (25, 40), color).save(output, format="PNG")
    return output.getvalue()


def headers(client):
    return {"Origin": ORIGIN, "X-CSRF-Token": client.get("/api/v1/auth/csrf").json()["csrf_token"]}


def upload(client, raw, **extra):
    return client.post(
        "/api/v1/profile/avatar",
        files={"file": ("synthetic.png", raw, "image/png")},
        headers=headers(client),
        **extra,
    )


def test_avatar_upload_sanitization_replacement_and_account_isolation(identity_client):
    client = identity_client
    account(client)
    assert client.get("/api/v1/auth/avatar").status_code == 404
    assert (
        client.post("/api/v1/profile/avatar", files={"file": ("a.png", png())}).status_code == 403
    )
    response = upload(client, png() + b"synthetic-private-tail")
    assert response.status_code == 200, response.text
    url = response.json()["avatar_url"]
    result = client.get(url)
    assert result.status_code == 200 and result.headers["content-type"] == "image/png"
    assert b"synthetic-private-tail" not in result.content
    assert "no-store" in result.headers["cache-control"]
    with Image.open(io.BytesIO(result.content)) as image:
        assert image.size == (256, 256)
    first_image = result.content
    assert upload(client, b"<svg><script>synthetic</script></svg>").status_code == 422
    assert client.get(url).content == first_image
    changed = upload(client, png("blue"))
    assert changed.status_code == 200
    assert changed.json()["avatar_url"] != url
    assert client.get(changed.json()["avatar_url"]).content != first_image
    first_cookie = client.cookies.get("astroagent_session")
    other = client.fresh()
    other.store = client.store
    account(other, "second@example.org")
    assert other.get(url).status_code == 404
    assert (
        other.request("DELETE", "/api/v1/profile/avatar", headers=headers(other)).status_code == 200
    )
    assert client.get(url).status_code == 200
    assert (
        client.request("DELETE", "/api/v1/profile/avatar", headers=headers(client)).status_code
        == 200
    )
    assert client.get(url).status_code == 404
    assert client.get("/api/v1/auth/session").json()["user"]["avatar_url"] == ""
    assert client.store.authenticate(first_cookie)


def test_avatar_stream_size_and_anonymous_boundary(identity_client):
    client = identity_client
    assert client.get("/api/v1/profile/summary").status_code == 401
    assert upload(client, png()).status_code == 401
    account(client)
    assert upload(client, b"x" * (5 * 1024 * 1024 + 1)).status_code == 413
    assert client.get("/api/v1/auth/avatar").status_code == 404


def test_existing_identity_schema_adds_avatar_storage_without_losing_accounts(identity_client):
    client = identity_client
    account(client)
    before = client.get("/api/v1/auth/session").json()["user"]
    with client.store.connect() as db:
        db.execute("DROP TABLE public.auth_avatars")
        db.execute("ALTER TABLE public.auth_users DROP COLUMN avatar_updated_at")
    client.store.check()
    after = client.get("/api/v1/auth/session").json()["user"]
    assert after["id"] == before["id"] and after["email"] == before["email"]
    assert upload(client, png()).status_code == 200


def test_profile_summary_counts_private_assets_and_known_model_usage(identity_client):
    client = identity_client
    account(client)
    conversation = post(client, "conversations", {"title": "Synthetic profile counts"}).json()
    project = post(client, "projects", {"name": "Synthetic private assets"}).json()
    user = client.store.authenticate(client.cookies.get("astroagent_session"))
    service = client.identity.tenants.for_user(user)
    with service.repository.connection() as db, service.repository.transaction(db):
        for index, state in enumerate(["completed", "failed", "running"]):
            record = {
                "model": "synthetic-chat",
                "execution_status": state,
                "received_at": "2026-11-16T00:00:00Z",
                "response": {
                    "results": [{}] if state == "completed" else [],
                    "literature_results": [],
                    "gaia_results": [],
                },
            }
            db.execute(
                "INSERT INTO turns(id,conversation_id,ordinal,request_id,request_hash,"
                "state,record,size_bytes,reserved_bytes) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    conversation["id"],
                    index + 1,
                    str(uuid4()),
                    "synthetic",
                    state,
                    json.dumps(record),
                    0,
                    0,
                ),
            )
        for state in ["completed", "queued"]:
            record = {
                "state": state,
                "created_at": "2026-11-16T01:00:00Z",
                "request": {"model_id": "synthetic-plot"},
                "model_usage": {"input_tokens": 10, "output_tokens": 5},
            }
            db.execute(
                "INSERT INTO plot_operations(id,project_id,kind,state,record) VALUES (?,?,?,?,?)",
                (str(uuid4()), project["id"], "plan", state, json.dumps(record)),
            )
        for state in ["completed", "skipped", "queued"]:
            record = {
                "state": state,
                "model": "synthetic-local",
                "created_at": "2026-11-16T02:00:00Z",
                "usage": {"prompt_eval_count": 3, "eval_count": 2} if state == "completed" else {},
            }
            db.execute(
                "INSERT INTO local_assistant_tasks(id,kind,state,record) VALUES (?,?,?,?)",
                (str(uuid4()), "automatic_title", state, json.dumps(record)),
            )
    response = client.get("/api/v1/profile/summary")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["workspace"]["conversations_count"] == 1
    assert value["workspace"]["projects_count"] == 1
    assert value["workspace"]["turns_count"] == 3
    assert value["workspace"]["completed_turns"] == 1
    assert value["workspace"]["failed_turns"] == 1
    assert value["workspace"]["simbad_queries"] == 1
    assert value["total_model_calls"] == 4
    assert value["known_total_tokens"] == 20
    models = {m["model"]: m for m in value["models"]}
    assert models["synthetic-chat"]["calls"] == 2
    assert models["synthetic-plot"]["plot_calls"] == 1
    assert models["synthetic-local"]["local_calls"] == 1
    assert models["synthetic-chat"]["total_tokens"] is None
    other = client.fresh()
    other.store = client.store
    account(other, "second@example.org")
    isolated = other.get("/api/v1/profile/summary")
    assert isolated.status_code == 200, isolated.text
    assert isolated.json()["total_model_calls"] == 0
    assert isolated.json()["workspace"]["conversations_count"] == 0
    assert "synthetic-chat" not in isolated.text
