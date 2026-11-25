"""V1.6 identity primitives; no legacy middleware bypass or private configuration."""

import asyncio
import base64
import hashlib
import hmac
import struct

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from astroagent.auth_config import AuthSettings
from astroagent.auth_security import email_address, hash_password, totp_step, verify_password
from astroagent.errors import ServiceError

pytestmark = pytest.mark.identity


def settings(**kwargs):
    return AuthSettings(
        _env_file=None,
        origin="http://127.0.0.1:5173",
        local_http=True,
        secret=Fernet.generate_key().decode(),
        **kwargs,
    )


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.org",
        "https://user:pass@example.org",
        "https://example.org/path",
        "https://example.org?x=1",
        "https://example.org#token",
        "file:///tmp/site",
    ],
)
def test_untrusted_origin_is_rejected(origin):
    with pytest.raises(ValidationError):
        AuthSettings(_env_file=None, origin=origin)


def test_remote_origin_requires_secure_cookies_and_encrypted_smtp():
    assert AuthSettings(_env_file=None, origin="https://example.org").secure
    with pytest.raises(ValidationError):
        AuthSettings(_env_file=None, origin="http://127.0.0.1:5173")
    with pytest.raises(ValidationError):
        settings(smtp_mode="plain")


@pytest.mark.parametrize("password", ["short", "x" * 129, "x" * 8, "passwordpassword"])
def test_password_length_common_and_repeated_rejected(password):
    with pytest.raises(ServiceError):
        hash_password(password, settings())


def test_unicode_password_normalization_and_bounds():
    value = "Stellar cafe\u0301 entropy 2048"
    encoded = hash_password(value, settings())
    assert encoded.startswith("$argon2id$")
    assert verify_password(encoded, "Stellar caf\u00e9 entropy 2048")
    assert not verify_password(encoded, "wrong unique password")
    assert verify_password(hash_password("A" + "z" * 127, settings()), "A" + "z" * 127)
    assert verify_password(hash_password("A" + "z" * 7, settings()), "A" + "z" * 7)


def test_blocklist_tamper_fails_closed(tmp_path):
    path = tmp_path / "blocklist.txt"
    path.write_text("not the distributed password list")
    with pytest.raises(ServiceError) as error:
        hash_password(
            "A unique stellar password",
            settings(
                password_blocklist=path,
                password_blocklist_sha256="0" * 64,
            ),
        )
    assert error.value.error.code == "password_policy_unavailable"


def test_email_domain_normalized_without_merging_local_parts():
    assert email_address("Observer@EXAMPLE.org")[0] == "Observer@example.org"
    assert email_address("observer@example.org")[0] != email_address("Observer@example.org")[0]
    assert email_address("astro@\u4f8b\u5b50.com")[0] == "astro@xn--fsqu00a.com"
    with pytest.raises(ServiceError):
        email_address("not-an-email")


def otp(secret, step):
    raw = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = raw[-1] & 15
    return f"{(struct.unpack('>I', raw[offset : offset + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"


def test_totp_one_use_window_and_ascii(monkeypatch):
    monkeypatch.setattr("astroagent.auth_security.time.time", lambda: 3000)
    secret = base64.b32encode(b"fixed synthetic seed").decode()
    assert totp_step(secret, otp(secret, 100)) == 100
    assert totp_step(secret, otp(secret, 100), 100) is None
    assert totp_step(secret, otp(secret, 98)) is None
    assert totp_step(secret, "１２３４５６") is None


def test_secure_session_cookie_flags():
    from fastapi import Response

    from astroagent.api.auth import set_session

    response = Response()
    set_session(response, AuthSettings(_env_file=None, origin="https://example.org"), "synthetic")
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Max-Age=" in cookie.split("astroagent_preauth")[0]


def test_device_parsing_and_anomaly_detection():
    from types import SimpleNamespace

    from astroagent.auth_device import (
        build_anomalous_login_email,
        detect_login_anomalies,
        extract_client_context,
    )

    desktop_req = SimpleNamespace(
        headers={
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "sec-ch-ua-platform": '"Windows"',
            "sec-ch-ua-mobile": "?0",
        },
        state=SimpleNamespace(
            trusted_client_country="CN",
            trusted_client_region="Shanghai",
            trusted_client_city="",
        ),
    )
    desktop_ctx = extract_client_context(desktop_req, "198.51.100.10")
    assert desktop_ctx.device_type == "desktop"
    assert desktop_ctx.os == "Windows 10/11"
    assert desktop_ctx.browser == "Chrome 131"
    assert desktop_ctx.country_code == "CN"
    assert desktop_ctx.location == "中国 · Shanghai"
    assert desktop_ctx.network_prefix == "198.51.100.0/24"

    mobile_req = SimpleNamespace(
        headers={
            "user-agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1"
            ),
        },
        state=SimpleNamespace(
            trusted_client_country="JP",
            trusted_client_region="Tokyo",
            trusted_client_city="",
        ),
    )
    mobile_ctx = extract_client_context(mobile_req, "203.0.113.45")
    assert mobile_ctx.device_type == "mobile"
    assert "iPhone" in mobile_ctx.device_name
    assert "Safari" in mobile_ctx.browser
    assert mobile_ctx.location == "日本 · Tokyo"

    history = [
        {
            "source_hash": "hash-cn",
            "network_prefix": desktop_ctx.network_prefix,
            "country_code": desktop_ctx.country_code,
            "login_location": desktop_ctx.location,
            "last_location": desktop_ctx.location,
            "device_type": desktop_ctx.device_type,
            "device_name": desktop_ctx.device_name,
            "os": desktop_ctx.os,
            "browser": desktop_ctx.browser,
        }
    ]
    assert (
        detect_login_anomalies(
            current=desktop_ctx, current_source_hash="hash-cn", recent_sessions=history
        )
        == []
    )
    anomalies = detect_login_anomalies(
        current=mobile_ctx, current_source_hash="hash-jp", recent_sessions=history
    )
    assert "different_location" in anomalies and "new_device" in anomalies
    mail_body = build_anomalous_login_email(
        current=mobile_ctx,
        reasons=anomalies,
        mfa_used=True,
        when_beijing="2026-11-25 08:30:00",
    )
    assert "203.0.113.45" in mail_body
    assert "日本 · Tokyo" in mail_body
    assert "不会强制退出" in mail_body


def test_revocation_between_download_chunks_stops_delivery():
    from types import SimpleNamespace

    from astroagent.auth_access import IdentityAccess

    principal = {"id": "synthetic", "namespace": "aa_" + "0" * 32, "admin": False}
    revoked = False
    store = SimpleNamespace(authenticate=lambda *args: None if revoked else principal)
    identity = SimpleNamespace(
        store=store,
        ensure_control_lock=lambda: None,
        settings=SimpleNamespace(origin="https://example.org"),
    )
    scope = {
        "type": "http",
        "path": "/api/v1/artifacts/synthetic/download",
        "method": "GET",
        "headers": [(b"cookie", b"astroagent_session=synthetic")],
        "app": SimpleNamespace(state=SimpleNamespace(identity=identity)),
    }
    messages = []

    async def application(scope, receive, send):
        nonlocal revoked
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"authorized chunk", "more_body": True})
        revoked = True
        await send(
            {"type": "http.response.body", "body": b"must not be delivered", "more_body": False}
        )

    async def send(message):
        messages.append(message)

    asyncio.run(IdentityAccess(application)(scope, None, send))
    assert [m.get("body") for m in messages if m["type"] == "http.response.body"] == [
        b"authorized chunk",
        b"",
    ]
