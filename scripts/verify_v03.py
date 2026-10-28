"""V0.3 真实 HTTP 验收；保留完整失败记录，并在 finally 停止临时 Uvicorn。"""

import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from record_utils import (
    ROOT,
    create_record_directory,
    project_version,
    runtime_metadata,
    write_report,
)

from astroagent.config import Settings
from astroagent.gaia import GaiaService
from astroagent.schemas import GaiaQuery

SOURCE_ID = "5853498713190525696"


def gaia_success(status, body):
    results = body.get("gaia_results", [])
    return (
        status == 200
        and body.get("status") == "success"
        and bool(results)
        and all(
            r["status"] == "success"
            and r["data"]
            and r["analysis"]
            and r["analysis"]["sample_size"] == r["returned_count"]
            and r["total_found"] is None
            for r in results
        )
        and any(s["name"] == "Gaia" for s in body.get("sources", []))
    )


def main():
    output = create_record_directory("acceptance-v03")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    report = {
        "application_version": project_version(),
        "started_at": datetime.now(UTC).isoformat(),
        "command": ["scripts/verify_v03.py"],
        **runtime_metadata(),
        "checks": [],
        "empty_condition_preflight": [],
        "server_stopped": False,
        "server_port_closed": False,
    }

    def request(path, payload=None, timeout=240):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
        req = Request(base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            response = urlopen(req, timeout=timeout)
        except HTTPError as exc:
            response = exc
        with response:
            body = response.read().decode("utf-8")
            return response.status, body if path == "/docs" else json.loads(body)

    def check(name, path, predicate, payload=None):
        item = {
            "name": name,
            "path": path,
            "request": payload,
            "started_at": datetime.now(UTC).isoformat(),
            "passed": False,
        }
        report["checks"].append(item)
        started = time.perf_counter()
        try:
            status, body = request(path, payload)
            item.update(http_status=status, body=body)
            item["passed"] = bool(predicate(status, body))
        except Exception as exc:
            item["error_type"] = type(exc).__name__
        item["seconds"] = round(time.perf_counter() - started, 3)
        print(f"{name}: {'passed' if item['passed'] else 'FAILED'}", flush=True)

    def chat_check(name, message, predicate):
        check(name, "/api/v1/chat", predicate, {"message": message})

    process = None
    try:
        # Public direct preflight confirms a currently empty condition; no fabricated ID truth.
        service = GaiaService(Settings().gaia_timeout_seconds)
        empty_id = None
        for identifier in ("1", "2", "3"):
            found = service.query(GaiaQuery(mode="source_id", source_id=identifier))
            report["empty_condition_preflight"].append(found.model_dump(mode="json"))
            if found.status == "not_found":
                empty_id = identifier
                break
            if found.status == "error":
                break
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
            report["server_pid"] = process.pid
            report["server_port"] = port
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
                        and "gaia_results"
                        in b["components"]["schemas"]["ChatResponse"]["properties"]
                    ),
                )
                check("empty_message", "/api/v1/chat", lambda s, b: s == 422, {"message": " "})
                chat_check(
                    "gaia_exact_distance",
                    f"查询 Gaia DR3 source_id {SOURCE_ID} 的测量信息并估算距离，"
                    "说明方法、单位、历元、近似条件和未做的零点校正，给出来源。",
                    lambda s, b: (
                        gaia_success(s, b)
                        and not b["results"]
                        and not b["literature_results"]
                        and b["gaia_results"][0]["query"]["mode"] == "source_id"
                        and b["gaia_results"][0]["data"][0]["source_id"] == SOURCE_ID
                        and b["gaia_results"][0]["analysis"]["estimate_distance"] is True
                        and len(b["gaia_results"][0]["analysis"]["distance_estimates"]) == 1
                        and "近似" in b["answer"]
                        and "零点" in b["answer"]
                    ),
                )
                chat_check(
                    "gaia_cone_analysis_off",
                    "以 ICRS 赤经 56.75 度、赤纬 24.12 度为中心，查询 5 角分内最近的 20 个 "
                    "Gaia DR3 位置候选源，总结视差和自行；不要估算距离，不加质量筛选，说明截断。",
                    lambda s, b: (
                        gaia_success(s, b)
                        and b["gaia_results"][0]["query"]["mode"] == "cone"
                        and 1 <= b["gaia_results"][0]["returned_count"] <= 20
                        and b["gaia_results"][0]["query"]["radius_arcmin"] == 5
                        and b["gaia_results"][0]["analysis"]["distance_estimates"] == []
                        and b["gaia_results"][0]["analysis"]["quality_filters"] == {}
                        and "候选" in b["answer"]
                    ),
                )
                chat_check(
                    "gaia_quality_filters",
                    "以 ICRS 赤经 56.75 度、赤纬 24.12 度为中心查 5 角分内最近的 3 个 Gaia DR3 源，"
                    "明确要求 RUWE≤1.4、正视差信噪比≥10；不要估算距离，说明质量选择的局限。",
                    lambda s, b: (
                        gaia_success(s, b)
                        and b["gaia_results"][0]["analysis"]["quality_filters"]
                        == {"ruwe_max": 1.4, "parallax_snr_min": 10}
                        and all(
                            r["ruwe"] <= 1.4 and r["parallax"] / r["parallax_error"] >= 10
                            for r in b["gaia_results"][0]["data"]
                        )
                    ),
                )
                chat_check(
                    "gaia_confirmed_no_match",
                    f"仅精确查询 Gaia DR3 source_id {empty_id or '1'}，"
                    "不更换编号或查询条件，说明是否匹配。",
                    lambda s, b: (
                        empty_id is not None
                        and s == 200
                        and b.get("status") == "error"
                        and not b["sources"]
                        and bool(b["gaia_results"])
                        and all(
                            r["status"] == "not_found"
                            and r["data"] == []
                            and r["query"]["source_id"] == empty_id
                            for r in b["gaia_results"]
                        )
                    ),
                )
                chat_check(
                    "simbad_to_gaia",
                    "先通过 SIMBAD 获取 M45 的坐标，再查中心附近 5 角分内最近的 3 个 Gaia DR3 源，"
                    "总结视场自行，说明位置候选、星团成员与参考历元的限制，给出来源。",
                    lambda s, b: (
                        gaia_success(s, b)
                        and b["results"]
                        and b["results"][0]["status"] == "success"
                        and abs(
                            b["gaia_results"][0]["query"]["ra_deg"]
                            - b["results"][0]["data"]["ra_deg"]
                        )
                        < 1e-7
                        and abs(
                            b["gaia_results"][0]["query"]["dec_deg"]
                            - b["results"][0]["data"]["dec_deg"]
                        )
                        < 1e-7
                        and "候选" in b["answer"]
                        and "成员" in b["answer"]
                    ),
                )
                chat_check(
                    "simbad_regression",
                    "请通过 SIMBAD 查询 Betelgeuse 的坐标与类型，给出来源。",
                    lambda s, b: (
                        s == 200
                        and b.get("status") == "success"
                        and bool(b["results"])
                        and b["results"][0]["status"] == "success"
                        and 88 < b["results"][0]["data"]["ra_deg"] < 90
                        and not b["literature_results"]
                        and not b["gaia_results"]
                    ),
                )
                chat_check(
                    "ads_regression",
                    "检索 bibcode 为 2007A&A...474..653V 的文献，给出书目信息与来源。",
                    lambda s, b: (
                        s == 200
                        and b.get("status") == "success"
                        and bool(b["literature_results"])
                        and b["literature_results"][0]["status"] == "success"
                        and b["literature_results"][0]["papers"][0]["bibcode"]
                        == "2007A&A...474..653V"
                        and not b["results"]
                        and not b["gaia_results"]
                    ),
                )
                chat_check(
                    "three_tools",
                    "分别完成三项独立查询并区分来源：SIMBAD 的 M45 坐标；Gaia DR3 source_id "
                    f"{SOURCE_ID} 的测量信息；ADS 的 bibcode:2016A&A...595A...2G 文献。"
                    "不假定该 Gaia 源是 M45 成员或该文的研究对象。",
                    lambda s, b: (
                        gaia_success(s, b)
                        and bool(b["results"])
                        and bool(b["literature_results"])
                        and all(
                            r["status"] == "success" for r in b["results"] + b["literature_results"]
                        )
                        and {r["name"] for r in b["sources"]} == {"SIMBAD", "ADS", "Gaia"}
                    ),
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
        report["server_exit_code"] = process.poll() if process is not None else None
        with socket.socket() as sock:
            sock.settimeout(1)
            report["server_port_closed"] = sock.connect_ex(("127.0.0.1", port)) != 0
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["outcome"] = (
            "passed"
            if len(report["checks"]) == 12
            and all(c["passed"] for c in report["checks"])
            and report["server_stopped"]
            and report["server_port_closed"]
            else "failed"
        )
        path = write_report(output, report)
        print(
            f"{report['outcome']}; server stopped={report['server_stopped']}; report: {path}",
            flush=True,
        )
    return 0 if report["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
