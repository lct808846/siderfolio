"""本机 Host / Origin 与会话接收边界；不依赖模型配置或数据库可用性。"""

import ipaddress
import os
import re
import secrets
import tempfile

from fastapi.responses import JSONResponse

from astroagent.config import LocalSettings

CONVERSATION_BODY_LIMIT = 32 * 1024


class LocalAccess:
    def __init__(self, app):
        self.app = app
        self._cached_key = None
        self._cached_settings = None

    def _settings(self):
        key = (
            os.getenv("ASTROAGENT_DEPLOYMENT_MODE"),
            os.getenv("ASTROAGENT_ALLOWED_HOSTS"),
            os.getenv("ASTROAGENT_ALLOWED_ORIGINS"),
            os.getenv("ASTROAGENT_PROXY_TOKEN"),
        )
        if key == self._cached_key and self._cached_settings is not None:
            return self._cached_settings
        try:
            settings = LocalSettings()
        except Exception:
            settings = LocalSettings.model_construct(
                allowed_origins=[], allowed_hosts=["127.0.0.1", "localhost", "[::1]"]
            )
        self._cached_key = key
        self._cached_settings = settings
        return settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        settings = self._settings()
        headers = {k.lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        host = headers.get(b"host", "")
        hostname = host.split("]", 1)[0] + "]" if host.startswith("[") else host.split(":", 1)[0]
        origin = headers.get(b"origin")
        api = scope["path"].startswith("/api/")

        async def with_headers(message):
            if message["type"] == "http.response.start":
                values = list(message.get("headers", []))
                existing = {k.lower() for k, v in values}
                if b"x-content-type-options" not in existing:
                    values.append((b"x-content-type-options", b"nosniff"))
                if api and b"cache-control" not in existing:
                    values.append((b"cache-control", b"no-store"))
                if origin in settings.allowed_origins:
                    values.extend(
                        [
                            (b"access-control-allow-origin", origin.encode("latin1")),
                            (b"vary", b"Origin"),
                        ]
                    )
                message = {**message, "headers": values}
            await send(message)

        async def failure(code, name, text):
            return await JSONResponse(
                status_code=code,
                content={
                    "error": {
                        "code": name,
                        "message": text,
                        "retryable": False,
                    }
                },
            )(scope, receive, with_headers)

        if hostname.lower() not in settings.allowed_hosts:
            return await failure(400, "invalid_host", "仅接受已配置的本机主机。")
        if settings.deployment_mode == "container" and scope["path"] != "/health":
            token = settings.proxy_token.get_secret_value()
            if not token or not secrets.compare_digest(
                headers.get(b"x-astroagent-proxy", ""), token
            ):
                return await failure(403, "proxy_required", "请通过已配置的本机网页入口访问。")
            try:
                address = str(ipaddress.ip_address(headers.get(b"x-astroagent-client-address", "")))
                scope.setdefault("state", {})["trusted_client_address"] = address
            except ValueError:
                pass
        if api and origin is not None and origin not in settings.allowed_origins:
            return await failure(403, "origin_not_allowed", "此网页来源未获允许。")
        if api and scope["method"] == "OPTIONS":
            method = headers.get(b"access-control-request-method", "")
            requested_headers = {
                h.strip().lower()
                for h in headers.get(b"access-control-request-headers", "").split(",")
                if h.strip()
            }
            if method not in {"GET", "POST", "PATCH", "PUT", "DELETE"} or not requested_headers <= {
                "content-type",
                "x-csrf-token",
            }:
                return await failure(403, "origin_not_allowed", "不支持此预检请求。")
            response = JSONResponse(
                content={},
                headers={
                    "Access-Control-Allow-Methods": "GET, POST, PATCH, PUT, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, X-CSRF-Token",
                },
            )
            return await response(scope, receive, with_headers)
        importing = scope["path"] == "/api/v1/projects/import" and scope["method"] == "POST"
        uploading = scope["method"] == "POST" and re.fullmatch(
            r"/api/v1/projects/[0-9a-f-]{36}/documents(?:/[0-9a-f-]{36}/versions)?", scope["path"]
        )
        chat_uploading = scope["method"] == "POST" and scope["path"] == "/api/v1/chat/attachments"
        avatar_uploading = scope["method"] == "POST" and scope["path"] == "/api/v1/profile/avatar"
        plot_uploading = scope["method"] == "PUT" and re.fullmatch(
            r"/api/v1/projects/[0-9a-fA-F-]{36}/plotting/datasets/[0-9a-fA-F-]{36}/upload",
            scope["path"],
        )
        uploading = uploading or chat_uploading or avatar_uploading or plot_uploading
        if uploading:
            if (
                headers.get(b"content-type", "").split(";", 1)[0].strip().lower()
                != "multipart/form-data"
                or headers.get(b"content-encoding", "identity").lower() != "identity"
            ):
                return await failure(
                    415, "knowledge_upload_media", "仅接受未压缩multipart单文件上传。"
                )
            # Bound actual transport bytes, spool to disk above 1 MiB, and replay in chunks.
            # Never allocate a 20 MiB multipart bytearray in the ASGI middleware.
            with tempfile.SpooledTemporaryFile(max_size=1024**2) as spool:
                received = 0
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    received += len(chunk)
                    limit_mb = (
                        5 if (plot_uploading or avatar_uploading) else 10 if chat_uploading else 20
                    )
                    if received > limit_mb * 1024**2 + 64 * 1024:
                        return await failure(
                            413, "knowledge_upload_too_large", "文件及multipart开销超过接收上限。"
                        )
                    spool.write(chunk)
                    if not message.get("more_body", False):
                        break
                spool.seek(0)
                remaining = received

                async def replay_upload():
                    nonlocal remaining
                    if remaining:
                        chunk = spool.read(min(65536, remaining))
                        remaining -= len(chunk)
                        return {"type": "http.request", "body": chunk, "more_body": remaining > 0}
                    return {"type": "http.request", "body": b"", "more_body": False}

                return await self.app(scope, replay_upload, with_headers)
        if scope["path"].startswith(
            (
                "/api/v1/conversations",
                "/api/v1/projects",
                "/api/v1/setup",
                "/api/v1/local-titles",
                "/api/v1/literature",
            )
        ) and scope["method"] in {
            "POST",
            "PATCH",
            "PUT",
            "DELETE",
        }:
            if scope["method"] == "DELETE" and scope["path"].startswith("/api/v1/conversations"):
                return await self.app(scope, receive, with_headers)
            bodyless_delete = (
                scope["method"] == "DELETE"
                and (
                    re.fullmatch(
                        r"/api/v1/projects/[0-9a-fA-F-]{36}/(?:rag/previews|compute-tasks)/[0-9a-fA-F-]{36}",
                        scope["path"],
                    )
                    is not None
                    or re.fullmatch(
                        r"/api/v1/literature/items/[0-9a-fA-F-]{36}",
                        scope["path"],
                    )
                    is not None
                )
            )
            bodyless_action = scope["method"] == "POST" and (
                scope["path"] == "/api/v1/projects/default"
                or re.fullmatch(
                    r"/api/v1/conversations/[0-9a-fA-F-]{36}/archive",
                    scope["path"],
                )
                is not None
                or re.fullmatch(
                    r"/api/v1/projects/[0-9a-fA-F-]{36}/compute-tasks/[0-9a-fA-F-]{36}/(?:cancel|copy)",
                    scope["path"],
                )
                is not None
            )
            bodyless_operation = (bodyless_delete or bodyless_action) and not headers.get(
                b"content-type", ""
            ).strip()
            if (
                not bodyless_operation
                and headers.get(b"content-type", "").split(";", 1)[0].strip().lower()
                != ("application/zip" if importing else "application/json")
                or headers.get(b"content-encoding", "identity").strip().lower() != "identity"
            ):
                return await failure(
                    415, "unsupported_conversation_media_type", "仅支持未压缩JSON请求。"
                )
            body = bytearray()
            turn_upload = scope["method"] == "POST" and re.fullmatch(
                r"/api/v1/conversations/[0-9a-fA-F-]{36}/turns(?:/stream)?", scope["path"]
            )
            body_limit = (
                32 * 1024**2
                if importing
                else 128 * 1024
                if turn_upload
                else CONVERSATION_BODY_LIMIT
            )
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > body_limit:
                    return await failure(
                        413,
                        "conversation_request_too_large",
                        "项目包超过32 MiB。"
                        if importing
                        else "请求超过接收上限，请减少附件内容。"
                        if turn_upload
                        else "请求超过32 KiB。",
                    )
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            if bodyless_operation and body:
                return await failure(
                    415, "unsupported_conversation_media_type", "仅支持空请求或JSON。"
                )
            # Guard decoder recursion and non-finite / duplicated JSON keys before FastAPI.
            import json

            try:

                def pairs(values):
                    result = {}
                    for k, v in values:
                        if k in result:
                            raise ValueError("Duplicate key")
                        result[k] = v
                    return result

                def constant(value):
                    raise ValueError("Non-finite constant")

                parsed = (
                    {}
                    if importing or bodyless_operation
                    else json.loads(
                        body.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant
                    )
                )

                def depth(value, level=0):
                    if level > 32:
                        raise ValueError("Nested JSON")
                    if isinstance(value, dict):
                        for child in value.values():
                            depth(child, level + 1)
                    if isinstance(value, list):
                        for child in value:
                            depth(child, level + 1)

                depth(parsed)
            except (ValueError, TypeError, RecursionError, UnicodeError):
                return await failure(422, "invalid_conversation_request", "会话请求无效。")
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            return await self.app(scope, replay, with_headers)
        return await self.app(scope, receive, with_headers)
