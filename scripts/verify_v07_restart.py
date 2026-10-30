"""中断正在查询的合成流程，验证重启与显式继续；不接触真实科研服务。"""

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from uuid import uuid4

import requests
from record_utils import ROOT, create_record_directory, runtime_metadata, write_report


def main():
    out = create_record_directory("restart-v07")
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        **runtime_metadata(),
        "checks": {},
        "data_kind": "synthetic_not_observations",
        "servers": [],
    }
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    session = requests.Session()
    session.trust_env = False
    process = None
    logs = []
    with tempfile.TemporaryDirectory(prefix="astroagent-restart-v07-") as tmp:
        env = os.environ.copy()
        env.update(
            ASTROAGENT_DATA_DIR=tmp, PYTHONIOENCODING="utf-8", DEEPSEEK_API_KEY="", ADS_API_TOKEN=""
        )

        def start():
            nonlocal process
            log = (out / f"server-{len(logs)}.txt").open("w", encoding="utf-8")
            logs.append(log)
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "scripts.fixture_server:app",
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
            report["servers"].append({"pid": process.pid, "stopped": False})
            for _ in range(100):
                try:
                    if session.get(base + "/health", timeout=1).ok:
                        return
                except requests.RequestException:
                    time.sleep(0.25)
            raise RuntimeError("Server did not start")

        def stop():
            nonlocal process
            if process:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                report["servers"][-1]["stopped"] = True
                process = None

        def call(method, path, **kwargs):
            response = session.request(method, base + path, timeout=90, **kwargs)
            response.raise_for_status()
            return response.json()

        try:
            start()
            project = call("POST", "/api/v1/projects", json={"name": "合成重启"})
            path = f"/api/v1/projects/{project['id']}/workflows"
            run = call(
                "POST",
                path,
                json={
                    "expected_revision": 0,
                    "name": "中断恢复",
                    "template_id": "ads_evidence",
                    "parameters": {
                        "query": "__wait_project__",
                        "rows": 1,
                        "start": 0,
                        "sort": "date_desc",
                    },
                },
            )
            path += "/" + run["id"]
            payload = {
                "expected_revision": run["revision"],
                "client_request_id": str(uuid4()),
                "confirmed": True,
            }

            def trigger():
                s = requests.Session()
                s.trust_env = False
                try:
                    s.post(base + path + "/execute", json=payload, timeout=90)
                except requests.RequestException:
                    pass
                finally:
                    s.close()

            worker = threading.Thread(target=trigger)
            worker.start()
            for _ in range(100):
                current = call("GET", path)
                if current["state"] == "running" and current["current_step_id"] == "query_ads":
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("running state not observed")
            report["checks"]["running_observed"] = True
            stop()
            worker.join(timeout=15)
            report["checks"]["request_thread_stopped"] = not worker.is_alive()
            start()
            recovered = call("GET", path)
            report["checks"]["interrupted_after_restart"] = recovered["state"] == "interrupted"
            step = next(s for s in recovered["steps"] if s["id"] == "query_ads")
            report["checks"]["interrupted_attempt_preserved"] = (
                len(step["attempts"]) == 1 and step["attempts"][0]["state"] == "interrupted"
            )
            replay = call("POST", path + "/execute", json=payload)["run"]
            report["checks"]["old_request_not_replayed"] = (
                replay["state"] == "interrupted"
                and len(next(s for s in replay["steps"] if s["id"] == "query_ads")["attempts"]) == 1
            )
            resumed = call(
                "POST",
                path + "/execute",
                json={
                    "expected_revision": replay["revision"],
                    "client_request_id": str(uuid4()),
                    "confirmed": True,
                },
            )["run"]
            attempts = next(s for s in resumed["steps"] if s["id"] == "query_ads")["attempts"]
            report["checks"]["explicit_resume_succeeds"] = resumed["state"] == "succeeded" and [
                a["state"] for a in attempts
            ] == ["interrupted", "succeeded"]
        except Exception as exc:
            report["error"] = type(exc).__name__ + ": " + str(exc)[:500]
        finally:
            stop()
            for log in logs:
                log.close()
    report["outcome"] = (
        "passed"
        if len(report["checks"]) == 6
        and all(report["checks"].values())
        and all(s["stopped"] for s in report["servers"])
        else "failed"
    )
    report["finished_at"] = datetime.now(UTC).isoformat()
    print(report["checks"])
    print(write_report(out, report))
    return 0 if report["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
