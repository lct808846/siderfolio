"""Explicit plotting preparation, isolated runs and bounded artifact downloads."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from astroagent.api.attachments import UPLOAD_SCHEMA
from astroagent.api.conversations import Service
from astroagent.errors import ServiceError
from astroagent.plot_data import MAX_DATA
from astroagent.plot_schemas import (
    PlotDataPreview,
    PlotDataset,
    PlotInitialize,
    PlotOperation,
    PlotPage,
    PlotPlanRequest,
    PlotRunRequest,
    PlotSelection,
    PlotStatus,
    SnapshotDatasetRequest,
    TurnDatasetRequest,
)
from astroagent.plot_service import FILES
from astroagent.schemas import ErrorResponse

router = APIRouter(
    tags=["plotting"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 413, 422, 503)},
)


def get_plotting(service: Service):
    return service.plotting


Plotting = Annotated[object, Depends(get_plotting)]
ROOT = "/api/v1/projects/{project_id}/plotting"


@router.get("/api/v1/setup/plotting", response_model=PlotStatus)
def status(service: Plotting):
    return service.status()


@router.post("/api/v1/setup/plotting", response_model=PlotStatus)
def initialize(request: PlotInitialize, service: Plotting):
    with service.conversations.gate:
        service.store.initialize()
    return service.status()


@router.get(ROOT, response_model=PlotPage)
def page(project_id: UUID, service: Plotting):
    return service.store.list(str(project_id))


@router.put(
    ROOT + "/datasets/{dataset_id}/upload", response_model=PlotDataset, openapi_extra=UPLOAD_SCHEMA
)
async def upload(project_id: UUID, dataset_id: UUID, request: Request, service: Plotting):
    try:
        async with request.form(max_files=1, max_fields=0, max_part_size=32768) as form:
            fields = list(form.multi_items())
            if (
                len(fields) != 1
                or fields[0][0] != "file"
                or not isinstance(fields[0][1], UploadFile)
            ):
                raise ValueError("Single file required")
            file = fields[0][1]
            raw = await file.read(MAX_DATA + 1)
            if len(raw) > MAX_DATA:
                raise ServiceError(413, "plot_dataset_too_large", "文件超过5 MiB。")
            name = (file.filename or "data.csv").replace("\\", "/").rsplit("/", 1)[-1]
            return await run_in_threadpool(
                service.upload, str(project_id), str(dataset_id), name, raw
            )
    except (HTTPException, ValueError) as exc:
        raise ServiceError(422, "plot_upload_invalid", "请选择一个UTF-8 CSV或TSV文件。") from exc


@router.put(ROOT + "/datasets/{dataset_id}/snapshot", response_model=PlotDataset)
def snapshot(
    project_id: UUID, dataset_id: UUID, request: SnapshotDatasetRequest, service: Plotting
):
    return service.snapshot(str(project_id), str(dataset_id), request)


@router.put(ROOT + "/datasets/{dataset_id}/turn", response_model=PlotDataset)
def turn(project_id: UUID, dataset_id: UUID, request: TurnDatasetRequest, service: Plotting):
    with service.conversations.gate:
        return service.turn(str(project_id), str(dataset_id), request)


@router.get(ROOT + "/datasets/{dataset_id}/preview", response_model=PlotDataPreview)
def preview(project_id: UUID, dataset_id: UUID, service: Plotting):
    return service.preview(str(project_id), str(dataset_id))


@router.get(ROOT + "/datasets/{dataset_id}/data.csv")
def data_file(project_id: UUID, dataset_id: UUID, service: Plotting):
    with service.store.repo.connection() as db:
        _, data, _ = service.store.dataset(db, str(project_id), str(dataset_id))
    return Response(
        data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="data.csv"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put(ROOT + "/plans/{plan_id}", response_model=PlotOperation)
def plan(project_id: UUID, plan_id: UUID, request: PlotPlanRequest, service: Plotting):
    return service.plan(str(project_id), str(plan_id), request)


@router.put(ROOT + "/runs/{run_id}", response_model=PlotOperation)
def run(project_id: UUID, run_id: UUID, request: PlotRunRequest, service: Plotting):
    return service.run(str(project_id), str(run_id), request)


@router.get(ROOT + "/operations/{operation_id}", response_model=PlotOperation)
def operation(project_id: UUID, operation_id: UUID, service: Plotting):
    with service.store.repo.connection() as db:
        return service.store.operation(db, str(project_id), str(operation_id))


@router.get(ROOT + "/runs/{run_id}/files/{name}")
def output(project_id: UUID, run_id: UUID, name: str, service: Plotting):
    data = service.output(str(project_id), str(run_id), name)
    return Response(
        data,
        media_type=FILES[name],
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.post(ROOT + "/runs/{run_id}/bundle")
def bundle(project_id: UUID, run_id: UUID, request: PlotSelection, service: Plotting):
    return Response(
        service.bundle(str(project_id), str(run_id), request.files),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="astroagent-plot.zip"'},
    )
