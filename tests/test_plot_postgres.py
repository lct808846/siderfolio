"""V1.3 plotting flow with isolated PostgreSQL and synthetic model proposals."""

import hashlib
import json
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from test_rag_postgres import pg_client as pg_client

pytestmark = pytest.mark.postgres

SCRIPT = """import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
with open("/input/data.csv", newline="") as f:
    rows = list(csv.DictReader(f))
plt.scatter([float(r["x"]) for r in rows], [float(r["y"]) for r in rows])
plt.savefig("/output/figure.png")
plt.savefig("/output/figure.pdf")
"""


def test_plot_lifecycle_confirmations_and_export(pg_client, monkeypatch):
    import astroagent.plot_service as module

    proposal = {
        "engine": "python",
        "chart": "scatter",
        "title": "Synthetic scatter",
        "columns": ["x", "y"],
        "axes": {"x": "x", "y": "y"},
        "filters": [],
        "explanation": "Synthetic data",
        "warnings": [],
        "script": SCRIPT,
    }
    calls = []

    def generate(request, info, data):
        calls.append((request.model_id, info["rows"], data))
        return proposal, {"total_tokens": 5}

    monkeypatch.setattr(module, "generate", generate)
    status = pg_client.get("/api/v1/setup/plotting").json()
    assert status["storage_ready"] is False
    assert pg_client.post("/api/v1/setup/plotting", json={}).status_code == 422
    assert pg_client.post("/api/v1/setup/plotting", json={"confirm_create_tables": True}).json()[
        "storage_ready"
    ]
    response = pg_client.post("/api/v1/projects", json={"name": "Synthetic plotting"})
    assert response.status_code == 201, response.text
    root = "/api/v1/projects/" + response.json()["id"] + "/plotting"
    dataset_id, plan_id, run_id = (str(uuid4()) for _ in range(3))
    raw = b"x,y\n1,2\n2,4\n3,3\n"
    uploaded = pg_client.put(
        root + f"/datasets/{dataset_id}/upload", files={"file": ("data.csv", raw, "text/csv")}
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["rows"] == 3
    preview = pg_client.get(root + f"/datasets/{dataset_id}/preview")
    assert preview.status_code == 200 and preview.json()["sample_rows"] == 3
    plan_data = {
        "dataset_id": dataset_id,
        "model_id": "synthetic",
        "engine": "python",
        "question": "scatter x y",
    }
    assert pg_client.put(root + f"/plans/{plan_id}", json=plan_data).status_code == 422
    assert calls == []
    plan_data["confirm_external_data"] = True
    result = pg_client.put(root + f"/plans/{plan_id}", json=plan_data)
    assert result.status_code == 200 and result.json()["state"] == "completed", result.text
    assert len(calls) == 1
    assert pg_client.put(root + f"/plans/{plan_id}", json=plan_data).json()["state"] == "completed"
    assert len(calls) == 1
    assert pg_client.put(root + f"/runs/{run_id}", json={"plan_id": plan_id}).status_code == 422
    result = pg_client.put(
        root + f"/runs/{run_id}", json={"plan_id": plan_id, "confirm_execute": True}
    )
    assert result.status_code == 200 and result.json()["state"] == "completed", result.text
    replay = pg_client.put(
        root + f"/runs/{run_id}", json={"plan_id": plan_id, "confirm_execute": True}
    )
    assert replay.status_code == 200 and replay.json()["id"] == run_id
    files = ["figure.png", "figure.pdf", "data.csv", "script.py", "manifest.json"]
    downloaded = {
        name: pg_client.get(root + f"/runs/{run_id}/files/{name}").content for name in files
    }
    assert downloaded["figure.png"].startswith(b"\x89PNG\r\n\x1a\n")
    assert downloaded["figure.pdf"].startswith(b"%PDF-")
    assert downloaded["script.py"] == SCRIPT.encode()
    manifest = json.loads(downloaded["manifest.json"])
    for name in files[:-1]:
        assert manifest["files"][name]["sha256"] == hashlib.sha256(downloaded[name]).hexdigest()
    bundle = pg_client.post(root + f"/runs/{run_id}/bundle", json={"files": files})
    assert bundle.status_code == 200, bundle.text
    with ZipFile(BytesIO(bundle.content)) as archive:
        assert {name: archive.read(name) for name in files} == downloaded

    project_root = root.removesuffix("/plotting")
    revision = pg_client.get(project_root).json()["revision"]
    assert (
        pg_client.post(
            project_root + "/archive",
            json={
                "expected_revision": revision,
                "format_version": 5,
            },
        ).status_code
        == 409
    )
    exported = pg_client.post(
        project_root + "/archive",
        json={
            "expected_revision": revision,
            "format_version": 6,
        },
    )
    assert exported.status_code == 200, exported.text
    with ZipFile(BytesIO(exported.content)) as archive:
        assert "plotting.json" in archive.namelist()
    restored = pg_client.post(
        "/api/v1/projects/import",
        content=exported.content,
        headers={"Content-Type": "application/zip"},
    )
    assert restored.status_code == 201, restored.text
    restored_root = "/api/v1/projects/" + restored.json()["project"]["id"] + "/plotting"
    restored_page = pg_client.get(restored_root).json()
    assert len(restored_page["datasets"]) == 1
    restored_plan = next(op for op in restored_page["operations"] if op["kind"] == "plan")
    assert restored_plan["id"] != plan_id and restored_plan["imported"] is True
    restored_run = next(op for op in restored_page["operations"] if op["kind"] == "run")
    assert restored_run["id"] != run_id and restored_run["imported"] is True
    assert (
        pg_client.get(restored_root + f"/runs/{restored_run['id']}/files/figure.png").content
        == downloaded["figure.png"]
    )
    assert (
        pg_client.put(
            restored_root + "/runs/" + str(uuid4()),
            json={
                "plan_id": restored_plan["id"],
                "confirm_execute": True,
            },
        ).status_code
        == 409
    )
