"""测量已启动服务的串行响应延迟，按服务版本保存每次记录。"""

import argparse
import time
from datetime import UTC, datetime

import requests
from record_utils import create_record_directory, write_report


def sample_count(value):
    count = int(value)
    if not 1 <= count <= 20:
        raise argparse.ArgumentTypeError("sample count must be between 1 and 20")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--samples", type=sample_count, default=3)
    parser.add_argument("--health-samples", type=sample_count, default=5)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    schema = requests.get(base + "/openapi.json", timeout=10)
    schema.raise_for_status()
    version = schema.json()["info"]["version"]
    output = create_record_directory("latency", version=version)
    message = "请查询 Betelgeuse 的坐标和天体类型，并给出数据来源。"
    report = {
        "application_version": version,
        "measured_at": datetime.now(UTC).isoformat(),
        "message": message,
        "method": "sequential complete HTTP response; not a concurrency or percentile benchmark",
        "health": [],
        "chat": [],
    }
    try:
        for endpoint, count in (("health", args.health_samples), ("chat", args.samples)):
            for index in range(count):
                started = time.perf_counter()
                response = (
                    requests.get(base + "/health", timeout=5)
                    if endpoint == "health"
                    else requests.post(
                        base + "/api/v1/chat", json={"message": message}, timeout=180
                    )
                )
                elapsed = time.perf_counter() - started
                sample = {
                    "sample": index + 1,
                    "seconds": round(elapsed, 4),
                    "http_status": response.status_code,
                }
                report[endpoint].append(sample)
                response.raise_for_status()
                body = response.json()
                if endpoint == "chat":
                    sample.update(
                        status=body.get("status"),
                        query_count=len(body.get("results", [])),
                        source_count=len(body.get("sources", [])),
                    )
                    if sample["status"] != "success" or sample["source_count"] < 1:
                        raise RuntimeError("Chat query did not complete successfully")
                print(f"{endpoint} {index + 1}: {elapsed:.4f}s", flush=True)
        report["outcome"] = "passed"
    except Exception as exc:
        report["outcome"] = "failed"
        report["failure_type"] = type(exc).__name__
        raise
    finally:
        for endpoint in ("health", "chat"):
            values = [sample["seconds"] for sample in report[endpoint]]
            if values:
                report[endpoint + "_summary"] = {
                    "mean_seconds": round(sum(values) / len(values), 4),
                    "min_seconds": min(values),
                    "max_seconds": max(values),
                }
        print(f"Report: {write_report(output, report)}", flush=True)


if __name__ == "__main__":
    main()
