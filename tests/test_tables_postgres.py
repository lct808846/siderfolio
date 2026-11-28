"""Verify the authenticated table upload and download paths with disposable data."""

from urllib.parse import unquote

import pytest
from test_identity_postgres import ORIGIN, account, post
from test_identity_postgres import identity_client as identity_client

from astroagent.table_schemas import MAX_TABLE_UPLOAD_BYTES

pytestmark = [pytest.mark.identity, pytest.mark.postgres]


def test_table_multipart_upload_unicode_export_and_delete(identity_client):
    client = identity_client
    account(client, "table-fixture@example.org")
    project = post(client, "projects", {"name": "合成星表项目"})
    assert project.status_code == 201
    base = f"/api/v1/projects/{project.json()['id']}/tables"
    headers = {
        "Origin": ORIGIN,
        "X-CSRF-Token": client.get("/api/v1/auth/csrf").json()["csrf_token"],
    }
    data = b"source_id,ra,dec\n5853498710037763559,56.6,24.1\n"
    files = {"file": ("observations.csv", data, "text/csv")}
    assert client.post(base + "/inspect", json={}, headers=headers).status_code == 415
    oversized = {"file": ("large.csv", b"x" * (MAX_TABLE_UPLOAD_BYTES + 1), "text/csv")}
    assert client.post(base + "/inspect", files=oversized, headers=headers).status_code == 413

    inspected = client.post(base + "/inspect", files=files, headers=headers)
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["format"] == "csv"
    uploaded = client.post(
        base + "/upload", files=files, data={"name": "昴星团观测表"}, headers=headers
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["row_count"] == 1
    target = f"{base}/{uploaded.json()['id']}"

    exported = client.get(target + "/export?format=csv")
    assert exported.status_code == 200, exported.text
    disposition = exported.headers["content-disposition"]
    assert 'filename="table.csv"' in disposition
    assert unquote(disposition.split("filename*=UTF-8''", 1)[1]) == "昴星团观测表.csv"
    assert b"5853498710037763559" in exported.content
    assert client.delete(target, headers=headers).status_code == 204
    assert client.get(target).status_code == 404
