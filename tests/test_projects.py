"""V0.6 行为验收：迁移、不可变副本、重跑并发、离线归档和坏包回滚。"""

import hashlib
import json
import sqlite3
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from fastapi.testclient import TestClient

from astroagent.api import conversations, projects
from astroagent.config import LocalSettings
from astroagent.conversation_schemas import Turn
from astroagent.conversations import ConversationRepository, encode
from astroagent.errors import ServiceError
from astroagent.main import app
from astroagent.project_archives import decode_archive
from astroagent.project_service import compare_snapshots
from astroagent.schemas import ChatResponse
from scripts.export_samples import synthetic_request
from scripts.synthetic_services import SyntheticAds, SyntheticGaia, SyntheticSimbad


class Agent:
    def converse(self, *args):
        return ChatResponse.model_validate(synthetic_request()["snapshot"])


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(conversations, "get_agent", lambda: Agent())
    calls = []

    def factory():
        def execute(family, parameters):
            calls.append((family, parameters))
            from astroagent.schemas import GaiaQuery, LiteratureQuery

            if family == "gaia":
                return SyntheticGaia().query(GaiaQuery(**parameters))
            if family == "ads":
                return SyntheticAds().search(LiteratureQuery(**parameters))
            return SyntheticSimbad().query(parameters["object_name"])

        return execute

    monkeypatch.setattr(projects, "get_executor", factory)
    with TestClient(app) as value:
        value.calls = calls
        yield value


def project(client, name="候选源项目"):
    response = client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def detail(client, p):
    return client.get(f"/api/v1/projects/{p['id']}").json()


def prepared(client):
    p = project(client)
    c = client.post("/api/v1/conversations", json={"title": "完整100行"}).json()
    response = client.post(
        f"/api/v1/conversations/{c['id']}/turns",
        json={
            "message": "合成验收，不是实际观测",
            "client_request_id": str(uuid4()),
            "expected_revision": 0,
        },
    )
    assert response.status_code == 200, response.text
    t = response.json()
    response = client.put(
        f"/api/v1/projects/{p['id']}/conversations/{c['id']}",
        json={
            "expected_revision": 0,
            "expected_conversation_revision": 1,
            "expected_metadata_revision": 0,
        },
    )
    assert response.status_code == 200, response.text
    response = client.post(
        f"/api/v1/projects/{p['id']}/snapshots",
        json={
            "expected_revision": 1,
            "name": "原始样本",
            "conversation_id": c["id"],
            "turn_id": t["turn_id"],
        },
    )
    assert response.status_code == 201, response.text
    return p, c, t, response.json()


def rerun(client, p, s, family="gaia", key=None, revision=None):
    body = {
        "expected_revision": detail(client, p)["revision"] if revision is None else revision,
        "family": family,
        "result_index": 0,
        "client_request_id": key or str(uuid4()),
        "confirmed": True,
    }
    return client.post(f"/api/v1/projects/{p['id']}/snapshots/{s['id']}/reruns", json=body), body


def archive(client, p):
    response = client.post(
        f"/api/v1/projects/{p['id']}/archive",
        json={"expected_revision": detail(client, p)["revision"]},
    )
    assert response.status_code == 200, response.text
    return response.content


def restore(client, raw):
    return client.post(
        "/api/v1/projects/import", content=raw, headers={"Content-Type": "application/zip"}
    )


def repack(raw, mutate=None, extra=None, duplicate=False):
    with ZipFile(BytesIO(raw)) as z:
        values = {n: z.read(n) for n in z.namelist()}
    if mutate:
        mutate(values)
        manifest = json.loads(values["manifest.json"])
        for name in ("project.json", "conversations.json", "snapshots.json"):
            manifest["files"][name] = {
                "bytes": len(values[name]),
                "sha256": hashlib.sha256(values[name]).hexdigest(),
            }
        values["manifest.json"] = encode(manifest).encode()
    out = BytesIO()
    with ZipFile(out, "w") as z:
        for name, value in values.items():
            if isinstance(extra, ZipInfo) and extra.filename == name:
                z.writestr(extra, value)
                continue
            z.writestr(name, value)
        if extra and not isinstance(extra, ZipInfo):
            z.writestr(extra, b"invalid")
        if duplicate:
            z.writestr("manifest.json", values["manifest.json"])
    return out.getvalue()


def test_full_snapshot_survives_conversation_delete_and_project_delete_retains_other_history(
    client,
):
    p, c, t, s = prepared(client)
    assert s["response"] == t["response"]
    assert len(s["response"]["gaia_results"][0]["data"]) == 100
    assert type(s["response"]["gaia_results"][0]["data"][0]["source_id"]) is str
    assert client.delete(f"/api/v1/conversations/{c['id']}").status_code == 204
    stored = client.get(f"/api/v1/projects/{p['id']}/snapshots/{s['id']}").json()
    assert stored["response"] == s["response"] and stored["sha256"] == s["sha256"]
    assert stored["conversation_id"] is None and stored["origin"]["conversation_id"] == c["id"]
    restored = restore(client, archive(client, p))
    assert restored.status_code == 201, restored.text
    another = client.post("/api/v1/conversations", json={"title": "保留"}).json()
    assert (
        client.request(
            "DELETE",
            f"/api/v1/projects/{p['id']}",
            json={"expected_revision": detail(client, p)["revision"], "confirm": True},
        ).status_code
        == 204
    )
    assert client.get(f"/api/v1/conversations/{another['id']}").status_code == 200


def test_project_revision_move_conflict_and_metadata_revision(client):
    p, c, _, _ = prepared(client)
    other = project(client, "另一项目")
    path = f"/api/v1/projects/{other['id']}/conversations/{c['id']}"
    body = {
        "expected_revision": 0,
        "expected_source_project_id": p["id"],
        "expected_source_revision": 1,
        "expected_conversation_revision": 1,
        "expected_metadata_revision": 1,
    }
    assert client.put(path, json=body).status_code == 409
    body["expected_source_revision"] = 2
    assert client.put(path, json=body).status_code == 200
    assert client.put(path, json=body).status_code == 409
    assert c["id"] not in detail(client, p)["conversation_ids"]
    result = client.patch(
        f"/api/v1/conversations/{c['id']}",
        json={"title": "新名称", "expected_metadata_revision": 1},
    )
    assert result.status_code == 409
    assert (
        client.patch(
            f"/api/v1/projects/{p['id']}",
            json={"name": "过期修改", "description": "", "expected_revision": 2},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("family", ["simbad", "ads", "gaia"])
def test_direct_rerun_parameters_idempotency_and_old_snapshot_immutable(
    client, family, monkeypatch
):
    p, _, _, s = prepared(client)

    def forbidden_model():
        raise AssertionError("Direct rerun must not construct a language model agent")

    monkeypatch.setattr(conversations, "get_agent", forbidden_model)
    response, body = rerun(client, p, s, family)
    assert response.status_code == 200, response.text
    r = response.json()
    assert r["state"] == "completed" and r["snapshot_id"] != s["id"]
    repeated = client.post(f"/api/v1/projects/{p['id']}/snapshots/{s['id']}/reruns", json=body)
    assert repeated.json() == r and len(client.calls) == 1
    assert client.get(f"/api/v1/projects/{p['id']}/snapshots/{s['id']}").json() == s
    new = client.get(f"/api/v1/projects/{p['id']}/snapshots/{r['snapshot_id']}").json()
    assert new["rerun_of"] == s["id"] and new["sha256"] != s["sha256"]
    field = {"simbad": "results", "ads": "literature_results", "gaia": "gaia_results"}[family]
    assert len(new["response"][field]) == 1
    assert all(
        not new["response"][f] for f in {"results", "literature_results", "gaia_results"} - {field}
    )
    if family == "gaia":
        assert r["parameters"] == s["response"]["gaia_results"][0]["query"]
    body["result_index"] = 1
    assert (
        client.post(f"/api/v1/projects/{p['id']}/snapshots/{s['id']}/reruns", json=body).status_code
        == 409
    )
    imported = restore(client, archive(client, p))
    assert imported.status_code == 201, imported.text
    assert len(detail(client, imported.json()["project"])["reruns"]) == 1
    imported_body = imported.json()
    imported_new = client.get(
        f"/api/v1/projects/{imported_body['project']['id']}/snapshots/{imported_body['id_map']['snapshots'][new['id']]}"
    ).json()
    assert imported_new["rerun_of"] == imported_body["id_map"]["snapshots"][s["id"]]
    assert imported_new["rerun_origin_id"] == s["id"]
    removed = client.request(
        "DELETE",
        f"/api/v1/projects/{p['id']}/snapshots/{s['id']}",
        json={"expected_revision": detail(client, p)["revision"]},
    )
    assert removed.status_code == 204
    retained = client.get(f"/api/v1/projects/{p['id']}/snapshots/{new['id']}").json()
    assert retained["rerun_of"] is None and retained["rerun_origin_id"] == s["id"]
    assert retained["response"] == new["response"] and retained["sha256"] == new["sha256"]
    assert restore(client, archive(client, p)).status_code == 201


def test_failed_direct_rerun_is_deliverable_and_exportable(client, monkeypatch):
    p, _, _, s = prepared(client)
    from astroagent.simbad import SimbadService

    monkeypatch.setattr(
        projects, "get_executor", lambda: lambda *a: SimbadService(1).query("offline blocked")
    )
    response, _ = rerun(client, p, s, "simbad")
    assert response.status_code == 200
    r = response.json()
    new = client.get(f"/api/v1/projects/{p['id']}/snapshots/{r['snapshot_id']}").json()
    assert new["response"]["status"] == "error" and new["response"]["results"][0]["error"]
    assert restore(client, archive(client, p)).status_code == 201


def test_confirmation_invalid_index_and_no_automatic_retry(client):
    p, _, _, s = prepared(client)
    path = f"/api/v1/projects/{p['id']}/snapshots/{s['id']}/reruns"
    body = {
        "expected_revision": 2,
        "family": "gaia",
        "result_index": 0,
        "confirmed": False,
        "client_request_id": str(uuid4()),
    }
    assert client.post(path, json=body).status_code == 422
    body.update(confirmed=True, result_index=11)
    assert client.post(path, json=body).status_code == 422
    assert not client.calls and not detail(client, p)["reruns"]


def test_running_rerun_replay_busy_guards_and_global_slots(client, monkeypatch):
    p, c, _, s = prepared(client)
    entered, release = threading.Event(), threading.Event()

    def execute(*args):
        entered.set()
        assert release.wait(10)
        raise ServiceError(502, "synthetic_failure", "合成失败")

    monkeypatch.setattr(projects, "get_executor", lambda: execute)
    path = f"/api/v1/projects/{p['id']}/snapshots/{s['id']}/reruns"
    body = {
        "expected_revision": 2,
        "family": "gaia",
        "result_index": 0,
        "confirmed": True,
        "client_request_id": str(uuid4()),
    }
    with ThreadPoolExecutor() as pool:
        future = pool.submit(client.post, path, json=body)
        try:
            assert entered.wait(5)
            running = client.post(path, json=body)
            assert running.status_code == 202 and running.json()["state"] == "running"
            assert (
                client.request(
                    "DELETE",
                    f"/api/v1/projects/{p['id']}",
                    json={"expected_revision": 3, "confirm": True},
                ).status_code
                == 409
            )
            assert (
                client.request(
                    "DELETE",
                    f"/api/v1/projects/{p['id']}/conversations/{c['id']}",
                    json={
                        "expected_revision": 3,
                        "expected_source_project_id": p["id"],
                        "expected_conversation_revision": 1,
                        "expected_metadata_revision": 1,
                    },
                ).status_code
                == 409
            )
            slots = app.state.conversation_service.slots
            assert slots.acquire(blocking=False)
            try:
                response = client.post("/api/v1/chat", json={"message": "不应执行"})
                assert response.status_code == 503
            finally:
                slots.release()
        finally:
            release.set()
        result = future.result().json()
    assert result["state"] == "failed" and result["snapshot_id"] is None


def test_archive_roundtrip_new_ids_full_response_no_external_calls_and_repeat_import(client):
    p, c, t, s = prepared(client)
    raw = archive(client, p)
    with ZipFile(BytesIO(raw)) as z:
        assert set(z.namelist()) == {
            "manifest.json",
            "project.json",
            "snapshots.json",
            "conversations.json",
        }
    first, second = restore(client, raw), restore(client, raw)
    assert first.status_code == second.status_code == 201, first.text
    a, b = first.json(), second.json()
    assert a["project"]["id"] != b["project"]["id"] != p["id"]
    assert a["project"]["import_map"] == a["id_map"]
    assert a["project"]["provenance"] == "imported_unverified"
    new_c, new_t, new_s = (
        a["id_map"][family][old]
        for family, old in (
            ("conversations", c["id"]),
            ("turns", t["turn_id"]),
            ("snapshots", s["id"]),
        )
    )
    assert (
        client.get(f"/api/v1/conversations/{new_c}/turns/{new_t}").json()["response"]
        == t["response"]
    )
    saved = client.get(f"/api/v1/projects/{a['project']['id']}/snapshots/{new_s}").json()
    assert (
        saved["response"] == s["response"] and saved["sha256"] == s["sha256"] and not client.calls
    )
    preview = client.post(
        f"/api/v1/projects/{a['project']['id']}/snapshots/{new_s}/artifacts",
        json={"plots": [{"kind": "proper_motion", "gaia_result_index": 0}]},
    )
    assert preview.status_code == 201, preview.text
    assert client.get(preview.json()["download_url"]).status_code == 200
    assert restore(client, archive(client, a["project"])).status_code == 201


@pytest.mark.parametrize(
    "kind",
    [
        "extra",
        "duplicate",
        "traversal",
        "symlink",
        "corrupt",
        "unknown_version",
        "unknown_field",
        "unknown_response_field",
        "broken_reference",
        "changed_response",
        "nonfinite",
        "duplicate_json",
        "invalid_utf8",
    ],
)
def test_bad_archives_reject_atomically(client, kind):
    p, _, _, _ = prepared(client)
    raw = archive(client, p)

    def mutate(values):
        if kind == "unknown_version":
            m = json.loads(values["manifest.json"])
            m["version"] = 99
            values["manifest.json"] = encode(m).encode()
        elif kind == "unknown_field":
            v = json.loads(values["project.json"])
            v["project"]["api_key"] = "not-a-credential"
            values["project.json"] = encode(v).encode()
        elif kind in ("unknown_response_field", "broken_reference", "changed_response"):
            v = json.loads(values["snapshots.json"])
            if kind == "unknown_response_field":
                v[0]["response"]["unknown"] = True
            elif kind == "broken_reference":
                v[0]["turn_id"] = str(uuid4())
            else:
                v[0]["response"]["gaia_results"][0]["data"][0]["source_id"] = "1"
            values["snapshots.json"] = encode(v).encode()
        elif kind == "nonfinite":
            values["snapshots.json"] = b"[NaN]"
        elif kind == "duplicate_json":
            values["project.json"] = b'{"project":{},"project":{},"reruns":[]}'
        elif kind == "invalid_utf8":
            values["snapshots.json"] = b"\xff"

    if kind == "extra":
        raw = repack(raw, extra=".env")
    elif kind == "duplicate":
        with pytest.warns(UserWarning):
            raw = repack(raw, duplicate=True)
    elif kind == "traversal":
        raw = repack(raw, extra="../outside")
    elif kind == "symlink":
        info = ZipInfo("snapshots.json")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        raw = repack(raw, extra=info)
    elif kind == "corrupt":
        raw = raw[:25]
    else:
        raw = repack(raw, mutate)
    before = client.get("/api/v1/projects").json()
    result = restore(client, raw)
    assert result.status_code == 422, result.text
    assert client.get("/api/v1/projects").json() == before
    assert not client.calls


def test_import_budget_and_write_failure_roll_back_all_rows(client, monkeypatch):
    p, _, _, _ = prepared(client)
    raw = archive(client, p)
    repo = app.state.conversation_service.repository
    with repo.connection() as db:
        used = repo._used(db)
    monkeypatch.setattr(repo.settings, "storage_bytes", used + 1)
    before = client.get("/api/v1/conversations").json()
    assert restore(client, raw).status_code == 409
    assert client.get("/api/v1/conversations").json() == before
    monkeypatch.setattr(repo.settings, "storage_bytes", 256 * 1024**2)
    monkeypatch.setattr(
        app.state.conversation_service.projects.repository,
        "_insert_snapshot",
        lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError("synthetic")),
    )
    assert restore(client, raw).status_code == 503
    assert client.get("/api/v1/conversations").json() == before


def test_archive_actual_size_limits_and_local_request_boundaries(client, monkeypatch):
    p, _, _, _ = prepared(client)
    raw = archive(client, p)
    import astroagent.project_archives as module

    monkeypatch.setattr(module, "MAX_MEMBER", 1000)
    with pytest.raises(ServiceError):
        decode_archive(raw)
    assert (
        client.post(
            "/api/v1/projects",
            content=b'{"name":"x","name":"y"}',
            headers={"Content-Type": "application/json"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/projects", json={"name": "x"}, headers={"Origin": "https://outside.invalid"}
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/v1/projects/{p['id']}/conversations/{uuid4()}",
            json={
                "expected_revision": 0,
                "expected_conversation_revision": 0,
                "expected_metadata_revision": 0,
            },
            headers={"Content-Type": "text/plain"},
        ).status_code
        == 415
    )
    assert (
        client.options(
            "/api/v1/projects",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/projects/import",
            content=(b"x" * 65536 for _ in range(513)),
            headers={"Content-Type": "application/zip"},
        ).status_code
        == 413
    )


def test_comparison_determinism_exact_ids_and_missing_not_zero(client):
    p, _, _, s = prepared(client)
    response, _ = rerun(client, p, s)
    new = client.get(
        f"/api/v1/projects/{p['id']}/snapshots/{response.json()['snapshot_id']}"
    ).json()
    first = compare_snapshots(s, new, True)
    assert first == compare_snapshots(s, new, True)
    assert all(type(i) is str for m in first["identifiers"] for i in m["intersection"])
    assert "5853498713190525696" in first["identifiers"][0]["intersection"]
    assert any(d["left"]["value"] is None for d in first["differences"])
    path = f"/api/v1/projects/{p['id']}/comparisons"
    assert (
        client.post(
            path, json={"left_id": s["id"], "right_id": new["id"], "match_identifiers": True}
        ).json()
        == first
    )


def test_v05_migration_backup_and_v2_failure_rollback(tmp_path, monkeypatch):
    settings = LocalSettings(data_dir=tmp_path / "legacy")
    settings.data_dir.mkdir()
    path = settings.data_dir / "astroagent.sqlite3"
    cid, tid = str(uuid4()), str(uuid4())
    legacy_turn = Turn(
        conversation_id=cid,
        turn_id=tid,
        revision=1,
        client_request_id=str(uuid4()),
        message="V0.5格式合成迁移样本",
        execution_status="completed",
        received_at="2026-10-29T00:00:00+00:00",
        completed_at="2026-10-29T00:00:01+00:00",
        response=ChatResponse.model_validate(synthetic_request()["snapshot"]),
    ).model_dump_json()
    with sqlite3.connect(path) as db:
        ConversationRepository._migrate_v1(db)
        db.execute(
            "INSERT INTO conversations VALUES (?,?,?,?,?)",
            (cid, "旧会话", "2026-10-29T00:00:00+00:00", "2026-10-29T00:00:00+00:00", 1),
        )
        db.execute(
            "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?)",
            (
                tid,
                cid,
                1,
                json.loads(legacy_turn)["client_request_id"],
                "legacy-hash",
                "completed",
                legacy_turn,
                len(legacy_turn.encode()),
                0,
            ),
        )
    repo = ConversationRepository(settings)
    migrate = repo._migrate_v2

    def fail(db):
        db.execute("CREATE TABLE partial_migration (value TEXT)")
        raise sqlite3.OperationalError("synthetic")

    monkeypatch.setattr(repo, "_migrate_v2", fail)
    with pytest.raises(ServiceError):
        repo.initialize()
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='partial_migration'"
        ).fetchall()
    monkeypatch.setattr(repo, "_migrate_v2", migrate)
    repo.initialize()
    try:
        assert repo.list()[0]["metadata_revision"] == 0
        with repo.connection() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 2
            assert (
                db.execute("SELECT record FROM turns WHERE id=?", (tid,)).fetchone()[0]
                == legacy_turn
            )
        assert len(repo.turn(cid, tid).response.gaia_results[0].data) == 100
        assert list(settings.data_dir.glob("migration-v2-*.sqlite3"))
    finally:
        repo.close()


def test_interrupted_rerun_recovered_without_replaying(client):
    p, _, _, s = prepared(client)
    service = app.state.conversation_service.projects
    from astroagent.project_schemas import RerunRequest
    from astroagent.project_service import selection

    request = RerunRequest(
        expected_revision=2,
        family="gaia",
        result_index=0,
        client_request_id=str(uuid4()),
        confirmed=True,
    )
    _, digest = service.repository.existing_rerun(p["id"], s["id"], request)
    record, turn = service.repository.reserve_rerun(
        p["id"], s["id"], request, selection(s, "gaia", 0), digest
    )
    repo = service.repository.repo
    repo.close()
    repo.initialize()
    fetched = service.repository.rerun(p["id"], record["id"])
    assert fetched["state"] == "interrupted"
    old = repo.turn(turn.conversation_id, turn.turn_id)
    assert old.execution_status == "interrupted"
    result, code = service.rerun(p["id"], s["id"], request)
    assert result == fetched and code == 200 and not client.calls


def test_resaving_imported_history_never_promotes_provenance(client):
    p, c, t, _ = prepared(client)
    restored = restore(client, archive(client, p)).json()
    imported = restored["project"]
    cid, tid = (
        restored["id_map"]["conversations"][c["id"]],
        restored["id_map"]["turns"][t["turn_id"]],
    )
    # Removing the imported project must not erase the surviving turn's provenance.
    assert (
        client.request(
            "DELETE",
            f"/api/v1/projects/{imported['id']}",
            json={"expected_revision": 0, "confirm": True},
        ).status_code
        == 204
    )
    target = project(client, "新项目")
    conv = client.get(f"/api/v1/conversations/{cid}").json()
    assigned = client.put(
        f"/api/v1/projects/{target['id']}/conversations/{cid}",
        json={
            "expected_revision": 0,
            "expected_conversation_revision": conv["revision"],
            "expected_metadata_revision": conv["metadata_revision"],
        },
    )
    assert assigned.status_code == 200
    saved = client.post(
        f"/api/v1/projects/{target['id']}/snapshots",
        json={
            "expected_revision": 1,
            "conversation_id": cid,
            "turn_id": tid,
            "name": "重新命名的导入数据",
        },
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["provenance"] == "imported_unverified"
    assert saved.json()["origin"]["archive_sha256"] == restored["archive_sha256"]


def test_project_revision_follows_linked_conversation_changes(client):
    p, c, _, _ = prepared(client)
    before = detail(client, p)
    response = client.post(
        f"/api/v1/conversations/{c['id']}/turns",
        json={
            "message": "第二轮合成问题",
            "expected_revision": 1,
            "client_request_id": str(uuid4()),
        },
    )
    assert response.status_code == 200
    assert detail(client, p)["revision"] == before["revision"] + 2
    stale = client.post(
        f"/api/v1/projects/{p['id']}/archive", json={"expected_revision": before["revision"]}
    )
    assert stale.status_code == 409


def test_compressed_archive_expansion_is_bounded_by_actual_total_bytes(client, monkeypatch):
    import astroagent.project_archives as module

    monkeypatch.setattr(module, "MAX_TOTAL", 128 * 1024)
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as z:
        z.writestr("manifest.json", b"{}")
        z.writestr("project.json", b" " * 2 * 1024**2)
        z.writestr("snapshots.json", b"[]")
        z.writestr("conversations.json", b"[]")
    assert len(stream.getvalue()) < 4096
    before = client.get("/api/v1/projects").json()
    result = restore(client, stream.getvalue())
    assert result.status_code == 413
    assert client.get("/api/v1/projects").json() == before


def test_archive_operation_busy_returns_without_writing_or_queueing(client):
    p = project(client)
    service = app.state.conversation_service.projects
    service.archive_export_slot.acquire()
    service.archive_import_slot.acquire()
    try:
        assert (
            client.post(
                f"/api/v1/projects/{p['id']}/archive", json={"expected_revision": 0}
            ).status_code
            == 503
        )
        assert restore(client, b"not-read-while-busy").status_code == 503
        assert len(client.get("/api/v1/projects").json()) == 1
    finally:
        service.archive_export_slot.release()
        service.archive_import_slot.release()


def test_boolean_version_and_broken_history_reference_rejected(client):
    p, _, _, _ = prepared(client)
    raw = archive(client, p)

    def boolean_version(values):
        m = json.loads(values["manifest.json"])
        m["version"] = True
        values["manifest.json"] = encode(m).encode()

    assert restore(client, repack(raw, boolean_version)).status_code == 422

    def broken_history(values):
        data = json.loads(values["conversations.json"])
        data[0]["turns"][0]["context"]["included_turn_ids"] = [str(uuid4())]
        values["conversations.json"] = encode(data).encode()

    assert restore(client, repack(raw, broken_history)).status_code == 422
    assert (
        client.request(
            "DELETE", f"/api/v1/projects/{p['id']}", json={"expected_revision": 2, "confirm": 1}
        ).status_code
        == 422
    )


def test_project_and_snapshot_quota_never_overwrite_previous_records(client):
    p, c, t, _ = prepared(client)
    for i in range(19):
        project(client, f"项目{i}")
    assert client.post("/api/v1/projects", json={"name": "超限"}).status_code == 409
    for i in range(99):
        result = client.post(
            f"/api/v1/projects/{p['id']}/snapshots",
            json={
                "expected_revision": i + 2,
                "conversation_id": c["id"],
                "turn_id": t["turn_id"],
                "name": f"副本{i}",
            },
        )
        assert result.status_code == 201
    result = client.post(
        f"/api/v1/projects/{p['id']}/snapshots",
        json={
            "expected_revision": 101,
            "conversation_id": c["id"],
            "turn_id": t["turn_id"],
            "name": "超限",
        },
    )
    assert result.status_code == 409 and len(detail(client, p)["snapshots"]) == 100
