"""Local-only helper APIs; no tool execution or automatic application of manual results."""

from uuid import UUID

from fastapi import APIRouter

from astroagent.api.conversations import Service
from astroagent.local_model_schemas import (
    LocalClear,
    LocalInitialize,
    LocalPreferenceUpdate,
    LocalProbe,
    LocalStatus,
    LocalTaskRequest,
    LocalTaskView,
)
from astroagent.schemas import ErrorResponse

router = APIRouter(
    tags=["local-assistant"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 413, 422, 503)},
)
ROOT = "/api/v1/local-assistant"


@router.get(ROOT, response_model=LocalStatus)
def status(service: Service):
    return service.local_assistant.status()


@router.post(ROOT + "/probe", response_model=LocalStatus)
def probe(request: LocalProbe, service: Service):
    return service.local_assistant.status(probe=True)


@router.post(ROOT + "/initialize", response_model=LocalStatus)
def initialize(request: LocalInitialize, service: Service):
    service.local_assistant.store.initialize()
    return service.local_assistant.status()


@router.put(ROOT + "/preferences", response_model=LocalStatus)
def preferences(request: LocalPreferenceUpdate, service: Service):
    service.local_assistant.store.update_preferences(request)
    return service.local_assistant.status()


@router.put(ROOT + "/jobs/{task_id}", response_model=LocalTaskView)
def submit(task_id: UUID, request: LocalTaskRequest, service: Service):
    return service.local_assistant.submit(str(task_id), request)


@router.get(ROOT + "/jobs/{task_id}", response_model=LocalTaskView)
def task(task_id: UUID, service: Service):
    return service.local_assistant.view(str(task_id))


@router.post(ROOT + "/clear", response_model=LocalStatus)
def clear(request: LocalClear, service: Service):
    service.local_assistant.clear()
    return service.local_assistant.status()


@router.get(
    "/api/v1/conversations/{conversation_id}/local-title", response_model=list[LocalTaskView]
)
def title_state(conversation_id: UUID, service: Service):
    return [
        service.local_assistant.view(value["id"])
        for value in service.local_assistant.store.latest_title(str(conversation_id))
    ]
