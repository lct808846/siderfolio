"""V0.7 固定流程：合成数据端到端、幂等与项目归档恢复。"""

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from test_projects import project

pytest_plugins = ("test_projects",)


def test_schema2_migration_backup_and_failure_rollback(tmp_path, monkeypatch):
    from astroagent.config import LocalSettings
    from astroagent.conversations import ConversationRepository
    from astroagent.errors import ServiceError

    settings = LocalSettings(_env_file=None, data_dir=tmp_path)
    repo = ConversationRepository(settings)
    with sqlite3.connect(repo.path) as db:
        repo._migrate_v1(db)
        repo._migrate_v2(db)
        db.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
            ("old-id", "旧会话", "2026-01-01", "2026-01-01", 0, 0),
        )
        db.commit()
    original = repo._migrate_v3

    def broken(db):
        original(db)
        raise sqlite3.OperationalError("synthetic migration failure")

    monkeypatch.setattr(repo, "_migrate_v3", broken)
    with pytest.raises(ServiceError):
        repo.initialize()
    with sqlite3.connect(repo.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT title FROM conversations").fetchone()[0] == "旧会话"
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='workflows'").fetchall()
    assert list(tmp_path.glob("migration-v3-*.sqlite3"))
    monkeypatch.setattr(repo, "_migrate_v3", original)
    repo.initialize()
    try:
        with sqlite3.connect(repo.path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 3
            assert db.execute("SELECT title FROM conversations").fetchone()[0] == "旧会话"
    finally:
        repo.close()


@pytest.mark.parametrize(
    ("template", "parameters", "family"),
    [
        (
            "gaia_field",
            {
                "input_mode": "coordinates",
                "ra_deg": 56.75,
                "dec_deg": 24.12,
                "radius_arcmin": 5,
                "limit": 100,
                "plots": ["parallax_histogram"],
            },
            "gaia",
        ),
        ("ads_evidence", {"query": "synthetic", "rows": 1, "start": 0, "sort": "date_desc"}, "ads"),
    ],
)
def test_flow_archive_and_idempotency(client, monkeypatch, template, parameters, family):
    from astroagent.api import projects, workflows

    monkeypatch.setattr(workflows, "get_executor", projects.get_executor)
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    response = client.post(
        base + "/workflows",
        json={
            "expected_revision": 0,
            "template_id": template,
            "name": "合成验收",
            "parameters": parameters,
        },
    )
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["state"] == "pending" and not client.calls
    request = {
        "expected_revision": run["revision"],
        "client_request_id": str(uuid4()),
        "confirmed": True,
    }
    path = base + "/workflows/" + run["id"]
    response = client.post(path + "/execute", json=request)
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    assert run["state"] == "succeeded", run
    assert [c[0] for c in client.calls] == [family]
    assert run["outputs"]
    for output in run["outputs"]:
        item = client.get(path + "/outputs/" + output["id"])
        assert item.status_code == 200
        assert hashlib.sha256(item.content).hexdigest() == output["sha256"]
    replay = client.post(path + "/execute", json=request)
    assert replay.status_code == 200, replay.text
    assert [c[0] for c in client.calls] == [family]
    current = client.get(base).json()
    old_format = client.post(
        base + "/archive", json={"expected_revision": current["revision"], "format_version": 1}
    )
    assert old_format.status_code == 409
    bundle = client.post(
        base + "/archive", json={"expected_revision": current["revision"], "format_version": 2}
    )
    assert bundle.status_code == 200, bundle.text
    damaged = BytesIO(bundle.content)
    with ZipFile(damaged, "a") as archive:
        archive.writestr("unexpected.json", b"{}")
    before = len(client.get("/api/v1/projects").json())
    refused = client.post(
        "/api/v1/projects/import",
        content=damaged.getvalue(),
        headers={"Content-Type": "application/zip"},
    )
    assert refused.status_code == 422
    assert len(client.get("/api/v1/projects").json()) == before
    with ZipFile(BytesIO(bundle.content)) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    payload = json.loads(members["workflows.json"])
    payload["outputs"][0]["content"] = "Y29ycnVwdA=="
    members["workflows.json"] = json.dumps(payload, ensure_ascii=False).encode()
    manifest = json.loads(members["manifest.json"])
    manifest["files"]["workflows.json"] = {
        "bytes": len(members["workflows.json"]),
        "sha256": hashlib.sha256(members["workflows.json"]).hexdigest(),
    }
    members["manifest.json"] = json.dumps(manifest, ensure_ascii=False).encode()
    damaged = BytesIO()
    with ZipFile(damaged, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    refused = client.post(
        "/api/v1/projects/import",
        content=damaged.getvalue(),
        headers={"Content-Type": "application/zip"},
    )
    assert refused.status_code == 422
    assert len(client.get("/api/v1/projects").json()) == before
    restored = client.post(
        "/api/v1/projects/import",
        content=bundle.content,
        headers={"Content-Type": "application/zip"},
    )
    assert restored.status_code == 201, restored.text
    restored_id = restored.json()["project"]["id"]
    flows = client.get(f"/api/v1/projects/{restored_id}/workflows").json()
    assert len(flows) == 1 and flows[0]["provenance"] == "imported_unverified"
    imported_path = f"/api/v1/projects/{restored_id}/workflows/{flows[0]['id']}"
    imported = client.get(imported_path).json()
    assert imported["id"] != run["id"]
    assert {o["sha256"] for o in imported["outputs"]} == {o["sha256"] for o in run["outputs"]}
    for output in imported["outputs"]:
        content = client.get(imported_path + "/outputs/" + output["id"])
        assert content.status_code == 200
        assert hashlib.sha256(content.content).hexdigest() == output["sha256"]
    assert [c[0] for c in client.calls] == [family]


@pytest.mark.parametrize("cell", ["=1+1", "+2", "@cmd", "-cmd", "\tformula"])
def test_archive_csv_rejects_spreadsheet_formulas(cell):
    from astroagent.workflow_io import safe_csv

    with pytest.raises(ValueError):
        safe_csv(("\ufeffheader\n" + cell + "\n").encode("utf-8"))


def test_name_and_coordinates_are_mutually_exclusive(client):
    p = project(client)
    r = client.post(
        f"/api/v1/projects/{p['id']}/workflows",
        json={
            "expected_revision": 0,
            "template_id": "gaia_field",
            "name": "错误输入",
            "parameters": {
                "input_mode": "name",
                "object_name": "M45",
                "ra_deg": 56.75,
                "radius_arcmin": 5,
                "limit": 10,
            },
        },
    )
    assert r.status_code == 422
    assert not client.calls


def test_workflow_quota_rejects_51st_without_side_effect(client):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    payload = {
        "template_id": "ads_evidence",
        "parameters": {"query": "synthetic", "rows": 1, "start": 0, "sort": "date_desc"},
    }
    for index in range(50):
        revision = client.get(base).json()["revision"]
        result = client.post(
            base + "/workflows", json={**payload, "name": str(index), "expected_revision": revision}
        )
        assert result.status_code == 201, result.text
    revision = client.get(base).json()["revision"]
    result = client.post(
        base + "/workflows", json={**payload, "name": "overflow", "expected_revision": revision}
    )
    assert result.status_code == 409
    assert len(client.get(base + "/workflows").json()) == 50
    assert not client.calls


def test_attempt_and_operation_limits_preserve_failed_history(client, monkeypatch):
    from astroagent.schemas import ErrorInfo
    from astroagent.workflow_service import StepProduct, WorkflowService

    monkeypatch.setattr(
        WorkflowService,
        "perform",
        lambda *args: StepProduct(error=ErrorInfo(code="synthetic", message="模拟失败")),
    )
    p = project(client)
    base = f"/api/v1/projects/{p['id']}/workflows"
    run = client.post(
        base,
        json={
            "expected_revision": 0,
            "template_id": "ads_evidence",
            "name": "配额",
            "parameters": {"query": "synthetic", "rows": 1, "start": 0, "sort": "date_desc"},
        },
    ).json()
    path = base + "/" + run["id"] + "/execute"
    for index in range(20):
        result = client.post(
            path,
            json={
                "expected_revision": run["revision"],
                "client_request_id": str(uuid4()),
                "confirmed": True,
            },
        )
        assert result.status_code == 200, result.text
        run = result.json()["run"]
        assert run["state"] == "failed"
        attempts = run["steps"][0]["attempts"]
        assert len(attempts) == min(index + 1, 5)
    assert run["error"]["code"] == "workflow_attempt_limit"
    assert len(run["operations"]) == 20
    result = client.post(
        path,
        json={
            "expected_revision": run["revision"],
            "client_request_id": str(uuid4()),
            "confirmed": True,
        },
    )
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "workflow_operation_limit"
    assert not client.calls


def test_failed_name_resolution_never_queries_gaia(client, monkeypatch):
    from astroagent.api import workflows
    from astroagent.schemas import ErrorInfo
    from scripts.synthetic_services import SyntheticSimbad

    calls = []

    def factory():
        def execute(family, params):
            calls.append(family)
            result = SyntheticSimbad().query(params["object_name"])
            result.status = "not_found"
            result.data = None
            result.error = ErrorInfo(code="object_not_found", message="未找到")
            return result

        return execute

    monkeypatch.setattr(workflows, "get_executor", factory)
    p = project(client)
    path = f"/api/v1/projects/{p['id']}/workflows"
    created = client.post(
        path,
        json={
            "expected_revision": 0,
            "template_id": "gaia_field",
            "name": "名称失败",
            "parameters": {
                "input_mode": "name",
                "object_name": "unknown",
                "radius_arcmin": 5,
                "limit": 10,
            },
        },
    )
    assert created.status_code == 201, created.text
    run = created.json()
    result = client.post(
        path + "/" + run["id"] + "/execute",
        json={
            "expected_revision": run["revision"],
            "client_request_id": str(uuid4()),
            "confirmed": True,
        },
    )
    assert result.status_code == 200
    assert result.json()["run"]["state"] == "failed"
    assert calls == ["simbad"]


def test_resume_reuses_successful_query_after_export_failure(client, monkeypatch):
    from astroagent.api import projects, workflows
    from astroagent.schemas import ErrorInfo
    from astroagent.workflow_service import StepProduct, WorkflowService

    monkeypatch.setattr(workflows, "get_executor", projects.get_executor)
    original = WorkflowService.perform
    failures = []

    def fail_once(self, run, step_id, actual, executor):
        if step_id == "export_results" and not failures:
            failures.append(True)
            return StepProduct(error=ErrorInfo(code="synthetic", message="导出失败"))
        return original(self, run, step_id, actual, executor)

    monkeypatch.setattr(WorkflowService, "perform", fail_once)
    p = project(client)
    path = f"/api/v1/projects/{p['id']}/workflows"
    created = client.post(
        path,
        json={
            "expected_revision": 0,
            "template_id": "ads_evidence",
            "name": "恢复检查",
            "parameters": {"query": "synthetic", "rows": 1, "start": 0, "sort": "date_desc"},
        },
    )
    assert created.status_code == 201, created.text
    run = created.json()
    path += "/" + run["id"] + "/execute"
    first = client.post(
        path,
        json={
            "expected_revision": run["revision"],
            "client_request_id": str(uuid4()),
            "confirmed": True,
        },
    ).json()["run"]
    assert first["state"] == "failed"
    assert [c[0] for c in client.calls] == ["ads"]
    second = client.post(
        path,
        json={
            "expected_revision": first["revision"],
            "client_request_id": str(uuid4()),
            "confirmed": True,
        },
    )
    assert second.status_code == 200, second.text
    resumed = second.json()["run"]
    assert resumed["state"] == "succeeded", resumed
    assert [c[0] for c in client.calls] == ["ads"]
    assert len(next(s for s in resumed["steps"] if s["id"] == "export_results")["attempts"]) == 2


def test_corrupt_checkpoint_blocks_resume(client, monkeypatch):
    from astroagent.api import projects, workflows
    from astroagent.schemas import ErrorInfo
    from astroagent.workflow_service import StepProduct, WorkflowService

    monkeypatch.setattr(workflows, "get_executor", projects.get_executor)
    original = WorkflowService.perform

    def fail_export(self, run, step_id, actual, executor):
        if step_id == "export_results":
            return StepProduct(error=ErrorInfo(code="synthetic", message="导出失败"))
        return original(self, run, step_id, actual, executor)

    monkeypatch.setattr(WorkflowService, "perform", fail_export)
    p = project(client)
    base = f"/api/v1/projects/{p['id']}/workflows"
    created = client.post(
        base,
        json={
            "expected_revision": 0,
            "template_id": "ads_evidence",
            "name": "损坏检查点",
            "parameters": {"query": "synthetic", "rows": 1, "start": 0, "sort": "date_desc"},
        },
    )
    run = created.json()
    path = base + "/" + run["id"] + "/execute"
    run = client.post(
        path,
        json={
            "expected_revision": run["revision"],
            "client_request_id": str(uuid4()),
            "confirmed": True,
        },
    ).json()["run"]
    assert run["state"] == "failed"
    repository = client.app.state.conversation_service.repository
    with repository.connection() as db, repository.transaction(db):
        db.execute("UPDATE workflow_outputs SET content=? WHERE run_id=?", (b"corrupt", run["id"]))
    result = client.post(
        path,
        json={
            "expected_revision": run["revision"],
            "client_request_id": str(uuid4()),
            "confirmed": True,
        },
    )
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "workflow_checkpoint_invalid"
    assert [c[0] for c in client.calls] == ["ads"]


def test_running_request_replay_and_conflict_do_not_repeat_query(client, monkeypatch):
    from astroagent.api import projects, workflows

    ready, release = threading.Event(), threading.Event()
    synthetic = projects.get_executor

    def factory():
        execute = synthetic()

        def waiting(family, parameters):
            ready.set()
            assert release.wait(15)
            return execute(family, parameters)

        return waiting

    monkeypatch.setattr(workflows, "get_executor", factory)
    p = project(client)
    base = f"/api/v1/projects/{p['id']}/workflows"
    run = client.post(
        base,
        json={
            "expected_revision": 0,
            "template_id": "ads_evidence",
            "name": "并发",
            "parameters": {"query": "synthetic", "rows": 1, "start": 0, "sort": "date_desc"},
        },
    ).json()
    path = base + "/" + run["id"] + "/execute"
    body = {
        "expected_revision": run["revision"],
        "client_request_id": str(uuid4()),
        "confirmed": True,
    }
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, path, json=body)
        try:
            assert ready.wait(10)
            assert client.post(path, json=body).status_code == 202
            conflict = client.post(path, json={**body, "expected_revision": 999})
            assert conflict.status_code == 409
        finally:
            release.set()
        result = pending.result(timeout=30)
    assert result.status_code == 200
    assert result.json()["run"]["state"] == "succeeded"
    assert [c[0] for c in client.calls] == ["ads"]


@pytest.mark.parametrize(
    ("template", "parameters", "failed_step"),
    [
        (
            "gaia_field",
            {"input_mode": "name", "object_name": "M45", "radius_arcmin": 5, "limit": 10},
            step,
        )
        for step in ("resolve_name", "query_gaia", "save_snapshot", "export_results")
    ]
    + [
        ("ads_evidence", {"query": "synthetic", "rows": 1, "start": 0, "sort": "date_desc"}, step)
        for step in ("query_ads", "evidence_table", "save_snapshot", "export_results")
    ],
)
def test_each_failed_step_can_resume_and_archive(
    client, monkeypatch, template, parameters, failed_step
):
    from astroagent.api import projects, workflows
    from astroagent.schemas import ErrorInfo
    from astroagent.workflow_service import StepProduct, WorkflowService

    monkeypatch.setattr(workflows, "get_executor", projects.get_executor)
    original = WorkflowService.perform
    failed = []

    def fail_once(self, run, step_id, actual, executor):
        if step_id == failed_step and not failed:
            failed.append(True)
            return StepProduct(error=ErrorInfo(code="synthetic", message="模拟故障"))
        return original(self, run, step_id, actual, executor)

    monkeypatch.setattr(WorkflowService, "perform", fail_once)
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    created = client.post(
        base + "/workflows",
        json={
            "expected_revision": 0,
            "template_id": template,
            "name": "失败恢复",
            "parameters": parameters,
        },
    )
    assert created.status_code == 201, created.text
    run = created.json()
    path = base + "/workflows/" + run["id"]
    result = client.post(
        path + "/execute",
        json={
            "expected_revision": run["revision"],
            "client_request_id": str(uuid4()),
            "confirmed": True,
        },
    )
    assert result.status_code == 200, result.text
    run = result.json()["run"]
    assert run["state"] == "failed", run
    prior_calls = list(client.calls)
    current = client.get(base).json()
    bundle = client.post(
        base + "/archive", json={"expected_revision": current["revision"], "format_version": 2}
    )
    assert bundle.status_code == 200, bundle.text
    restored = client.post(
        "/api/v1/projects/import",
        content=bundle.content,
        headers={"Content-Type": "application/zip"},
    )
    assert restored.status_code == 201, restored.text
    restored_project = restored.json()["project"]["id"]
    restored_flows = client.get(f"/api/v1/projects/{restored_project}/workflows").json()
    imported = restored_flows[0]
    assert imported["provenance"] == "imported_unverified"
    blocked = client.post(
        f"/api/v1/projects/{restored_project}/workflows/{imported['id']}/execute",
        json={
            "expected_revision": imported["revision"],
            "client_request_id": str(uuid4()),
            "confirmed": True,
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "workflow_imported_read_only"
    assert client.calls == prior_calls
    result = client.post(
        path + "/execute",
        json={
            "expected_revision": run["revision"],
            "client_request_id": str(uuid4()),
            "confirmed": True,
        },
    )
    assert result.status_code == 200, result.text
    resumed = result.json()["run"]
    assert resumed["state"] == "succeeded", resumed
    assert len(next(s for s in resumed["steps"] if s["id"] == failed_step)["attempts"]) == 2
    assert client.calls[: len(prior_calls)] == prior_calls
    if failed_step in ("save_snapshot", "export_results", "evidence_table"):
        assert client.calls == prior_calls


@pytest.mark.parametrize(
    ("template", "parameters", "interrupted_step"),
    [
        (
            "gaia_field",
            {"input_mode": "name", "object_name": "M45", "radius_arcmin": 5, "limit": 10},
            step,
        )
        for step in ("resolve_name", "query_gaia", "save_snapshot", "export_results")
    ]
    + [
        ("ads_evidence", {"query": "synthetic", "rows": 1, "start": 0, "sort": "date_desc"}, step)
        for step in ("query_ads", "evidence_table", "save_snapshot", "export_results")
    ],
)
def test_failure_between_step_execution_and_commit(
    client, monkeypatch, template, parameters, interrupted_step
):
    from astroagent.api import projects, workflows
    from astroagent.workflows import WorkflowRepository

    monkeypatch.setattr(workflows, "get_executor", projects.get_executor)
    original = WorkflowRepository.finish_step
    failures = []

    def fail_before_commit(self, project_id, run_id, attempt_id, product, elapsed):
        run = self.read(project_id, run_id)
        if run.current_step_id == interrupted_step and not failures:
            failures.append(True)
            raise RuntimeError("synthetic failure before commit")
        return original(self, project_id, run_id, attempt_id, product, elapsed)

    monkeypatch.setattr(WorkflowRepository, "finish_step", fail_before_commit)
    p = project(client)
    base = f"/api/v1/projects/{p['id']}/workflows"
    run = client.post(
        base,
        json={
            "expected_revision": 0,
            "name": "提交故障",
            "template_id": template,
            "parameters": parameters,
        },
    ).json()
    path = base + "/" + run["id"] + "/execute"
    response = client.post(
        path,
        json={
            "expected_revision": run["revision"],
            "client_request_id": str(uuid4()),
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    assert run["state"] == "interrupted", run
    step = next(s for s in run["steps"] if s["id"] == interrupted_step)
    assert step["attempts"][-1]["state"] == "interrupted"
    before = list(client.calls)
    response = client.post(
        path,
        json={
            "expected_revision": run["revision"],
            "client_request_id": str(uuid4()),
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    resumed = response.json()["run"]
    assert resumed["state"] == "succeeded", resumed
    assert [
        a["state"]
        for a in next(s for s in resumed["steps"] if s["id"] == interrupted_step)["attempts"]
    ] == ["interrupted", "succeeded"]
    if interrupted_step in ("save_snapshot", "export_results", "evidence_table"):
        assert client.calls == before
