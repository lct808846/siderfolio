"""Email ownership is confirmed by POST; credentials never appear in URLs or logs."""

import base64
import hmac
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from astroagent.auth_security import (
    PASSWORDS,
    digest,
    email_address,
    hash_password,
    keyed,
    opaque,
    totp_step,
    verify_password,
)
from astroagent.auth_store import AUTH_LOCK
from astroagent.errors import ServiceError

router = APIRouter(prefix="/api/v1/auth", tags=["identity"])
COOKIE = "astroagent_session"
PREAUTH = "astroagent_preauth"
GENERIC = {"message": "验证邮件已发送，请查收邮件并按提示继续操作。"}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class EmailInput(Input):
    email: str = Field(max_length=254)
    request_id: UUID


class TokenInput(Input):
    token: SecretStr


class PasswordInput(TokenInput):
    password: SecretStr
    username: str = Field(default="", max_length=64)


class ProfileInput(Input):
    username: str = Field(min_length=1, max_length=32)


def clean_username(value: str) -> str:
    cleaned = unicodedata.normalize("NFKC", value or "").strip()
    if not (1 <= len(cleaned) <= 32) or any(
        unicodedata.category(c).startswith("C") for c in cleaned
    ):
        raise ServiceError(400, "invalid_username", "用户名长度须为 1 至 32 个字符。")
    return cleaned


class LoginInput(Input):
    email: str = Field(max_length=254)
    password: SecretStr
    code: str = Field(default="", max_length=80)


class ProofInput(Input):
    password: SecretStr
    code: str = Field(default="", max_length=80)


class ChangePasswordInput(ProofInput):
    new_password: SecretStr


class SessionRevokeInput(ProofInput):
    session_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class CodeInput(Input):
    code: str = Field(min_length=6, max_length=6)


def runtime(request):
    value = getattr(request.app.state, "identity", None)
    if value is None:
        raise ServiceError(503, "identity_unavailable", "身份服务尚未就绪，请联系本机管理员。")
    return value


def actor(request):
    value = getattr(request.state, "principal", None)
    if not value:
        raise ServiceError(401, "login_required", "请先登录。")
    return value


def source(request):
    # Only LocalAccess, after verifying the private proxy credential, can set this.
    return getattr(request.state, "trusted_client_address", None) or (
        request.client.host if request.client else "unknown"
    )


def set_session(response, settings, token):
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.cookie_max_age,
        secure=settings.secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(PREAUTH, secure=settings.secure, httponly=True, samesite="lax", path="/")


def invalid_link():
    return ServiceError(422, "email_link_invalid", "链接无效、已使用或已过期，请重新申请邮件。")


def consume(db, token, purpose):
    if not 32 <= len(token) <= 256:
        raise invalid_link()
    row = db.execute(
        (
            "SELECT * FROM public.auth_tokens WHERE hash=%s AND purpose=%s AND "
            "consumed_at IS NULL AND expires_at>now() FOR UPDATE"
        ),
        (digest(token), purpose),
    ).fetchone()
    if not row:
        raise invalid_link()
    db.execute("UPDATE public.auth_tokens SET consumed_at=now() WHERE hash=%s", (row["hash"],))
    return row["user_id"]


def check_otp(store, db, user, code):
    if not user["totp_secret"]:
        return False
    secret = store.crypto.decrypt(user["totp_secret"].encode()).decode()
    step = totp_step(secret, code, user["totp_step"])
    if step is not None:
        db.execute("UPDATE public.auth_users SET totp_step=%s WHERE id=%s", (step, user["id"]))
        return True
    result = db.execute(
        (
            "UPDATE public.auth_recovery SET consumed_at=now() WHERE user_id=%s AND "
            "hash=%s AND consumed_at IS NULL RETURNING hash"
        ),
        (user["id"], digest(code)),
    ).fetchone()
    return bool(result)


@router.get("/csrf")
def csrf(request: Request, response: Response):
    service = runtime(request)
    principal = getattr(request.state, "principal", None)
    token = request.cookies.get(COOKIE) if principal else request.cookies.get(PREAUTH)
    if not token or len(token) > 256:
        token = opaque()
        response.set_cookie(
            PREAUTH,
            token,
            max_age=900,
            secure=service.settings.secure,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return {"csrf_token": service.csrf(token), "registration_available": service.registration_ready}


@router.get("/session")
def session(request: Request, response: Response):
    service, user = runtime(request), actor(request)
    token = request.cookies.get(COOKIE, "")
    if token:
        set_session(response, service.settings, token)
    return {
        "user": service.store.public_user(user),
        "csrf_token": service.csrf(token),
        "idle_seconds": service.settings.idle_seconds,
        "absolute_seconds": service.settings.absolute_seconds,
    }


def issue_email(body, request, purpose):
    service = runtime(request)
    canonical, display = email_address(body.email)
    service.store.rate("email", source(request), canonical, limit=5, seconds=3600)
    if not service.registration_ready:
        raise ServiceError(
            503, "email_unavailable", "邮件注册或找回服务暂不可用，请联系管理员；已有账号可登录。"
        )
    with service.store.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(%s)", (AUTH_LOCK,))
        if (
            purpose == "activate"
            and db.execute("SELECT count(*) AS n FROM public.auth_users").fetchone()["n"]
            >= service.settings.registration_limit
        ):
            raise ServiceError(
                503, "registration_capacity", "注册与重发服务暂已达到名额上限，请联系管理员。"
            )
        user = db.execute(
            "SELECT * FROM public.auth_users WHERE email_key=%s FOR UPDATE", (canonical,)
        ).fetchone()
        if purpose == "activate" and not user:
            identifier = str(uuid4())
            user = db.execute(
                (
                    "INSERT INTO public.auth_users(id,email_key,email_display,namespace) VALUES "
                    "(%s,%s,%s,%s) RETURNING *"
                ),
                (identifier, canonical, display, "aa_" + UUID(identifier).hex),
            ).fetchone()
        eligible = (
            user
            and not user["disabled"]
            and (
                (purpose == "activate" and not user["active"])
                or (purpose == "reset" and user["active"])
            )
        )
        if eligible:
            service.store.token(db, user, purpose, str(body.request_id))
        service.store.audit(
            db, None, "email_" + purpose, "accepted", source=service.source_hash(source(request))
        )
    return GENERIC


@router.post("/continue")
def continue_auth(body: EmailInput, request: Request):
    service = runtime(request)
    canonical, _ = email_address(body.email)
    with service.store.connect() as db:
        user = db.execute(
            "SELECT id, active, disabled, totp_secret FROM public.auth_users WHERE email_key=%s",
            (canonical,),
        ).fetchone()
        if user and user["active"]:
            if user["disabled"]:
                raise ServiceError(403, "account_disabled", "该账号已被禁用，请联系管理员。")
            return {"action": "login", "totp_enabled": bool(user["totp_secret"])}
        if user and not user["disabled"]:
            recent = db.execute(
                (
                    "SELECT extract(epoch FROM (now() - created_at)) AS elapsed "
                    "FROM public.auth_outbox WHERE user_id=%s AND purpose='activate' "
                    "AND state IN ('pending','submitted') ORDER BY created_at DESC LIMIT 1"
                ),
                (user["id"],),
            ).fetchone()
            if recent and 0 <= recent["elapsed"] < 60:
                return {
                    **GENERIC,
                    "action": "activate_sent",
                    "cooldown": max(1, 60 - int(recent["elapsed"])),
                }
    issue_email(body, request, "activate")
    return {**GENERIC, "action": "activate_sent", "cooldown": 60}


@router.post("/register")
def register(body: EmailInput, request: Request):
    return issue_email(body, request, "activate")


@router.post("/resend")
def resend(body: EmailInput, request: Request):
    return issue_email(body, request, "activate")


@router.post("/forgot-password")
def forgot(body: EmailInput, request: Request):
    return issue_email(body, request, "reset")


@router.post("/activate/confirm")
def confirm(body: TokenInput, request: Request):
    service = runtime(request)
    service.store.rate("activate", source(request), limit=15)
    with service.store.connect() as db:
        user_id = consume(db, body.token.get_secret_value(), "activate")
        user = db.execute(
            "SELECT * FROM public.auth_users WHERE id=%s FOR UPDATE", (user_id,)
        ).fetchone()
        if user["active"] or user["disabled"]:
            raise invalid_link()
        token = opaque()
        db.execute(
            "INSERT INTO public.auth_tokens VALUES (%s,%s,'activate_setup',%s,NULL)",
            (digest(token), user_id, datetime.now(UTC) + timedelta(minutes=5)),
        )
    return {"setup_token": token}


def finish_password(body, request, purpose):
    service = runtime(request)
    service.store.rate("password_token", source(request), limit=10)
    encoded = hash_password(body.password.get_secret_value(), service.settings)
    with service.store.connect() as db:
        user_id = consume(db, body.token.get_secret_value(), purpose)
        user = db.execute(
            "SELECT * FROM public.auth_users WHERE id=%s FOR UPDATE", (user_id,)
        ).fetchone()
        if (
            user["disabled"]
            or (purpose == "activate_setup" and user["active"])
            or (purpose == "reset" and not user["active"])
        ):
            raise invalid_link()
        if purpose == "activate_setup":
            uname = (
                clean_username(body.username)
                if body.username.strip()
                else (
                    (user.get("username") or "").strip() or user["email_display"].split("@")[0][:32]
                )
            )
            db.execute(
                (
                    "UPDATE public.auth_users SET "
                    "active=true,username=%s,password_hash=%s,generation=generation+1 WHERE id=%s"
                ),
                (uname, encoded, user_id),
            )
        else:
            db.execute(
                (
                    "UPDATE public.auth_users SET "
                    "active=true,password_hash=%s,generation=generation+1 WHERE id=%s"
                ),
                (encoded, user_id),
            )
        db.execute(
            (
                "UPDATE public.auth_tokens SET consumed_at=now() WHERE user_id=%s AND "
                "consumed_at IS NULL"
            ),
            (user_id,),
        )
        service.store.revoke(db, user_id)
        service.store.audit(
            db, user_id, "activated" if purpose == "activate_setup" else "password_reset", "ok"
        )
        if purpose == "reset":
            service.store.security_mail(db, user, "密码已重置；所有旧会话已退出。")
    return {
        "message": "密码已设置，请返回登录。",
        "email": user["email_display"],
        "totp_enabled": bool(user["totp_secret"]),
    }


@router.post("/activate/complete")
def activate(body: PasswordInput, request: Request):
    return finish_password(body, request, "activate_setup")


@router.post("/reset-password")
def reset(body: PasswordInput, request: Request):
    return finish_password(body, request, "reset")


@router.post("/profile")
def update_profile(body: ProfileInput, request: Request):
    service, user = runtime(request), actor(request)
    uname = clean_username(body.username)
    with service.store.connect() as db:
        db.execute("UPDATE public.auth_users SET username=%s WHERE id=%s", (uname, user["id"]))
    return {"message": "用户名已更新。", "username": uname}


@router.get("/avatar")
def read_avatar(request: Request):
    service, user = runtime(request), actor(request)
    with service.store.connect() as db:
        row = db.execute(
            "SELECT content_type, content FROM public.auth_avatars WHERE user_id=%s",
            (user["id"],),
        ).fetchone()
    if not row:
        raise ServiceError(404, "avatar_not_found", "尚未上传头像。")
    return Response(
        content=bytes(row["content"]),
        media_type=row["content_type"] or "image/png",
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response):
    service = runtime(request)
    try:
        canonical, _ = email_address(body.email)
    except ServiceError:
        canonical = "invalid"
    service.store.rate("login", source(request), canonical, limit=10)
    service.store.login_backoff(canonical, source(request))
    password = body.password.get_secret_value()
    with service.store.connect() as db:
        user = db.execute(
            "SELECT * FROM public.auth_users WHERE email_key=%s FOR UPDATE", (canonical,)
        ).fetchone()
        valid = verify_password(
            user["password_hash"] if user and user["password_hash"] else service.dummy_hash,
            password,
        )
        valid = valid and user and user["active"] and not user["disabled"]
        if valid and user["totp_secret"] and not body.code.strip():
            return {"action": "totp_required", "message": "请输入双因素验证码。"}
        mfa = (
            check_otp(service.store, db, user, body.code)
            if valid and user["totp_secret"]
            else False
        )
        if valid and user["totp_secret"] and not mfa:
            valid = False
        current_source = service.source_hash(source(request))
        if not valid:
            service.store.audit(db, None, "login", "denied", source=current_source)
        else:
            old = getattr(request.state, "principal", None)
            if old:
                db.execute(
                    "UPDATE public.auth_sessions SET revoked=true WHERE hash=%s",
                    (old["session_hash"],),
                )
            anomalous_prior = db.execute(
                (
                    "UPDATE public.auth_sessions SET revoked=true WHERE user_id=%s AND NOT "
                    "revoked AND source_hash IS NOT NULL AND source_hash<>%s RETURNING hash"
                ),
                (user["id"], current_source),
            ).fetchall()
            if anomalous_prior:
                service.store.audit(
                    db,
                    user["id"],
                    "anomalous_location_login",
                    "revoked_prior",
                    source=current_source,
                    reason="different_network_source",
                )
                service.store.security_mail(
                    db, user, "检测到异地或新网络位置登录，原有其他网络位置的会话已自动保护性下线。"
                )
            if PASSWORDS.check_needs_rehash(user["password_hash"]):
                db.execute(
                    "UPDATE public.auth_users SET password_hash=%s WHERE id=%s",
                    (PASSWORDS.hash(unicodedata.normalize("NFC", password)), user["id"]),
                )
            token = service.store.session(db, user["id"], mfa, source_hash=current_source)
            db.execute("UPDATE public.auth_users SET last_login=now() WHERE id=%s", (user["id"],))
            service.store.audit(db, user["id"], "login", "ok", source=current_source)
    if not valid:
        service.store.login_backoff(canonical, source(request), failed=True)
        raise ServiceError(401, "login_failed", "邮箱、密码或验证码不正确，或账号暂不可用。")
    service.store.clear_login_backoff(canonical)
    set_session(response, service.settings, token)
    return {"message": "登录成功。"}


@router.post("/logout")
def logout(request: Request, response: Response):
    service, user = runtime(request), actor(request)
    with service.store.connect() as db:
        db.execute(
            "UPDATE public.auth_sessions SET revoked=true WHERE hash=%s", (user["session_hash"],)
        )
        service.store.audit(db, user["id"], "logout", "ok")
    response.delete_cookie(
        COOKIE, secure=service.settings.secure, httponly=True, samesite="lax", path="/"
    )
    return {"message": "已退出。"}


def proof(service, request, body, db):
    user = actor(request)
    current = db.execute(
        "SELECT * FROM public.auth_users WHERE id=%s FOR UPDATE", (user["id"],)
    ).fetchone()
    if (
        not current
        or not current["active"]
        or current["disabled"]
        or not verify_password(current["password_hash"], body.password.get_secret_value())
    ):
        raise ServiceError(403, "reauth_failed", "重新认证失败。")
    if current["totp_secret"] and not check_otp(service.store, db, current, body.code):
        raise ServiceError(403, "reauth_failed", "重新认证失败。")
    return current


@router.post("/reauthenticate")
def reauthenticate(body: ProofInput, request: Request):
    service, user = runtime(request), actor(request)
    service.store.rate("reauth", source(request), user["id"], limit=8)
    with service.store.connect() as db:
        current = proof(service, request, body, db)
        db.execute(
            (
                "UPDATE public.auth_sessions SET reauth_at=now(),mfa_at=CASE WHEN %s THEN "
                "now() ELSE mfa_at END WHERE hash=%s"
            ),
            (bool(current["totp_secret"]), user["session_hash"]),
        )
        service.store.audit(db, user["id"], "reauthenticated", "ok")
    return {"message": "重新认证有效期5分钟。"}


@router.post("/change-password")
def change_password(body: ChangePasswordInput, request: Request, response: Response):
    service, user = runtime(request), actor(request)
    service.store.rate("change_password", source(request), user["id"], limit=5)
    encoded = hash_password(body.new_password.get_secret_value(), service.settings)
    with service.store.connect() as db:
        current = proof(service, request, body, db)
        db.execute(
            ("UPDATE public.auth_users SET password_hash=%s,generation=generation+1 WHERE id=%s"),
            (encoded, user["id"]),
        )
        service.store.revoke(db, user["id"])
        service.store.security_mail(db, current, "密码已修改；所有会话已退出。")
        service.store.audit(db, user["id"], "password_changed", "ok")
    response.delete_cookie(
        COOKIE, secure=service.settings.secure, httponly=True, samesite="lax", path="/"
    )
    return {"message": "密码已修改，请重新登录。"}


@router.get("/sessions")
def sessions(request: Request):
    service, user = runtime(request), actor(request)
    with service.store.connect() as db:
        rows = db.execute(
            (
                "SELECT hash,created_at,last_seen,expires_at FROM public.auth_sessions WHERE "
                "user_id=%s AND NOT revoked AND expires_at>now() "
                "AND last_seen>now()-(%s*interval '1 second') ORDER BY created_at DESC "
                "LIMIT 100"
            ),
            (user["id"], service.settings.idle_seconds),
        ).fetchall()
    result = []
    for row in rows:
        session_hash = row.pop("hash")
        result.append(
            {
                "id": keyed(service.settings, "session-management", f"{user['id']}:{session_hash}"),
                "current": hmac.compare_digest(session_hash, user["session_hash"]),
                **row,
            }
        )
    return result


@router.post("/sessions/revoke")
def revoke_session(body: SessionRevokeInput, request: Request):
    service, user = runtime(request), actor(request)
    service.store.rate("revoke_session", source(request), user["id"], limit=8)
    with service.store.connect() as db:
        proof(service, request, body, db)
        rows = db.execute(
            (
                "SELECT hash FROM public.auth_sessions WHERE user_id=%s AND NOT revoked "
                "AND expires_at>now() AND last_seen>now()-(%s*interval '1 second') "
                "ORDER BY created_at DESC LIMIT 100 FOR UPDATE"
            ),
            (user["id"], service.settings.idle_seconds),
        ).fetchall()
        target = next(
            (
                row["hash"]
                for row in rows
                if hmac.compare_digest(
                    keyed(service.settings, "session-management", f"{user['id']}:{row['hash']}"),
                    body.session_id,
                )
            ),
            None,
        )
        if target is None:
            raise ServiceError(404, "session_not_found", "该会话已退出或失效，请刷新列表。")
        if hmac.compare_digest(target, user["session_hash"]):
            raise ServiceError(
                409, "current_session_protected", "不能在活动会话列表中退出当前浏览器。"
            )
        db.execute(
            "UPDATE public.auth_sessions SET revoked=true WHERE user_id=%s AND hash=%s",
            (user["id"], target),
        )
        service.store.audit(db, user["id"], "session_revoked", "ok", target=user["id"])
    return {"message": "所选浏览器会话已退出。"}


@router.post("/sessions/revoke-all")
def revoke_all(body: ProofInput, request: Request, response: Response):
    service, user = runtime(request), actor(request)
    service.store.rate("revoke_sessions", source(request), user["id"], limit=5)
    with service.store.connect() as db:
        proof(service, request, body, db)
        service.store.revoke(db, user["id"])
        service.store.audit(db, user["id"], "sessions_revoked", "ok")
    response.delete_cookie(
        COOKIE, secure=service.settings.secure, httponly=True, samesite="lax", path="/"
    )
    return {"message": "所有会话已退出。"}


@router.post("/totp/enroll")
def enroll(body: ProofInput, request: Request):
    service, user = runtime(request), actor(request)
    service.store.rate("totp_enroll", source(request), user["id"], limit=5)
    with service.store.connect() as db:
        proof(service, request, body, db)
        secret = base64.b32encode(secrets.token_bytes(20)).decode()
        db.execute(
            (
                "UPDATE public.auth_users SET "
                "totp_pending=%s,totp_pending_until=now()+interval '10 minutes' WHERE id=%s"
            ),
            (service.store.crypto.encrypt(secret.encode()).decode(), user["id"]),
        )
    account_label = quote(user.get("email_display") or user.get("email_key") or "user", safe="@.")
    otpauth_uri = (
        f"otpauth://totp/AstroAgent:{account_label}"
        f"?secret={secret}&issuer=AstroAgent&algorithm=SHA1&digits=6&period=30"
    )
    return {
        "secret": secret,
        "otpauth_uri": otpauth_uri,
        "issuer": "AstroAgent",
        "period": 30,
        "digits": 6,
        "message": "请使用身份验证器扫描二维码，并输入 6 位动态验证码完成绑定。",
    }


@router.post("/totp/disable")
def disable_totp(body: ProofInput, request: Request, response: Response):
    service, user = runtime(request), actor(request)
    service.store.rate("totp_disable", source(request), user["id"], limit=5)
    with service.store.connect() as db:
        current = proof(service, request, body, db)
        if current["admin"]:
            raise ServiceError(403, "admin_mfa_required", "管理员账号必须保持多因素身份验证开启。")
        if not current["totp_secret"]:
            raise ServiceError(409, "totp_not_enabled", "身份验证器尚未启用，请刷新账号状态。")
        db.execute(
            (
                "UPDATE public.auth_users SET totp_secret=NULL,totp_pending=NULL,"
                "totp_pending_until=NULL,totp_step=-1,generation=generation+1 WHERE id=%s"
            ),
            (user["id"],),
        )
        db.execute("DELETE FROM public.auth_recovery WHERE user_id=%s", (user["id"],))
        service.store.revoke(db, user["id"])
        service.store.security_mail(db, current, "多因素身份验证已关闭；所有旧会话已退出。")
        service.store.audit(db, user["id"], "totp_disabled", "ok")
    response.delete_cookie(
        COOKIE, secure=service.settings.secure, httponly=True, samesite="lax", path="/"
    )
    return {"message": "多因素身份验证已关闭，请重新登录。"}


@router.post("/totp/confirm")
def confirm_totp(body: CodeInput, request: Request, response: Response):
    service, user = runtime(request), actor(request)
    service.store.rate("totp_confirm", source(request), user["id"], limit=10)
    with service.store.connect() as db:
        current = db.execute(
            "SELECT * FROM public.auth_users WHERE id=%s FOR UPDATE", (user["id"],)
        ).fetchone()
        if not current["totp_pending"] or current["totp_pending_until"] < datetime.now(UTC):
            raise ServiceError(422, "totp_expired", "绑定已过期，请重新开始。")
        secret = service.store.crypto.decrypt(current["totp_pending"].encode()).decode()
        step = totp_step(secret, body.code)
        if step is None:
            raise ServiceError(422, "totp_invalid", "验证码不正确，请核对验证器时间。")
        db.execute(
            (
                "UPDATE public.auth_users SET totp_secret=totp_pending,totp_pending=NULL,totp"
                "_pending_until=NULL,totp_step=%s,generation=generation+1 WHERE id=%s"
            ),
            (step, user["id"]),
        )
        db.execute("DELETE FROM public.auth_recovery WHERE user_id=%s", (user["id"],))
        codes = [secrets.token_hex(10) for _ in range(10)]
        for code in codes:
            db.execute(
                "INSERT INTO public.auth_recovery VALUES (%s,%s,NULL)", (digest(code), user["id"])
            )
        service.store.revoke(db, user["id"])
        token = service.store.session(
            db, user["id"], True, source_hash=service.source_hash(source(request))
        )
        service.store.audit(db, user["id"], "totp_bound", "ok")
    set_session(response, service.settings, token)
    return {"recovery_codes": codes, "message": "恢复码仅显示一次，请离线保存。"}
