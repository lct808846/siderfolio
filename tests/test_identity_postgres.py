"""Production identity middleware and real PostgreSQL, using disposable databases."""

import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from psycopg import sql
from starlette.websockets import WebSocketDisconnect
from test_identity_security import otp

from astroagent.auth_config import AuthSettings
from astroagent.auth_store import AuthStore
from astroagent.config import LocalSettings
from astroagent.errors import ServiceError

pytestmark = [pytest.mark.identity, pytest.mark.postgres]
ORIGIN = "http://127.0.0.1:5173"
PASSWORD = "Synthetic nebula entropy 2048"


@pytest.fixture
def identity_client(monkeypatch, tmp_path):
    if os.getenv("ASTROAGENT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("Identity integration requires a disposable PostgreSQL environment")
    url = os.getenv("ASTROAGENT_TEST_DATABASE_URL", "")
    parsed = urlsplit(url)
    assert parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    assert parsed.path.startswith("/astroagent_test") and not parsed.query and not parsed.fragment
    name = "astroagent_test_identity_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as db:
        db.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
    target = urlunsplit(parsed._replace(path="/" + name))
    try:
        with psycopg.connect(target, autocommit=True) as db:
            db.execute("CREATE EXTENSION vector")
            db.execute("CREATE EXTENSION pg_trgm")
        monkeypatch.setenv("ASTROAGENT_DATABASE_URL", target)
        monkeypatch.setenv("ASTROAGENT_AUTH_ORIGIN", ORIGIN)
        monkeypatch.setenv("ASTROAGENT_AUTH_LOCAL_HTTP", "true")
        monkeypatch.setenv("ASTROAGENT_AUTH_SECRET", Fernet.generate_key().decode())
        monkeypatch.setenv("ASTROAGENT_RAG_MODEL_PATH", str(tmp_path / "synthetic-embedding"))
        monkeypatch.setenv("ASTROAGENT_RAG_MODEL_SHA256", "f" * 64)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-key-not-valid")
        for key, value in {
            "HOST": "smtp.example.org",
            "USER": "fixture@example.org",
            "PASSWORD": "synthetic-not-a-credential",
            "FROM": "fixture@example.org",
        }.items():
            monkeypatch.setenv("ASTROAGENT_AUTH_SMTP_" + key, value)
        from astroagent.auth_mail import MailWorker
        from astroagent.main import app

        monkeypatch.setattr(MailWorker, "start", lambda self: None)
        monkeypatch.setattr(MailWorker, "close", lambda self: None)
        store = AuthStore(LocalSettings(), AuthSettings())
        store.install()
        with TestClient(app, base_url=ORIGIN) as client:
            assert app.state.identity is not None, app.state.storage_code
            client.identity = app.state.identity
            client.store = store
            client.fresh = lambda: TestClient(app, base_url=ORIGIN)
            yield client
    finally:
        with psycopg.connect(url, autocommit=True) as db:
            db.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def post(client, path, body, method="POST"):
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200, response.text
    return client.request(
        method,
        "/api/v1/" + path,
        json=body,
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": response.json()["csrf_token"],
        },
    )


def mail_token(client, email):
    with client.store.connect() as db:
        row = db.execute(
            "SELECT o.payload FROM public.auth_outbox o JOIN public.auth_users u "
            "ON u.id=o.user_id WHERE u.email_key=%s AND o.state='pending' "
            "ORDER BY o.created_at DESC LIMIT 1",
            (email,),
        ).fetchone()
    payload = json.loads(client.store.crypto.decrypt(row["payload"].encode()))
    return parse_qs(urlsplit(payload["url"]).fragment)["token"][0]


def account(client, email="observer@example.org", *, login=True):
    response = post(client, "auth/register", {"email": email, "request_id": str(uuid4())})
    assert response.status_code == 200, response.text
    token = mail_token(client, email)
    response = post(client, "auth/activate/confirm", {"token": token})
    assert response.status_code == 200, response.text
    setup = response.json()["setup_token"]
    assert (
        post(client, "auth/activate/complete", {"token": setup, "password": PASSWORD}).status_code
        == 200
    )
    if login:
        response = post(client, "auth/login", {"email": email, "password": PASSWORD})
        assert response.status_code == 200, response.text
    return token, setup


def synthetic_admin(client):
    """Promote only this disposable database's synthetic account and enroll MFA."""
    account(client)
    with client.store.connect() as db:
        db.execute("UPDATE public.auth_users SET admin=true")
    enrollment = post(client, "auth/totp/enroll", {"password": PASSWORD})
    code = otp(enrollment.json()["secret"], int(time.time()) // 30)
    response = post(client, "auth/totp/confirm", {"code": code})
    assert response.status_code == 200, response.text
    return response.json()["recovery_codes"]


def test_disable_mfa_clears_secrets_revokes_sessions_and_requires_proof(identity_client):
    client = identity_client
    account(client)
    enrollment = post(client, "auth/totp/enroll", {"password": PASSWORD})
    code = otp(enrollment.json()["secret"], int(time.time()) // 30)
    confirmed = post(client, "auth/totp/confirm", {"code": code})
    assert confirmed.status_code == 200, confirmed.text
    recovery = confirmed.json()["recovery_codes"]
    cookie = client.cookies.get("astroagent_session")
    assert (
        post(
            client, "auth/totp/disable", {"password": "wrong-password", "code": recovery[0]}
        ).status_code
        == 403
    )
    assert (
        post(client, "auth/totp/disable", {"password": PASSWORD, "code": "invalid"}).status_code
        == 403
    )
    response = post(client, "auth/totp/disable", {"password": PASSWORD, "code": recovery[0]})
    assert response.status_code == 200, response.text
    assert client.store.authenticate(cookie) is None
    assert client.get("/api/v1/auth/session").status_code == 401
    with client.store.connect() as db:
        user = db.execute(
            "SELECT totp_secret,totp_pending,totp_pending_until,totp_step FROM public.auth_users"
        ).fetchone()
        assert user == {
            "totp_secret": None,
            "totp_pending": None,
            "totp_pending_until": None,
            "totp_step": -1,
        }
        assert db.execute("SELECT count(*) AS n FROM public.auth_recovery").fetchone()["n"] == 0
        assert (
            db.execute(
                "SELECT count(*) AS n FROM public.auth_sessions WHERE NOT revoked"
            ).fetchone()["n"]
            == 0
        )
        assert db.execute("SELECT 1 FROM public.auth_audit WHERE event='totp_disabled'").fetchone()
    response = post(client, "auth/login", {"email": "observer@example.org", "password": PASSWORD})
    assert response.status_code == 200 and "totp_required" not in response.text


def test_admin_cannot_disable_required_mfa(identity_client):
    client = identity_client
    recovery = synthetic_admin(client)
    response = post(client, "auth/totp/disable", {"password": PASSWORD, "code": recovery[0]})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "admin_mfa_required"
    assert client.get("/api/v1/auth/session").json()["user"]["totp_enabled"]


def test_provider_admin_boundary_encryption_revision_and_secret_retention(identity_client):
    from astroagent.model_providers import KEY

    client = identity_client
    account(client)
    path = "admin/model-providers"
    assert client.get("/api/v1/" + path).status_code == 403
    with client.store.connect() as db:
        db.execute("UPDATE public.auth_users SET admin=true")
    assert client.get("/api/v1/" + path).status_code == 403
    enrollment = post(client, "auth/totp/enroll", {"password": PASSWORD})
    code = otp(enrollment.json()["secret"], int(time.time()) // 30)
    assert post(client, "auth/totp/confirm", {"code": code}).status_code == 200
    with client.store.connect() as db:
        db.execute("UPDATE public.auth_sessions SET reauth_at=NULL")
    value = client.get("/api/v1/" + path).json()
    body = {
        "revision": value["revision"],
        "id": "synthetic",
        "name": "Synthetic provider",
        "base_url": "https://models.example.org/v1",
        "api_key": "synthetic-qa-private-key",
        "protocol": "gemini",
        "models": [{"id": "synthetic-model", "label": "Synthetic"}],
    }
    response = post(client, path, body, "PUT")
    assert response.status_code == 200, response.text
    assert "synthetic-qa-private-key" not in response.text
    saved = response.json()
    assert saved["revision"] == value["revision"] + 1
    with client.store.connect() as db:
        encrypted = db.execute(
            "SELECT value FROM public.auth_meta WHERE key=%s", (KEY,)
        ).fetchone()["value"]
        assert "synthetic-qa-private-key" not in encrypted
        assert (
            "synthetic-qa-private-key" in client.store.crypto.decrypt(encrypted.encode()).decode()
        )
    assert post(client, path, body, "PUT").status_code == 409
    body.pop("api_key")
    body["revision"] = saved["revision"]
    body["name"] = "Synthetic renamed"
    response = post(client, path, body, "PUT")
    assert response.status_code == 200, response.text
    body["revision"] = response.json()["revision"]
    body["base_url"] = "https://different.example.org/v1"
    assert post(client, path, body, "PUT").status_code == 422
    chosen = response.json()["providers"][-1]["models"][0]["selection_id"]
    response = post(client, path + "/default", {"model": chosen, "revision": body["revision"]})
    assert response.status_code == 200, response.text
    assert client.get("/api/v1/models").json()["default_model"] == chosen
    status = client.get("/api/v1/setup/status")
    assert status.status_code == 200, status.text
    assert status.json()["answering_model"] == chosen
    assert "synthetic-qa-private-key" not in status.text
    assert post(client, "setup/initialize", {"confirmed": False}).status_code == 422
    assert post(client, "setup/initialize", {"confirmed": True}).status_code == 200
    removed = post(client, path + "/synthetic", {"revision": response.json()["revision"]}, "DELETE")
    assert removed.status_code == 200, removed.text
    assert chosen not in {m["id"] for m in client.get("/api/v1/models").json()["models"]}
    # Model configuration intentionally needs MFA, while account administration keeps recent proof.
    assert post(client, "admin/mail/" + str(uuid4()) + "/retry", {}).status_code == 403


def test_provider_validation_redacts_key_and_blocks_internal_directory(
    identity_client, monkeypatch
):
    import socket

    client = identity_client
    synthetic_admin(client)
    body = {
        "revision": 0,
        "id": "synthetic",
        "name": "Synthetic",
        "base_url": "http://127.0.0.1",
        "api_key": "synthetic-qa-private-key",
    }
    response = post(client, "admin/model-providers", body, "PUT")
    assert response.status_code == 422 and "synthetic-qa-private-key" not in response.text
    body["base_url"] = "https://models.example.org/v1"
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    response = post(client, "admin/model-providers/discover", body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "provider_address_invalid"
    # No CSRF bypass is introduced by the model-settings recent-proof exception.
    assert client.put("/api/v1/admin/model-providers", json=body).status_code == 403


def test_password_precedes_mfa_challenge(identity_client):
    client = identity_client
    synthetic_admin(client)
    email = "observer@example.org"
    assert post(client, "auth/logout", {}).status_code == 200
    wrong = post(client, "auth/login", {"email": email, "password": "wrong-password"})
    assert wrong.status_code == 401
    assert "totp_required" not in wrong.text
    # Clear synthetic backoff to isolate challenge semantics, without weakening production logic.
    with client.store.connect() as db:
        db.execute("DELETE FROM public.auth_attempts")
    response = post(client, "auth/login", {"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["action"] == "totp_required"
    assert client.get("/api/v1/auth/session").status_code == 401


def test_session_revocation_is_owned_requires_proof_and_protects_current(identity_client):
    client = identity_client
    account(client)
    original = client.cookies.get("astroagent_session")
    assert (
        post(
            client, "auth/login", {"email": "observer@example.org", "password": PASSWORD}
        ).status_code
        == 200
    )
    # A new login explicitly revokes an authenticated previous browser, so use an
    # independent unauthenticated cookie jar for the second synthetic browser.
    other = client.fresh()
    assert (
        post(
            other, "auth/login", {"email": "observer@example.org", "password": PASSWORD}
        ).status_code
        == 200
    )
    sessions = client.get("/api/v1/auth/sessions").json()
    current = next(s for s in sessions if s["current"])
    target = next(s for s in sessions if not s["current"])
    body = {"session_id": target["id"], "password": "wrong-password"}
    assert post(client, "auth/sessions/revoke", body).status_code == 403
    body["password"] = PASSWORD
    assert (
        post(client, "auth/sessions/revoke", {**body, "session_id": current["id"]}).status_code
        == 409
    )
    assert post(client, "auth/sessions/revoke", {**body, "session_id": "0" * 64}).status_code == 404
    assert post(client, "auth/sessions/revoke", body).status_code == 200
    assert other.get("/api/v1/auth/session").status_code == 401
    assert client.get("/api/v1/auth/session").status_code == 200
    assert original != client.cookies.get("astroagent_session")
    foreign = client.fresh()
    foreign.store = client.store
    account(foreign, "second@example.org")
    foreign_id = foreign.get("/api/v1/auth/sessions").json()[0]["id"]
    assert (
        post(client, "auth/sessions/revoke", {**body, "session_id": foreign_id}).status_code == 404
    )
    assert foreign.get("/api/v1/auth/session").status_code == 200


def test_all_business_routes_deny_anonymous_before_body(identity_client):
    from astroagent.auth_access import PUBLIC
    from astroagent.main import app

    client = identity_client
    protected = 0
    for path, operations in app.openapi()["paths"].items():
        for verb in operations:
            method = verb.upper()
            if path == "/health" or (method, path) in PUBLIC:
                continue
            response = client.request(method, path)
            assert response.status_code == 401, (method, path, response.status_code)
            protected += 1
    assert protected > 75
    for path in ("/api/v1/missing", "/api/v1/%2e%2e/admin", "/openapi.json", "/docs"):
        assert client.get(path).status_code == 401
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect("/api/v1/events"):
            pytest.fail("Anonymous WebSocket must never be accepted")
    assert error.value.code == 4401


def test_registration_scanner_replay_and_cookie_policy(identity_client):
    client = identity_client
    email, request_id = "observer@example.org", str(uuid4())
    body = {"email": email, "request_id": request_id}
    assert post(client, "auth/register", body).status_code == 200
    token = mail_token(client, email)
    assert client.get("/activate#token=" + token).status_code == 401
    with client.store.connect() as db:
        assert not db.execute("SELECT active FROM public.auth_users").fetchone()["active"]
        assert token not in str(db.execute("SELECT hash FROM public.auth_tokens").fetchall())
    assert post(client, "auth/register", body).status_code == 200
    assert mail_token(client, email) == token
    setup = post(client, "auth/activate/confirm", {"token": token}).json()["setup_token"]
    assert post(client, "auth/activate/confirm", {"token": token}).status_code == 422
    assert (
        post(client, "auth/activate/complete", {"token": setup, "password": PASSWORD}).status_code
        == 200
    )
    assert (
        post(client, "auth/activate/complete", {"token": setup, "password": PASSWORD}).status_code
        == 422
    )
    response = post(client, "auth/login", {"email": email, "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Max-Age=" in cookie.split("astroagent_preauth")[0]
    assert client.get("/api/v1/auth/session").json()["user"]["email"] == email
    assert post(client, "auth/logout", {}).status_code == 200
    assert client.get("/api/v1/conversations").status_code == 401


def test_csrf_origin_body_limit_and_error_redaction(identity_client):
    client = identity_client
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    body = {"email": "observer@example.org", "request_id": str(uuid4())}
    assert client.post("/api/v1/auth/register", json=body).status_code == 403
    assert (
        client.post(
            "/api/v1/auth/register",
            json=body,
            headers={
                "Origin": "https://evil.example.org",
                "X-CSRF-Token": csrf,
            },
        ).status_code
        == 403
    )
    response = client.post(
        "/api/v1/auth/login",
        content='{"password":"' + "z" * 17000 + '"}',
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 413 and "z" * 100 not in response.text
    response = post(client, "auth/login", {"password": "synthetic-secret-marker"})
    assert response.status_code == 422 and "synthetic-secret-marker" not in response.text


def test_two_accounts_isolate_ids_and_missing_table_never_falls_back(identity_client):
    client = identity_client
    account(client)
    first = post(client, "conversations", {"title": "First account private data"})
    assert first.status_code == 201, first.text
    identifier = first.json()["id"]
    project = post(client, "projects", {"name": "First private project"}).json()
    first_cookie = client.cookies.get("astroagent_session")
    assert post(client, "auth/logout", {}).status_code == 200
    account(client, "second@example.org")
    assert client.get("/api/v1/conversations").json() == []
    assert client.get("/api/v1/conversations/" + identifier).status_code == 404
    assert client.get("/api/v1/projects/" + project["id"]).status_code == 404
    assert (
        post(client, "conversations/" + identifier, {"title": "stolen"}, "PATCH").status_code == 404
    )
    second = post(client, "conversations", {"title": "Second private data"})
    assert second.status_code == 201
    user = client.identity.store.authenticate(client.cookies.get("astroagent_session"))
    service = client.identity.tenants.for_user(user)
    with client.store.connect() as db:
        db.execute(
            sql.SQL("ALTER TABLE {}.conversations RENAME TO missing_conversations").format(
                sql.Identifier(user["namespace"])
            )
        )
        db.execute("CREATE TABLE public.conversations(id text, title text)")
        db.execute("INSERT INTO public.conversations VALUES ('public-private','must not leak')")
    with pytest.raises((psycopg.errors.UndefinedTable, ServiceError)):
        service.repository.list()
    assert not client.identity.store.authenticate(first_cookie)


@pytest.mark.parametrize("expiry", ["absolute", "revoked", "disabled"])
def test_session_expiry_and_disable_fail_closed(identity_client, expiry):
    client = identity_client
    account(client)
    with client.store.connect() as db:
        statement = {
            "absolute": "UPDATE public.auth_sessions SET expires_at=now()-interval '1 second'",
            "revoked": "UPDATE public.auth_sessions SET revoked=true",
            "disabled": "UPDATE public.auth_users SET disabled=true,generation=generation+1",
        }[expiry]
        db.execute(statement)
    assert client.get("/api/v1/conversations").status_code == 401


def test_reset_revokes_all_sessions_and_tokens(identity_client):
    client = identity_client
    account(client)
    cookie = client.cookies.get("astroagent_session")
    response = post(
        client,
        "auth/forgot-password",
        {"email": "observer@example.org", "request_id": str(uuid4())},
    )
    assert response.status_code == 200
    token = mail_token(client, "observer@example.org")
    new_password = "Another synthetic nebula password 4096"
    assert (
        post(client, "auth/reset-password", {"token": token, "password": new_password}).status_code
        == 200
    )
    assert not client.store.authenticate(cookie)
    assert (
        post(client, "auth/reset-password", {"token": token, "password": new_password}).status_code
        == 422
    )
    assert (
        post(
            client, "auth/login", {"email": "observer@example.org", "password": new_password}
        ).status_code
        == 200
    )


def test_wrong_key_and_lost_lock_fail_closed(identity_client):
    client = identity_client
    account(client)
    wrong = AuthStore(
        LocalSettings(),
        client.identity.settings.model_copy(
            update={
                "secret": AuthSettings(
                    _env_file=None,
                    origin=ORIGIN,
                    local_http=True,
                    secret=Fernet.generate_key().decode(),
                ).secret,
            }
        ),
    )
    with pytest.raises(ServiceError) as error:
        wrong.check()
    assert error.value.error.code == "identity_key_mismatch"
    client.identity.guard.close()
    assert client.get("/api/v1/conversations").status_code == 503


def test_encrypted_outbox_submission_and_expired_mail(identity_client, monkeypatch):
    client = identity_client
    post(client, "auth/register", {"email": "observer@example.org", "request_id": str(uuid4())})
    token = mail_token(client, "observer@example.org")
    worker = client.identity.mail
    row = worker.take()
    assert token not in row["payload"] and "observer@example.org" not in row["payload"]
    sent = []

    @contextmanager
    def smtp(*args, **kwargs):
        assert kwargs["context"].check_hostname and kwargs["timeout"] == 10

        class Connection:
            def login(self, *credentials):
                pass

            def send_message(self, message):
                sent.append(message)

        yield Connection()

    monkeypatch.setattr("astroagent.auth_mail.smtplib.SMTP_SSL", smtp)
    worker.deliver(row)
    assert len(sent) == 1 and token in sent[0].get_content()
    with client.store.connect() as db:
        state = db.execute("SELECT state,payload FROM public.auth_outbox").fetchone()
        assert state == {"state": "submitted", "payload": ""}
        db.execute("UPDATE public.auth_outbox SET created_at=now()-interval '61 seconds'")
    post(client, "auth/resend", {"email": "observer@example.org", "request_id": str(uuid4())})
    row = worker.take()
    with client.store.connect() as db:
        db.execute("UPDATE public.auth_tokens SET expires_at=now()-interval '1 second'")
    worker.deliver(row)
    assert len(sent) == 1
    with client.store.connect() as db:
        assert (
            db.execute("SELECT state FROM public.auth_outbox WHERE id=%s", (row["id"],)).fetchone()[
                "state"
            ]
            == "cancelled"
        )


def test_disabled_generation_blocks_existing_worker_repository(identity_client):
    client = identity_client
    account(client)
    post(client, "conversations", {"title": "Synthetic ongoing task"})
    user = client.store.authenticate(client.cookies.get("astroagent_session"))
    repository = client.identity.tenants.for_user(user).repository
    with client.store.connect() as db:
        db.execute(
            "UPDATE public.auth_users SET generation=generation+1 WHERE id=%s", (user["id"],)
        )
    with pytest.raises(ServiceError) as error:
        repository.create("must not commit")
    assert error.value.error.code == "account_unavailable"


def test_generation_change_during_transaction_rolls_back(identity_client):
    client = identity_client
    account(client)
    post(client, "conversations", {"title": "Before revocation"})
    user = client.store.authenticate(client.cookies.get("astroagent_session"))
    repository = client.identity.tenants.for_user(user).repository
    with repository.connection() as db:
        with pytest.raises(ServiceError):
            with repository.transaction(db):
                db.execute("UPDATE conversations SET title=?", ("must roll back",))
                with client.store.connect() as control:
                    control.execute("UPDATE public.auth_users SET generation=generation+1")
        assert db.execute("SELECT title FROM conversations").fetchone()[0] == "Before revocation"


def test_concurrent_email_confirmation_is_one_use(identity_client):
    client = identity_client
    post(client, "auth/register", {"email": "observer@example.org", "request_id": str(uuid4())})
    token = mail_token(client, "observer@example.org")
    from astroagent.main import app

    def confirm():
        # No second lifespan: both browser sessions use the one production runtime.
        other = TestClient(app, base_url=ORIGIN)
        try:
            return post(other, "auth/activate/confirm", {"token": token}).status_code
        finally:
            other.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: confirm(), range(2)))
    assert sorted(results) == [200, 422]


def test_admin_requires_totp_recent_proof_and_one_use_recovery(identity_client):
    client = identity_client
    account(client)
    assert client.get("/api/v1/admin/overview").status_code == 403
    user = client.store.authenticate(client.cookies.get("astroagent_session"))
    # Explicit fixture promotion, never a first-user production default.
    with client.store.connect() as db:
        db.execute("UPDATE public.auth_users SET admin=true WHERE id=%s", (user["id"],))
    assert client.get("/api/v1/conversations").status_code == 403
    enrollment = post(client, "auth/totp/enroll", {"password": PASSWORD})
    assert enrollment.status_code == 200, enrollment.text
    code = otp(enrollment.json()["secret"], int(time.time()) // 30)
    confirmation = post(client, "auth/totp/confirm", {"code": code})
    assert confirmation.status_code == 200, confirmation.text
    recovery = confirmation.json()["recovery_codes"]
    assert len(recovery) == 10 and len(set(recovery)) == 10
    assert client.get("/api/v1/admin/overview").status_code == 200
    assert (
        post(client, "auth/reauthenticate", {"password": PASSWORD, "code": code}).status_code == 403
    )
    assert (
        post(client, "auth/reauthenticate", {"password": PASSWORD, "code": recovery[0]}).status_code
        == 200
    )
    assert (
        post(client, "auth/reauthenticate", {"password": PASSWORD, "code": recovery[0]}).status_code
        == 403
    )
    response = post(
        client,
        "admin/users/" + user["id"],
        {
            "action": "disable",
            "reason": "account_review",
        },
        "PATCH",
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "self_lockout"
    with client.store.connect() as db:
        db.execute("UPDATE public.auth_sessions SET reauth_at=now()-interval '6 minutes'")
        stored = db.execute("SELECT hash FROM public.auth_recovery").fetchall()
        assert not any(value in str(stored) for value in recovery)
    assert post(client, "admin/mail/" + str(uuid4()) + "/retry", {}).status_code == 403


def test_offline_maintenance_refuses_running_backend(identity_client, monkeypatch):
    from astroagent.identity_cli import main

    account(identity_client)
    monkeypatch.setattr("sys.argv", ["identity", "initialize"])
    with pytest.raises(ValueError, match="Stop all"):
        main()


def test_email_rate_limit_idempotency_and_expiry(identity_client):
    client = identity_client
    request = {"email": "observer@example.org", "request_id": str(uuid4())}
    assert post(client, "auth/register", request).status_code == 200
    token = mail_token(client, request["email"])
    with client.store.connect() as db:
        db.execute("UPDATE public.auth_tokens SET expires_at=now()-interval '1 second'")
    assert post(client, "auth/activate/confirm", {"token": token}).status_code == 422
    for _ in range(4):
        assert post(client, "auth/resend", request).status_code == 200
    assert post(client, "auth/resend", request).status_code == 429
    with client.store.connect() as db:
        assert db.execute("SELECT count(*) AS n FROM public.auth_outbox").fetchone()["n"] == 1


def test_tenant_document_vector_and_archive_roundtrip(identity_client):
    from test_rag_postgres import build, preview, project_with_document

    client = identity_client
    account(client)
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf})
    root, document = project_with_document(client)
    user = client.store.authenticate(client.cookies.get("astroagent_session"))
    service = client.identity.tenants.for_user(user)

    class Embedder:
        def identity(self):
            return "f" * 64

        def encode(self, texts):
            return [[1 / math.sqrt(384)] * 384 for _ in texts]

    service.rag.embedder = Embedder()
    build(client, root)
    evidence = preview(client, root)
    assert evidence["semantic_status"] == "ready"
    document_path = root + "/documents/" + document["id"]
    content_path = document_path + "/versions/" + document["current_version_id"] + "/content"
    original = client.get(content_path)
    assert original.status_code == 200 and b"Binary cluster" in original.content
    revision = client.get(root).json()["revision"]
    exported = client.post(
        root + "/archive", json={"expected_revision": revision, "format_version": 6}
    )
    assert exported.status_code == 200, exported.text
    restored = client.post(
        "/api/v1/projects/import",
        content=exported.content,
        headers={
            "Content-Type": "application/zip",
        },
    )
    assert restored.status_code == 201, restored.text
    client.headers.clear()
    assert post(client, "auth/logout", {}).status_code == 200
    account(client, "second@example.org")
    assert client.get(document_path).status_code == 404
    assert client.get(content_path).status_code == 404
    assert (
        post(
            client,
            root.removeprefix("/api/v1/") + "/rag/previews",
            {
                "question": "binary cluster",
            },
        ).status_code
        == 404
    )
    assert client.get(root + "/rag/answers").status_code == 404


def test_smtp_rejection_does_not_activate_account(identity_client, monkeypatch):
    import smtplib

    client = identity_client
    post(client, "auth/register", {"email": "observer@example.org", "request_id": str(uuid4())})
    worker = client.identity.mail

    @contextmanager
    def rejected(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"synthetic credential failure")
        yield  # pragma: no cover

    monkeypatch.setattr("astroagent.auth_mail.smtplib.SMTP_SSL", rejected)
    monkeypatch.setattr(worker.stop, "wait", lambda _: worker.stop.set())
    worker.run()
    with client.store.connect() as db:
        row = db.execute("SELECT state,error_class FROM public.auth_outbox").fetchone()
        assert row == {"state": "failed", "error_class": "smtp_authentication"}
        assert not db.execute("SELECT active FROM public.auth_users").fetchone()["active"]


def test_login_denials_are_generic_and_backoff_is_enforced(identity_client):
    client = identity_client
    account(client, login=False)
    response = post(
        client, "auth/login", {"email": "observer@example.org", "password": "wrong password"}
    )
    assert response.status_code == 401
    public_error = response.json()
    assert (
        post(
            client, "auth/login", {"email": "observer@example.org", "password": PASSWORD}
        ).status_code
        == 429
    )
    with client.store.connect() as db:
        db.execute("UPDATE public.auth_attempts SET blocked_until=now()-interval '1 second'")
    response = post(
        client, "auth/login", {"email": "unknown@example.org", "password": "wrong password"}
    )
    assert response.status_code == 401 and response.json() == public_error


def test_offline_admin_preview_confirmation_and_no_default_admin(identity_client, monkeypatch):
    from astroagent.identity_cli import main

    client = identity_client
    account(client)
    user = client.store.authenticate(client.cookies.get("astroagent_session"))
    assert not user["admin"]
    client.identity.close()
    argv = ["identity", "bootstrap-admin", "--email", "observer@example.org"]
    monkeypatch.setattr("sys.argv", argv)
    main()
    with client.store.connect() as db:
        assert not db.execute("SELECT admin FROM public.auth_users").fetchone()["admin"]
    monkeypatch.setattr("sys.argv", [*argv, "--apply"])
    monkeypatch.setattr("builtins.input", lambda _: "wrong-confirmation")
    with pytest.raises(ValueError, match="Confirmation"):
        main()
    monkeypatch.setattr("builtins.input", lambda _: user["id"])
    main()
    with client.store.connect() as db:
        assert db.execute("SELECT admin FROM public.auth_users").fetchone()["admin"]
    assert not client.store.authenticate(client.cookies.get("astroagent_session"))


def test_expired_mail_lease_recovers_and_exhaustion_stops_retry(identity_client, monkeypatch):
    client = identity_client
    post(client, "auth/register", {"email": "observer@example.org", "request_id": str(uuid4())})
    worker = client.identity.mail
    first = worker.take()
    assert first and worker.take() is None
    with client.store.connect() as db:
        db.execute("UPDATE public.auth_outbox SET lease_until=now()-interval '1 second'")
    second = worker.take()
    assert second["id"] == first["id"] and second["attempts"] == 1
    with client.store.connect() as db:
        db.execute("UPDATE public.auth_outbox SET attempts=5,lease_until=now()-interval '1 second'")
    assert worker.take() is None
    monkeypatch.setattr(worker.stop, "wait", lambda _: worker.stop.set())
    worker.run()
    with client.store.connect() as db:
        row = db.execute("SELECT state,error_class,attempts FROM public.auth_outbox").fetchone()
        assert row == {"state": "failed", "error_class": "retry_exhausted", "attempts": 5}


def test_starttls_precedes_authentication_and_submission(identity_client, monkeypatch):
    client = identity_client
    post(client, "auth/register", {"email": "observer@example.org", "request_id": str(uuid4())})
    worker = client.identity.mail
    worker.settings.smtp_mode = "starttls"
    operations = []

    @contextmanager
    def smtp(*args, **kwargs):
        assert "context" not in kwargs

        class Connection:
            def ehlo(self):
                operations.append("ehlo")

            def starttls(self, context):
                assert context.check_hostname
                operations.append("starttls")

            def login(self, *args):
                operations.append("login")

            def send_message(self, message):
                operations.append("submit")

        yield Connection()

    monkeypatch.setattr("astroagent.auth_mail.smtplib.SMTP", smtp)
    worker.deliver(worker.take())
    assert operations == ["ehlo", "starttls", "ehlo", "login", "submit"]


def test_profile_is_private_and_persists_in_session(identity_client):
    client = identity_client
    account(client)
    user = client.store.authenticate(client.cookies.get("astroagent_session"))
    response = post(client, "auth/profile", {"username": "Research Observer"})
    assert response.status_code == 200, response.text
    assert client.get("/api/v1/auth/session").json()["user"]["username"] == "Research Observer"
    for username in ("", "x" * 33, "bad\x00name"):
        assert post(client, "auth/profile", {"username": username}).status_code in (400, 422)
    post(client, "auth/logout", {})
    account(client, "second@example.org")
    assert post(client, "auth/profile", {"username": "Other Observer"}).status_code == 200
    with client.store.connect() as db:
        assert (
            db.execute(
                "SELECT username FROM public.auth_users WHERE id=%s", (user["id"],)
            ).fetchone()["username"]
            == "Research Observer"
        )


def test_existing_identity_schema_accepts_username_feature(identity_client):
    client = identity_client
    account(client)
    with client.store.connect() as db:
        db.execute("ALTER TABLE public.auth_users DROP COLUMN username")
    client.store.check()
    response = post(client, "auth/profile", {"username": "Upgraded Observer"})
    assert response.status_code == 200, response.text


def test_current_persistent_session_renewal_preserves_revocation(identity_client):
    client = identity_client
    account(client)
    cookie = client.cookies.get("astroagent_session")
    with client.store.connect() as db:
        db.execute("UPDATE public.auth_sessions SET expires_at=now()+interval '20 minutes'")
        before = db.execute("SELECT expires_at FROM public.auth_sessions").fetchone()["expires_at"]
    client.store.authenticate(cookie)
    client.store.check()
    with client.store.connect() as db:
        after = db.execute("SELECT expires_at FROM public.auth_sessions").fetchone()["expires_at"]
    assert after > before, "Current persistent-login behavior renews a valid session"
    with client.store.connect() as db:
        db.execute("UPDATE public.auth_sessions SET revoked=true")
    client.store.check()
    assert client.store.authenticate(cookie) is None


def test_existing_browser_session_survives_network_change_and_new_login(identity_client):
    client = identity_client
    account(client)
    with client.store.connect() as db:
        db.execute(
            "UPDATE public.auth_sessions SET source_hash='synthetic-other-network', "
            "last_seen=now()-interval '1 day'"
        )
    assert client.get("/api/v1/auth/session").status_code == 200

    other = client.fresh()
    try:
        response = post(
            other, "auth/login", {"email": "observer@example.org", "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        assert other.get("/api/v1/auth/session").status_code == 200
        assert client.get("/api/v1/conversations").status_code == 200
    finally:
        other.close()


def test_enrollment_uri_roundtrip_matches_returned_secret(identity_client):
    client = identity_client
    account(client)
    response = post(client, "auth/totp/enroll", {"password": PASSWORD})
    assert response.status_code == 200, response.text
    value = response.json()
    uri = urlsplit(value["otpauth_uri"])
    query = parse_qs(uri.query)
    assert uri.scheme == "otpauth" and uri.netloc == "totp"
    assert query["secret"] == [value["secret"]]
    assert query["issuer"] == ["Siderfolio"]
    assert query["digits"] == ["6"] and query["period"] == ["30"]


def test_current_email_continue_flow_and_resend_cooldown(identity_client):
    client = identity_client
    account(client, login=False)
    known = post(
        client, "auth/continue", {"email": "observer@example.org", "request_id": str(uuid4())}
    )
    assert known.status_code == 200
    assert known.json() == {"action": "login", "totp_enabled": False}
    body = {"email": "new@example.org", "request_id": str(uuid4())}
    first = post(client, "auth/continue", body)
    assert first.status_code == 200 and first.json()["action"] == "activate_sent"
    second = post(client, "auth/continue", {**body, "request_id": str(uuid4())})
    assert second.status_code == 200 and 0 < second.json()["cooldown"] <= 60
    with client.store.connect() as db:
        count = db.execute(
            "SELECT count(*) AS n FROM public.auth_outbox o JOIN public.auth_users u "
            "ON u.id=o.user_id WHERE u.email_key='new@example.org'"
        ).fetchone()["n"]
        assert count == 1


def test_multidevice_details_anomaly_email_non_revoking_and_revoke_others(identity_client):
    client = identity_client
    win_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    iphone_ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1"
    )
    client.headers.update({"User-Agent": win_ua})
    account(client)

    # Simulate an active prior session from a different network/country and device.
    with client.store.connect() as db:
        db.execute(
            "UPDATE public.auth_sessions SET source_hash='known-cn-source', "
            "login_ip='198.51.100.10', last_ip='198.51.100.10', "
            "network_prefix='198.51.100.0/24', country_code='CN', "
            "login_location='中国 · Shanghai', last_location='中国 · Shanghai'"
        )

    other = client.fresh()
    third = client.fresh()
    try:
        other.headers.update({"User-Agent": iphone_ua})
        resp = post(other, "auth/login", {"email": "observer@example.org", "password": PASSWORD})
        assert resp.status_code == 200, resp.text
        # Both devices stay logged in simultaneously; anomaly does NOT force logout.
        assert client.get("/api/v1/auth/session").status_code == 200
        assert other.get("/api/v1/auth/session").status_code == 200

        with client.store.connect() as db:
            mail_row = db.execute(
                "SELECT payload FROM public.auth_outbox WHERE purpose='security' "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            assert mail_row is not None
            payload = json.loads(client.store.crypto.decrypt(mail_row["payload"].encode()))
            assert payload["subject"] == "Siderfolio 异常登录提醒"
            assert "iPhone" in payload["message"]
            assert "不会强制退出" in payload["message"]

        third.headers.update({"User-Agent": win_ua})
        assert (
            post(
                third, "auth/login", {"email": "observer@example.org", "password": PASSWORD}
            ).status_code
            == 200
        )

        device_list = client.get("/api/v1/auth/sessions").json()
        assert len(device_list) == 3
        assert device_list[0]["current"] is True
        assert device_list[0]["device_type"] == "desktop"
        assert "Chrome" in device_list[0]["browser"]
        mobile_item = next(item for item in device_list if item["device_type"] == "mobile")
        assert mobile_item["is_anomalous"] is True
        assert "new_device" in mobile_item["anomaly_reasons"]
        assert "iPhone" in mobile_item["user_agent"]

        revoked = post(client, "auth/sessions/revoke-others", {"password": PASSWORD})
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["revoked_count"] == 2
        assert client.get("/api/v1/auth/session").status_code == 200
        assert other.get("/api/v1/auth/session").status_code == 401
        assert third.get("/api/v1/auth/session").status_code == 401
    finally:
        other.close()
        third.close()
