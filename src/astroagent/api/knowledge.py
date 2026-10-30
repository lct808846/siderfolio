"""项目本地知识库API；上传文件及选项在调用本地解析器前严格校验。"""

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from astroagent.api.conversations import Service
from astroagent.errors import ServiceError
from astroagent.knowledge_schemas import (
    DocumentAction,
    DocumentDelete,
    DocumentDetail,
    DocumentResult,
    DocumentUpload,
    EvidenceRecord,
    EvidenceView,
    KnowledgeDocument,
    KnowledgeOperation,
    KnowledgeQuery,
    KnowledgeResult,
    TextPreview,
    TextSource,
)
from astroagent.knowledge_text import checksum
from astroagent.project_archives import strict_json
from astroagent.schemas import ErrorResponse

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["knowledge"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 413, 415, 422, 503)},
)


def get_knowledge(service: Service):
    return service.knowledge


Knowledge = Annotated[object, Depends(get_knowledge)]
DOCUMENT_RESPONSES = {
    201: {"model": DocumentResult},
    202: {"model": DocumentResult},
    **{code: {"model": DocumentResult | ErrorResponse} for code in (409, 413, 422, 503)},
}
UPLOAD_SCHEMA = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["file", "options"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "options": {
                            "type": "string",
                            "description": (
                                "JSON DocumentUpload：expected_revision、client_request_id、"
                                "metadata、allow_duplicate、restore_version_id"
                            ),
                        },
                    },
                }
            }
        },
    }
}


async def read_upload(request):
    try:
        async with request.form(max_files=1, max_fields=1, max_part_size=32768) as form:
            pairs = list(form.multi_items())
            if len(pairs) != 2 or {key for key, _ in pairs} != {"file", "options"}:
                raise ServiceError(
                    422, "knowledge_upload_invalid", "必须且只能上传file与options两个字段。"
                )
            file, options = form["file"], form["options"]
            if (
                not isinstance(file, UploadFile)
                or not isinstance(options, str)
                or len(options.encode("utf-8")) > 32768
            ):
                raise ServiceError(422, "knowledge_upload_invalid", "文件或JSON选项无效。")
            options = DocumentUpload.model_validate(strict_json(options.encode("utf-8")))
            data = bytearray()
            while chunk := await file.read(65536):
                if len(data) + len(chunk) > 20 * 1024**2:
                    raise ServiceError(413, "knowledge_file_size", "文件超过20 MiB。")
                data.extend(chunk)
            return file.filename, bytes(data), options
    except (AssertionError, TypeError, ModuleNotFoundError) as exc:
        raise ServiceError(
            503,
            "knowledge_multipart_unavailable",
            "需安装锁定的上传依赖及兼容的Starlette，未放宽上传保护。",
        ) from exc
    except (ValidationError, ValueError, HTTPException) as exc:
        raise ServiceError(
            422, "knowledge_upload_invalid", "multipart字段或严格JSON选项无效。"
        ) from exc


@router.post(
    "/documents",
    response_model=DocumentResult,
    openapi_extra=UPLOAD_SCHEMA,
    responses=DOCUMENT_RESPONSES,
)
async def upload(project_id: UUID, request: Request, response: Response, service: Knowledge):
    filename, content, options = await read_upload(request)
    from starlette.concurrency import run_in_threadpool

    value, response.status_code = await run_in_threadpool(
        service.submit, str(project_id), options, filename=filename, content=content
    )
    return value


@router.post(
    "/documents/{document_id}/versions",
    response_model=DocumentResult,
    openapi_extra=UPLOAD_SCHEMA,
    responses=DOCUMENT_RESPONSES,
)
async def upload_version(
    project_id: UUID, document_id: UUID, request: Request, response: Response, service: Knowledge
):
    filename, content, options = await read_upload(request)
    from starlette.concurrency import run_in_threadpool

    value, response.status_code = await run_in_threadpool(
        service.submit,
        str(project_id),
        options,
        filename=filename,
        content=content,
        document_id=str(document_id),
    )
    return value


@router.get("/documents", response_model=list[KnowledgeDocument])
def documents(project_id: UUID, service: Knowledge):
    return service.repository.list(str(project_id))


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def document(project_id: UUID, document_id: UUID, service: Knowledge):
    return service.repository.detail(str(project_id), str(document_id))


@router.get("/documents/{document_id}/versions/{version_id}/content", response_class=Response)
def content(project_id: UUID, document_id: UUID, version_id: UUID, service: Knowledge):
    version, data = service.repository.content(str(project_id), str(document_id), str(version_id))
    # Download the original as an attachment. The UI creates a sandboxed PDF-only blob preview.
    return Response(
        data,
        media_type=version.media_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename=original."
                f"{'pdf' if version.media_type == 'application/pdf' else 'md'}; "
                f"filename*=UTF-8''{quote(version.filename, safe='')}"
            ),
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/documents/{document_id}/reindex",
    response_model=DocumentResult,
    responses=DOCUMENT_RESPONSES,
)
def reindex(
    project_id: UUID,
    document_id: UUID,
    request: DocumentAction,
    response: Response,
    service: Knowledge,
):
    value, response.status_code = service.submit(
        str(project_id), request, document_id=str(document_id), action=True
    )
    return value


@router.delete("/documents/{document_id}", status_code=204)
def delete(project_id: UUID, document_id: UUID, request: DocumentDelete, service: Knowledge):
    with service.conversations.gate:
        service.repository.delete(str(project_id), str(document_id), request)
    return Response(status_code=204)


@router.post("/knowledge/search", response_model=KnowledgeResult)
def search(project_id: UUID, request: KnowledgeQuery, service: Knowledge):
    return service.search(str(project_id), request)


@router.post("/knowledge/answers", response_model=KnowledgeResult)
def answer(project_id: UUID, request: KnowledgeQuery, service: Knowledge):
    return service.search(str(project_id), request)


@router.get("/knowledge/evidence", response_model=list[EvidenceRecord])
def references(project_id: UUID, service: Knowledge):
    return service.evidence_list(str(project_id))


@router.get("/knowledge/evidence/{evidence_id}", response_model=EvidenceView)
def evidence(project_id: UUID, evidence_id: UUID, service: Knowledge):
    return service.evidence(str(project_id), str(evidence_id))


@router.get("/knowledge/operations/{request_id}", response_model=KnowledgeOperation)
def operation(project_id: UUID, request_id: UUID, service: Knowledge):
    with service.repository.repo.connection() as db:
        service.repository.projects._project(db, str(project_id))
        row = db.execute(
            "SELECT record FROM knowledge_operations WHERE project_id=? AND request_id=?",
            (str(project_id), str(request_id)),
        ).fetchone()
        if not row:
            raise ServiceError(
                404,
                "knowledge_operation_not_found",
                "尚未找到此请求记录；可保留原编号核对，不能据此声称远端请求已取消。",
            )
        return KnowledgeOperation.model_validate_json(row[0])


@router.get("/documents/{document_id}/versions/{version_id}/text", response_model=TextPreview)
def extraction_text(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    service: Knowledge,
    source_position: int = Query(default=1, ge=1, le=500),
):
    service.repository.content(str(project_id), str(document_id), str(version_id))
    with service.repository.repo.connection() as db:
        service.repository._version(db, str(project_id), str(document_id), str(version_id))
        row = db.execute(
            "SELECT record FROM knowledge_sources WHERE version_id=? AND position=?",
            (str(version_id), source_position),
        ).fetchone()
        if not row:
            raise ServiceError(404, "knowledge_text_not_found", "此位置没有已保存的提取记录。")
        source = TextSource.model_validate_json(row[0])
        if source.text is None:
            raise ServiceError(404, "knowledge_text_unavailable", "此归档没有可核对的提取原文。")
        if checksum(source.text) != source.sha256:
            raise ServiceError(422, "knowledge_text_corrupt", "提取文本摘要不符。")
        return {
            "version_id": source.version_id,
            "source_position": source.position,
            "page": source.page,
            "state": source.state,
            "text": source.text[:24000],
            "sha256": source.sha256,
            "original_characters": len(source.text),
            "truncated": len(source.text) > 24000,
            "error": source.error,
        }
