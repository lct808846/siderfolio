"""V0.9 schema4 upgrade and transactional rollback checks."""

import hashlib
import json
import sqlite3
import subprocess
import sys

import pytest


def test_schema4_upgrade_backup_and_failure_rollback(tmp_path, monkeypatch):
    from astroagent import knowledge, project_links
    from astroagent.config import LocalSettings
    from astroagent.conversations import ConversationRepository
    from astroagent.errors import ServiceError

    repo = ConversationRepository(LocalSettings(_env_file=None, data_dir=tmp_path))
    with sqlite3.connect(repo.path) as db:
        repo._migrate_v1(db)
        repo._migrate_v2(db)
        repo._migrate_v3(db)
        knowledge.migrate(db)
        db.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
            ("old-id", "preserved", "2026-01-01", "2026-01-01", 0, 0),
        )
        db.commit()
    original = project_links.migrate

    def broken(db):
        original(db)
        raise sqlite3.OperationalError("injected schema5 failure")

    monkeypatch.setattr(project_links, "migrate", broken)
    with pytest.raises(ServiceError):
        repo.initialize()
    with sqlite3.connect(repo.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT title FROM conversations").fetchone()[0] == "preserved"
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name IN ('project_links','project_link_requests')"
        ).fetchall()
    backup = next(tmp_path.glob("migration-v5-*.sqlite3"))
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT title FROM conversations").fetchone()[0] == "preserved"
    monkeypatch.setattr(project_links, "migrate", original)
    repo.initialize()
    try:
        with sqlite3.connect(repo.path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 5
            assert db.execute("SELECT title FROM conversations").fetchone()[0] == "preserved"
            assert (
                len(
                    db.execute(
                        "SELECT name FROM sqlite_master WHERE name IN "
                        "('project_links','project_link_requests')"
                    ).fetchall()
                )
                == 2
            )
    finally:
        repo.close()


def test_backup_restore_preserves_schema_and_rejects_overwrite(tmp_path):
    from astroagent.config import LocalSettings
    from astroagent.conversations import ConversationRepository

    source = tmp_path / "source"
    source.mkdir()
    repo = ConversationRepository(LocalSettings(_env_file=None, data_dir=source))
    repo.initialize()
    try:
        with sqlite3.connect(repo.path) as db:
            db.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
                ("saved-id", "backup sentinel", "2026-01-01", "2026-01-01", 0, 0),
            )
    finally:
        repo.close()
    backup = tmp_path / "backup.sqlite3"
    command = [sys.executable, "scripts/manage_data.py"]
    subprocess.run(
        [*command, "backup", "--database", str(repo.path), "--output", str(backup)],
        check=True,
        capture_output=True,
    )
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    manifest = json.loads(backup.with_name(backup.name + ".manifest.json").read_text("utf-8"))
    assert manifest["database_schema"] == 5 and manifest["sha256"] == digest
    restored = tmp_path / "restore"
    restore = [
        *command,
        "restore",
        "--backup",
        str(backup),
        "--new-data-dir",
        str(restored),
        "--expected-sha256",
        digest,
        "--confirm",
    ]
    subprocess.run(restore, check=True, capture_output=True)
    with sqlite3.connect(restored / "astroagent.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert db.execute("SELECT title FROM conversations").fetchone()[0] == "backup sentinel"
    before = (restored / "astroagent.sqlite3").read_bytes()
    assert subprocess.run(restore, capture_output=True).returncode != 0
    assert (restored / "astroagent.sqlite3").read_bytes() == before
