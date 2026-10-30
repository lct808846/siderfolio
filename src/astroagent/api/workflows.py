"""固定科研流程API；创建与查看不触网，执行必须显式确认。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from astroagent.api.conversations import Service
from astroagent.project_service import get_executor
from astroagent.schemas import ErrorResponse
from astroagent.workflow_schemas import (
    WorkflowCreate,
    WorkflowDelete,
    WorkflowDetail,
    WorkflowExecute,
    WorkflowExecution,
    WorkflowSummary,
    WorkflowTemplate,
)
from astroagent.workflow_templates import templates

router = APIRouter(
    prefix="/api/v1",
    tags=["workflows"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 413, 422, 503)},
)


def get_workflows(service: Service):
    return service.workflows


Workflows = Annotated[object, Depends(get_workflows)]


@router.get("/workflow-templates", response_model=list[WorkflowTemplate])
def catalog():
    return templates()


@router.post("/projects/{project_id}/workflows", response_model=WorkflowDetail, status_code=201)
def create(project_id: UUID, request: WorkflowCreate, service: Workflows):
    with service.conversations.gate:
        run = service.repository.create(str(project_id), request)
        return service.repository.detail(str(project_id), run.id)


@router.get("/projects/{project_id}/workflows", response_model=list[WorkflowSummary])
def list_runs(project_id: UUID, service: Workflows):
    return service.repository.list(str(project_id))


@router.get("/projects/{project_id}/workflows/{run_id}", response_model=WorkflowDetail)
def detail(project_id: UUID, run_id: UUID, service: Workflows):
    return service.repository.detail(str(project_id), str(run_id))


@router.post(
    "/projects/{project_id}/workflows/{run_id}/execute",
    response_model=WorkflowExecution,
    responses={202: {"model": WorkflowExecution}},
)
def execute(
    project_id: UUID, run_id: UUID, request: WorkflowExecute, response: Response, service: Workflows
):
    value, response.status_code = service.execute(
        str(project_id), str(run_id), request, get_executor
    )
    return value


@router.get(
    "/projects/{project_id}/workflows/{run_id}/outputs/{output_id}",
    response_class=Response,
    responses={
        200: {
            "content": {
                media: {"schema": {"type": "string", "format": "binary"}}
                for media in ("application/zip", "application/json", "image/png", "text/csv")
            }
        }
    },
)
def output(project_id: UUID, run_id: UUID, output_id: UUID, service: Workflows):
    info, content = service.repository.output(str(project_id), str(run_id), str(output_id))
    disposition = "inline" if info.media_type == "image/png" else "attachment"
    return Response(
        content,
        media_type=info.media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{info.filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/projects/{project_id}/workflows/{run_id}", status_code=204)
def delete(project_id: UUID, run_id: UUID, request: WorkflowDelete, service: Workflows):
    with service.conversations.gate:
        service.repository.delete(str(project_id), str(run_id), request)
    return Response(status_code=204)
