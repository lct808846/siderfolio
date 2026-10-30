"""显式 --run 后，使用合成Markdown和临时库进行本地知识库评估。开发时不自动执行。"""

import argparse
import json
import math
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", action="store_true", help="显式运行评估；使用临时数据库，不访问外部服务"
    )
    options = parser.parse_args()
    if not options.run:
        parser.error("评估未执行；发布前明确使用 --run。")
    import httpx
    import requests
    from fastapi.testclient import TestClient

    from astroagent import __version__
    from astroagent.main import app

    root = Path(__file__).resolve().parents[1]
    fixtures = root / "scripts/knowledge_eval"
    definition = json.loads((fixtures / "cases.json").read_text(encoding="utf-8"))
    report = {
        "version": __version__,
        "fixture_version": definition["fixture_version"],
        "data": "synthetic",
        "external_services": False,
        "thresholds": definition["thresholds"],
        "cases": [],
    }

    def blocked(*args, **kwargs):
        raise AssertionError("Evaluation must not access external HTTP")

    with tempfile.TemporaryDirectory(prefix="astroagent-eval-") as temporary:
        with (
            patch.dict(
                "os.environ",
                {
                    "ASTROAGENT_DATA_DIR": temporary,
                    "ASTROAGENT_ALLOWED_HOSTS": '["testserver","localhost","127.0.0.1"]',
                },
            ),
            patch.object(requests.Session, "request", blocked),
            patch.object(httpx.HTTPTransport, "handle_request", blocked),
            TestClient(app) as client,
        ):
            response = client.post(
                "/api/v1/projects", json={"name": "Synthetic knowledge evaluation"}
            )
            response.raise_for_status()
            project = response.json()
            response = client.post(
                f"/api/v1/projects/{project['id']}/documents",
                files={
                    "file": ("corpus.md", (fixtures / "corpus.md").read_bytes(), "text/markdown")
                },
                data={
                    "options": json.dumps(
                        {
                            "expected_revision": project["revision"],
                            "client_request_id": str(uuid4()),
                        }
                    )
                },
            )
            response.raise_for_status()
            document = response.json()["document"]
            if document["state"] not in ("ready", "partial"):
                raise RuntimeError("Synthetic document was not indexed; evaluation is incomplete")
            for case in definition["cases"]:
                started = time.perf_counter()
                response = client.post(
                    f"/api/v1/projects/{project['id']}/knowledge/answers",
                    json={"query": case["query"], "limit": 5},
                )
                elapsed = time.perf_counter() - started
                response.raise_for_status()
                result = response.json()
                valid = True
                for hit in result["hits"]:
                    reference = client.get(
                        f"/api/v1/projects/{project['id']}/knowledge/evidence/{hit['evidence']['id']}"
                    )
                    reference.raise_for_status()
                    value = reference.json()
                    valid = (
                        valid
                        and value["evidence"]["validity"] == "available"
                        and value["text"] == hit["text"]
                    )
                covered = (
                    any(
                        hit["evidence"]["document_id"] == document["id"]
                        and hit["evidence"]["line_start"]
                        <= case["expected_line"]
                        <= hit["evidence"]["line_end"]
                        and case["expected_phrase"] in hit["text"]
                        for hit in result["hits"]
                    )
                    if case["expected_line"] is not None
                    else not result["hits"]
                )
                report["cases"].append(
                    {
                        "id": case["id"],
                        "status_matches": result["status"] == case["expected_status"],
                        "covered": covered,
                        "references_valid": valid,
                        "seconds": elapsed,
                        "returned_count": result["returned_count"],
                    }
                )
    positives = [
        row
        for case, row in zip(definition["cases"], report["cases"], strict=True)
        if case["expected_status"] == "evidence_found"
    ]
    negatives = [
        row
        for case, row in zip(definition["cases"], report["cases"], strict=True)
        if case["expected_status"] == "insufficient_evidence"
    ]
    latencies = sorted(row["seconds"] for row in report["cases"])
    metrics = {
        "positive_top5_coverage": sum(row["covered"] and row["status_matches"] for row in positives)
        / len(positives),
        "no_answer_refusal_rate": sum(row["covered"] and row["status_matches"] for row in negatives)
        / len(negatives),
        "invalid_references": sum(not row["references_valid"] for row in report["cases"]),
        "p95_seconds": latencies[math.ceil(len(latencies) * 0.95) - 1],
    }
    thresholds = definition["thresholds"]
    report["metrics"] = metrics
    report["passed"] = (
        metrics["positive_top5_coverage"] >= thresholds["positive_top5_coverage"]
        and metrics["no_answer_refusal_rate"] >= thresholds["no_answer_refusal_rate"]
        and metrics["invalid_references"] <= thresholds["invalid_references"]
        and metrics["p95_seconds"] <= thresholds["p95_seconds"]
    )
    output = (
        root
        / f"docs/test-records/v{__version__}/knowledge-evaluation"
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
