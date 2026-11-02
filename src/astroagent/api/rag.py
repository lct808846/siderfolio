"""Independent RAG API. Preview is local; generation requires the exact preview token."""

from uuid import UUID

from fastapi import APIRouter, Response

from astroagent.api.conversations import Service
from astroagent.rag_schemas import (
    Confirm,
    GenerateRequest,
    IndexRequest,
    IndexStatus,
    Preview,
    RagAnswerView,
    RagPage,
    RagQuery,
    RagStatus,
)
from astroagent.schemas import ErrorResponse

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/rag",
    tags=["rag"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 413, 422, 503)},
)


@router.get("/status", response_model=RagStatus)
def status(project_id: UUID, service: Service):
    return service.rag.status(str(project_id))


@router.post("/indexes", response_model=IndexStatus)
def build(project_id: UUID, body: IndexRequest, service: Service):
    return service.rag.build(str(project_id), body)


@router.delete("/indexes/{index_id}", status_code=204)
def delete_index(project_id: UUID, index_id: UUID, body: Confirm, service: Service):
    service.rag.delete_index(str(project_id), str(index_id), body)
    return Response(status_code=204)


@router.post("/previews", response_model=Preview)
def preview(project_id: UUID, body: RagQuery, service: Service):
    return service.rag.preview(str(project_id), body)


@router.delete("/previews/{preview_id}", status_code=204)
def discard(project_id: UUID, preview_id: UUID, service: Service):
    with service.gate, service.repository.connection() as db, service.repository.transaction(db):
        service.rag.projects._project(db, str(project_id))
        db.execute(
            "DELETE FROM rag_previews WHERE id=? AND project_id=?",
            (str(preview_id), str(project_id)),
        )
    return Response(status_code=204)


@router.post("/answers", response_model=RagAnswerView)
def generate(project_id: UUID, body: GenerateRequest, service: Service):
    return service.rag.generate(str(project_id), body)


@router.get("/answers", response_model=RagPage)
def history(project_id: UUID, service: Service, after: UUID | None = None):
    return service.rag.history(str(project_id), str(after) if after else None)


@router.get("/answers/{answer_id}", response_model=RagAnswerView)
def detail(project_id: UUID, answer_id: UUID, service: Service):
    return service.rag.detail(str(project_id), str(answer_id))


@router.delete("/answers/{answer_id}", status_code=204)
def delete(project_id: UUID, answer_id: UUID, body: Confirm, service: Service):
    service.rag.delete(str(project_id), str(answer_id), body)
    return Response(status_code=204)
