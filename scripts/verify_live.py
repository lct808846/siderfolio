"""启动临时 Uvicorn 并验收真实 HTTP 查询，结束后停止子进程。

使用：python scripts/verify_live.py
需要 DEEPSEEK_API_KEY 和外网，会执行两次聊天查询并产生模型用量。
报告仅包含公开查询结果、运行版本与 HTTP 状态，不包含密钥。
"""

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
    output = create_record_directory("acceptance")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    checks = []

    def request(path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = Request(base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            response = urlopen(req, timeout=180)
        except HTTPError as exc:
            response = exc
        with response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if path != "/docs" else body

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
                    raise RuntimeError(f"Uvicorn failed to start; inspect {output / 'uvicorn.txt'}")
                try:
                    status, health = request("/health")
                    break
                except (URLError, TimeoutError):
                    if time.monotonic() > deadline:
                        raise RuntimeError("Server startup timed out") from None
                    time.sleep(0.2)
            assert status == 200 and health == {"status": "ok"}
            checks.append({"name": "health", "http_status": status, "body": health})
            status, html = request("/docs")
            assert status == 200 and "/openapi.json" in html
            checks.append({"name": "swagger", "http_status": status})
            status, schema = request("/openapi.json")
            assert status == 200 and "/api/v1/chat" in schema["paths"]
            checks.append({"name": "openapi", "http_status": status})
            status, invalid = request("/api/v1/chat", {"message": " "})
            assert status == 422
            checks.append({"name": "empty_message", "http_status": status})
            status, star = request(
                "/api/v1/chat",
                {"message": "请通过 SIMBAD 查询 Betelgeuse 的坐标、类型和光谱类型，并给出来源。"},
            )
            assert status == 200 and star["status"] == "success", star
            assert star["results"] and star["sources"], star
            data = star["results"][0]["data"]
            assert 88 < data["ra_deg"] < 90 and 7 < data["dec_deg"] < 8
            checks.append({"name": "betelgeuse", "http_status": status, "body": star})
            missing_name = "AstroAgentDefinitelyMissingObject20261026"
            status, missing = request(
                "/api/v1/chat",
                {"message": f"请调用 SIMBAD 查询名称 {missing_name} 的天体。"},
            )
            assert status == 200 and missing["status"] == "error", missing
            assert missing["results"] and not missing["sources"], missing
            assert all(
                item["status"] == "not_found" and item["data"] is None
                for item in missing["results"]
            ), missing
            checks.append({"name": "unknown_object", "http_status": status, "body": missing})
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    report = {
        "application_version": project_version(),
        "verified_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "versions": {
            name: importlib.metadata.version(name)
            for name in (
                "astroagent",
                "fastapi",
                "langchain-core",
                "langchain-openai",
                "astroquery",
            )
        },
        "server_stopped": process.poll() is not None,
        "checks": checks,
    }
    path = write_report(output, report)
    print(f"Passed {len(checks)} live HTTP checks; server stopped. Report: {path}")


if __name__ == "__main__":
    main()
