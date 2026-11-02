"""Opt-in schema5 to PostgreSQL migration of a disposable synthetic database."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

pytestmark = pytest.mark.postgres


def test_sqlite5_migrates_without_changing_source_and_refuses_replay(tmp_path):
    if os.getenv("ASTROAGENT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("Requires the dedicated PostgreSQL test instance")
    import psycopg
    from psycopg import sql

    from astroagent.config import LocalSettings
    from astroagent.conversations import ConversationRepository

    url = os.getenv("ASTROAGENT_TEST_DATABASE_URL", "")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("postgres", "postgresql")
        or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
        or not parsed.path.lstrip("/").startswith("astroagent_test")
        or parsed.query
        or parsed.fragment
    ):
        pytest.fail("A dedicated local astroagent_test database is required")
    source = tmp_path / "source"
    source.mkdir()
    repository = ConversationRepository(LocalSettings(_env_file=None, data_dir=source))
    repository.initialize()
    try:
        with sqlite3.connect(repository.path) as db:
            db.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
                ("synthetic-id", "Synthetic migration", "2026-01-01", "2026-01-01", 0, 0),
            )
    finally:
        repository.close()
    backup_path = tmp_path / "consistent-backup.sqlite3"
    with sqlite3.connect(repository.path) as source_db, sqlite3.connect(backup_path) as backup_db:
        source_db.backup(backup_db)
    with sqlite3.connect(backup_path) as backup_db:
        assert backup_db.execute("SELECT title FROM conversations").fetchone()[0] == (
            "Synthetic migration"
        )
    source_hash = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    name = "astroagent_test_" + uuid4().hex
    target = urlunsplit(parsed._replace(path="/" + name))
    with psycopg.connect(url, autocommit=True, connect_timeout=5) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
    try:
        env = os.environ.copy()
        env["ASTROAGENT_DATABASE_URL"] = target
        command = [
            sys.executable,
            "scripts/migrate_sqlite_to_postgres.py",
            "--source",
            str(backup_path),
            "--expected-sha256",
            source_hash,
            "--confirm",
        ]
        first_report = tmp_path / "first.json"
        first = subprocess.run(
            [*command, "--report", str(first_report)], env=env, capture_output=True, timeout=120
        )
        assert first.returncode == 0, first_report.read_text(encoding="utf-8")
        assert json.loads(first_report.read_text(encoding="utf-8"))["completed"]
        assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == source_hash
        with psycopg.connect(target) as db:
            assert db.execute(
                "SELECT title FROM conversations WHERE id=%s", ("synthetic-id",)
            ).fetchone() == ("Synthetic migration",)
        second_report = tmp_path / "second.json"
        second = subprocess.run(
            [*command, "--report", str(second_report)], env=env, capture_output=True, timeout=120
        )
        assert second.returncode != 0
        assert not json.loads(second_report.read_text(encoding="utf-8"))["completed"]
        with psycopg.connect(target) as db:
            assert db.execute("SELECT count(*) FROM conversations").fetchone()[0] == 1
    finally:
        with psycopg.connect(url, autocommit=True, connect_timeout=5) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
