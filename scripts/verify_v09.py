"""显式--run的合成集成检查；临时库/进程内HTTP，不替代TCP、浏览器或真实文献验收。"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("未执行检查；发布前由用户明确使用--run。")
    started_at = datetime.now(UTC).isoformat()
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    def git_value(*arguments):
        try:
            result = subprocess.run(
                ["git", "--no-optional-locks", *arguments],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    import sqlite3

    import httpx
    import requests
    from fastapi.testclient import TestClient

    from astroagent import __version__

    if int(__version__.split(".")[0]) >= 1:
        parser.error(
            "此入口为旧SQLite基线；V1.0请使用隔离的PostgreSQL集成与独立RAG评估计划，禁止连接日常库。"
        )
    from astroagent.api import conversations, workflows
    from astroagent.main import app
    from astroagent.schemas import ChatResponse, GaiaQuery, LiteratureQuery
    from scripts.export_samples import synthetic_request
    from scripts.synthetic_services import SyntheticAds, SyntheticGaia, SyntheticSimbad

    class Agent:
        def converse(self, *args, **kwargs):
            return ChatResponse.model_validate(synthetic_request()["snapshot"])

    def executor():
        def execute(family, parameters):
            if family == "gaia":
                return SyntheticGaia().query(GaiaQuery(**parameters))
            if family == "ads":
                return SyntheticAds().search(LiteratureQuery(**parameters))
            return SyntheticSimbad().query(parameters["object_name"])

        return execute

    def blocked(*args, **kwargs):
        raise AssertionError("Synthetic integration must not access external HTTP")

    report = {
        "version": __version__,
        "kind": "synthetic_inprocess_integration",
        "external_services": False,
        "real_literature_evaluation": False,
        "started_at": started_at,
        "commit": git_value("rev-parse", "HEAD"),
        "working_tree_status": git_value("status", "--porcelain", "--untracked-files=normal"),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "sqlite": sqlite3.sqlite_version,
        },
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scenarios_sha256": hashlib.sha256(
            (root / "docs/development/v0.9.0/integration_cases.json").read_bytes()
        ).hexdigest(),
        "results": [],
    }
    payload = b"# Synthetic reference\nA binary cluster fixture only; no observational claim.\n"

    def check(name, condition):
        report["results"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)

    try:
        with tempfile.TemporaryDirectory(prefix="astroagent-v09-") as temporary:
            with (
                patch.dict(
                    "os.environ",
                    {
                        "ASTROAGENT_DATA_DIR": temporary,
                        "ASTROAGENT_ALLOWED_HOSTS": '["testserver","localhost","127.0.0.1"]',
                    },
                ),
                patch.object(conversations, "get_agent", lambda: Agent()),
                patch.object(workflows, "get_executor", executor),
                patch.object(requests.Session, "request", blocked),
                patch.object(httpx.HTTPTransport, "handle_request", blocked),
                TestClient(app) as client,
            ):

                def call(method, path, body=None, expected=(200, 201), **kwargs):
                    response = client.request(method, path, json=body, **kwargs)
                    if response.status_code not in expected:
                        raise AssertionError(f"Unexpected HTTP {response.status_code}: {path}")
                    return response.json() if response.status_code != 204 else None

                project = call("POST", "/api/v1/projects", {"name": "V0.9 synthetic integration"})
                base = f"/api/v1/projects/{project['id']}"

                def revision():
                    return call("GET", base)["revision"]

                conversation = call("POST", "/api/v1/conversations", {"title": "Synthetic query"})
                conversation_path = f"/api/v1/conversations/{conversation['id']}"
                turn = call(
                    "POST",
                    conversation_path + "/turns",
                    {
                        "message": "Synthetic result, not an observation",
                        "client_request_id": str(uuid4()),
                        "expected_revision": 0,
                    },
                )

                def membership(remove=False):
                    c = call("GET", conversation_path)
                    return call(
                        "DELETE" if remove else "PUT",
                        base + f"/conversations/{c['id']}",
                        {
                            "expected_revision": revision(),
                            "expected_conversation_revision": c["revision"],
                            "expected_metadata_revision": c["metadata_revision"],
                            "expected_source_project_id": project["id"] if remove else None,
                        },
                        expected=(204,) if remove else (200, 201),
                    )

                membership()
                response = client.post(
                    base + "/documents",
                    files={"file": ("synthetic.md", payload, "text/markdown")},
                    data={
                        "options": json.dumps(
                            {"expected_revision": revision(), "client_request_id": str(uuid4())}
                        )
                    },
                )
                response.raise_for_status()
                document = response.json()["document"]
                check("synthetic_document_ready", document["state"] == "ready")
                evidence = call(
                    "POST", base + "/knowledge/answers", {"query": "binary cluster", "limit": 5}
                )["hits"][0]["evidence"]
                snapshot = call(
                    "POST",
                    base + "/snapshots",
                    {
                        "expected_revision": revision(),
                        "conversation_id": conversation["id"],
                        "turn_id": turn["turn_id"],
                        "name": "Synthetic saved result",
                    },
                )
                run = call(
                    "POST",
                    base + "/workflows",
                    {
                        "expected_revision": revision(),
                        "name": "Synthetic Gaia workflow",
                        "template_id": "gaia_field",
                        "parameters": {
                            "input_mode": "coordinates",
                            "ra_deg": 56.75,
                            "dec_deg": 24.12,
                            "radius_arcmin": 5,
                            "limit": 100,
                        },
                    },
                )
                executed = call(
                    "POST",
                    base + f"/workflows/{run['id']}/execute",
                    {
                        "expected_revision": run["revision"],
                        "client_request_id": str(uuid4()),
                        "confirmed": True,
                    },
                )
                check("synthetic_workflow_completed", executed["run"]["state"] == "succeeded")
                requests_by_type, links = {}, {}
                for kind, identifier in (
                    ("snapshot", snapshot["id"]),
                    ("conversation_turn", turn["turn_id"]),
                    ("workflow_run", run["id"]),
                ):
                    body = {
                        "expected_revision": revision(),
                        "client_request_id": str(uuid4()),
                        "target_type": kind,
                        "target_id": identifier,
                        "evidence_id": evidence["id"],
                        "note": "Original synthetic user note",
                        "confirmed": True,
                    }
                    result = call("POST", base + "/links", body)
                    requests_by_type[kind], links[kind] = body, result["detail"]["link"]
                    check(f"create_{kind}", result["detail"]["link"]["state"] == "active")
                check("overview_all_types", call("GET", base + "/overview")["link_count"] == 3)
                first = links["snapshot"]
                changed = call(
                    "PATCH",
                    base + f"/links/{first['id']}",
                    {
                        "expected_revision": revision(),
                        "expected_link_revision": first["revision"],
                        "note": "Changed user note",
                    },
                )
                replay = call("POST", base + "/links", requests_by_type["snapshot"])
                check(
                    "replay_original_response_and_latest_revision",
                    replay["replayed"]
                    and replay["detail"]["link"]["note"] == "Original synthetic user note"
                    and replay["detail"]["latest_revision"] == changed["link"]["revision"],
                )
                conflict = client.post(
                    base + "/links",
                    json={**requests_by_type["snapshot"], "note": "Different body"},
                )
                check(
                    "same_key_changed_body_conflict",
                    conflict.status_code == 409 and call("GET", base + "/links")["total"] == 3,
                )
                stale_patch = client.patch(
                    base + f"/links/{first['id']}",
                    json={
                        "expected_revision": revision(),
                        "expected_link_revision": first["revision"],
                        "note": "Must not overwrite",
                    },
                )
                current_link = call("GET", base + f"/links/{first['id']}")
                check(
                    "stale_link_revision_rejected",
                    stale_patch.status_code == 409
                    and current_link["link"]["note"] == "Changed user note",
                )
                duplicate_body = {
                    **requests_by_type["snapshot"],
                    "expected_revision": revision(),
                    "client_request_id": str(uuid4()),
                    "note": "Do not overwrite",
                }
                duplicate = call("POST", base + "/links", duplicate_body)
                check(
                    "duplicate_pair_preserves_note",
                    duplicate["duplicate"]
                    and duplicate["detail"]["link"]["note"] == "Changed user note",
                )
                foreign = call("POST", "/api/v1/projects", {"name": "Foreign synthetic project"})
                rejected = client.post(
                    f"/api/v1/projects/{foreign['id']}/links",
                    json={
                        **requests_by_type["snapshot"],
                        "expected_revision": 0,
                        "client_request_id": str(uuid4()),
                    },
                )
                check("cross_project_404", rejected.status_code == 404)
                for legacy_format in (1, 2, 3):
                    old_export = client.post(
                        base + "/archive",
                        json={
                            "expected_revision": revision(),
                            "format_version": legacy_format,
                            "knowledge_mode": "metadata",
                        },
                    )
                    check(
                        f"format{legacy_format}_refuses_link_history", old_export.status_code == 409
                    )
                    empty_export = client.post(
                        f"/api/v1/projects/{foreign['id']}/archive",
                        json={
                            "expected_revision": 0,
                            "format_version": legacy_format,
                            "knowledge_mode": "metadata",
                        },
                    )
                    empty_export.raise_for_status()
                    empty_import = call(
                        "POST",
                        "/api/v1/projects/import",
                        expected=(201,),
                        content=empty_export.content,
                        headers={"Content-Type": "application/zip"},
                    )
                    check(
                        f"format{legacy_format}_imports_without_links",
                        call("GET", f"/api/v1/projects/{empty_import['project']['id']}/links")[
                            "total"
                        ]
                        == 0,
                    )
                full = client.post(
                    base + "/archive",
                    json={
                        "expected_revision": revision(),
                        "format_version": 4,
                        "knowledge_mode": "full",
                        "confirmed_include_originals": True,
                    },
                )
                full.raise_for_status()
                with ZipFile(BytesIO(full.content)) as archive:
                    members = {name: archive.read(name) for name in archive.namelist()}
                original_members = dict(members)
                check(
                    "fixed_seven_members",
                    set(members)
                    == {
                        "manifest.json",
                        "project.json",
                        "conversations.json",
                        "snapshots.json",
                        "workflows.json",
                        "knowledge.json",
                        "links.json",
                    },
                )
                restored = call(
                    "POST",
                    "/api/v1/projects/import",
                    expected=(201,),
                    content=full.content,
                    headers={"Content-Type": "application/zip"},
                )
                restored_links = call("GET", f"/api/v1/projects/{restored['project']['id']}/links")[
                    "items"
                ]
                check(
                    "full_restore_new_ids_and_unverified",
                    len(restored_links) == 3
                    and all(
                        v["link"]["id"] not in {old["id"] for old in links.values()}
                        and v["link"]["state"] == "active"
                        and v["link"]["provenance"] == "imported_unverified"
                        for v in restored_links
                    ),
                )
                metadata = client.post(
                    base + "/archive",
                    json={
                        "expected_revision": revision(),
                        "format_version": 4,
                        "knowledge_mode": "metadata",
                    },
                )
                metadata.raise_for_status()
                copied = call(
                    "POST",
                    "/api/v1/projects/import",
                    expected=(201,),
                    content=metadata.content,
                    headers={"Content-Type": "application/zip"},
                )
                copied_base = f"/api/v1/projects/{copied['project']['id']}"
                check(
                    "metadata_links_unavailable",
                    all(
                        item["link"]["state"] == "evidence_unavailable"
                        for item in call("GET", copied_base + "/links")["items"]
                    ),
                )
                copied_doc = call("GET", copied_base + "/documents")[0]
                copied_detail = call("GET", copied_base + f"/documents/{copied_doc['id']}")
                response = client.post(
                    copied_base + f"/documents/{copied_doc['id']}/versions",
                    files={"file": ("synthetic.md", payload, "text/markdown")},
                    data={
                        "options": json.dumps(
                            {
                                "expected_revision": copied_detail["project_revision"],
                                "client_request_id": str(uuid4()),
                                "restore_version_id": copied_detail["current_version_id"],
                            }
                        )
                    },
                )
                response.raise_for_status()
                check(
                    "same_hash_restores_original_link_evidence",
                    all(
                        item["link"]["state"] == "active"
                        for item in call("GET", copied_base + "/links")["items"]
                    ),
                )
                corrupted = json.loads(members["links.json"])
                corrupted["links"][0]["evidence_text_sha256"] = "0" * 64
                members["links.json"] = json.dumps(corrupted, ensure_ascii=False).encode()
                manifest = json.loads(members["manifest.json"])
                manifest["files"]["links.json"] = {
                    "bytes": len(members["links.json"]),
                    "sha256": hashlib.sha256(members["links.json"]).hexdigest(),
                }
                members["manifest.json"] = json.dumps(manifest).encode()
                stream = BytesIO()
                with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
                    for name, data in members.items():
                        archive.writestr(name, data)
                before = len(call("GET", "/api/v1/projects"))
                response = client.post(
                    "/api/v1/projects/import",
                    content=stream.getvalue(),
                    headers={"Content-Type": "application/zip"},
                )
                check(
                    "corrupt_link_atomic_rejection",
                    response.status_code == 422 and len(call("GET", "/api/v1/projects")) == before,
                )
                for case in (
                    "duplicate_link",
                    "duplicate_request",
                    "foreign_target",
                    "unknown_member",
                ):
                    modified = dict(original_members)
                    if case == "unknown_member":
                        modified["unexpected.json"] = b"{}"
                    else:
                        content = json.loads(modified["links.json"])
                        if case == "duplicate_link":
                            content["links"].append(content["links"][0])
                        elif case == "duplicate_request":
                            content["requests"].append(content["requests"][0])
                        else:
                            content["links"][0]["target_id"] = str(uuid4())
                        modified["links.json"] = json.dumps(content, ensure_ascii=False).encode()
                        manifest = json.loads(modified["manifest.json"])
                        manifest["files"]["links.json"] = {
                            "bytes": len(modified["links.json"]),
                            "sha256": hashlib.sha256(modified["links.json"]).hexdigest(),
                        }
                        modified["manifest.json"] = json.dumps(manifest).encode()
                    stream = BytesIO()
                    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
                        for name, data in modified.items():
                            archive.writestr(name, data)
                    response = client.post(
                        "/api/v1/projects/import",
                        content=stream.getvalue(),
                        headers={"Content-Type": "application/zip"},
                    )
                    check(
                        f"{case}_atomic_rejection",
                        response.status_code == 422
                        and len(call("GET", "/api/v1/projects")) == before,
                    )
                call(
                    "DELETE",
                    base + f"/links/{first['id']}",
                    {
                        "expected_revision": revision(),
                        "expected_link_revision": changed["link"]["revision"],
                        "confirmed": True,
                    },
                    expected=(204,),
                )
                replay = call("POST", base + "/links", requests_by_type["snapshot"])
                check(
                    "unlink_replay_does_not_recreate",
                    not replay["detail"]["present"] and call("GET", base + "/links")["total"] == 2,
                )
                membership(remove=True)
                membership()
                turn_link = call("GET", base + f"/links/{links['conversation_turn']['id']}")
                check(
                    "move_back_does_not_revive",
                    turn_link["link"]["state"] == "target_unavailable"
                    and turn_link["link"]["target_invalidated"],
                )
                call(
                    "DELETE",
                    base + f"/documents/{document['id']}",
                    {"expected_revision": revision(), "confirmed": True},
                    expected=(204,),
                )
                workflow_link = call("GET", base + f"/links/{links['workflow_run']['id']}")
                check(
                    "document_delete_hides_original",
                    workflow_link["link"]["state"] == "evidence_unavailable"
                    and workflow_link["evidence"] is None,
                )
                call(
                    "DELETE",
                    base + f"/workflows/{run['id']}",
                    {"expected_revision": executed["run"]["revision"], "confirmed": True},
                    expected=(204,),
                )
                check(
                    "workflow_delete_tombstone",
                    call("GET", base + f"/links/{links['workflow_run']['id']}")["link"][
                        "target_invalidated"
                    ],
                )
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["failure"] = type(exc).__name__ + ": " + str(exc)
    report["finished_at"] = datetime.now(UTC).isoformat()
    output = (
        Path(__file__).resolve().parents[1]
        / f"docs/test-records/v{__version__}/integration"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    output.mkdir(parents=True)
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
