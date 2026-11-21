"""V1.7 queue and ownership checked with real identity and disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from test_identity_postgres import account, post
from test_identity_postgres import identity_client as identity_client

from astroagent.api import compute
from astroagent.compute_io import write
from astroagent.compute_schemas import binary_template
from astroagent.compute_tasks import Dispatcher

pytestmark = [pytest.mark.identity, pytest.mark.postgres]
SCHEMA = Path(__file__).resolve().parents[1] / "scripts" / "compute_schema.sql"


@pytest.fixture
def laboratory(identity_client, tmp_path, monkeypatch):
    client = identity_client
    monkeypatch.setenv("ASTROAGENT_COMPUTE_ENABLED", "1")
    from astroagent import compute_tasks

    spool = tmp_path / "compute-spool"
    spool.mkdir()
    (spool / "heartbeat").touch()
    monkeypatch.setattr(compute_tasks, "spool", lambda: spool)
    with client.store.connect() as db:
        db.execute(SCHEMA.read_text(encoding="utf-8"))
    account(client)
    return client, spool, Dispatcher(client.store)


def project(client, name="Compute acceptance"):
    response = post(client, "projects", {"name": name})
    assert response.status_code == 201
    value = response.json()
    return f"projects/{value['id']}/compute-tasks", value


def draft(client, base, name="Binary orbit"):
    response = post(client, base, {"name": name, "parameters": binary_template().model_dump()})
    assert response.status_code == 201
    assert response.json()["state"] == "draft"
    return response.json()


def confirmation(task, **updates):
    return {
        "request_id": str(uuid4()),
        "expected_revision": task["revision"],
        "parameter_sha256": task["parameter_sha256"],
        "confirmed": True,
        **updates,
    }


def detail(client, base, task):
    response = client.get(f"/api/v1/{base}/{task['id']}")
    assert response.status_code == 200
    return response.json()


def test_queue_capacity_retries_claim_cancellation_and_late_result(laboratory):
    client, spool, dispatcher = laboratory
    base, _ = project(client)
    tasks = [draft(client, base, f"Run {i}") for i in range(3)]
    urls = [f"{base}/{task['id']}/confirm" for task in tasks]
    first = confirmation(tasks[0])
    rejected = post(client, urls[0], {**first, "parameter_sha256": "f" * 64})
    assert rejected.status_code == 409
    assert detail(client, base, tasks[0])["state"] == "draft"
    assert post(client, urls[0], first).json()["state"] == "queued"
    duplicate = post(client, urls[0], first).json()
    assert sum(event["state"] == "queued" for event in duplicate["events"]) == 1
    assert post(client, urls[1], confirmation(tasks[1])).json()["state"] == "queued"
    limited = post(client, urls[2], confirmation(tasks[2]))
    assert (limited.status_code, limited.json()["error"]["code"]) == (409, "compute_queue_limit")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: dispatcher.tick(), range(2)))
    running = detail(client, base, tasks[0])
    assert running["state"] == "running"
    assert sum(event["state"] == "running" for event in running["events"]) == 1
    assert detail(client, base, tasks[1])["state"] == "queued"
    pending_path = f"{base}/{tasks[1]['id']}"
    assert post(client, pending_path + "/cancel", None).json()["state"] == "cancelled"

    attempt = spool / running["attempt_id"].replace("-", "")
    assert (attempt / "input").exists()
    running_path = f"{base}/{running['id']}"
    assert post(client, running_path + "/cancel", None).json()["state"] == "cancelling"
    write(attempt / "done", "succeeded")
    dispatcher.tick()
    assert detail(client, base, running)["state"] == "cancelled"
    assert client.get(f"/api/v1/{running_path}/result").status_code == 409
    dispatcher.tick()
    assert not attempt.exists()


def test_worker_lease_expiration_fences_late_attempt(laboratory):
    client, spool, dispatcher = laboratory
    base, _ = project(client)
    entry = draft(client, base)
    assert post(client, f"{base}/{entry['id']}/confirm", confirmation(entry)).status_code == 200
    dispatcher.tick()
    dispatcher.tick()
    running = detail(client, base, entry)
    attempt = spool / running["attempt_id"].replace("-", "")
    (spool / "heartbeat").unlink()
    with client.store.connect() as db:
        db.execute("UPDATE public.compute_tasks SET lease_until=now()-interval '1 second'")
    dispatcher.tick()
    assert detail(client, base, entry)["state"] == "interrupted"
    assert (attempt / "cancel").exists()
    write(attempt / "done", "succeeded")
    dispatcher.tick()
    assert not attempt.exists()
    assert detail(client, base, entry)["state"] == "interrupted"


def test_compute_proposal_is_a_preview_and_project_delete_removes_records(laboratory, monkeypatch):
    client, _, _ = laboratory
    base, owner_project = project(client)
    body = {"description": "仅包含本次提交的合成描述"}
    outputs = iter(
        (
            AIMessage(content='{"clarification":"请补充三维速度。"}'),
            AIMessage(content='{"parameters":' + binary_template().model_dump_json() + "}"),
            AIMessage(content='{"parameters":{"samples":1}}'),
        )
    )

    class Model:
        def invoke(self, messages):
            assert len(messages) == 2 and messages[-1].content == body["description"]
            return next(outputs)

    monkeypatch.setattr(compute, "chat_model", lambda *args, **kwargs: Model())
    for expected in ("clarification", "parameters"):
        response = post(client, base + "/describe", body)
        assert response.status_code == 200
        assert response.json()[expected]
    assert post(client, base + "/describe", body).status_code == 502
    assert client.get(f"/api/v1/{base}").json()["tasks"] == []
    entry = draft(client, base)
    response = post(
        client,
        f"projects/{owner_project['id']}",
        {"expected_revision": owner_project["revision"], "confirm": True},
        method="DELETE",
    )
    assert response.status_code == 204
    with client.store.connect() as db:
        assert (
            db.execute("SELECT 1 FROM public.compute_tasks WHERE id=%s", (entry["id"],)).fetchone()
            is None
        )
