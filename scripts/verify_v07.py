"""V0.7 流程 HTTP 与归档验收；--live 访问真实科研服务，不调用模型。"""

import argparse
import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from uuid import uuid4

import requests
from record_utils import ROOT, create_record_directory, runtime_metadata, write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    out = create_record_directory("live-workflows" if args.live else "acceptance-v07")
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        **runtime_metadata(),
        "data_kind": "real_queries" if args.live else "synthetic_not_observations",
        "checks": [],
        "server": {},
    }
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    session = requests.Session()
    session.trust_env = False
    base = f"http://127.0.0.1:{port}"
    process = None
    with tempfile.TemporaryDirectory(prefix="astroagent-v07-") as tmp:
        env = os.environ.copy()
        env.update(ASTROAGENT_DATA_DIR=tmp, PYTHONIOENCODING="utf-8")
        if not args.live:
            env.update(DEEPSEEK_API_KEY="", ADS_API_TOKEN="")
        entry = "astroagent.main:app" if args.live else "scripts.fixture_server:app"
        with (out / "server.txt").open("w", encoding="utf-8") as log:
            try:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        entry,
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                report["server"] = {"pid": process.pid, "port": port}
                for _ in range(100):
                    try:
                        if session.get(base + "/health", timeout=1).ok:
                            break
                    except requests.RequestException:
                        time.sleep(0.25)
                else:
                    raise RuntimeError("Server did not start")

                def check(name, action):
                    item = {"name": name, "passed": False}
                    report["checks"].append(item)
                    try:
                        action(item)
                        item["passed"] = True
                    except Exception as exc:
                        item["error"] = str(exc)[:500]
                    print(name, "passed" if item["passed"] else "FAILED", flush=True)

                def call(method, path, expected=200, **kwargs):
                    response = session.request(method, base + path, timeout=300, **kwargs)
                    if response.status_code != expected:
                        raise AssertionError(
                            f"{path}: HTTP {response.status_code} expected {expected}"
                        )
                    return response

                project = call("POST", "/api/v1/projects", 201, json={"name": "流程验收"}).json()
                prefix = "/api/v1/projects/" + project["id"]
                cases = [
                    (
                        "gaia-coordinate",
                        "gaia_field",
                        {
                            "input_mode": "coordinates",
                            "ra_deg": 56.75,
                            "dec_deg": 24.12,
                            "radius_arcmin": 5,
                            "limit": 10,
                            "plots": ["parallax_histogram"],
                        },
                    ),
                    (
                        "ads",
                        "ads_evidence",
                        {
                            "query": 'title:"binary cluster"',
                            "rows": 1,
                            "start": 0,
                            "sort": "date_desc",
                        },
                    ),
                ]
                if args.live:
                    cases.append(
                        (
                            "gaia-name",
                            "gaia_field",
                            {
                                "input_mode": "name",
                                "object_name": "M45",
                                "radius_arcmin": 5,
                                "limit": 10,
                            },
                        )
                    )
                for name, template, parameters in cases:

                    def execute(item, name=name, template=template, parameters=parameters):
                        revision = call("GET", prefix).json()["revision"]
                        run = call(
                            "POST",
                            prefix + "/workflows",
                            201,
                            json={
                                "name": name,
                                "template_id": template,
                                "expected_revision": revision,
                                "parameters": parameters,
                            },
                        ).json()
                        assert run["state"] == "pending"
                        path = prefix + "/workflows/" + run["id"]
                        payload = {
                            "expected_revision": run["revision"],
                            "client_request_id": str(uuid4()),
                            "confirmed": True,
                        }
                        run = call("POST", path + "/execute", json=payload).json()["run"]
                        item["state"] = run["state"]
                        item["steps"] = [
                            {"id": s["id"], "state": s["state"], "error": s.get("error")}
                            for s in run["steps"]
                        ]
                        assert run["state"] == "succeeded", str(item["steps"])
                        assert run["outputs"]
                        steps = {step["id"]: step for step in run["steps"]}
                        query_step = "query_gaia" if template == "gaia_field" else "query_ads"
                        attempt = steps[query_step]["attempts"][-1]
                        result = attempt["output"]["response"]
                        item["actual_parameters"] = attempt["input"]["parameters"]
                        if template == "gaia_field":
                            gaia = result["gaia_results"][0]
                            assert gaia["status"] == "success"
                            assert len(gaia["data"]) == gaia["returned_count"]
                            assert all(isinstance(row["source_id"], str) for row in gaia["data"])
                            item["source"] = gaia["source"]["url"]
                            item["returned_count"] = gaia["returned_count"]
                            if parameters["input_mode"] == "name":
                                resolved = steps["resolve_name"]["attempts"][-1]["output"]
                                coords = resolved["coordinates"]
                                assert item["actual_parameters"]["ra_deg"] == coords["ra_deg"]
                                assert item["actual_parameters"]["dec_deg"] == coords["dec_deg"]
                                item["simbad_source"] = resolved["result"]["source"]["url"]
                        else:
                            ads = result["literature_results"][0]
                            assert (
                                ads["status"] == "success" and ads["query"] == parameters["query"]
                            )
                            evidence = steps["evidence_table"]["attempts"][-1]["output"]
                            assert len(evidence["rows"]) == len(ads["papers"])
                            for paper, row in zip(ads["papers"], evidence["rows"], strict=True):
                                assert row["bibcode"] == paper["bibcode"]
                                assert row["abstract"] == paper["abstract"]
                            item["source"] = ads["source"]["url"]
                            item["returned_count"] = len(ads["papers"])
                        for output in run["outputs"]:
                            data = call("GET", path + "/outputs/" + output["id"]).content
                            assert hashlib.sha256(data).hexdigest() == output["sha256"]
                        replay = call("POST", path + "/execute", json=payload).json()
                        assert replay["run"]["id"] == run["id"]
                        item["outputs"] = len(run["outputs"])

                    check(name, execute)

                def archive(item):
                    revision = call("GET", prefix).json()["revision"]
                    package = call(
                        "POST",
                        prefix + "/archive",
                        json={"expected_revision": revision, "format_version": 2},
                    ).content
                    restored = call(
                        "POST",
                        "/api/v1/projects/import",
                        201,
                        data=package,
                        headers={"Content-Type": "application/zip"},
                    ).json()
                    restored_id = restored["project"]["id"]
                    runs = call("GET", "/api/v1/projects/" + restored_id + "/workflows").json()
                    assert len(runs) == len(cases)
                    assert all(r["provenance"] == "imported_unverified" for r in runs)
                    item["restored_runs"] = len(runs)

                check("archive-restore", archive)
            except Exception as exc:
                report["checks"].append(
                    {
                        "name": "harness",
                        "passed": False,
                        "error": type(exc).__name__ + ": " + str(exc)[:500],
                    }
                )
            finally:
                if process:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
                    report["server"]["stopped"] = process.poll() is not None
    report["outcome"] = (
        "passed"
        if report["checks"]
        and all(c["passed"] for c in report["checks"])
        and report["server"].get("stopped")
        else "failed"
    )
    report["finished_at"] = datetime.now(UTC).isoformat()
    print(write_report(out, report))
    return 0 if report["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
