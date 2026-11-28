"""V2.3 项目天文数据表管理、VizieR 只读检索、确定性算子与导出接口。"""

from __future__ import annotations

import json
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from astroagent.api.attachments import UPLOAD_SCHEMA
from astroagent.api.chat import get_agent
from astroagent.api.conversations import Service
from astroagent.errors import ServiceError
from astroagent.schemas import ErrorResponse
from astroagent.table_schemas import (
    MAX_TABLE_UPLOAD_BYTES,
    AnalysisDataset,
    AnalysisRunResponse,
    OperatorName,
    ProjectTablesPage,
    SendToPlotRequest,
    TableImportGaiaRequest,
    TableImportVizierTurnRequest,
    TableInspectResponse,
    TablePreviewResponse,
    VizierPreset,
    VizierQueryHttpRequest,
    VizierQueryHttpResponse,
)
from astroagent.table_service import SendToPlotResponse

router = APIRouter(
    tags=["tables"],
    responses={code: {"model": ErrorResponse} for code in (401, 404, 409, 413, 415, 422, 503)},
)


def get_tables(service: Service):
    return service.tables


Tables = Annotated[object, Depends(get_tables)]


@router.get("/api/v1/tables/vizier/presets", response_model=list[VizierPreset])
def vizier_presets(service: Tables):
    return service.vizier_presets()


@router.post("/api/v1/tables/vizier/query", response_model=VizierQueryHttpResponse)
def vizier_query(request: VizierQueryHttpRequest, service: Tables):
    agent = get_agent()
    return service.query_vizier(request, vizier_service=getattr(agent, "vizier", None))


@router.get("/api/v1/projects/{project_id}/tables", response_model=ProjectTablesPage)
def list_project_tables(project_id: UUID, service: Tables):
    return service.list_project(str(project_id))


@router.post(
    "/api/v1/projects/{project_id}/tables/inspect",
    response_model=TableInspectResponse,
    openapi_extra=UPLOAD_SCHEMA,
)
async def inspect_upload(project_id: UUID, request: Request, service: Tables):
    with service.store.repo.connection() as db:
        service.store.projects._project(db, str(project_id))
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
            raw = await file.read(MAX_TABLE_UPLOAD_BYTES + 1)
            if len(raw) > MAX_TABLE_UPLOAD_BYTES:
                raise ServiceError(413, "table_too_large", "文件不能超过 10 MiB。")
            name = (file.filename or "table.csv").replace("\\", "/").rsplit("/", 1)[-1]
            return await run_in_threadpool(service.inspect_upload, name, raw)
    except ServiceError:
        raise
    except (HTTPException, ValueError) as exc:
        raise ServiceError(422, "table_upload_invalid", "请选择一个有效的天文数据表文件。") from exc


@router.post(
    "/api/v1/projects/{project_id}/tables/upload",
    response_model=AnalysisDataset,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "name": {"type": "string"},
                            "hdu_index": {"type": "integer"},
                            "selected_columns": {"type": "string"},
                        },
                    }
                }
            },
        }
    },
)
async def upload_table(project_id: UUID, request: Request, service: Tables):
    try:
        async with request.form(max_files=1, max_fields=8, max_part_size=65536) as form:
            file = form.get("file")
            if not isinstance(file, UploadFile):
                raise ValueError("Missing file")
            raw = await file.read(MAX_TABLE_UPLOAD_BYTES + 1)
            if len(raw) > MAX_TABLE_UPLOAD_BYTES:
                raise ServiceError(413, "table_too_large", "文件不能超过 10 MiB。")
            filename = (file.filename or "table.csv").replace("\\", "/").rsplit("/", 1)[-1]
            name_val = form.get("name")
            name = str(name_val).strip() if isinstance(name_val, str) and name_val.strip() else None
            hdu_raw = form.get("hdu_index")
            hdu_index: int | None = None
            if isinstance(hdu_raw, str) and hdu_raw.strip() != "":
                hdu_index = int(hdu_raw.strip())
            cols_raw = form.get("selected_columns")
            selected_columns: list[str] | None = None
            if isinstance(cols_raw, str) and cols_raw.strip():
                parsed_cols = json.loads(cols_raw)
                if not isinstance(parsed_cols, list) or not all(
                    isinstance(c, str) for c in parsed_cols
                ):
                    raise ValueError("Invalid selected_columns")
                selected_columns = parsed_cols
            return await run_in_threadpool(
                service.upload_dataset,
                project_id=str(project_id),
                filename=filename,
                raw=raw,
                name=name,
                hdu_index=hdu_index,
                selected_columns=selected_columns,
            )
    except ServiceError:
        raise
    except (HTTPException, ValueError, json.JSONDecodeError) as exc:
        raise ServiceError(422, "table_upload_invalid", "数据表上传参数或文件格式无效。") from exc


@router.post("/api/v1/projects/{project_id}/tables/from-gaia", response_model=AnalysisDataset)
def import_from_gaia(project_id: UUID, request: TableImportGaiaRequest, service: Tables):
    return service.import_from_gaia(str(project_id), request)


@router.post("/api/v1/projects/{project_id}/tables/from-vizier", response_model=AnalysisDataset)
def import_from_vizier(project_id: UUID, request: TableImportVizierTurnRequest, service: Tables):
    return service.import_from_vizier_turn(str(project_id), request)


@router.get("/api/v1/projects/{project_id}/tables/{dataset_id}", response_model=AnalysisDataset)
def get_dataset(project_id: UUID, dataset_id: UUID, service: Tables):
    return service.get_dataset(str(project_id), str(dataset_id))


@router.get(
    "/api/v1/projects/{project_id}/tables/{dataset_id}/preview",
    response_model=TablePreviewResponse,
)
def preview_dataset(
    project_id: UUID,
    dataset_id: UUID,
    service: Tables,
    offset: int = 0,
    limit: int = 50,
):
    return service.preview_dataset(str(project_id), str(dataset_id), offset=offset, limit=limit)


@router.delete("/api/v1/projects/{project_id}/tables/{dataset_id}", status_code=204)
def delete_dataset(project_id: UUID, dataset_id: UUID, service: Tables):
    service.delete_dataset(str(project_id), str(dataset_id))
    return Response(status_code=204)


@router.post(
    "/api/v1/projects/{project_id}/tables/runs/{operator}",
    response_model=AnalysisRunResponse,
)
async def run_operator(
    project_id: UUID,
    operator: OperatorName,
    payload: dict[str, Any],
    service: Tables,
):
    return await run_in_threadpool(service.run_operator, str(project_id), operator, payload)


@router.post(
    "/api/v1/projects/{project_id}/tables/{dataset_id}/send-to-plot",
    response_model=SendToPlotResponse,
)
def send_to_plot(
    project_id: UUID,
    dataset_id: UUID,
    service: Tables,
    request: SendToPlotRequest | None = None,
):
    return service.send_to_plot(
        str(project_id),
        str(dataset_id),
        name=request.name if request else None,
    )


@router.get("/api/v1/projects/{project_id}/tables/{dataset_id}/export")
def export_dataset(
    project_id: UUID,
    dataset_id: UUID,
    service: Tables,
    format: str = "csv",
):
    data, media, filename = service.export_dataset(str(project_id), str(dataset_id), format)
    fallback = filename if filename.isascii() else f"table.{format}"
    return Response(
        data,
        media_type=media,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
            ),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/v1/projects/{project_id}/tables/runs/{run_id}/bundle")
def export_run_bundle(project_id: UUID, run_id: UUID, service: Tables):
    zip_bytes = service.export_run_bundle(str(project_id), str(run_id))
    return Response(
        zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="table-analysis-{run_id}.zip"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
