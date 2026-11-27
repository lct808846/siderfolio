"""V2.2 长期记忆接口：记忆开关、合成摘要与添加记忆（不提供逐条原始记忆查询）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from astroagent.api.conversations import get_service
from astroagent.errors import ServiceError
from astroagent.memory_schemas import (
    MemoryCreateRequest,
    MemoryItem,
    MemoryPreferences,
    MemoryPreferencesUpdate,
    MemorySummaryOverview,
)
from astroagent.schemas import ErrorResponse

router = APIRouter(
    prefix="/api/v1/memories",
    tags=["memory"],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
)


Service = Annotated[object, Depends(get_service)]


def get_memory_service(service: Service):
    memory = getattr(service, "memory", None)
    if memory is None:
        raise ServiceError(503, "memory_service_unavailable", "记忆服务暂不可用。")
    return memory


Memory = Annotated[object, Depends(get_memory_service)]


@router.get("/summary", response_model=MemorySummaryOverview)
def read_memory_summary(memory: Memory):
    return memory.summary_overview()


@router.get("/preferences", response_model=MemoryPreferences)
def read_memory_preferences(memory: Memory):
    return memory.get_preferences()


@router.put("/preferences", response_model=MemoryPreferences)
def update_memory_preferences(body: MemoryPreferencesUpdate, memory: Memory):
    return memory.update_preferences(body)


@router.post("", status_code=201, response_model=MemoryItem)
def create_memory(body: MemoryCreateRequest, memory: Memory):
    return memory.create_memory(body)
