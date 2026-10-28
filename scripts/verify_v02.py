"""V0.2 真实 HTTP 验收，逐项存证，失败也保存报告并停止自建服务。"""

import importlib.metadata
import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from record_utils import ROOT, create_record_directory, project_version, write_report


def main():
    output = create_record_directory("acceptance-v02")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    report = {
        "application_version": project_version(),
        "started_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "versions": {
            name: importlib.metadata.version(name)
            for name in (
                "astroagent",
                "fastapi",
                "langchain-core",
                "langchain-openai",
                "astroquery",
                "requests",
            )
        },
        "checks": [],
        "server_stopped": False,
    }

    def request(path, payload=None, timeout=240):
        data = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        )
        req = Request(base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            response = urlopen(req, timeout=timeout)
        except HTTPError as exc:
            response = exc
        with response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if path != "/docs" else body

    def check(name, path, predicate, payload=None):
        item = {
            "name": name,
            "path": path,
            "request": payload,
            "started_at": datetime.now(UTC).isoformat(),
            "passed": False,
        }
        report["checks"].append(item)
        try:
            status, body = request(path, payload)
            item.update(http_status=status, body=body)
            item["passed"] = bool(predicate(status, body))
        except Exception as exc:
            # No upstream exception strings, headers or credentials in reports.
            item["error_type"] = type(exc).__name__
        print(f"{name}: {'passed' if item['passed'] else 'FAILED'}", flush=True)

    def ads_success(status, body):
        return (
            status == 200
            and body.get("status") == "success"
            and bool(body.get("literature_results"))
            and all(r["status"] == "success" and r["papers"] for r in body["literature_results"])
            and any(s["name"] == "ADS" for s in body.get("sources", []))
        )

    process = None
    try:
        with (output / "uvicorn.txt").open("x", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "astroagent.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Server exited before readiness")
                    try:
                        request("/health", timeout=1)
                        break
                    except (URLError, TimeoutError):
                        if time.monotonic() > deadline:
                            raise RuntimeError("Server readiness timed out") from None
                        time.sleep(0.2)
                check("health", "/health", lambda s, b: s == 200 and b == {"status": "ok"})
                check("swagger", "/docs", lambda s, b: s == 200 and "/openapi.json" in b)
                check(
                    "openapi",
                    "/openapi.json",
                    lambda s, b: (
                        s == 200
                        and b["info"]["version"] == project_version()
                        and "literature_results"
                        in b["components"]["schemas"]["ChatResponse"]["properties"]
                    ),
                )
                check("empty_message", "/api/v1/chat", lambda s, b: s == 422, {"message": " "})
                check(
                    "simbad_only",
                    "/api/v1/chat",
                    lambda s, b: (
                        s == 200
                        and b.get("status") == "success"
                        and b.get("results")
                        and not b.get("literature_results")
                        and 88 < b["results"][0]["data"]["ra_deg"] < 90
                    ),
                    {"message": "请通过 SIMBAD 查询 Betelgeuse 的坐标与类型，给出来源。"},
                )
                check(
                    "ads_only",
                    "/api/v1/chat",
                    lambda s, b: (
                        ads_success(s, b)
                        and not b.get("results")
                        and b["literature_results"][0]["papers"][0]["bibcode"]
                        == "2007A&A...474..653V"
                    ),
                    {"message": "检索 bibcode 为 2007A&A...474..653V 的文献，给出书目信息与来源。"},
                )
                check(
                    "combined",
                    "/api/v1/chat",
                    lambda s, b: (
                        ads_success(s, b)
                        and b.get("results")
                        and all(r["status"] == "success" for r in b["results"])
                        and any(source["name"] == "SIMBAD" for source in b["sources"])
                    ),
                    {
                        "message": "查询 Betelgeuse 的坐标，再找 2 篇 2020—2026 年"
                        "其变暗相关论文，给出来源。"
                    },
                )
                check(
                    "ads_no_match",
                    "/api/v1/chat",
                    lambda s, b: (
                        s == 200
                        and b.get("status") == "error"
                        and not b.get("sources")
                        and bool(b.get("literature_results"))
                        and all(
                            r["status"] == "not_found" and r["total_found"] == 0 and not r["papers"]
                            for r in b["literature_results"]
                        )
                    ),
                    {
                        "message": '请仅检索 bibcode:"AstroAgentDefinitelyMissingPaperV02"，'
                        "不要改写检索条件；说明是否匹配。"
                    },
                )
                check(
                    "simbad_no_match",
                    "/api/v1/chat",
                    lambda s, b: (
                        s == 200
                        and b.get("status") == "error"
                        and not b.get("sources")
                        and bool(b.get("results"))
                        and all(r["status"] == "not_found" for r in b["results"])
                    ),
                    {"message": "请调用 SIMBAD 查询 AstroAgentDefinitelyMissingObjectV02。"},
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    except Exception as exc:
        report["error_type"] = type(exc).__name__
    finally:
        report["server_stopped"] = process is None or process.poll() is not None
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["outcome"] = (
            "passed"
            if len(report["checks"]) == 9
            and all(c["passed"] for c in report["checks"])
            and report["server_stopped"]
            else "failed"
        )
        path = write_report(output, report)
        # Local convenience copy; the per-run evidence above is never overwritten.
        (ROOT / "outputs").mkdir(exist_ok=True)
        (ROOT / "outputs" / "v0.2-acceptance.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{report['outcome']}; server stopped={report['server_stopped']}; report: {path}")
    return 0 if report["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
