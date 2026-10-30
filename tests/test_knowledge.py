"""V0.8 本地知识库合成样本及隐私归档回归。"""

import hashlib
import json
import os
import shutil
import sqlite3
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest
from test_projects import project

pytest_plugins = ("test_projects",)


def test_segment_limit_at_exact_boundary():
    from astroagent.knowledge_text import segment

    sources = [{"position": i, "page": i, "state": "text", "text": "x"} for i in range(1, 25002)]
    args = (str(uuid4()), str(uuid4()), str(uuid4()))
    assert len(segment(sources[:25000], *args)) == 25000
    with pytest.raises(ValueError, match="25000"):
        segment(sources, *args)


@pytest.mark.parametrize("old_version", [1, 2])
def test_older_schema_migrates_with_original_data_and_backup(tmp_path, old_version):
    from astroagent.config import LocalSettings
    from astroagent.conversations import ConversationRepository

    repo = ConversationRepository(LocalSettings(_env_file=None, data_dir=tmp_path))
    with sqlite3.connect(repo.path) as db:
        repo._migrate_v1(db)
        if old_version == 2:
            repo._migrate_v2(db)
        db.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at, revision) "
            "VALUES (?, ?, ?, ?, ?)",
            ("old-id", "旧会话", "2026-01-01", "2026-01-01", 0),
        )
        db.commit()
    repo.initialize()
    try:
        with sqlite3.connect(repo.path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 4
            assert db.execute("SELECT title FROM conversations").fetchone()[0] == "旧会话"
        backups = list(tmp_path.glob(f"migration-v{old_version + 1}-*.sqlite3"))
        assert backups
        with sqlite3.connect(backups[0]) as backup:
            assert backup.execute("PRAGMA user_version").fetchone()[0] == old_version
            assert backup.execute("SELECT title FROM conversations").fetchone()[0] == "旧会话"
    finally:
        repo.close()


def test_schema3_backup_restores_in_separate_directory(tmp_path):
    from astroagent.config import LocalSettings
    from astroagent.conversations import ConversationRepository

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    repo = ConversationRepository(LocalSettings(_env_file=None, data_dir=source_dir))
    with sqlite3.connect(repo.path) as db:
        repo._migrate_v1(db)
        repo._migrate_v2(db)
        repo._migrate_v3(db)
        db.execute(
            "INSERT INTO conversations VALUES (?,?,?,?,?,?)",
            ("old-id", "old conversation", "2026-01-01", "2026-01-01", 0, 0),
        )
        db.commit()
    repo.initialize()
    repo.close()
    backup = next(source_dir.glob("migration-v4-*.sqlite3"))
    restore_dir = tmp_path / "restored"
    restore_dir.mkdir()
    shutil.copyfile(backup, restore_dir / "astroagent.sqlite3")
    restored = ConversationRepository(LocalSettings(_env_file=None, data_dir=restore_dir))
    with sqlite3.connect(restored.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("SELECT title FROM conversations").fetchone()[0] == "old conversation"
    restored.initialize()
    try:
        with sqlite3.connect(restored.path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 4
            assert db.execute("SELECT title FROM conversations").fetchone()[0] == "old conversation"
    finally:
        restored.close()


def test_higher_schema_is_refused_without_modification(tmp_path):
    from astroagent.config import LocalSettings
    from astroagent.conversations import ConversationRepository
    from astroagent.errors import ServiceError

    repo = ConversationRepository(LocalSettings(_env_file=None, data_dir=tmp_path))
    with sqlite3.connect(repo.path) as db:
        db.execute("PRAGMA user_version=99")
        db.execute("CREATE TABLE sentinel(value TEXT)")
        db.execute("INSERT INTO sentinel VALUES ('unchanged')")
    with pytest.raises(ServiceError):
        repo.initialize()
    with sqlite3.connect(repo.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99
        assert db.execute("SELECT value FROM sentinel").fetchone()[0] == "unchanged"


def test_schema3_migration_backup_and_failed_upgrade_rollback(tmp_path, monkeypatch):
    from astroagent import knowledge
    from astroagent.config import LocalSettings
    from astroagent.conversations import ConversationRepository
    from astroagent.errors import ServiceError

    repo = ConversationRepository(LocalSettings(_env_file=None, data_dir=tmp_path))
    with sqlite3.connect(repo.path) as db:
        repo._migrate_v1(db)
        repo._migrate_v2(db)
        repo._migrate_v3(db)
        db.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
            ("old-id", "旧会话", "2026-01-01", "2026-01-01", 0, 0),
        )
        db.commit()
    original = knowledge.migrate

    def broken(db):
        original(db)
        raise sqlite3.OperationalError("synthetic migration failure")

    monkeypatch.setattr(knowledge, "migrate", broken)
    with pytest.raises(ServiceError):
        repo.initialize()
    with sqlite3.connect(repo.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("SELECT title FROM conversations").fetchone()[0] == "旧会话"
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='knowledge_documents'"
        ).fetchall()
    assert list(tmp_path.glob("migration-v4-*.sqlite3"))
    monkeypatch.setattr(knowledge, "migrate", original)
    repo.initialize()
    try:
        with sqlite3.connect(repo.path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 4
            assert db.execute("SELECT title FROM conversations").fetchone()[0] == "旧会话"
            assert db.execute("SELECT json_extract('{\"v\":1}', '$.v')").fetchone()[0] == 1
            assert (
                db.execute("SELECT value FROM knowledge_meta WHERE key='fts_available'").fetchone()[
                    0
                ]
                == "1"
            )
    finally:
        repo.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object-specific failure path")
def test_parser_refuses_when_windows_job_is_unavailable(monkeypatch):
    from astroagent import knowledge_parser
    from astroagent.errors import ServiceError

    processes, directories = [], []
    popen = knowledge_parser.subprocess.Popen

    def start(*args, **kwargs):
        directories.append(kwargs["cwd"])
        child = popen(*args, **kwargs)
        processes.append(child)
        return child

    def unavailable(process):
        raise OSError("synthetic job failure")

    monkeypatch.setattr(knowledge_parser.subprocess, "Popen", start)
    monkeypatch.setattr(knowledge_parser, "windows_job", unavailable)
    with pytest.raises(ServiceError) as exc:
        knowledge_parser.parse_document(b"# synthetic private text", "text/markdown")
    assert exc.value.error.code == "knowledge_parser_unavailable"
    assert processes and processes[0].poll() is not None
    assert all(not directory.exists() for directory in directories)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object-specific memory limit")
def test_parser_windows_job_memory_limit(monkeypatch, tmp_path):
    from astroagent import knowledge_parser

    worker = tmp_path / "knowledge_worker.py"
    worker.write_text(
        "import json,sys\n"
        "sys.stdin.buffer.read(1)\n"
        "try:\n"
        "    bytearray(800 * 1024**2)\n"
        "except MemoryError:\n"
        "    result = {'ok': True, 'limited': True}\n"
        "else:\n"
        "    result = {'ok': True, 'limited': False}\n"
        "with open(sys.argv[3], 'w') as output:\n"
        "    json.dump(result, output)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(knowledge_parser, "__file__", str(tmp_path / "knowledge_parser.py"))
    assert knowledge_parser.parse_document(b"synthetic", "text/markdown")["limited"] is True


def test_parser_timeout_terminates_worker_and_cleans_temp(monkeypatch, tmp_path):
    from astroagent import knowledge_parser
    from astroagent.errors import ServiceError

    worker = tmp_path / "knowledge_worker.py"
    worker.write_text(
        "import sys,time\nsys.stdin.buffer.read(1)\ntime.sleep(60)\n", encoding="utf-8"
    )
    monkeypatch.setattr(knowledge_parser, "__file__", str(tmp_path / "knowledge_parser.py"))
    processes, directories = [], []
    popen = knowledge_parser.subprocess.Popen

    def start(*args, **kwargs):
        directories.append(kwargs["cwd"])
        child = popen(*args, **kwargs)
        processes.append(child)
        return child

    monkeypatch.setattr(knowledge_parser.subprocess, "Popen", start)
    with pytest.raises(ServiceError) as exc:
        knowledge_parser.parse_document(b"# synthetic timeout", "text/markdown")
    assert exc.value.error.code == "knowledge_parser_timeout"
    assert processes and processes[0].poll() is not None
    assert all(not directory.exists() for directory in directories)


def upload(
    client,
    base,
    content,
    revision,
    *,
    name="sample.md",
    key=None,
    document_id=None,
    restore_version_id=None,
):
    path = base + "/documents" + (f"/{document_id}/versions" if document_id else "")
    options = {"expected_revision": revision, "client_request_id": key or str(uuid4())}
    if restore_version_id is not None:
        options["restore_version_id"] = restore_version_id
    return client.post(
        path,
        files={"file": (name, content, "application/octet-stream")},
        data={"options": json.dumps(options)},
    )


def test_public_pdf_when_explicitly_provided(client):
    from pypdf import PdfReader

    path = os.getenv("ASTROAGENT_ACCEPTANCE_PUBLIC_PDF")
    if not path:
        pytest.skip("public PDF acceptance requires explicit local fixture")
    raw = Path(path).read_bytes()
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    response = upload(client, base, raw, 0, name="public.pdf")
    assert response.status_code == 201, response.text
    document = response.json()["document"]
    version = document["current_version_id"]
    assert document["state"] in ("ready", "partial")
    assert (
        client.get(f"{base}/documents/{document['id']}/versions/{version}/content").content == raw
    )
    first = client.get(
        f"{base}/documents/{document['id']}/versions/{version}/text?source_position=1"
    )
    assert first.status_code == 200 and "binary star clusters" in first.json()["text"]
    reader = PdfReader(BytesIO(raw), strict=True)
    for position, page in enumerate(reader.pages, start=1):
        response = client.get(
            f"{base}/documents/{document['id']}/versions/{version}/text?source_position={position}"
        )
        assert response.status_code == 200, response.text
        actual = response.json()
        expected = page.extract_text() or ""
        assert actual["page"] == position and not actual["truncated"]
        assert actual["text"] == expected
        assert actual["sha256"] == hashlib.sha256(expected.encode()).hexdigest()
    result = client.post(base + "/knowledge/answers", json={"query": "dynamical fate"})
    assert result.status_code == 200, result.text
    assert any(hit["evidence"]["page"] == 1 for hit in result.json()["hits"])


def test_oversized_upload_does_not_create_document(client):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    response = upload(client, base, b"x" * (20 * 1024**2 + 1), 0)
    assert response.status_code == 413, response.text
    assert client.get(base + "/documents").json() == []
    assert client.get(base).json()["revision"] == 0


def test_pdf_page_and_markdown_line_limits(client):
    from pypdf import PdfWriter

    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    writer = PdfWriter()
    for _ in range(501):
        writer.add_blank_page(width=100, height=100)
    raw = BytesIO()
    writer.write(raw)
    pdf = upload(client, base, raw.getvalue(), 0, name="too-many-pages.pdf")
    assert pdf.status_code == 422 and pdf.json()["document"]["state"] == "failed", pdf.text
    revision = client.get(base).json()["revision"]
    markdown = upload(client, base, b"line\n" * 200001, revision, name="too-many-lines.md")
    assert markdown.status_code == 422 and markdown.json()["document"]["state"] == "failed", (
        markdown.text
    )
    answer = client.post(base + "/knowledge/answers", json={"query": "line"})
    assert answer.status_code == 200 and answer.json()["status"] == "insufficient_evidence"


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_archive_roundtrip_and_refusal_with_knowledge(client, version):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    empty = client.post(base + "/archive", json={"expected_revision": 0, "format_version": version})
    assert empty.status_code == 200, empty.text
    restored = client.post(
        "/api/v1/projects/import",
        content=empty.content,
        headers={"Content-Type": "application/zip"},
    )
    assert restored.status_code == 201, restored.text
    restored_id = restored.json()["project"]["id"]
    assert client.get(f"/api/v1/projects/{restored_id}/documents").json() == []
    assert upload(client, base, b"# evidence\nsynthetic", 0).status_code == 201
    revision = client.get(base).json()["revision"]
    refused = client.post(
        base + "/archive", json={"expected_revision": revision, "format_version": version}
    )
    assert refused.status_code == 409, refused.text


def test_multipart_rejects_extra_field_and_oversized_options(client):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    options = json.dumps({"expected_revision": 0, "client_request_id": str(uuid4())})
    extra = client.post(
        base + "/documents",
        files={"file": ("a.md", b"synthetic", "text/markdown")},
        data={"options": options, "unexpected": "x"},
    )
    assert extra.status_code == 422, extra.text
    oversized = client.post(
        base + "/documents",
        files={"file": ("a.md", b"synthetic", "text/markdown")},
        data={"options": "x" * 32769},
    )
    assert oversized.status_code in (413, 422), oversized.text
    assert client.get(base + "/documents").json() == []
    assert client.get(base).json()["revision"] == 0


def test_upload_transport_actual_bytes_and_content_encoding_are_bounded(client):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    headers = {"Content-Type": "multipart/form-data; boundary=synthetic"}
    oversized = client.post(
        base + "/documents", headers=headers, content=b"x" * (20 * 1024**2 + 64 * 1024 + 1)
    )
    assert oversized.status_code == 413, oversized.text
    assert oversized.json()["error"]["code"] == "knowledge_upload_too_large"
    compressed = client.post(
        base + "/documents",
        headers={**headers, "Content-Encoding": "gzip"},
        content=b"not-a-compressed-file",
    )
    assert compressed.status_code == 415, compressed.text
    assert client.get(base + "/documents").json() == []
    assert client.get(base).json()["revision"] == 0


def test_upload_idempotency_conflict_and_busy_rejection(client):
    from astroagent.knowledge_service import PARSER_SLOT

    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    key = str(uuid4())
    content = b"# synthetic\nunique-idempotency-term\n"
    first = upload(client, base, content, 0, key=key)
    assert first.status_code == 201, first.text
    repeated = upload(client, base, content, 0, key=key)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["operation"]["id"] == first.json()["operation"]["id"]
    changed = upload(client, base, b"different content", 0, key=key)
    assert changed.status_code == 409, changed.text
    stale = upload(client, base, b"different content", 0)
    assert stale.status_code == 409, stale.text
    revision = client.get(base).json()["revision"]
    assert PARSER_SLOT.acquire(blocking=False)
    try:
        busy = upload(client, base, b"# busy", revision)
        assert busy.status_code == 503, busy.text
    finally:
        PARSER_SLOT.release()
    assert len(client.get(base + "/documents").json()) == 1
    assert client.get(base).json()["revision"] == revision


@pytest.mark.parametrize("limit", ["documents", "versions", "operations"])
def test_project_knowledge_count_limits_are_atomic(client, limit):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    first = upload(client, base, b"# seed\nexisting text", 0)
    assert first.status_code == 201, first.text
    document = first.json()["document"]
    revision = client.get(base).json()["revision"]
    path = Path(os.environ["ASTROAGENT_DATA_DIR"]) / "astroagent.sqlite3"
    with sqlite3.connect(path) as db:
        if limit == "documents":
            for _ in range(99):
                db.execute(
                    "INSERT INTO knowledge_documents VALUES (?,?,?)", (str(uuid4()), p["id"], "{}")
                )
        elif limit == "versions":
            record = db.execute(
                "SELECT record FROM knowledge_versions WHERE document_id=?", (document["id"],)
            ).fetchone()[0]
            for _ in range(199):
                db.execute(
                    "INSERT INTO knowledge_versions VALUES (?,?,?,?,?)",
                    (str(uuid4()), document["id"], p["id"], record, None),
                )
        else:
            for _ in range(499):
                db.execute(
                    "INSERT INTO knowledge_operations VALUES (?,?,?,?,?,?,?)",
                    (str(uuid4()), p["id"], str(uuid4()), "synthetic", "done", "{}", 0),
                )
        db.commit()
    before = client.get(base).json()["revision"]
    result = upload(
        client,
        base,
        b"# distinct\nnew text",
        revision,
        document_id=document["id"] if limit == "versions" else None,
    )
    assert result.status_code == 409, result.text
    assert (
        result.json()["error"]["code"]
        == f"knowledge_{limit[:-1] if limit != 'operations' else 'operation'}_limit"
    )
    assert client.get(base).json()["revision"] == before


def test_candidate_scan_limit_and_evidence_quota(client):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    assert upload(client, base, "# 测试\n星系证据 uniqueplanet".encode(), 0).status_code == 201
    path = Path(os.environ["ASTROAGENT_DATA_DIR"]) / "astroagent.sqlite3"
    with sqlite3.connect(path) as db:
        original = db.execute(
            "SELECT id, normalized FROM knowledge_units WHERE project_id=?", (p["id"],)
        ).fetchone()
        db.execute(
            "UPDATE knowledge_units SET normalized=? WHERE id=?",
            ("星" * (7 * 1024**2), original[0]),
        )
        db.commit()
    too_broad = client.post(base + "/knowledge/answers", json={"query": "星"})
    assert too_broad.status_code == 422, too_broad.text
    assert too_broad.json()["error"]["code"] == "knowledge_query_too_broad"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE knowledge_units SET normalized=? WHERE id=?", (original[1], original[0]))
        doc_id = db.execute(
            "SELECT id FROM knowledge_documents WHERE project_id=?", (p["id"],)
        ).fetchone()[0]
        db.executemany(
            "INSERT INTO knowledge_evidence VALUES (?,?,?,?)",
            [(str(uuid4()), p["id"], doc_id, "{}") for _ in range(1000)],
        )
        db.commit()
    over_quota = client.post(base + "/knowledge/answers", json={"query": "uniqueplanet"})
    assert over_quota.status_code == 409, over_quota.text
    assert over_quota.json()["error"]["code"] == "knowledge_evidence_limit"
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM knowledge_evidence WHERE project_id=?", (p["id"],)
            ).fetchone()[0]
            == 1000
        )


def test_storage_budget_rejects_upload_without_replacing_original(client):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    raw = b"# existing\npreserved uniqueplanet"
    first = upload(client, base, raw, 0)
    assert first.status_code == 201, first.text
    document = first.json()["document"]
    version = document["current_version_id"]
    revision = client.get(base).json()["revision"]
    path = Path(os.environ["ASTROAGENT_DATA_DIR"]) / "astroagent.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE knowledge_operations SET reserved_bytes=? WHERE project_id=?",
            (256 * 1024**2, p["id"]),
        )
        db.commit()
    rejected = upload(client, base, b"# replacement", revision, document_id=document["id"])
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "project_storage_limit"
    assert client.get(base).json()["revision"] == revision
    detail = client.get(base + "/documents/" + document["id"]).json()
    assert detail["current_version_id"] == version
    assert (
        client.get(f"{base}/documents/{document['id']}/versions/{version}/content").content == raw
    )


@pytest.mark.skipif(
    os.getenv("ASTROAGENT_RUN_LARGE_ACCEPTANCE") != "1",
    reason="explicit opt-in for 256 MiB disk acceptance",
)
def test_real_256_mib_stored_payload_triggers_budget_and_preserves_original(client):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    raw = b"# Original\nuniqueplanet preserved"
    first = upload(client, base, raw, 0)
    assert first.status_code == 201, first.text
    document = first.json()["document"]
    version = document["current_version_id"]
    revision = client.get(base).json()["revision"]
    path = Path(os.environ["ASTROAGENT_DATA_DIR"]) / "astroagent.sqlite3"
    fake_version = str(uuid4())
    with sqlite3.connect(path) as db:
        record = db.execute(
            "SELECT record FROM knowledge_versions WHERE id=?", (version,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO knowledge_versions VALUES (?,?,?,?,zeroblob(?))",
            (fake_version, document["id"], p["id"], record, 256 * 1024**2),
        )
        db.commit()
        assert (
            db.execute(
                "SELECT length(content) FROM knowledge_versions WHERE id=?", (fake_version,)
            ).fetchone()[0]
            == 256 * 1024**2
        )
    try:
        result = upload(client, base, b"# replacement", revision, document_id=document["id"])
        assert result.status_code == 409, result.text
        assert result.json()["error"]["code"] == "project_storage_limit"
        assert client.get(base).json()["revision"] == revision
        assert (
            client.get(f"{base}/documents/{document['id']}/versions/{version}/content").content
            == raw
        )
    finally:
        with sqlite3.connect(path) as db:
            db.execute("DELETE FROM knowledge_versions WHERE id=?", (fake_version,))
            db.commit()
            db.execute("VACUUM")


def test_index_unavailable_preserves_projects_and_explicit_reindex_recovers(client):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    response = upload(client, base, b"# Document\nuniqueplanet evidence", 0)
    assert response.status_code == 201, response.text
    doc_id = response.json()["document"]["id"]
    revision = client.get(base).json()["revision"]
    path = Path(os.environ["ASTROAGENT_DATA_DIR"]) / "astroagent.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE knowledge_meta SET value='0' WHERE key='fts_available'")
        db.commit()
    blocked = client.post(base + "/knowledge/answers", json={"query": "uniqueplanet"})
    assert blocked.status_code == 503, blocked.text
    assert blocked.json()["error"]["code"] == "knowledge_index_unavailable"
    assert client.get(base).status_code == 200
    assert client.get("/api/v1/conversations").status_code == 200
    rebuilt = client.post(
        f"{base}/documents/{doc_id}/reindex",
        json={"expected_revision": revision, "client_request_id": str(uuid4()), "confirmed": True},
    )
    assert rebuilt.status_code == 200, rebuilt.text
    recovered = client.post(base + "/knowledge/answers", json={"query": "uniqueplanet"})
    assert recovered.status_code == 200 and recovered.json()["hits"], recovered.text


def test_explicit_restore_old_version_reindexes_old_content(client):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    original = upload(client, base, b"# First\noriginal uniqueplanet\n", 0)
    assert original.status_code == 201, original.text
    document = original.json()["document"]
    old_version = document["current_version_id"]
    revision = client.get(base).json()["revision"]
    replacement = upload(
        client, base, b"# Second\nreplacement uniquenebula\n", revision, document_id=document["id"]
    )
    assert replacement.status_code == 200, replacement.text
    revision = client.get(base).json()["revision"]
    restored = client.post(
        f"{base}/documents/{document['id']}/reindex",
        json={
            "expected_revision": revision,
            "client_request_id": str(uuid4()),
            "confirmed": True,
            "version_id": old_version,
        },
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["document"]["current_version_id"] == old_version
    old_hit = client.post(base + "/knowledge/answers", json={"query": "uniqueplanet"}).json()
    new_hit = client.post(base + "/knowledge/answers", json={"query": "uniquenebula"}).json()
    assert old_hit["hits"]
    assert new_hit["status"] == "insufficient_evidence"


def test_reindex_rejects_changed_segmentation_without_retargeting_reference(client, monkeypatch):
    from astroagent import knowledge

    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    response = upload(client, base, b"# Original\nuniqueplanet evidence", 0)
    assert response.status_code == 201
    document = response.json()["document"]
    hit = client.post(base + "/knowledge/answers", json={"query": "uniqueplanet"}).json()["hits"][0]
    evidence = hit["evidence"]
    original_segment = knowledge.segment

    def altered(*args):
        units = original_segment(*args)
        units[0]["char_start"] += 1
        return units

    monkeypatch.setattr(knowledge, "segment", altered)
    revision = client.get(base).json()["revision"]
    result = client.post(
        f"{base}/documents/{document['id']}/reindex",
        json={"expected_revision": revision, "client_request_id": str(uuid4()), "confirmed": True},
    )
    assert result.status_code == 422, result.text
    version = result.json()["document"]["versions"][0]
    assert version["error"]["code"] == "knowledge_segmentation_changed"
    reference = client.get(base + "/knowledge/evidence/" + evidence["id"])
    assert reference.status_code == 200
    assert reference.json()["evidence"]["version_id"] == evidence["version_id"]
    assert reference.json()["evidence"]["id"] == evidence["id"]


def test_tampered_full_archive_rejected_atomically(client):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    response = upload(client, base, b"# original\nunique evidence\n", 0)
    assert response.status_code == 201, response.text
    revision = client.get(base).json()["revision"]
    archive = client.post(
        base + "/archive",
        json={
            "expected_revision": revision,
            "format_version": 3,
            "knowledge_mode": "full",
            "confirmed_include_originals": True,
        },
    )
    assert archive.status_code == 200, archive.text
    with ZipFile(BytesIO(archive.content)) as z:
        files = {name: z.read(name) for name in z.namelist()}
    bundle = json.loads(files["knowledge.json"])
    bundle["versions"][0]["content_base64"] = "dGFtcGVyZWQ="
    files["knowledge.json"] = json.dumps(bundle, ensure_ascii=False).encode()
    manifest = json.loads(files["manifest.json"])
    manifest["files"]["knowledge.json"] = {
        "bytes": len(files["knowledge.json"]),
        "sha256": hashlib.sha256(files["knowledge.json"]).hexdigest(),
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False).encode()
    output = BytesIO()
    with ZipFile(output, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    before = client.get("/api/v1/projects").json()
    imported = client.post(
        "/api/v1/projects/import",
        content=output.getvalue(),
        headers={"Content-Type": "application/zip"},
    )
    assert imported.status_code == 422, imported.text
    assert client.get("/api/v1/projects").json() == before


@pytest.mark.parametrize(
    "mutation",
    ["unknown", "path", "duplicate", "wrong_owner", "nan", "bad_position", "bad_reference"],
)
def test_invalid_knowledge_archives_rejected_without_import(client, mutation):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    assert upload(client, base, b"# evidence\ntext", 0).status_code == 201
    assert client.post(base + "/knowledge/answers", json={"query": "evidence"}).json()["hits"]
    revision = client.get(base).json()["revision"]
    archive = client.post(
        base + "/archive",
        json={
            "expected_revision": revision,
            "format_version": 3,
            "knowledge_mode": "full",
            "confirmed_include_originals": True,
        },
    )
    assert archive.status_code == 200
    with ZipFile(BytesIO(archive.content)) as z:
        files = {name: z.read(name) for name in z.namelist()}
    if mutation in ("wrong_owner", "nan", "bad_position", "bad_reference"):
        bundle = json.loads(files["knowledge.json"])
        if mutation == "wrong_owner":
            bundle["documents"][0]["project_id"] = str(uuid4())
        elif mutation == "nan":
            bundle["documents"][0]["metadata"]["year"] = float("nan")
        elif mutation == "bad_position":
            bundle["units"][0]["char_start"] = 999999
        else:
            bundle["evidence"][0]["version_id"] = str(uuid4())
        files["knowledge.json"] = json.dumps(bundle, allow_nan=True).encode()
        manifest = json.loads(files["manifest.json"])
        manifest["files"]["knowledge.json"] = {
            "bytes": len(files["knowledge.json"]),
            "sha256": hashlib.sha256(files["knowledge.json"]).hexdigest(),
        }
        files["manifest.json"] = json.dumps(manifest).encode()
    raw = BytesIO()
    with ZipFile(raw, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
        if mutation == "unknown":
            z.writestr("unknown.json", "{}")
        elif mutation == "path":
            z.writestr("../outside.json", "{}")
        elif mutation == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                z.writestr("knowledge.json", files["knowledge.json"])
    before = client.get("/api/v1/projects").json()
    result = client.post(
        "/api/v1/projects/import",
        content=raw.getvalue(),
        headers={"Content-Type": "application/zip"},
    )
    assert result.status_code in (400, 422), result.text
    assert client.get("/api/v1/projects").json() == before


def test_knowledge_archive_import_transaction_failure_rolls_back(client, monkeypatch):
    from astroagent import knowledge_archives

    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    assert upload(client, base, b"# document\nprivate synthetic", 0).status_code == 201
    revision = client.get(base).json()["revision"]
    backup = client.post(
        base + "/archive",
        json={
            "expected_revision": revision,
            "format_version": 3,
            "knowledge_mode": "full",
            "confirmed_include_originals": True,
        },
    )
    assert backup.status_code == 200
    original = knowledge_archives.import_knowledge

    def fail_after_import(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.OperationalError("synthetic transaction failure")

    monkeypatch.setattr(knowledge_archives, "import_knowledge", fail_after_import)
    before = client.get("/api/v1/projects").json()
    path = Path(os.environ["ASTROAGENT_DATA_DIR"]) / "astroagent.sqlite3"
    with sqlite3.connect(path) as db:
        before_docs = db.execute("SELECT count(*) FROM knowledge_documents").fetchone()[0]
    result = client.post(
        "/api/v1/projects/import",
        content=backup.content,
        headers={"Content-Type": "application/zip"},
    )
    assert result.status_code == 503, result.text
    assert client.get("/api/v1/projects").json() == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM knowledge_documents").fetchone()[0] == before_docs


def test_markdown_versions_references_privacy_archive_and_delete(client):
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    original = "# 合成章节\r\n银河潮汐 synthetic tidal evidence\r\n".encode()
    first = upload(client, base, original, 0)
    assert first.status_code == 201, first.text
    doc = first.json()["document"]
    assert doc["state"] == "ready", doc
    version = doc["current_version_id"]
    content = client.get(f"{base}/documents/{doc['id']}/versions/{version}/content")
    assert content.content == original
    search = client.post(base + "/knowledge/answers", json={"query": "银河潮汐", "limit": 5})
    assert search.status_code == 200, search.text
    hits = search.json()["hits"]
    assert hits and "银河潮汐" in hits[0]["text"]
    evidence_id = hits[0]["evidence"]["id"]
    revision = client.get(base).json()["revision"]
    replacement = upload(
        client, base, b"# Replacement\nnewer independent text\n", revision, document_id=doc["id"]
    )
    assert replacement.status_code == 200, replacement.text
    previous = client.get(base + "/knowledge/evidence/" + evidence_id).json()
    assert previous["historical_version"] and "银河潮汐" in previous["text"]
    revision = client.get(base).json()["revision"]
    metadata = client.post(
        base + "/archive",
        json={"expected_revision": revision, "format_version": 3, "knowledge_mode": "metadata"},
    )
    assert metadata.status_code == 200, metadata.text
    with ZipFile(BytesIO(metadata.content)) as z:
        assert set(z.namelist()) == {
            "manifest.json",
            "project.json",
            "conversations.json",
            "snapshots.json",
            "workflows.json",
            "knowledge.json",
        }
        assert original not in z.read("knowledge.json")
        knowledge = json.loads(z.read("knowledge.json"))
        assert all(v["content_base64"] is None for v in knowledge["versions"])
        assert all(s["text"] is None for s in knowledge["sources"])
        assert all(u["text"] is None for u in knowledge["units"])
    full_without_confirmation = client.post(
        base + "/archive",
        json={
            "expected_revision": revision,
            "format_version": 3,
            "knowledge_mode": "full",
            "confirmed_include_originals": False,
        },
    )
    assert full_without_confirmation.status_code in (409, 422)
    metadata_restored = client.post(
        "/api/v1/projects/import",
        content=metadata.content,
        headers={"Content-Type": "application/zip"},
    )
    assert metadata_restored.status_code == 201, metadata_restored.text
    metadata_id = metadata_restored.json()["project"]["id"]
    metadata_base = f"/api/v1/projects/{metadata_id}"
    metadata_doc = client.get(metadata_base + "/documents").json()[0]
    detail = client.get(metadata_base + "/documents/" + metadata_doc["id"]).json()
    old = next(v for v in detail["versions"] if v["sha256"] == doc["versions"][0]["sha256"])
    assert not old["content_available"]
    references = client.get(metadata_base + "/knowledge/evidence").json()
    missing = client.get(metadata_base + "/knowledge/evidence/" + references[0]["id"]).json()
    assert missing["evidence"]["validity"] == "original_unavailable" and missing["text"] is None
    revision = client.get(metadata_base).json()["revision"]
    mismatch = upload(
        client,
        metadata_base,
        b"different original",
        revision,
        document_id=metadata_doc["id"],
        restore_version_id=old["id"],
    )
    assert mismatch.status_code == 422
    revision = client.get(metadata_base).json()["revision"]
    restored_original = upload(
        client,
        metadata_base,
        original,
        revision,
        document_id=metadata_doc["id"],
        restore_version_id=old["id"],
    )
    assert restored_original.status_code == 200, restored_original.text
    available = client.get(metadata_base + "/knowledge/evidence/" + references[0]["id"]).json()
    assert available["evidence"]["validity"] == "available" and "银河潮汐" in available["text"]
    revision = client.get(base).json()["revision"]
    full = client.post(
        base + "/archive",
        json={
            "expected_revision": revision,
            "format_version": 3,
            "knowledge_mode": "full",
            "confirmed_include_originals": True,
        },
    )
    assert full.status_code == 200, full.text
    restored = client.post(
        "/api/v1/projects/import", content=full.content, headers={"Content-Type": "application/zip"}
    )
    assert restored.status_code == 201, restored.text
    restored_id = restored.json()["project"]["id"]
    restored_docs = client.get(f"/api/v1/projects/{restored_id}/documents").json()
    assert len(restored_docs) == 1 and restored_docs[0]["provenance"] == "imported_unverified"
    revision = client.get(base).json()["revision"]
    deleted = client.request(
        "DELETE",
        base + "/documents/" + doc["id"],
        json={"expected_revision": revision, "confirmed": True},
    )
    assert deleted.status_code == 204, deleted.text
    evidence = client.get(base + "/knowledge/evidence/" + evidence_id).json()
    assert evidence["evidence"]["validity"] == "deleted" and evidence["text"] is None


def test_project_isolation_and_no_answer(client):
    first = project(client, "一")
    second = project(client, "二")
    first_base = f"/api/v1/projects/{first['id']}"
    second_base = f"/api/v1/projects/{second['id']}"
    result = upload(client, first_base, b"# Secret\nunique-private-needle\n", 0)
    assert result.status_code == 201, result.text
    doc = result.json()["document"]
    assert client.get(second_base + "/documents/" + doc["id"]).status_code == 404
    result = client.post(
        second_base + "/knowledge/answers", json={"query": "unique-private-needle"}
    )
    assert result.status_code == 200 and result.json()["status"] == "insufficient_evidence"


def test_pdf_physical_pages_blank_encrypted_and_corrupt(client):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=400)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 30 300 Td (Unique synthetic binary cluster) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_blank_page(width=300, height=400)
    buffer = BytesIO()
    writer.write(buffer)
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    result = upload(client, base, buffer.getvalue(), 0, name="synthetic.pdf")
    assert result.status_code == 201, result.text
    doc = result.json()["document"]
    version = next(v for v in doc["versions"] if v["id"] == doc["current_version_id"])
    assert version["page_count"] == 2 and doc["state"] == "partial"
    page2 = client.get(
        f"{base}/documents/{doc['id']}/versions/{version['id']}/text?source_position=2"
    )
    assert page2.status_code == 200 and page2.json()["state"] == "no_text"
    result = client.post(base + "/knowledge/answers", json={"query": "binary cluster"})
    assert result.status_code == 200 and result.json()["hits"][0]["evidence"]["page"] == 1
    encrypted = PdfWriter()
    encrypted.add_blank_page(width=100, height=100)
    encrypted.encrypt("private-password")
    protected = BytesIO()
    encrypted.write(protected)
    revision = client.get(base).json()["revision"]
    bad = upload(client, base, protected.getvalue(), revision, name="encrypted.pdf")
    assert bad.status_code == 422 and bad.json()["document"]["state"] == "failed"
    assert "encrypted_pdf" in bad.json()["document"]["versions"][-1]["error"]["code"]
    revision = client.get(base).json()["revision"]
    bad = upload(client, base, b"%PDF-1.7\ninvalid", revision, name="broken.pdf")
    assert bad.status_code == 422 and bad.json()["document"]["state"] == "failed"


def test_pdf_worker_reports_mixed_page_extraction_failure(monkeypatch, tmp_path):
    import pypdf

    from astroagent.knowledge_worker import extract

    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            if self.text is None:
                raise ValueError("synthetic page corruption")
            return self.text

    class Reader:
        is_encrypted = False
        pages = [Page("first page"), Page(None), Page("")]

    monkeypatch.setattr(pypdf, "PdfReader", lambda *args, **kwargs: Reader())
    result = extract(tmp_path / "synthetic.pdf", "application/pdf")
    assert result["page_count"] == 3
    assert [(s["page"], s["state"], s["error"]) for s in result["sources"]] == [
        (1, "text", None),
        (2, "failed", "page_extraction_failed"),
        (3, "no_text", None),
    ]


def test_mixed_corrupt_pdf_pages_preserve_successful_page(client):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(100, 100)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 5 50 Td (uniqueplanet evidence) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    corrupt = writer.add_blank_page(100, 100)
    corrupt[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    bad_stream = DecodedStreamObject()
    bad_stream.set_data(b"BT (unclosed")
    corrupt[NameObject("/Contents")] = writer._add_object(bad_stream)
    writer.add_blank_page(100, 100)
    pdf = BytesIO()
    writer.write(pdf)
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    uploaded = upload(client, base, pdf.getvalue(), 0, name="mixed-corrupt.pdf")
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()["document"]
    assert document["state"] == "partial"
    version = document["current_version_id"]
    for page_number, expected in [(1, "text"), (2, "failed"), (3, "no_text")]:
        result = client.get(
            f"{base}/documents/{document['id']}/versions/{version}/text?source_position={page_number}"
        )
        assert result.status_code == 200 and result.json()["state"] == expected, result.text
    search = client.post(base + "/knowledge/answers", json={"query": "uniqueplanet"})
    assert search.status_code == 200
    assert search.json()["hits"][0]["evidence"]["page"] == 1


def test_pdf_worker_rejects_extracted_text_above_limit(monkeypatch, tmp_path):
    import pypdf

    from astroagent.knowledge_worker import extract

    class Page:
        def extract_text(self):
            return "x" * (20 * 1024**2 + 1)

    class Reader:
        is_encrypted = False
        pages = [Page()]

    monkeypatch.setattr(pypdf, "PdfReader", lambda *args, **kwargs: Reader())
    with pytest.raises(ValueError, match="text_limit"):
        extract(tmp_path / "synthetic.pdf", "application/pdf")


def test_markdown_bom_mixed_line_endings_heading_and_offsets(tmp_path):
    from astroagent.knowledge_text import segment
    from astroagent.knowledge_worker import extract

    raw = b"\xef\xbb\xbf# Heading\r\nfirst\r## Section\n```\n# Not heading\n```\nlast"
    path = tmp_path / "synthetic.md"
    path.write_bytes(raw)
    result = extract(path, "text/markdown")
    assert result["line_count"] == 7
    source = result["sources"][0]
    assert source["text"] == raw.decode("utf-8-sig")
    units = segment([source], str(uuid4()), str(uuid4()), str(uuid4()))
    assert units[0]["line_start"] == 1 and units[0]["line_end"] == 7
    assert source["text"][units[0]["char_start"] : units[0]["char_end"]] == units[0]["text"]
    assert "Not heading" not in units[0]["heading_path"]


def test_image_only_pdf_is_reported_without_ocr(client):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    image = DecodedStreamObject()
    image.set_data(bytes([0, 0, 0]))
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): writer._add_object(image)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"q 50 0 0 50 0 0 cm /Im1 Do Q")
    page[NameObject("/Contents")] = writer._add_object(stream)
    raw = BytesIO()
    writer.write(raw)
    p = project(client)
    base = f"/api/v1/projects/{p['id']}"
    response = upload(client, base, raw.getvalue(), 0, name="image-only.pdf")
    assert response.status_code == 422, response.text
    document = response.json()["document"]
    assert document["state"] == "failed"
    version = document["versions"][0]
    assert version["error"]["code"] == "knowledge_no_text"
    assert any("不执行OCR" in warning for warning in version["warnings"])
