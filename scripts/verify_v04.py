"""启动真实 Uvicorn 验收导出；--live 查询真实数据库/模型并保存完整证据。"""

import argparse
import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

from export_samples import synthetic_request
from record_utils import (
    ROOT,
    create_record_directory,
    project_version,
    runtime_metadata,
    write_report,
)

from astroagent.config import Settings


def verify_archive(content, expected_snapshot):
    with ZipFile(BytesIO(content)) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert len(names) == len(set(names))
        assert set(names) == {f["path"] for f in manifest["files"]} | {"manifest.json"}
        assert json.loads(archive.read("snapshot.json")) == expected_snapshot
        assert manifest["source_authenticity_verified"] is False
        for item in manifest["files"]:
            body = archive.read(item["path"])
            assert len(body) == item["bytes"]
            assert hashlib.sha256(body).hexdigest() == item["sha256"]
        for p in manifest["plots"]:
            assert p["valid_count"] + p["skipped_count"] == p["delivered_count"]
            if p["status"] == "success":
                from PIL import Image

                with Image.open(BytesIO(archive.read(p["output_path"]))) as image:
                    assert image.size == (1200, 900)
                    image.verify()
                if p["kind"] == "parallax_histogram":
                    assert sum(p["parameters"]["bin_counts"]) == p["valid_count"]
        return manifest, {name: archive.read(name) for name in names if name.endswith(".png")}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="实际模型与三个数据源查询，会产生用量")
    parser.add_argument(
        "--only",
        nargs="+",
        choices=[
            "cone",
            "exact",
            "simbad",
            "ads",
            "name",
            "three-tools",
        ],
        help="仅重试所选联网场景，不能替代完整验收",
    )
    args = parser.parse_args()
    if args.only and not args.live:
        parser.error("--only requires --live")
    output = create_record_directory("live-export-tests" if args.live else "acceptance-v04")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    report = {
        "application_version": project_version(),
        "started_at": datetime.now(UTC).isoformat(),
        "command": [
            "scripts/verify_v04.py",
            *(["--live"] if args.live else []),
            *(["--only", *args.only] if args.only else []),
        ],
        "live_scenario_scope": args.only or "all",
        "data_kind": "real_queries" if args.live else "synthetic_not_observations",
        **runtime_metadata(),
        "checks": [],
        "server_stopped": False,
        "server_port_closed": False,
        "visual_review": "pending_manual_inspection",
    }

    def request(path, payload=None, raw=None, headers=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else raw
        req = Request(
            base + path, data=data, headers=headers or {"Content-Type": "application/json"}
        )
        try:
            response = urlopen(req, timeout=240)
        except HTTPError as exc:
            response = exc
        with response:
            content = response.read()
            body = (
                None
                if response.headers.get_content_type() == "application/zip"
                else (
                    json.loads(content)
                    if response.headers.get_content_type() == "application/json"
                    else content.decode("utf-8")
                )
            )
            return response.status, dict(response.headers), content, body

    def check(name, action):
        record = {"name": name, "passed": False, "started_at": datetime.now(UTC).isoformat()}
        report["checks"].append(record)
        try:
            action(record)
            record["passed"] = True
        except Exception as exc:
            record["error_type"] = type(exc).__name__
        print(f"{name}: {'passed' if record['passed'] else 'FAILED'}", flush=True)

    def endpoint_check(name, path, status, **kwargs):
        def run(record):
            code, headers, _, body = request(path, **kwargs)
            record.update(http_status=code, headers=headers, body=body)
            assert code == status

        check(name, run)

    def export_check(name, payload, expected_status="success", query_ok=True):
        def run(record):
            record["request"] = payload
            code, headers, content, body = request("/api/v1/exports", payload=payload)
            record.update(http_status=code, headers=headers, error_body=body)
            assert code == 200
            assert headers.get("cache-control") == "no-store"
            manifest, images = verify_archive(content, payload["snapshot"])
            (output / f"{name}.zip").write_bytes(content)
            (output / f"{name}-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            for image_name, image_body in images.items():
                (output / f"{name}-{image_name.rsplit('/', 1)[1]}").write_bytes(image_body)
            record.update(
                package=f"{name}.zip",
                manifest=f"{name}-manifest.json",
                hashes_verified=True,
                query_success=query_ok,
            )
            if expected_status:
                assert manifest["export_status"] == expected_status
            assert query_ok

        check(name, run)

    process = None
    try:
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        if not args.live:
            for key in ("DEEPSEEK_API_KEY", "ADS_API_TOKEN"):
                environment[key] = ""
        with (output / "uvicorn.txt").open("w", encoding="utf-8") as log:
            command = [
                sys.executable,
                "-m",
                "uvicorn",
                "astroagent.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=log)
            report.update(server_pid=process.pid, server_command=command)
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError("Server exited before readiness")
                try:
                    if request("/health")[0] == 200:
                        break
                except OSError:
                    time.sleep(0.25)
            else:
                raise RuntimeError("Server readiness timed out")
            endpoint_check("health", "/health", 200)
            endpoint_check("openapi", "/openapi.json", 200)
            if args.live:
                settings = Settings()
                report["credentials_present"] = {
                    "deepseek": bool(settings.deepseek_api_key.get_secret_value().strip()),
                    "ads": bool(settings.ads_api_token.get_secret_value().strip()),
                }
                messages = {
                    "cone": "查询 ICRS 赤经56.75度、赤纬24.12度、半径5角分内"
                    "最近100个Gaia DR3位置候选源，"
                    "不做质量筛选，不估算距离，给出来源和样本局限。",
                    "exact": "查询 Gaia DR3 source_id 5853498713190525696 的测量并估算距离，"
                    "给出来源。",
                    "simbad": "用 SIMBAD 查询 Betelgeuse 的坐标和光谱类型，给出来源。",
                    "ads": "用 ADS 检索 bibcode:2016A&A...595A...2G，取1篇，给出来源。",
                    "name": "先用SIMBAD查M45坐标，再查中心5角分内最近3个Gaia DR3位置候选源，"
                    "给出来源。",
                    "three-tools": "分别查SIMBAD的M45坐标，Gaia DR3 source_id 5853498713190525696，"
                    "ADS bibcode:2016A&A...595A...2G。三项独立，不假定源与M45或论文相关。",
                }
                for name, message in messages.items():
                    if args.only and name not in args.only:
                        continue
                    record = {"name": f"query-{name}", "message": message, "passed": False}
                    report["checks"].append(record)
                    try:
                        code, _, _, body = request("/api/v1/chat", payload={"message": message})
                        record.update(http_status=code, body=body)
                        needed = {
                            "simbad": ["results"],
                            "ads": ["literature_results"],
                            "three-tools": ["results", "literature_results", "gaia_results"],
                            "name": ["results", "gaia_results"],
                        }.get(name, ["gaia_results"])
                        record["passed"] = (
                            code == 200
                            and body.get("status") == "success"
                            and all(
                                body.get(k) and all(r["status"] == "success" for r in body[k])
                                for k in needed
                            )
                        )
                        print(
                            f"query-{name}: {'passed' if record['passed'] else 'FAILED'}",
                            flush=True,
                        )
                        if code == 200:
                            plot_specs = (
                                [
                                    {"gaia_result_index": 0, "kind": kind}
                                    for kind in (
                                        "proper_motion",
                                        "parallax_histogram",
                                        "observed_cmd",
                                    )
                                ]
                                if body.get("gaia_results")
                                else []
                            )
                            export_check(
                                name,
                                {"schema_version": "1", "snapshot": body, "plots": plot_specs},
                                expected_status="success" if name == "cone" else None,
                                query_ok=record["passed"],
                            )
                    except Exception as exc:
                        record["error_type"] = type(exc).__name__
            else:
                payload = synthetic_request()
                export_check("synthetic-full", payload)
                payload["plots"] = []
                export_check("data-only-no-keys", payload)
                payload = synthetic_request(1)
                export_check("single-point", payload, expected_status="partial")
                payload = synthetic_request()
                failed = payload["snapshot"]["results"][0]
                failed.update(
                    status="error",
                    data=None,
                    error={"code": "synthetic", "message": "合成失败", "retryable": True},
                )
                payload["snapshot"]["sources"].pop(0)
                payload["snapshot"]["status"] = "partial"
                export_check("partial-query", payload)
                failed["status"] = "not_found"
                export_check("not-found", payload)
                payload["snapshot"]["gaia_results"][0]["returned_count"] = 0
                endpoint_check("invalid-snapshot", "/api/v1/exports", 422, payload=payload)
                endpoint_check(
                    "invalid-media",
                    "/api/v1/exports",
                    415,
                    raw=b"{}",
                    headers={"Content-Type": "text/plain"},
                )
                endpoint_check("oversize", "/api/v1/exports", 413, raw=b" " * (2097152 + 1))

                def chunked(record):
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
                    try:
                        try:
                            connection.request(
                                "POST",
                                "/api/v1/exports",
                                body=iter([b" " * 65536] * 33),
                                headers={"Content-Type": "application/json"},
                                encode_chunked=True,
                            )
                        except BrokenPipeError:
                            pass
                        response = connection.getresponse()
                        record.update(http_status=response.status, body=json.loads(response.read()))
                        assert response.status == 413
                    finally:
                        connection.close()

                check("chunked-oversize-real-uvicorn", chunked)
    except Exception as exc:
        report["fatal_error_type"] = type(exc).__name__
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            report.update(
                server_exit_code=process.returncode, server_stopped=process.poll() is not None
            )
            with socket.socket() as sock:
                sock.settimeout(1)
                report["server_port_closed"] = sock.connect_ex(("127.0.0.1", port)) != 0
        report["outcome"] = (
            "passed"
            if (
                report["checks"]
                and all(c["passed"] for c in report["checks"])
                and "fatal_error_type" not in report
                and report["server_stopped"]
                and report["server_port_closed"]
            )
            else "failed"
        )
        report["finished_at"] = datetime.now(UTC).isoformat()
        print(f"Report: {write_report(output, report)}", flush=True)
    return 0 if report["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
