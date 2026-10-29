"""仅暴露清单登记的图片和缓存 ZIP，不解析客户端文件路径。"""

from uuid import UUID

from fastapi import APIRouter, Response

from astroagent.api.conversations import Service
from astroagent.export_schemas import ExportManifest
from astroagent.schemas import ErrorResponse

router = APIRouter(
    prefix="/api/v1/artifacts",
    tags=["artifacts"],
    responses={code: {"model": ErrorResponse} for code in (404, 410, 422, 500, 503)},
)
HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


@router.get("/{artifact_id}/manifest", response_model=ExportManifest)
def manifest(artifact_id: UUID, service: Service):
    return service.artifacts.get(str(artifact_id))["manifest"]


@router.get(
    "/{artifact_id}/figures/{figure_id}",
    response_class=Response,
    responses={
        200: {"content": {"image/png": {"schema": {"type": "string", "format": "binary"}}}},
    },
)
def figure(artifact_id: UUID, figure_id: UUID, service: Service):
    return Response(
        service.artifacts.figure(str(artifact_id), str(figure_id)),
        media_type="image/png",
        headers=HEADERS,
    )


@router.get(
    "/{artifact_id}/download",
    response_class=Response,
    responses={
        200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}},
    },
)
def download(artifact_id: UUID, service: Service):
    return Response(
        service.artifacts.get(str(artifact_id))["package"],
        media_type="application/zip",
        headers={
            **HEADERS,
            "Content-Disposition": 'attachment; filename="astroagent-results.zip"',
        },
    )
