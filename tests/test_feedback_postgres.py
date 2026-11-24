"""Exercise feedback and SMTP limits with synthetic users in the isolated database."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from PIL import Image
from test_identity_postgres import (
    ORIGIN,
    PASSWORD,
    account,
    post,
    synthetic_admin,
)
from test_identity_postgres import (
    identity_client as identity_client,
)

from astroagent.auth_mail_quota import MailQuotaReached, mail_quota_usage, reserve_mail_slot
from astroagent.feedback import install_feedback_schema

pytestmark = [pytest.mark.identity, pytest.mark.postgres]


def _submit(client, request_id=None, attachment=None):
    form = {
        "request_id": (None, str(request_id or uuid4())),
        "category": (None, "calculation"),
        "title": (None, "Synthetic observation"),
        "description": (None, "<b>Plain text marker</b>\nSynthetic second line"),
    }
    if attachment is not None:
        form["screenshot"] = ("synthetic.png", attachment, "image/png")
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    return client.post(
        "/api/v1/feedback", files=form, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}
    )


def test_feedback_privacy_admin_reply_and_notification(identity_client, monkeypatch):
    admin = identity_client
    recovery = synthetic_admin(admin)
    with closing(admin.fresh()) as reporter, closing(admin.fresh()) as other:
        reporter.store = other.store = admin.store
        account(reporter, "reporter@example.org")
        account(other, "other@example.org")
        settings = admin.identity.settings
        monkeypatch.setattr(settings, "local_http", False)
        monkeypatch.setattr(settings, "smtp_from", "Siderfolio <noreply@siderfolio.com>")
        picture = io.BytesIO()
        Image.new("RGB", (32, 24)).save(picture, "PNG")
        assert _submit(reporter, attachment=b"synthetic invalid image").status_code == 422
        request_id = uuid4()
        result = _submit(reporter, request_id, picture.getvalue())
        assert result.status_code == 201, result.text
        saved = result.json()
        path = "/api/v1/feedback/" + saved["id"]
        assert _submit(reporter, request_id).json()["id"] == saved["id"]
        assert reporter.get(path).json()["description"].startswith("<b>")
        screenshot = reporter.get(path + "/screenshot")
        assert screenshot.headers["content-type"] == "image/png"
        assert screenshot.headers["x-content-type-options"] == "nosniff"
        assert "no-store" in screenshot.headers["cache-control"]
        assert other.get("/api/v1/feedback").json()["items"] == []
        assert other.get(path).status_code == other.get(path + "/screenshot").status_code == 404
        assert other.get("/api/v1/admin/feedback").status_code == 403
        assert admin.get("/api/v1/admin/feedback?category=bug").json()["items"] == []
        assert len(admin.get("/api/v1/admin/feedback?status=pending").json()["items"]) == 1
        body = {
            "status": "resolved",
            "reply": "Synthetic reply",
            "request_id": str(uuid4()),
            "expected_updated_at": saved["updated_at"],
        }
        manage = "admin/feedback/" + saved["id"]
        with admin.store.connect() as db:
            db.execute(
                "UPDATE public.auth_sessions SET reauth_at=now()-interval '6 minutes' "
                "WHERE user_id IN (SELECT id FROM public.auth_users WHERE admin)"
            )
        assert post(admin, manage, body, "PATCH").status_code == 403
        assert (
            post(
                admin, "auth/reauthenticate", {"password": PASSWORD, "code": recovery[0]}
            ).status_code
            == 200
        )
        result = post(admin, manage, body, "PATCH")
        assert result.status_code == 200, result.text
        assert post(admin, manage, body, "PATCH").status_code == 200
        received = reporter.get(path).json()
        assert received["status"] == "resolved"
        assert [reply["body"] for reply in received["replies"]] == ["Synthetic reply"]
        with admin.store.connect() as db:
            messages = db.execute(
                "SELECT payload FROM public.auth_outbox "
                "WHERE purpose IN ('feedback_received','feedback_reply') ORDER BY purpose"
            ).fetchall()
        payloads = [
            json.loads(admin.store.crypto.decrypt(row["payload"].encode())) for row in messages
        ]
        assert [item["email"] for item in payloads] == [
            "support@siderfolio.com",
            "reporter@example.org",
        ]
        for item in payloads:
            assert "Synthetic" not in item["message"]
            link = urlsplit(item["message"].splitlines()[-1])
            assert link.path == "/login"
            assert saved["id"] in parse_qs(link.query)["next"][0]


def test_feedback_survives_enqueue_failure_and_caps_account(identity_client, monkeypatch):
    user = identity_client
    account(user)
    monkeypatch.setattr(user.identity.settings, "local_http", False)
    monkeypatch.setattr(user.identity.settings, "smtp_from", "noreply@siderfolio.com")

    def unavailable(db, *_):
        # Aborts the nested mailbox write, exercising transaction rollback.
        db.execute("SELECT 1/0")

    monkeypatch.setattr(user.identity.store, "enqueue_mail", unavailable)
    for _ in range(5):
        assert _submit(user).status_code == 201
    assert _submit(user).status_code == 429
    assert len(user.get("/api/v1/feedback").json()["items"]) == 5


def test_feedback_schema_adds_over_existing_identity(identity_client):
    user = identity_client
    account(user)
    with user.store.connect() as db:
        before = db.execute("SELECT id,email_key FROM public.auth_users").fetchall()
        # These tables are empty and belong solely to this temporary test database.
        db.execute("DROP TABLE public.auth_feedback_replies,public.auth_feedback")
        db.execute("DELETE FROM public.auth_meta WHERE key='feedback_schema'")
    assert user.get("/api/v1/feedback").status_code == 503
    with user.store.connect() as db:
        assert install_feedback_schema(db)
        assert not install_feedback_schema(db)
        assert db.execute("SELECT id,email_key FROM public.auth_users").fetchall() == before
    assert user.get("/api/v1/feedback").json()["items"] == []


def test_smtp_quota_reservations_are_atomic(identity_client, monkeypatch):
    store = identity_client.identity.store
    monkeypatch.setattr(store.settings, "mail_hour_limit", 10)
    monkeypatch.setattr(store.settings, "mail_day_limit", 2)
    monkeypatch.setattr(store.settings, "mail_month_limit", 3)

    def reserve(_):
        try:
            reserve_mail_slot(store)
        except MailQuotaReached:
            return False
        return True

    with ThreadPoolExecutor(max_workers=5) as pool:
        assert sum(pool.map(reserve, range(5))) == 2
    usage = {item.period: item for item in mail_quota_usage(store)}
    assert [usage[name].used for name in ("hour", "day", "month")] == [2, 2, 2]
    assert usage["day"].warning


def test_daily_mail_limits_and_cross_route_cooldown(identity_client, monkeypatch):
    client = identity_client
    monkeypatch.setattr(client.identity.settings, "mail_request_address_day_limit", 3)
    recipient = {"email": "pending@example.org"}
    for route in ("register", "resend", "continue"):
        result = post(client, "auth/" + route, {**recipient, "request_id": str(uuid4())})
        assert result.status_code == 200
    assert post(client, "auth/resend", {**recipient, "request_id": str(uuid4())}).status_code == 429
    with client.store.connect() as db:
        assert db.execute("SELECT count(*) AS n FROM public.auth_outbox").fetchone()["n"] == 1
