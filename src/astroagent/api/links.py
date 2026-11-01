"""项目总览和用户显式引用；所有读取均不访问外部服务。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from astroagent.api.conversations import Service
from astroagent.link_schemas import (
    LinkCreate,
    LinkCreated,
    LinkDelete,
    LinkDetail,
    LinkPage,
    LinkPatch,
    ProjectOverview,
    TargetKind,
)
from astroagent.schemas import ErrorResponse

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["project-links"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 413, 422, 503)},
)


def get_links(service: Service):
    return service.links


Links = Annotated[object, Depends(get_links)]


@router.get("/overview", response_model=ProjectOverview)
def overview(project_id: UUID, service: Links):
    return service.overview(str(project_id))


@router.get("/links", response_model=LinkPage)
def list_links(
    project_id: UUID,
    service: Links,
    limit: int = Query(default=25, ge=1, le=100),
    after: UUID | None = None,
    target_type: TargetKind | None = None,
    target_id: UUID | None = None,
    evidence_id: UUID | None = None,
):
    return service.page(
        str(project_id),
        limit,
        after=str(after) if after else None,
        target_type=target_type,
        target_id=str(target_id) if target_id else None,
        evidence_id=str(evidence_id) if evidence_id else None,
    )


@router.post("/links", response_model=LinkCreated, responses={201: {"model": LinkCreated}})
def create(project_id: UUID, request: LinkCreate, response: Response, service: Links):
    value, response.status_code = service.create(str(project_id), request)
    return value


@router.get("/links/{link_id}", response_model=LinkDetail)
def detail(project_id: UUID, link_id: UUID, service: Links):
    return service.detail(str(project_id), str(link_id))


@router.patch("/links/{link_id}", response_model=LinkDetail)
def update(project_id: UUID, link_id: UUID, request: LinkPatch, service: Links):
    return service.change(str(project_id), str(link_id), request)


@router.delete("/links/{link_id}", status_code=204)
def remove(project_id: UUID, link_id: UUID, request: LinkDelete, service: Links):
    service.change(str(project_id), str(link_id), request, remove=True)
    return Response(status_code=204)
