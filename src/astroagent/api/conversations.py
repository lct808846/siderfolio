"""会话 CRUD 与同步轮次；原无状态聊天入口保持独立。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from astroagent.api.chat import get_agent, get_agent_for_model
from astroagent.conversation_schemas import (
    ArtifactInfo,
    ArtifactRequest,
    Conversation,
    ConversationCreate,
    ConversationDetail,
    ConversationRename,
    Turn,
    TurnFailureResponse,
    TurnRequest,
)
from astroagent.errors import ServiceError
from astroagent.schemas import ErrorResponse

router = APIRouter(
    prefix="/api/v1/conversations",
    tags=["conversations"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 413, 415, 422, 503)},
)


def get_service(request: Request):
    service = getattr(request.app.state, "conversation_service", None)
    if service is None:
        raise ServiceError(
            503, "conversation_storage_unavailable", "本地会话存储不可用，请检查服务端配置。"
        )
    return service


Service = Annotated[object, Depends(get_service)]


@router.post("", status_code=201, response_model=Conversation)
def create(request: ConversationCreate, service: Service):
    with service.gate:
        return service.repository.create(request.title)


@router.get("", response_model=list[Conversation])
def list_conversations(service: Service):
    return service.repository.list()


@router.get("/{conversation_id}", response_model=ConversationDetail)
def detail(conversation_id: UUID, service: Service):
    return service.repository.detail(str(conversation_id))


@router.patch("/{conversation_id}", response_model=Conversation)
def rename(conversation_id: UUID, request: ConversationRename, service: Service):
    with service.gate:
        return service.repository.rename(
            str(conversation_id), request.title, request.expected_metadata_revision
        )


@router.delete("/{conversation_id}", status_code=204)
def delete(conversation_id: UUID, service: Service):
    service.delete(str(conversation_id))
    return Response(status_code=204)


@router.post(
    "/{conversation_id}/turns",
    response_model=Turn,
    responses={
        202: {"model": Turn},
        **{code: {"model": TurnFailureResponse} for code in (502, 503, 504)},
    },
)
def submit(conversation_id: UUID, request: TurnRequest, response: Response, service: Service):
    factory = get_agent
    if request.model is not None:
        selected_agent = get_agent_for_model(request.model)

        def factory():
            return selected_agent

    turn, response.status_code = service.submit(str(conversation_id), request, factory)
    return turn


@router.get("/{conversation_id}/turns/{turn_id}", response_model=Turn)
def read_turn(conversation_id: UUID, turn_id: UUID, service: Service):
    return service.repository.turn(str(conversation_id), str(turn_id))


@router.post(
    "/{conversation_id}/turns/{turn_id}/artifacts", status_code=201, response_model=ArtifactInfo
)
def generate(conversation_id: UUID, turn_id: UUID, request: ArtifactRequest, service: Service):
    return service.artifacts.generate(str(conversation_id), str(turn_id), request)
