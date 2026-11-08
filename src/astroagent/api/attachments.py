"""Attachment selection only parses locally; sending a turn authorizes model input."""

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from astroagent.attachment_schemas import MAX_FILE_BYTES, ChatAttachment
from astroagent.attachments import parse_attachment
from astroagent.errors import ServiceError

router = APIRouter(prefix="/api/v1/chat/attachments", tags=["attachments"])
UPLOAD_SCHEMA = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


@router.post("", response_model=ChatAttachment, openapi_extra=UPLOAD_SCHEMA)
async def upload(request: Request):
    try:
        async with request.form(max_files=1, max_fields=0, max_part_size=32768) as form:
            pairs = list(form.multi_items())
            if len(pairs) != 1 or pairs[0][0] != "file" or not isinstance(pairs[0][1], UploadFile):
                raise ServiceError(422, "attachment_upload_invalid", "请选择一个文件作为附件。")
            file = pairs[0][1]
            data = bytearray()
            while chunk := await file.read(65536):
                if len(data) + len(chunk) > MAX_FILE_BYTES:
                    raise ServiceError(413, "attachment_size_limit", "单个附件最多 10 MiB。")
                data.extend(chunk)
            return await run_in_threadpool(parse_attachment, file.filename, bytes(data))
    except (HTTPException, ValueError) as exc:
        raise ServiceError(
            422, "attachment_upload_invalid", "附件上传格式无效，请重新选择文件。"
        ) from exc
    except (AssertionError, TypeError, ModuleNotFoundError) as exc:
        raise ServiceError(
            503, "attachment_upload_unavailable", "本机上传依赖不可用，请检查服务端安装。"
        ) from exc
