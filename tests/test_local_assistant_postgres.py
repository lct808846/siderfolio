"""Deterministic local-model races against disposable PostgreSQL databases."""

import threading
from uuid import uuid4

import pytest
from test_rag_postgres import pg_client as pg_client

from astroagent.conversation_schemas import TurnRequest
from astroagent.errors import ServiceError
from astroagent.local_model_schemas import LocalPreferenceUpdate
from astroagent.local_model_service import LocalModelService

pytestmark = pytest.mark.postgres


def prepare(client, text="查询M45的坐标"):
    from astroagent.main import app

    service = app.state.conversation_service
    service.local_titles.close()
    settings = service.repository.settings.model_copy(
        update={"local_model_enabled": True, "local_model_digest": "a" * 64}
    )
    assistant = LocalModelService(service, settings)
    service.local_titles = assistant
    assistant.store.initialize()
    assistant.store.update_preferences(
        LocalPreferenceUpdate(expected_revision=0, enabled=True, auto_titles=True)
    )
    conversation = service.repository.create("新会话")
    turn = service.repository.reserve(
        conversation["id"],
        TurnRequest(message=text, client_request_id=str(uuid4()), expected_revision=0),
    )
    turn.execution_status = "completed"
    service.repository.finish(turn)
    return service.repository, assistant, turn


def gate(assistant, monkeypatch, failure=False):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def generate_title(text):
        calls.append(text)
        entered.set()
        assert release.wait(5), "test must release inference"
        if failure:
            raise ServiceError(504, "local_model_timeout", "synthetic timeout")
        return "M45坐标查询", {}

    monkeypatch.setattr(assistant.client, "generate_title", generate_title)
    return entered, release, calls


@pytest.mark.parametrize(
    "change", ["none", "rename", "rename_back", "delete", "disable", "cancel", "move"]
)
def test_automatic_title_preserves_user_actions(pg_client, monkeypatch, change):
    repo, assistant, turn = prepare(pg_client)
    baseline = repo.detail(turn.conversation_id)["title"]
    entered, release, calls = gate(assistant, monkeypatch)
    completion = assistant.schedule_title(turn)
    try:
        assert entered.wait(5)
        if change in ("rename", "rename_back"):
            repo.rename(turn.conversation_id, "人工标题")
            if change == "rename_back":
                repo.rename(turn.conversation_id, baseline)
        elif change == "delete":
            repo.delete(turn.conversation_id)
        elif change == "disable":
            assistant.store.update_preferences(
                LocalPreferenceUpdate(expected_revision=1, enabled=False, auto_titles=False)
            )
        elif change == "cancel":
            assistant.settle_title(completion, wait=False)
        elif change == "move":
            project = pg_client.post("/api/v1/projects", json={"name": "合成移动项目"}).json()
            current = repo.detail(turn.conversation_id)
            response = pg_client.put(
                f"/api/v1/projects/{project['id']}/conversations/{turn.conversation_id}",
                json={
                    "expected_revision": 0,
                    "expected_conversation_revision": current["revision"],
                    "expected_metadata_revision": current["metadata_revision"],
                    "expected_source_project_id": None,
                },
            )
            assert response.status_code == 200, response.text
    finally:
        release.set()
    assert completion.done.wait(5)
    assert len(calls) == 1
    if change == "delete":
        with pytest.raises(ServiceError):
            repo.detail(turn.conversation_id)
        return
    expected = "M45坐标查询" if change == "none" else "人工标题" if change == "rename" else baseline
    assert repo.detail(turn.conversation_id)["title"] == expected
    state = assistant.store.get(completion.task_id)
    assert state["title_applied"] is (change == "none")
    assert state["state"] == (
        "completed" if change == "none" else "skipped" if change == "cancel" else "superseded"
    )


def test_failed_title_preserves_baseline_without_remote_fallback(pg_client, monkeypatch):
    repo, assistant, turn = prepare(pg_client)
    baseline = repo.detail(turn.conversation_id)["title"]
    entered, release, calls = gate(assistant, monkeypatch, failure=True)
    completion = assistant.schedule_title(turn)
    assert entered.wait(5)
    release.set()
    assert completion.done.wait(5)
    assert repo.detail(turn.conversation_id)["title"] == baseline
    assert assistant.store.get(completion.task_id)["state"] == "failed"
    assert len(calls) == 1 and pg_client.model_payloads == []


def test_duplicate_automatic_request_never_replays_inference(pg_client, monkeypatch):
    _, assistant, turn = prepare(pg_client)
    entered, release, calls = gate(assistant, monkeypatch)
    first = assistant.schedule_title(turn)
    assert entered.wait(5)
    second = assistant.schedule_title(turn)
    release.set()
    assert first.done.wait(5) and second.done.wait(5)
    assert len(calls) == 1
    assert len(assistant.store.latest_title(turn.conversation_id)) == 1


def test_restart_marks_inflight_task_interrupted_without_replay(pg_client, monkeypatch):
    repo, assistant, turn = prepare(pg_client)
    entered, release, calls = gate(assistant, monkeypatch)
    completion = assistant.schedule_title(turn)
    assert entered.wait(5)
    assistant.close()
    release.set()
    replacement = LocalModelService(assistant.conversations, assistant.settings)
    try:
        assert replacement.store.get(completion.task_id)["state"] == "interrupted"
        assert not replacement.store.get(completion.task_id)["title_applied"]
        assert repo.detail(turn.conversation_id)["title"] != "M45坐标查询"
        assert len(calls) == 1 and replacement.tasks.empty()
    finally:
        replacement.close()


def test_automatic_prefix_is_bounded_and_does_not_cut_identifiers(pg_client):
    message = "请整理M45的Gaia查询需求。" + "背景说明" * 600 + "最终目标改为NGC 884，半径8角分。"
    _, assistant, turn = prepare(pg_client, message)
    source = assistant.store.title_source(turn.conversation_id)
    text = source[2]
    assert len(text) <= 2000 and len(text.encode()) <= 4096
    assert "NGC 884" not in text and len(text) < len(message)


def test_stale_tab_cannot_overwrite_manual_title_during_inference(pg_client, monkeypatch):
    repo, assistant, turn = prepare(pg_client)
    entered, release, _ = gate(assistant, monkeypatch)
    completion = assistant.schedule_title(turn)
    try:
        assert entered.wait(5)
        root = f"/api/v1/conversations/{turn.conversation_id}"
        original = pg_client.get(root).json()
        first = pg_client.patch(
            root,
            json={"title": "人工优先", "expected_metadata_revision": original["metadata_revision"]},
        )
        assert first.status_code == 200
        stale = pg_client.patch(
            root,
            json={"title": "旧标签页", "expected_metadata_revision": original["metadata_revision"]},
        )
        assert stale.status_code == 409
    finally:
        release.set()
    assert completion.done.wait(5)
    assert repo.detail(turn.conversation_id)["title"] == "人工优先"


@pytest.mark.parametrize(
    "message", ["x " * 999 + "65225812899613312", "前" * 1363 + " NGC 884 END"]
)
def test_cut_prefix_never_exposes_a_partial_identifier(pg_client, message):
    _, assistant, turn = prepare(pg_client, message)
    source = assistant.store.title_source(turn.conversation_id)
    assert source[3]
    assert len(source[2]) <= 2000 and len(source[2].encode()) <= 4096
    assert not source[2].rstrip().endswith(("65", "NGC 88"))


def test_disabled_model_keeps_rule_title_without_inference(pg_client, monkeypatch):
    repo, assistant, turn = prepare(pg_client)
    baseline = repo.detail(turn.conversation_id)["title"]
    assistant.settings = assistant.settings.model_copy(update={"local_model_enabled": False})

    def forbidden(*args):
        pytest.fail("disabled assistance must not call a model")

    monkeypatch.setattr(assistant.client, "generate_title", forbidden)
    assert assistant.schedule_title(turn) is None
    assert repo.detail(turn.conversation_id)["title"] == baseline
