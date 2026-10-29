"""会话真实 HTTP 验收；默认为明确合成替身，--live 访问真实模型/科研服务。"""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4
from zipfile import ZipFile

from record_utils import (
    ROOT,
    create_record_directory,
    project_version,
    runtime_metadata,
    write_report,
)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    out = create_record_directory("live-conversation-tests" if args.live else "acceptance-v05")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "application_version": project_version(),
        **runtime_metadata(),
        "command": ["scripts/verify_v05.py", *(["--live"] if args.live else [])],
        "data_kind": "real_queries" if args.live else "synthetic_not_observations",
        "checks": [],
        "servers": [],
        "visual_review": "pending_manual_inspection",
    }
    process = None
    logs = []

    def request(path, body=None, method=None, headers=None):
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = Request(
            base + path,
            data=data,
            method=method,
            headers=headers or {"Content-Type": "application/json"},
        )
        try:
            response = urlopen(req, timeout=300)
        except HTTPError as exc:
            response = exc
        with response:
            content = response.read()
            media = response.headers.get_content_type()
            parsed = json.loads(content) if media == "application/json" else None
            return response.status, parsed, content, dict(response.headers)

    def check(name, action):
        item = {"name": name, "passed": False}
        report["checks"].append(item)
        try:
            action(item)
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
        with socket.socket() as sock:
            sock.settimeout(1)
            closed = sock.connect_ex(("127.0.0.1", port)) != 0
        report["servers"][-1].update(
            exit_code=process.returncode, stopped=process.poll() is not None, port_closed=closed
        )
        process = None

    def start(data_dir):
        nonlocal process
        environment = os.environ.copy()
        environment["ASTROAGENT_DATA_DIR"] = str(data_dir)
        environment["PYTHONIOENCODING"] = "utf-8"
        if not args.live:
            environment["DEEPSEEK_API_KEY"] = ""
            environment["ADS_API_TOKEN"] = ""
        entry = "astroagent.main:app" if args.live else "scripts.fixture_server:app"
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
        log = (out / f"uvicorn-{len(logs)}.txt").open("w", encoding="utf-8")
        logs.append(log)
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=log)
        report["servers"].append(
            {"pid": process.pid, "command": command, "stopped": False, "port_closed": False}
        )
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError("Server exited")
            try:
                if request("/health")[0] == 200:
                    return
            except (OSError, URLError):
                time.sleep(0.25)
        raise RuntimeError("Server readiness timeout")

    def create(title):
        status, body, _, _ = request("/api/v1/conversations", {"title": title})
        assert status == 201, body
        return body

    def turn(conversation, message, revision, key=None):
        payload = {
            "message": message,
            "expected_revision": revision,
            "client_request_id": key or str(uuid4()),
        }
        status, body, _, _ = request(f"/api/v1/conversations/{conversation['id']}/turns", payload)
        return status, body, payload

    def export_turn(name, conversation, saved):
        def run(item):
            path = f"/api/v1/conversations/{conversation['id']}/turns/{saved['turn_id']}/artifacts"
            specs = (
                [
                    {"gaia_result_index": 0, "kind": kind}
                    for kind in ("proper_motion", "parallax_histogram", "observed_cmd")
                ]
                if saved["response"].get("gaia_results")
                else []
            )
            status, info, _, _ = request(path, {"plots": specs})
            item.update(http_status=status, body=info)
            assert status == 201
            status, _, content, headers = request(info["download_url"])
            assert status == 200
            (out / f"{name}.zip").write_bytes(content)
            _, manifest, _, _ = request(info["manifest_url"])
            with ZipFile(BytesIO(content)) as archive:
                assert json.loads(archive.read("snapshot.json")) == saved["response"]
                for f in manifest["files"]:
                    payload = archive.read(f["path"])
                    assert (
                        len(payload) == f["bytes"]
                        and hashlib.sha256(payload).hexdigest() == f["sha256"]
                    )
                for picture in info["figures"]:
                    status, _, image, _ = request(picture["url"])
                    assert status == 200
                    assert hashlib.sha256(image).hexdigest() == picture["sha256"]
                    assert any(
                        image == archive.read(n) for n in archive.namelist() if n.endswith(".png")
                    )
                    (out / f"{name}-{picture['kind']}.png").write_bytes(image)
                assert json.loads(archive.read("manifest.json")) == manifest
            item.update(hashes_verified=True, package=f"{name}.zip")
            return info

        check("artifact-" + name, run)

    @contextmanager
    def data_directory():
        with tempfile.TemporaryDirectory(prefix="astroagent-v05-") as data:
            try:
                yield data
            finally:
                stop()

    try:
        with data_directory() as data:
            start(data)
            check(
                "health-openapi",
                lambda item: item.update(version=request("/openapi.json")[1]["info"]["version"]),
            )
            conversation = create("联网Gaia验收" if args.live else "合成HTTP验收")
            key = str(uuid4())
            status, first, payload = turn(
                conversation,
                "查询 ICRS 赤经56.75度、赤纬24.12度、半径5角分内最近100个"
                "Gaia DR3位置候选源，不估算距离，给出来源。",
                0,
                key,
            )

            def first_check(item):
                item.update(http_status=status, request=payload, body=first)
                assert status == 200 and first["response"]["gaia_results"][0]["status"] == "success"
                assert len(first["response"]["gaia_results"][0]["data"]) == 100

            check("cone-100-rows", first_check)
            if first.get("response"):
                export_turn("cone", conversation, first)

            def duplicate(item):
                code, body, _, _ = request(
                    f"/api/v1/conversations/{conversation['id']}/turns", payload
                )
                item.update(http_status=code, body=body)
                assert code == 200 and body == first

            check("idempotent-replay", duplicate)
            status, second, request_body = turn(
                conversation, "只保留 RUWE≤1.4，其他条件不变，重新查询。", 1
            )

            def followup(item):
                item.update(http_status=status, request=request_body, body=second)
                assert status == 200
                previous = first["response"]["gaia_results"][0]
                result = second["response"]["gaia_results"][0]
                assert result["status"] == "success" and result["query"]["ruwe_max"] == 1.4
                for field in ("ra_deg", "dec_deg", "radius_arcmin", "limit"):
                    assert previous["query"][field] == result["query"][field]
                assert result["source"]["retrieved_at"] != previous["source"]["retrieved_at"]
                assert first["turn_id"] in second["context"]["included_turn_ids"]

            check("followup-real-parameters", followup)
            if second.get("response"):
                export_turn("filtered", conversation, second)
            if args.live:
                for name, message, follow_message in (
                    (
                        "ads",
                        "检索ADS bibcode:2016A&A...595A...2G，取1篇，给出来源。",
                        "上一轮第一篇的DOI是什么？只引用历史字段，不重新检索。",
                    ),
                    (
                        "exact",
                        "查询Gaia DR3 source_id 5853498713190525696并估算距离，说明近似。",
                        "解释上一轮距离近似条件和限制，不重新查询。",
                    ),
                    (
                        "name",
                        "先查SIMBAD的M45坐标，再查询中心5角分内最近3个Gaia DR3位置候选源。",
                        None,
                    ),
                    (
                        "three-tools",
                        "独立查询SIMBAD的M45坐标、Gaia DR3 source_id 5853498713190525696、"
                        "ADS bibcode:2016A&A...595A...2G，不假定三者关联。",
                        None,
                    ),
                ):
                    conv = create("联网验收-" + name)
                    code, saved, request_body = turn(conv, message, 0)

                    def query_check(item, code=code, saved=saved, request_body=request_body):
                        item.update(http_status=code, request=request_body, body=saved)
                        assert code == 200 and saved["response"]["status"] == "success"

                    check(name + "-query", query_check)
                    if saved.get("response"):
                        export_turn(name, conv, saved)
                    if follow_message and code == 200:
                        code, next_turn, request_body = turn(conv, follow_message, 1)

                        def reference_check(
                            item,
                            code=code,
                            saved=saved,
                            next_turn=next_turn,
                            request_body=request_body,
                        ):
                            item.update(http_status=code, request=request_body, body=next_turn)
                            assert (
                                code == 200
                                and saved["turn_id"] in next_turn["context"]["included_turn_ids"]
                            )
                            assert all(
                                not next_turn["response"].get(k)
                                for k in ("results", "literature_results", "gaia_results")
                            )
                            if saved["response"].get("literature_results"):
                                doi = saved["response"]["literature_results"][0]["papers"][0]["doi"]
                                if doi:
                                    assert any(d in next_turn["response"]["answer"] for d in doi)

                        check(name + "-history-reference", reference_check)
            else:

                def access(item):
                    assert (
                        request(
                            "/api/v1/conversations",
                            {},
                            headers={
                                "Content-Type": "application/json",
                                "Origin": "https://outside.invalid",
                            },
                        )[0]
                        == 403
                    )
                    assert request("/health", headers={"Host": "outside.invalid"})[0] == 400
                    assert (
                        request(
                            "/api/v1/conversations",
                            method="OPTIONS",
                            headers={
                                "Origin": "http://127.0.0.1:5173",
                                "Access-Control-Request-Method": "POST",
                                "Access-Control-Request-Headers": "content-type",
                            },
                        )[0]
                        == 200
                    )

                check("host-origin-cors", access)
                running = create("合成中断恢复")
                waiting_payload = {
                    "message": "__wait__ 合成慢查询",
                    "expected_revision": 0,
                    "client_request_id": str(uuid4()),
                }

                def slow():
                    try:
                        request(f"/api/v1/conversations/{running['id']}/turns", waiting_payload)
                    except OSError:
                        pass

                worker = threading.Thread(target=slow, daemon=True)
                worker.start()
                for _ in range(60):
                    body = request(f"/api/v1/conversations/{running['id']}")[1]
                    if body["turns"]:
                        break
                    time.sleep(0.1)
                assert body["turns"] and body["turns"][0]["execution_status"] == "running"
                interrupted_id = body["turns"][0]["turn_id"]
                stop()
                worker.join(timeout=5)
                start(data)

                def restart(item):
                    code, restored, _, _ = request(
                        f"/api/v1/conversations/{conversation['id']}/turns/{first['turn_id']}"
                    )
                    assert code == 200 and restored == first
                    code, interrupted, _, _ = request(
                        f"/api/v1/conversations/{running['id']}/turns/{interrupted_id}"
                    )
                    item.update(body=interrupted)
                    assert code == 200 and interrupted["execution_status"] == "interrupted"
                    repeat = request(
                        f"/api/v1/conversations/{running['id']}/turns", waiting_payload
                    )[1]
                    assert repeat == interrupted

                check("restart-persistence-interrupted-no-replay", restart)
                export_turn("restored", conversation, first)

                def crud(item):
                    path = f"/api/v1/conversations/{conversation['id']}"
                    assert (
                        request(path, {"title": "重命名合成会话"}, "PATCH")[1]["title"]
                        == "重命名合成会话"
                    )
                    assert request(path, method="DELETE")[0] == 204
                    assert request(path)[0] == 404

                check("rename-delete", crud)
    except Exception as exc:
        report["fatal_error_type"] = type(exc).__name__
    finally:
        stop()
        for log in logs:
            log.close()
        report["outcome"] = (
            "passed"
            if report["checks"]
            and all(c["passed"] for c in report["checks"])
            and "fatal_error_type" not in report
            and all(s["stopped"] and s["port_closed"] for s in report["servers"])
            else "failed"
        )
        report["finished_at"] = datetime.now(UTC).isoformat()
        print("Report:", write_report(out, report), flush=True)
    return 0 if report["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
