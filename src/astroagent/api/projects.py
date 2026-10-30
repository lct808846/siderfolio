"""V0.6 项目接口，写操作复用会话门锁与本机访问边界。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from astroagent.api.conversations import Service
from astroagent.conversation_schemas import ArtifactInfo, ArtifactRequest
from astroagent.errors import ServiceError
from astroagent.project_archives import export_archive, import_archive
from astroagent.project_schemas import (
    CompareRequest,
    Comparison,
    ImportResult,
    Membership,
    Project,
    ProjectArchiveRequest,
    ProjectCreate,
    ProjectDelete,
    ProjectDetail,
    ProjectUpdate,
    Rerun,
    RerunRequest,
    Revision,
    Snapshot,
    SnapshotCreate,
    SnapshotRename,
    SnapshotSummary,
)
from astroagent.project_service import compare_snapshots, get_executor
from astroagent.schemas import ChatResponse, ErrorResponse

router = APIRouter(
    prefix="/api/v1/projects",
    tags=["projects"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 413, 415, 422, 503)},
)


def get_projects(service: Service):
    return service.projects


Projects = Annotated[object, Depends(get_projects)]


@router.get("", response_model=list[Project])
def list_projects(service: Projects):
    return service.repository.list()


@router.post("", response_model=Project, status_code=201)
def create(request: ProjectCreate, service: Projects):
    with service.conversations.gate:
        return service.repository.create(request)


@router.get("/memberships", response_model=dict[str, str])
def memberships(service: Projects):
    with service.repository.repo.connection() as db:
        return {
            row[0]: row[1]
            for row in db.execute("SELECT conversation_id,project_id FROM project_conversations")
        }


@router.post(
    "/import",
    response_model=ImportResult,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def restore(request: Request, service: Projects):
    if not service.archive_import_slot.acquire(blocking=False):
        raise ServiceError(503, "project_import_busy", "已有归档正在导入，请稍后重试。")
    try:
        raw = await request.body()
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(import_archive, service.repository, raw)
    finally:
        service.archive_import_slot.release()


@router.get("/{project_id}", response_model=ProjectDetail)
def detail(project_id: UUID, service: Projects):
    return service.repository.detail(str(project_id))


@router.patch("/{project_id}", response_model=Project)
def update(project_id: UUID, request: ProjectUpdate, service: Projects):
    with service.conversations.gate:
        return service.repository.update(str(project_id), request)


@router.delete("/{project_id}", status_code=204)
def delete(project_id: UUID, request: ProjectDelete, service: Projects):
    with service.conversations.gate:
        service.repository.delete(str(project_id), request.expected_revision)
        service.conversations.artifacts.remove_project(str(project_id))
    return Response(status_code=204)


@router.put("/{project_id}/conversations/{conversation_id}", response_model=ProjectDetail)
def assign(project_id: UUID, conversation_id: UUID, request: Membership, service: Projects):
    with service.conversations.gate:
        return service.repository.membership(str(project_id), str(conversation_id), request)


@router.delete("/{project_id}/conversations/{conversation_id}", status_code=204)
def unassign(project_id: UUID, conversation_id: UUID, request: Membership, service: Projects):
    with service.conversations.gate:
        service.repository.membership(str(project_id), str(conversation_id), request, remove=True)
    return Response(status_code=204)


@router.get("/{project_id}/snapshots", response_model=list[SnapshotSummary])
def list_snapshots(project_id: UUID, service: Projects):
    return service.repository.detail(str(project_id))["snapshots"]


@router.post("/{project_id}/snapshots", response_model=Snapshot, status_code=201)
def save_snapshot(project_id: UUID, request: SnapshotCreate, service: Projects):
    with service.conversations.gate:
        return service.repository.save_snapshot(str(project_id), request)


@router.get("/{project_id}/snapshots/{snapshot_id}", response_model=Snapshot)
def read_snapshot(project_id: UUID, snapshot_id: UUID, service: Projects):
    return service.repository.snapshot(str(project_id), str(snapshot_id))


@router.patch("/{project_id}/snapshots/{snapshot_id}", response_model=Snapshot)
def rename_snapshot(
    project_id: UUID, snapshot_id: UUID, request: SnapshotRename, service: Projects
):
    with service.conversations.gate:
        return service.repository.change_snapshot(
            str(project_id), str(snapshot_id), request.expected_revision, request.name
        )


@router.delete("/{project_id}/snapshots/{snapshot_id}", status_code=204)
def delete_snapshot(project_id: UUID, snapshot_id: UUID, request: Revision, service: Projects):
    with service.conversations.gate:
        service.repository.change_snapshot(
            str(project_id), str(snapshot_id), request.expected_revision
        )
        service.conversations.artifacts.remove_project(str(project_id), str(snapshot_id))
    return Response(status_code=204)


@router.post(
    "/{project_id}/snapshots/{snapshot_id}/artifacts", status_code=201, response_model=ArtifactInfo
)
def snapshot_artifact(
    project_id: UUID, snapshot_id: UUID, request: ArtifactRequest, service: Projects
):
    def loader():
        return ChatResponse.model_validate(
            service.repository.snapshot(str(project_id), str(snapshot_id))["response"]
        )

    return service.conversations.artifacts.generate(
        str(project_id),
        str(snapshot_id),
        request,
        snapshot_loader=loader,
        owner=(str(project_id), str(snapshot_id)),
    )


@router.post("/{project_id}/comparisons", response_model=Comparison)
def compare(project_id: UUID, request: CompareRequest, service: Projects):
    with service.repository.repo.connection() as db:
        db.execute("BEGIN")
        service.repository._project(db, str(project_id))
        left = service.repository._get(db, "snapshots", request.left_id, str(project_id))
        right = service.repository._get(db, "snapshots", request.right_id, str(project_id))
    return compare_snapshots(left, right, request.match_identifiers)


@router.post(
    "/{project_id}/snapshots/{snapshot_id}/reruns",
    response_model=Rerun,
    responses={202: {"model": Rerun}},
)
def rerun(
    project_id: UUID,
    snapshot_id: UUID,
    request: RerunRequest,
    response: Response,
    service: Projects,
):
    result, response.status_code = service.rerun(
        str(project_id), str(snapshot_id), request, get_executor
    )
    return result


@router.get("/{project_id}/reruns/{rerun_id}", response_model=Rerun)
def read_rerun(project_id: UUID, rerun_id: UUID, service: Projects):
    return service.repository.rerun(str(project_id), str(rerun_id))


@router.post(
    "/{project_id}/archive",
    response_class=Response,
    responses={
        200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def archive(project_id: UUID, request: ProjectArchiveRequest, service: Projects):
    if not service.archive_export_slot.acquire(blocking=False):
        raise ServiceError(503, "project_archive_busy", "已有项目正在归档，请稍后重试。")
    try:
        payload = export_archive(
            service.repository, str(project_id), request.expected_revision, request.format_version
        )
        return Response(
            payload,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="astroagent-project.zip"'},
        )
    finally:
        service.archive_export_slot.release()
