"""Run the frozen, exploratory public-paper evaluation on an isolated local PostgreSQL database."""

import hashlib
import json
import os
import tempfile
import time
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql
from pypdf import PdfReader, PdfWriter

import astroagent.main as main
from astroagent.postgres import PostgresRepository


def main_eval():
    url = os.getenv("ASTROAGENT_TEST_DATABASE_URL", "")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("postgres", "postgresql")
        or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
        or not parsed.path.lstrip("/").startswith("astroagent_test")
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit("An independent local astroagent_test database is required")
    plan_file = Path("docs/development/v1.0.0/automated-evaluation-plan.json")
    raw_plan = plan_file.read_bytes()
    plan = json.loads(raw_plan)
    if os.getenv("ASTROAGENT_RAG_MODEL_SHA256") != plan["model_tree_sha256"]:
        raise SystemExit("The configured model must match the frozen plan")
    output = Path("docs/test-records/v1.0.0/automatic-evaluation") / datetime.now(UTC).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    output.mkdir(parents=True)
    report = {
        "kind": plan["evaluation_kind"],
        "plan_sha256": hashlib.sha256(raw_plan).hexdigest(),
        "model_sha256": plan["model_tree_sha256"],
        "limitations": plan["limitations"],
        "cases": [],
        "passed": False,
    }
    answer_check = os.getenv("ASTROAGENT_AUTOMATIC_ANSWER") == "1"
    if answer_check:
        answer_plan = Path("docs/development/v1.0.0/automatic-answer-check.json").read_bytes()
        report["answer_plan_sha256"] = hashlib.sha256(answer_plan).hexdigest()
    dbname = "astroagent_test_" + uuid4().hex
    target = urlunsplit(parsed._replace(path="/" + dbname))
    created = False

    class TestRepository(PostgresRepository):
        def initialize(self, *, create=True):
            return super().initialize(create=create)

    try:
        with psycopg.connect(url, autocommit=True, connect_timeout=5) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(dbname))
            )
        created = True
        with tempfile.TemporaryDirectory(prefix="astroagent-eval-v10-") as directory:
            env = {
                "ASTROAGENT_DATABASE_URL": target,
                "ASTROAGENT_DATA_DIR": directory,
                "ASTROAGENT_ALLOWED_HOSTS": '["testserver","127.0.0.1","localhost"]',
                "DEEPSEEK_API_KEY": os.getenv("ASTROAGENT_ACCEPTANCE_ANSWER_KEY", "")
                if answer_check
                else "",
                "ADS_API_TOKEN": "",
            }
            with (
                patch.dict(os.environ, env),
                patch.object(main, "PostgresRepository", TestRepository),
            ):
                with TestClient(main.app) as client:
                    response = client.post(
                        "/api/v1/projects", json={"name": "Public-page evaluation"}
                    )
                    response.raise_for_status()
                    project = response.json()
                    base = "/api/v1/projects/" + project["id"]
                    docs = {}
                    for item in plan["corpus"]:
                        path = Path(os.environ["ASTROAGENT_EVAL_PDF_" + item["id"].upper()])
                        raw = path.read_bytes()
                        if hashlib.sha256(raw).hexdigest() != item["original_sha256"]:
                            raise ValueError("Public PDF hash differs from frozen plan")
                        reader, writer = PdfReader(BytesIO(raw), strict=True), PdfWriter()
                        writer.add_page(reader.pages[item["physical_page"] - 1])
                        page = BytesIO()
                        writer.write(page)
                        revision = client.get(base).json()["revision"]
                        uploaded = client.post(
                            base + "/documents",
                            files={
                                "file": (item["id"] + ".pdf", page.getvalue(), "application/pdf")
                            },
                            data={
                                "options": json.dumps(
                                    {
                                        "expected_revision": revision,
                                        "client_request_id": str(uuid4()),
                                    }
                                )
                            },
                        )
                        uploaded.raise_for_status()
                        document = uploaded.json()["document"]
                        if document["state"] not in ("ready", "partial"):
                            raise ValueError("Public paper page did not parse")
                        docs[item["id"]] = document["id"]
                    revision = client.get(base).json()["revision"]
                    built = client.post(
                        base + "/rag/indexes",
                        json={
                            "expected_revision": revision,
                            "client_request_id": str(uuid4()),
                            "confirmed": True,
                        },
                    )
                    built.raise_for_status()
                    if built.json()["state"] != "ready":
                        raise ValueError("Real embedding index did not become ready")
                    for case in plan["cases"]:
                        started = time.perf_counter()
                        result = client.post(
                            base + "/rag/previews", json={"question": case["query"]}
                        )
                        result.raise_for_status()
                        value = result.json()
                        hits = value["evidence"]
                        invalid = 0
                        for item in hits:
                            stored = client.get(
                                base + "/knowledge/evidence/" + item["view"]["evidence"]["id"]
                            )
                            if stored.status_code != 200:
                                invalid += 1
                                continue
                            actual = stored.json()
                            invalid += not (
                                actual["evidence"]["validity"] == "available"
                                and actual["text"] == item["view"]["text"]
                                and actual["evidence"]["text_sha256"]
                                == item["view"]["evidence"]["text_sha256"]
                            )
                        covered = (
                            not hits
                            if case["expected"] is None
                            else any(
                                item["view"]["evidence"]["document_id"] == docs[case["expected"]]
                                for item in hits[:5]
                            )
                        )
                        report["cases"].append(
                            {
                                "id": case["id"],
                                "group": case["group"],
                                "covered": covered,
                                "status": value["status"],
                                "semantic_status": value["semantic_status"],
                                "lexical_candidates": value["lexical_candidates"],
                                "semantic_candidates": value["semantic_candidates"],
                                "returned_sources": [
                                    next(
                                        (
                                            k
                                            for k, v in docs.items()
                                            if v == item["view"]["evidence"]["document_id"]
                                        ),
                                        None,
                                    )
                                    for item in hits
                                ],
                                "invalid_citations": invalid,
                                "seconds": round(time.perf_counter() - started, 3),
                            }
                        )
                        consumed = False
                        if answer_check and case["group"] == "unanswerable" and hits:
                            generated = client.post(
                                base + "/rag/answers",
                                json={
                                    "client_request_id": str(uuid4()),
                                    "preview_id": value["id"],
                                    "confirmation_token": value["confirmation_token"],
                                    "confirmed": True,
                                },
                            )
                            report["cases"][-1]["answer_http_status"] = generated.status_code
                            if generated.status_code == 200:
                                record = generated.json()["record"]
                                report["cases"][-1]["answer_state"] = record["state"]
                                report["cases"][-1]["answer_citations"] = record["citation_labels"]
                                consumed = True
                        if not consumed:
                            discarded = client.request(
                                "DELETE", base + "/rag/previews/" + value["id"], json={}
                            )
                            discarded.raise_for_status()
        english = [c for c in report["cases"] if c["group"] == "english"]
        chinese = [c for c in report["cases"] if c["group"] == "chinese"]
        negative = [c for c in report["cases"] if c["group"] == "unanswerable"]
        metrics = {
            "english_hybrid_recall_at_5": sum(c["covered"] for c in english) / len(english),
            "chinese_hybrid_recall_at_5": sum(c["covered"] for c in chinese) / len(chinese),
            "unanswerable_refusal_rate": sum(
                c["covered"] and c["status"] == "no_results" for c in negative
            )
            / len(negative),
            "invalid_citation_count": sum(c["invalid_citations"] for c in report["cases"]),
        }
        report["metrics"] = metrics
        if answer_check:
            report["answer_level_refusal_rate"] = sum(
                c["status"] == "no_results" or c.get("answer_state") == "insufficient_evidence"
                for c in negative
            ) / len(negative)
        threshold = plan["thresholds"]
        report["passed"] = (
            metrics["english_hybrid_recall_at_5"] >= threshold["english_hybrid_recall_at_5"]
            and metrics["chinese_hybrid_recall_at_5"] >= threshold["chinese_hybrid_recall_at_5"]
            and metrics["unanswerable_refusal_rate"] >= threshold["unanswerable_refusal_rate"]
            and metrics["invalid_citation_count"] <= threshold["invalid_citation_count"]
        )
    except Exception as exc:
        report["failure"] = type(exc).__name__
        if hasattr(exc, "response") and exc.response is not None:
            report["failure_http_status"] = exc.response.status_code
            report["failure_http_path"] = str(exc.response.request.url.path)
    finally:
        if created:
            with psycopg.connect(url, autocommit=True, connect_timeout=5) as admin:
                admin.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(dbname))
                )
        report["test_database_dropped"] = created
        (output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main_eval())
