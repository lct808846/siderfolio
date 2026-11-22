"""Preferences, readiness, and history for automatic conversation naming."""

from uuid import UUID

from fastapi import APIRouter

from astroagent.api.conversations import Service
from astroagent.local_model_schemas import (
    LocalPreferenceUpdate,
    LocalProbe,
    LocalStatus,
    LocalTaskView,
)
from astroagent.schemas import ErrorResponse

router = APIRouter(
    tags=["local-titles"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 413, 422, 503)},
)
ROOT = "/api/v1/local-titles"


@router.get(ROOT, response_model=LocalStatus)
def status(service: Service):
    return service.local_titles.status()


@router.post(ROOT + "/probe", response_model=LocalStatus)
def probe(request: LocalProbe, service: Service):
    return service.local_titles.status(probe=True)


@router.put(ROOT + "/preferences", response_model=LocalStatus)
def preferences(request: LocalPreferenceUpdate, service: Service):
    service.local_titles.store.update_preferences(request)
    return service.local_titles.status()


@router.get(
    "/api/v1/conversations/{conversation_id}/local-title", response_model=list[LocalTaskView]
)
def title_state(conversation_id: UUID, service: Service):
    return [
        {"task": value} for value in service.local_titles.store.latest_title(str(conversation_id))
    ]
