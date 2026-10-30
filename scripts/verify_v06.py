"""项目真实 HTTP/恢复验收；--live 使用真实模型及三类数据源并产生用量。"""

import argparse
import hashlib
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4
from zipfile import ZipFile

from record_utils import ROOT, create_record_directory, runtime_metadata, write_report


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    out = create_record_directory("live-project-tests" if args.live else "acceptance-v06")
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        **runtime_metadata(),
        "command": ["scripts/verify_v06.py", *(["--live"] if args.live else [])],
        "data_kind": "real_queries" if args.live else "synthetic_not_observations",
        "checks": [],
        "servers": [],
    }
    process, logs = None, []
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    opener = build_opener(ProxyHandler({}))

    def request(path, body=None, method=None):
        binary = isinstance(body, bytes)
        data = (
            body
            if binary
            else json.dumps(body, ensure_ascii=False).encode()
            if body is not None
            else None
        )
        req = Request(
            base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/zip" if binary else "application/json"},
        )
        try:
            response = opener.open(req, timeout=300)
        except HTTPError as exc:
            response = exc
        with response:
            content = response.read()
            parsed = (
                json.loads(content)
                if response.headers.get_content_type() == "application/json"
                else content
            )
            return response.status, parsed

    def checked(name, fn):
        item = {"name": name, "passed": False}
        report["checks"].append(item)
        try:
            fn(item)
            item["passed"] = True
        except Exception as exc:
            item["error_type"] = type(exc).__name__
        print(name + (": passed" if item["passed"] else ": FAILED"), flush=True)

    def stop():
        nonlocal process
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        with socket.socket() as probe:
            probe.settimeout(2)
            code = probe.connect_ex(("127.0.0.1", port))
        report["servers"][-1].update(
            stopped=process.poll() is not None,
            exit_code=process.returncode,
            port_closed=code in (10061, 111, 61),
            connect_code=code,
        )
        if os.name == "nt":
            check = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "$ErrorActionPreference='Stop'; "
                    "@(Get-NetTCPConnection -State Listen | "
                    f"Where-Object LocalPort -eq {port}).Count",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            count = check.stdout.strip()
            report["servers"][-1].update(
                port_closed=check.returncode == 0 and count == "0",
                listener_count=int(count) if count.isdigit() else None,
                port_check="native Windows TCP listener table",
            )
        process = None

    def start(directory):
        nonlocal process
        environment = os.environ.copy()
        environment["ASTROAGENT_DATA_DIR"] = str(directory)
        environment["PYTHONIOENCODING"] = "utf-8"
        if not args.live:
            environment.update(DEEPSEEK_API_KEY="", ADS_API_TOKEN="")
        entry = "astroagent.main:app" if args.live else "scripts.fixture_server:app"
        log = (out / f"uvicorn-{len(logs)}.txt").open("x", encoding="utf-8")
        logs.append(log)
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            entry,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        report["servers"].append(
            {"pid": process.pid, "port": port, "command": command, "stopped": False}
        )
        for _ in range(160):
            if process.poll() is not None:
                raise RuntimeError("Server exited")
            try:
                if request("/health")[0] == 200:
                    return
            except (OSError, URLError):
                time.sleep(0.2)
        raise RuntimeError("Server readiness timeout")

    def detail(p):
        code, result = request(f"/api/v1/projects/{p['id']}")
        assert code == 200
        return result

    def conversation(message):
        code, c = request("/api/v1/conversations", {"title": "V0.6验收"})
        assert code == 201
        payload = {"message": message, "client_request_id": str(uuid4()), "expected_revision": 0}
        code, turn = request(f"/api/v1/conversations/{c['id']}/turns", payload)
        assert code == 200, turn
        return c, turn, payload

    def attach_and_save(p, c, t, name):
        revision = detail(p)["revision"]
        code, _ = request(
            f"/api/v1/projects/{p['id']}/conversations/{c['id']}",
            {
                "expected_revision": revision,
                "expected_conversation_revision": 1,
                "expected_metadata_revision": 0,
            },
            "PUT",
        )
        assert code == 200
        code, saved = request(
            f"/api/v1/projects/{p['id']}/snapshots",
            {
                "expected_revision": revision + 1,
                "conversation_id": c["id"],
                "turn_id": t["turn_id"],
                "name": name,
            },
        )
        assert code == 201, saved
        return saved

    def rerun(p, saved, family):
        payload = {
            "expected_revision": detail(p)["revision"],
            "family": family,
            "result_index": 0,
            "client_request_id": str(uuid4()),
            "confirmed": True,
        }
        code, result = request(
            f"/api/v1/projects/{p['id']}/snapshots/{saved['id']}/reruns", payload
        )
        return code, result, payload

    def snapshot(p, identifier):
        code, result = request(f"/api/v1/projects/{p['id']}/snapshots/{identifier}")
        assert code == 200
        return result

    def artifact(p, saved, name):
        def run(item):
            plots = (
                [
                    {"kind": k, "gaia_result_index": 0}
                    for k in ("proper_motion", "parallax_histogram", "observed_cmd")
                ]
                if saved["response"]["gaia_results"]
                else []
            )
            code, info = request(
                f"/api/v1/projects/{p['id']}/snapshots/{saved['id']}/artifacts", {"plots": plots}
            )
            item.update(http_status=code, artifact=info)
            assert code == 201
            code, data = request(info["download_url"])
            assert code == 200
            (out / f"{name}.zip").write_bytes(data)
            code, manifest = request(info["manifest_url"])
            assert code == 200
            with ZipFile(BytesIO(data)) as archive:
                assert json.loads(archive.read("snapshot.json")) == saved["response"]
                for entry in manifest["files"]:
                    content = archive.read(entry["path"])
                    assert (
                        len(content) == entry["bytes"]
                        and hashlib.sha256(content).hexdigest() == entry["sha256"]
                    )
                for figure in info["figures"]:
                    code, png = request(figure["url"])
                    assert code == 200
                    assert hashlib.sha256(png).hexdigest() == figure["sha256"]
                    assert any(
                        png == archive.read(n) for n in archive.namelist() if n.endswith(".png")
                    )
                    (out / f"{name}-{figure['kind']}.png").write_bytes(png)
            item["hashes_verified"] = True

        checked("artifact-" + name, run)

    try:
        with tempfile.TemporaryDirectory(prefix="astroagent-v06-") as data:
            try:
                start(Path(data) / "original")
                code, p = request(
                    "/api/v1/projects",
                    {"name": "V0.6真实项目验收" if args.live else "V0.6合成项目验收"},
                )
                assert code == 201
                saved_all = []
                for family, message in (
                    (
                        "gaia",
                        "查询ICRS赤经56.75度、赤纬24.12度、半径5角分内最近100个"
                        "Gaia DR3位置候选源，不估算距离。",
                    ),
                    ("ads", "检索ADS bibcode:2016A&A...595A...2G，取1篇，给出来源。"),
                    ("simbad", "请调用SIMBAD查询M45的坐标和类型，给出来源。"),
                ):
                    c, t, payload = conversation(message)
                    saved = attach_and_save(p, c, t, family + "-original")
                    saved_all.append(saved)

                    def query(item, t=t, payload=payload, family=family):
                        item.update(request=payload, turn=t)
                        assert t["response"]["status"] == "success"
                        if family == "gaia":
                            assert len(t["response"]["gaia_results"][0]["data"]) == 100

                    checked(family + "-query", query)
                    selected_family = family
                    code, r, replay = rerun(p, saved, selected_family)

                    def rerun_check(
                        item,
                        r=r,
                        replay=replay,
                        code=code,
                        saved=saved,
                        selected_family=selected_family,
                    ):
                        item.update(request=replay, rerun=r, http_status=code)
                        assert code == 200 and r["state"] == "completed"
                        result = snapshot(p, r["snapshot_id"])
                        item["snapshot"] = result
                        assert result["response"]["status"] == "success"
                        assert snapshot(p, saved["id"]) == saved
                        if selected_family == "gaia":
                            assert r["parameters"] == saved["response"]["gaia_results"][0]["query"]

                    checked(family + "-direct-rerun", rerun_check)

                    def idempotent(item, r=r, replay=replay, saved=saved):
                        code, repeat = request(
                            f"/api/v1/projects/{p['id']}/snapshots/{saved['id']}/reruns", replay
                        )
                        assert code == 200 and repeat == r
                        item["rerun_id"] = r["id"]

                    checked(family + "-idempotency", idempotent)
                    artifact(p, saved, family)
                    if r.get("snapshot_id"):
                        saved_all.append(snapshot(p, r["snapshot_id"]))
                if not args.live:
                    c, t, _ = conversation("检索ADS __wait_project__ 合成中断验收")
                    slow_snapshot = attach_and_save(p, c, t, "合成中断样本")
                    slow_payload = {
                        "expected_revision": detail(p)["revision"],
                        "family": "ads",
                        "result_index": 0,
                        "confirmed": True,
                        "client_request_id": str(uuid4()),
                    }
                    slow_path = f"/api/v1/projects/{p['id']}/snapshots/{slow_snapshot['id']}/reruns"

                    def slow():
                        try:
                            request(slow_path, slow_payload)
                        except OSError:
                            pass

                    worker = threading.Thread(target=slow, daemon=True)
                    worker.start()
                    for _ in range(100):
                        running = next(
                            (
                                r
                                for r in detail(p)["reruns"]
                                if r["client_request_id"] == slow_payload["client_request_id"]
                            ),
                            None,
                        )
                        if running:
                            break
                        time.sleep(0.05)
                    assert running and running["state"] == "running"
                    stop()
                    worker.join(timeout=5)
                    start(Path(data) / "original")

                    def interrupted(item):
                        code, value = request(slow_path, slow_payload)
                        item["rerun"] = value
                        assert code == 200 and value["state"] == "interrupted"
                        code, value_turn = request(
                            f"/api/v1/conversations/{value['conversation_id']}/turns/{value['turn_id']}"
                        )
                        assert code == 200 and value_turn["execution_status"] == "interrupted"

                    checked("restart-interrupted-rerun-no-replay", interrupted)
                    saved_all.append(slow_snapshot)
                if args.live:
                    for name, message in (
                        (
                            "name-chain",
                            "先查SIMBAD的M45坐标，再查询中心5角分内最近3个Gaia DR3位置候选源。",
                        ),
                        (
                            "three-tools",
                            "独立查询SIMBAD的M45坐标、Gaia DR3 source_id 5853498713190525696、"
                            "ADS bibcode:2016A&A...595A...2G，不假定三者关联。",
                        ),
                    ):
                        _, t, payload = conversation(message)
                        checked(
                            name, lambda item, t=t, payload=payload: query_live(item, t, payload)
                        )
                a, b = saved_all[:2]

                def compare(item):
                    path = f"/api/v1/projects/{p['id']}/comparisons"
                    body = {"left_id": a["id"], "right_id": b["id"], "match_identifiers": True}
                    code, first = request(path, body)
                    assert code == 200
                    assert request(path, body)[1] == first
                    item["comparison"] = first

                checked("deterministic-comparison", compare)
                before = detail(p)
                code, package = request(
                    f"/api/v1/projects/{p['id']}/archive",
                    {"expected_revision": before["revision"], "format_version": 1},
                )
                assert code == 200
                (out / "project.zip").write_bytes(package)

                def package_check(item):
                    with ZipFile(BytesIO(package)) as archive:
                        assert set(archive.namelist()) == {
                            "manifest.json",
                            "project.json",
                            "conversations.json",
                            "snapshots.json",
                        }
                        manifest = json.loads(archive.read("manifest.json"))
                        for name, entry in manifest["files"].items():
                            data = archive.read(name)
                            assert (
                                len(data) == entry["bytes"]
                                and hashlib.sha256(data).hexdigest() == entry["sha256"]
                            )
                    item.update(sha256=hashlib.sha256(package).hexdigest(), hashes_verified=True)

                checked("project-package-integrity", package_check)
                stop()
                start(Path(data) / "original")
                checked("restart-persistence", lambda item: assert_equal(item, detail(p), before))
                stop()
                start(Path(data) / "restored")
                code, restored = request("/api/v1/projects/import", package)

                def restore_check(item):
                    item.update(http_status=code, body=restored)
                    assert code == 201
                    assert restored["project"]["provenance"] == "imported_unverified"
                    assert restored["project"]["id"] != p["id"]
                    for old in saved_all:
                        new = snapshot(
                            restored["project"], restored["id_map"]["snapshots"][old["id"]]
                        )
                        assert new["response"] == old["response"] and new["sha256"] == old["sha256"]
                        assert new["provenance"] == "imported_unverified"

                checked("restore-fresh-database-all-snapshots", restore_check)
                first_restored = snapshot(
                    restored["project"], restored["id_map"]["snapshots"][a["id"]]
                )
                artifact(restored["project"], first_restored, "restored")

                def bad_package(item):
                    before = request("/api/v1/projects")[1]
                    assert request("/api/v1/projects/import", b"broken")[0] == 422
                    assert request("/api/v1/projects")[1] == before

                checked("bad-package-no-partial-write", bad_package)
                checked(
                    "restored-project-delete-retains-conversations",
                    lambda item: delete_preserves(item, restored["project"], request),
                )
            finally:
                stop()
    except Exception as exc:
        report["fatal_error_type"] = type(exc).__name__
    finally:
        stop()
        for log in logs:
            log.close()
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["outcome"] = (
            "passed"
            if report["checks"]
            and all(c["passed"] for c in report["checks"])
            and "fatal_error_type" not in report
            and all(s["stopped"] and s["port_closed"] for s in report["servers"])
            else "failed"
        )
        print("Report:", write_report(out, report), flush=True)
    return 0 if report["outcome"] == "passed" else 1


def query_live(item, turn, payload):
    item.update(request=payload, turn=turn)
    response = turn["response"]
    assert response["status"] == "success"
    assert response["results"] and response["gaia_results"]
    if payload["message"].startswith("先查"):
        source = response["results"][0]["data"]
        query = response["gaia_results"][0]["query"]
        assert source is not None
        assert math.isclose(source["ra_deg"], query["ra_deg"], abs_tol=1e-8)
        assert math.isclose(source["dec_deg"], query["dec_deg"], abs_tol=1e-8)
        assert query["radius_arcmin"] == 5 and query["limit"] == 3
    else:
        assert response["literature_results"]
        assert response["gaia_results"][0]["data"][0]["source_id"] == "5853498713190525696"
        assert response["literature_results"][0]["papers"][0]["bibcode"] == "2016A&A...595A...2G"


def assert_equal(item, actual, expected):
    assert actual == expected
    item["restored_project_id"] = actual["id"]


def delete_preserves(item, project, request):
    code, before = request(f"/api/v1/projects/{project['id']}")
    assert code == 200
    code, _ = request(
        f"/api/v1/projects/{project['id']}",
        {"expected_revision": before["revision"], "confirm": True},
        "DELETE",
    )
    assert code == 204
    for cid in before["conversation_ids"]:
        assert request(f"/api/v1/conversations/{cid}")[0] == 200
    item["retained_conversation_ids"] = before["conversation_ids"]


if __name__ == "__main__":
    raise SystemExit(main())
