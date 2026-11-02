"""Opt-in actual TCP acceptance with a new local test database; no model calls."""

import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import requests
from psycopg import sql


def main():
    url = os.environ.get("ASTROAGENT_TEST_DATABASE_URL", "")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("postgres", "postgresql")
        or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
        or not parsed.path.lstrip("/").startswith("astroagent_test")
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit("Dedicated local astroagent_test maintenance database required")
    name = "astroagent_test_" + uuid4().hex
    target = urlunsplit(parsed._replace(path="/" + name))
    out = Path("docs/test-records/v1.0.0/tcp-postgres") / datetime.now(UTC).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    out.mkdir(parents=True)
    real_model = os.environ.get("ASTROAGENT_ACCEPTANCE_REAL_MODEL") == "1"
    real_answer = os.environ.get("ASTROAGENT_ACCEPTANCE_REAL_ANSWER") == "1"
    report = {
        "kind": "postgres_tcp_synthetic_real_embedding"
        if real_model
        else "postgres_tcp_synthetic_no_model",
        "checks": [],
        "passed": False,
    }
    process = None
    created = False
    session = requests.Session()
    session.trust_env = False

    def check(name, value):
        report["checks"].append({"name": name, "passed": bool(value)})
        if not value:
            raise AssertionError(name)

    def start():
        nonlocal process
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env = os.environ.copy()
        env.update(
            ASTROAGENT_DATABASE_URL=target,
            DEEPSEEK_API_KEY=os.environ.get("ASTROAGENT_ACCEPTANCE_ANSWER_KEY", "")
            if real_answer
            else "",
            ADS_API_TOKEN="",
            ASTROAGENT_ALLOWED_HOSTS='["localhost","127.0.0.1"]',
        )
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
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("server exited before health check")
            try:
                if session.get(base + "/health", timeout=1).status_code == 200:
                    return base
            except requests.RequestException:
                pass
            time.sleep(0.2)
        raise RuntimeError("server health timeout")

    def stop():
        nonlocal process
        if process:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process = None

    try:
        with psycopg.connect(url, autocommit=True, connect_timeout=5) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name))
            )
        created = True
        base = start()
        state = session.get(base + "/api/v1/setup/status", timeout=10)
        check(
            "empty_database_requires_initialization",
            state.status_code == 200 and not state.json()["ready"],
        )
        denied = session.post(
            base + "/api/v1/setup/initialize", json={"confirmed": False}, timeout=10
        )
        check("initialization_requires_confirmation", denied.status_code == 422)
        ready = session.post(
            base + "/api/v1/setup/initialize", json={"confirmed": True}, timeout=30
        )
        check("initialization_succeeds", ready.status_code == 200 and ready.json()["ready"])
        project = session.post(
            base + "/api/v1/projects", json={"name": "TCP synthetic"}, timeout=10
        )
        check("project_created", project.status_code == 201)
        p = project.json()
        root = base + "/api/v1/projects/" + p["id"]
        uploaded = session.post(
            root + "/documents",
            files={
                "file": (
                    "fixture.md",
                    b"# Example\nBinary cluster synthetic evidence.\n",
                    "text/markdown",
                )
            },
            data={
                "options": json.dumps(
                    {"expected_revision": p["revision"], "client_request_id": str(uuid4())}
                )
            },
            timeout=60,
        )
        check(
            "document_uploaded",
            uploaded.status_code == 201 and uploaded.json()["document"]["state"] == "ready",
        )
        if real_model:
            revision = session.get(root, timeout=10).json()["revision"]
            built = session.post(
                root + "/rag/indexes",
                json={
                    "expected_revision": revision,
                    "client_request_id": str(uuid4()),
                    "confirmed": True,
                },
                timeout=180,
            )
            check(
                "real_model_vector_index",
                built.status_code == 200 and built.json()["state"] == "ready",
            )
        question = os.environ.get("ASTROAGENT_ACCEPTANCE_QUESTION", "binary cluster")
        preview = session.post(
            root + "/rag/previews",
            json={"question": question},
            timeout=180 if real_model else 30,
        )
        check(
            "lexical_preview_without_model",
            preview.status_code == 200 and bool(preview.json()["evidence"]),
        )
        if real_model:
            check("real_model_semantic_preview", preview.json()["semantic_status"] == "ready")
        if real_answer:
            value = preview.json()
            answer = session.post(
                root + "/rag/answers",
                json={
                    "client_request_id": str(uuid4()),
                    "preview_id": value["id"],
                    "confirmation_token": value["confirmation_token"],
                    "confirmed": True,
                },
                timeout=180,
            )
            if answer.status_code == 200:
                report["real_answer_state"] = answer.json()["record"]["state"]
                report["real_answer_citations"] = answer.json()["record"]["citation_labels"]
            check(
                "real_answer_has_validated_citations",
                answer.status_code == 200
                and answer.json()["record"]["state"] == "completed"
                and bool(answer.json()["record"]["citation_labels"]),
            )
        stop()
        base = start()
        state = session.get(base + "/api/v1/setup/status", timeout=10)
        check("restart_restores_database", state.status_code == 200 and state.json()["ready"])
        restored = session.get(base + "/api/v1/projects/" + p["id"], timeout=10)
        check(
            "project_survives_restart",
            restored.status_code == 200 and restored.json()["name"] == p["name"],
        )
        report["passed"] = True
    except Exception as exc:
        report["failure"] = type(exc).__name__ + ": " + str(exc)
    finally:
        stop()
        if created:
            with psycopg.connect(url, autocommit=True, connect_timeout=5) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        report["server_stopped"] = process is None
        report["test_database_dropped"] = created
        (out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(out)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
