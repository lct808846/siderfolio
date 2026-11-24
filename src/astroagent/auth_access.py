"""Deny-by-default identity boundary, before parsing business request bodies."""

import hmac
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from astroagent.errors import ServiceError
from astroagent.usage import account_usage

PUBLIC = {
    ("GET", "/api/v1/auth/csrf"),
    ("GET", "/api/v1/auth/session"),
    *(
        ("POST", f"/api/v1/auth/{path}")
        for path in (
            "continue",
            "register",
            "resend",
            "forgot-password",
            "activate/confirm",
            "activate/complete",
            "reset-password",
            "login",
        )
    ),
}


def administrator(user, recent=False):
    if not user or not user["admin"] or not user["totp_secret"] or not user.get("mfa_at"):
        raise ServiceError(403, "access_denied", "无权访问此功能。")
    if recent and (
        not user.get("reauth_at") or user["reauth_at"] < datetime.now(UTC) - timedelta(minutes=5)
    ):
        raise ServiceError(403, "reauth_required", "请先重新认证，再执行管理操作。")


def model_settings_request(path, method):
    root = "/api/v1/admin/model-providers"
    return (
        (method == "PUT" and path == root)
        or (method == "POST" and path in {root + "/default", root + "/discover"})
        or (method == "DELETE" and path.startswith(root + "/") and path.count("/") == 5)
    )


class IdentityAccess:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 4401})
        if scope["type"] != "http":
            return
        path, method = scope["path"], scope["method"]
        headers = {k.decode().lower(): v.decode("latin1") for k, v in scope.get("headers", [])}

        async def fail(status, code, message):
            response = JSONResponse(
                {"error": {"code": code, "message": message, "retryable": False}},
                status_code=status,
                headers={
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                },
            )
            return await response(scope, receive, send)

        # The frontend/ingress never forward a public /health. Direct backend probes only.
        if path == "/health" and "x-astroagent-proxy" not in headers:
            return await self.app(scope, receive, send)
        if method == "OPTIONS":
            return await self.app(scope, receive, send)
        identity = getattr(scope["app"].state, "identity", None)
        if identity is None:
            return await fail(503, "identity_unavailable", "身份服务尚未就绪，业务访问已关闭。")
        cookie = SimpleCookie()
        try:
            await run_in_threadpool(identity.ensure_control_lock)
            cookie.load(headers.get("cookie", ""))
            session = cookie["astroagent_session"].value if "astroagent_session" in cookie else ""
            anonymous = cookie["astroagent_preauth"].value if "astroagent_preauth" in cookie else ""
            user = await run_in_threadpool(identity.store.authenticate, session)
            if (method, path) not in PUBLIC and not user:
                return await fail(401, "login_required", "请先登录。")
            if method not in {"GET", "HEAD"}:
                if (
                    headers.get("origin") != identity.settings.origin
                    or headers.get("sec-fetch-site") == "cross-site"
                ):
                    return await fail(403, "csrf_origin", "请从本站页面提交操作。")
                secret = session if user else anonymous
                if (
                    not secret
                    or len(secret) > 256
                    or not hmac.compare_digest(
                        headers.get("x-csrf-token", ""), identity.csrf(secret)
                    )
                ):
                    return await fail(403, "csrf_invalid", "页面验证已失效，请刷新后重试。")
            if (
                user
                and user["admin"]
                and (not user["totp_secret"] or not user["mfa_at"])
                and not path.startswith("/api/v1/auth/")
            ):
                return await fail(403, "mfa_required", "管理员须先完成双因素认证。")
            if path in {
                "/docs",
                "/redoc",
                "/openapi.json",
                "/docs/oauth2-redirect",
                "/api/v1/setup/status",
                "/api/v1/setup/initialize",
                "/api/v1/setup/astronomy-transport",
            } or path.startswith("/api/v1/admin/"):
                administrator(
                    user,
                    recent=path.startswith("/api/v1/admin/")
                    and method not in {"GET", "HEAD"}
                    and not model_settings_request(path, method),
                )
            scope.setdefault("state", {})["principal"] = user
            # Bound all authentication inputs before pydantic or password hashing.
            if path.startswith("/api/v1/auth/") or path.startswith("/api/v1/admin/"):
                if method not in {"GET", "HEAD"}:
                    if headers.get("content-type", "").split(";", 1)[0] != "application/json":
                        return await fail(415, "identity_json_required", "请使用JSON提交身份请求。")
                    body = bytearray()
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > (65536 if model_settings_request(path, method) else 16384):
                            return await fail(413, "identity_input_too_large", "身份请求过大。")
                        if not message.get("more_body"):
                            break
                    original_receive, delivered = receive, False

                    async def replay():
                        nonlocal delivered
                        if not delivered:
                            delivered = True
                            return {"type": "http.request", "body": bytes(body), "more_body": False}
                        return await original_receive()

                    receive = replay
        except ServiceError as exc:
            return await fail(exc.status_code, exc.error.code, exc.error.message)
        except Exception:
            return await fail(503, "identity_unavailable", "身份验证暂不可用，业务访问已关闭。")

        started = False
        terminated = False

        async def secured_send(message):
            nonlocal started, terminated
            if terminated:
                return
            if (
                user
                and not path.startswith("/api/v1/auth/")
                and (
                    message["type"] == "http.response.start"
                    or (message["type"] == "http.response.body" and message.get("body"))
                )
            ):
                # Revocation is checked again before reading results and each file chunk.
                try:
                    valid = await run_in_threadpool(identity.store.authenticate, session, False)
                except Exception:
                    valid = None
                if not valid:
                    terminated = True
                    if not started:
                        started = True
                        await fail(401, "session_expired", "会话已失效，请重新登录。")
                    elif message["type"] == "http.response.body":
                        await send({"type": "http.response.body", "body": b"", "more_body": False})
                    return
            if message["type"] == "http.response.start":
                started = True
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"cache-control", b"no-store"),
                        (b"referrer-policy", b"no-referrer"),
                    ],
                }
            await send(message)

        with account_usage(identity.store, user):
            await self.app(scope, receive, secured_send)
