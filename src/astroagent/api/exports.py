"""无模型依赖的 ZIP 导出路由与 JSON 解析前的接收限制。"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from astroagent.errors import ServiceError
from astroagent.export_schemas import ExportRequest
from astroagent.exports import build_package
from astroagent.schemas import ErrorResponse

MAX_REQUEST_BYTES = 2 * 1024 * 1024
router = APIRouter(prefix="/api/v1", tags=["exports"])


class ExportBodyLimit:
    """仅导出 POST：实际字节累计，分块/无长度头也在解析前受限。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["path"] != "/api/v1/exports"
            or (scope["method"] != "POST")
        ):
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        media = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
        encoding = headers.get(b"content-encoding", b"identity").strip().lower()
        if media != b"application/json" or encoding != b"identity":
            response = JSONResponse(
                status_code=415,
                content={
                    "error": {
                        "code": "unsupported_export_media_type",
                        "message": "仅支持未压缩 JSON。",
                        "retryable": False,
                    }
                },
            )
            return await response(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "export_too_large",
                            "message": "请求超过 2 MiB。",
                            "retryable": False,
                        }
                    },
                )
                return await response(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)


def validate_json(body):
    # Bound nesting before either JSON decoder. Escape-aware scanning ignores braces in text.
    depth, quoted, escaped = 0, False, False
    for char in body.decode("utf-8"):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 64:
                raise ValueError("JSON nesting limit")
        elif char in "]}":
            depth -= 1

    def reject_constant(value):
        raise ValueError("Non-finite JSON constant")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    json.loads(body, parse_constant=reject_constant, object_pairs_hook=unique_pairs)
    return ExportRequest.model_validate_json(body)


def export_body(body):
    try:
        request = validate_json(body)
    except (ValidationError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise ServiceError(422, "invalid_export_snapshot", "导出请求或快照无效。") from exc
    return build_package(request)


@router.post(
    "/exports",
    response_class=Response,
    responses={
        200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}},
        **{code: {"model": ErrorResponse} for code in (413, 415, 422, 500, 503)},
    },
    summary="导出完整客户端查询快照与可选 Gaia 图表",
)
async def export(request: Request):
    package = await run_in_threadpool(export_body, await request.body())
    return Response(
        package,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="astroagent-results.zip"',
            "Cache-Control": "no-store",
        },
    )
