"""个人天文文献库 API：分页检索、详情、手动加入、标签/备注编辑与移除。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from astroagent.ads import AdsService
from astroagent.api.conversations import Service
from astroagent.config import LocalSettings, Settings
from astroagent.literature_schemas import (
    LiteratureItem,
    LiteratureListResponse,
    LiteratureManualAddRequest,
    LiteratureSaveReceipt,
    LiteratureStatusResponse,
    LiteratureUpdateRequest,
)
from astroagent.mcp_client import McpAdsAdapter, effective_astronomy_transport, get_mcp_pool
from astroagent.schemas import ErrorResponse

router = APIRouter(
    prefix="/api/v1/literature",
    tags=["literature"],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 415, 422, 503)},
)


def get_literature(service: Service):
    return service.literature


Literature = Annotated[object, Depends(get_literature)]


def _ads_verifier():
    try:
        local = LocalSettings()
        settings = Settings()
        if effective_astronomy_transport(local) == "mcp":
            return McpAdsAdapter(get_mcp_pool(local), settings)
        return AdsService(settings.ads_api_token, settings.ads_timeout_seconds)
    except Exception:
        return None


@router.get("/items", response_model=LiteratureListResponse)
def list_items(
    literature: Literature,
    q: str = Query(default="", max_length=200),
    year: int | None = Query(default=None, ge=1, le=9999),
    tag: str = Query(default="", max_length=40),
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return literature.list_items(q=q, year=year, tag=tag, page=page, page_size=page_size)


@router.get("/items/status", response_model=LiteratureStatusResponse)
def items_status(
    literature: Literature,
    bibcodes: str = Query(default="", max_length=2000),
):
    codes = [code.strip() for code in bibcodes.split(",") if code.strip()][:50]
    return LiteratureStatusResponse(saved=literature.status_by_bibcodes(codes))


@router.get("/items/{item_id}", response_model=LiteratureItem)
def get_item(item_id: UUID, literature: Literature):
    return literature.get_item(str(item_id))


@router.post("/items", response_model=LiteratureSaveReceipt, status_code=200)
def add_items(request: LiteratureManualAddRequest, literature: Literature):
    return literature.add_manual(request, ads_service=_ads_verifier())


@router.patch("/items/{item_id}", response_model=LiteratureItem)
def update_item(item_id: UUID, request: LiteratureUpdateRequest, literature: Literature):
    return literature.update_item(str(item_id), request)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(
    item_id: UUID,
    literature: Literature,
    expected_revision: int = Query(ge=1),
):
    literature.delete_item(str(item_id), expected_revision=expected_revision)
    return Response(status_code=204)
