"""会话 CRUD 与同步/流式轮次；原无状态聊天入口保持独立。"""

import asyncio
import json
import threading
import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from astroagent.api.chat import get_agent, get_agent_for_model
from astroagent.conversation_schemas import (
    ArchivedConversation,
    ArtifactInfo,
    ArtifactRequest,
    Conversation,
    ConversationBundle,
    ConversationCreate,
    ConversationDetail,
    ConversationRename,
    Turn,
    TurnFailureResponse,
    TurnRequest,
)
from astroagent.errors import ServiceError
from astroagent.model_providers import configured_pricing_snapshot
from astroagent.schemas import ErrorResponse
from astroagent.trace_runtime import enrich_trace_cost
from astroagent.trace_schemas import RunTrace

router = APIRouter(
    prefix="/api/v1/conversations",
    tags=["conversations"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 413, 415, 422, 503)},
)


def get_service(request: Request):
    principal = getattr(request.state, "principal", None)
    identity = getattr(request.app.state, "identity", None)
    if not principal or identity is None:
        raise ServiceError(401, "login_required", "请先登录。")
    return identity.tenants.for_user(principal)


Service = Annotated[object, Depends(get_service)]


@router.post("", status_code=201, response_model=Conversation)
def create(request: ConversationCreate, service: Service):
    with service.gate:
        return service.repository.create(request.title)


@router.get("", response_model=list[Conversation])
def list_conversations(service: Service, include_archived: bool = False):
    return service.repository.list(include_archived=include_archived)


@router.get("/archived", response_model=list[ArchivedConversation])
def list_archived_conversations(service: Service):
    return service.repository.list_archived()


@router.get("/{conversation_id}", response_model=ConversationDetail)
def detail(conversation_id: UUID, service: Service):
    return service.repository.detail(str(conversation_id))


@router.get("/{conversation_id}/bundle", response_model=ConversationBundle)
def bundle(conversation_id: UUID, service: Service):
    return service.bundle(str(conversation_id))


@router.post("/{conversation_id}/archive", response_model=ArchivedConversation)
def archive(conversation_id: UUID, service: Service):
    with service.gate:
        return service.repository.archive(str(conversation_id))


@router.delete("/{conversation_id}/archive", response_model=Conversation)
def unarchive(conversation_id: UUID, service: Service):
    with service.gate:
        return service.repository.unarchive(str(conversation_id))


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


def _agent_factory(model: str | None):
    if model is None:
        return get_agent
    selected_agent = get_agent_for_model(model)

    def factory():
        return selected_agent

    return factory


def _sse_frame(event: str, payload: dict) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {encoded}\n\n".encode()


@router.post(
    "/{conversation_id}/turns",
    response_model=Turn,
    responses={
        202: {"model": Turn},
        **{code: {"model": TurnFailureResponse} for code in (502, 503, 504)},
    },
)
def submit(conversation_id: UUID, request: TurnRequest, response: Response, service: Service):
    turn, response.status_code = service.submit(
        str(conversation_id), request, _agent_factory(request.model)
    )
    return turn


@router.post(
    "/{conversation_id}/turns/stream",
    responses={
        200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}},
        **{code: {"model": TurnFailureResponse} for code in (502, 503, 504)},
    },
)
async def submit_stream(conversation_id: UUID, request: TurnRequest, service: Service):
    factory = _agent_factory(request.model)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

    def push(event: str, payload: dict):
        loop.call_soon_threadsafe(queue.put_nowait, (event, payload))

    def on_event(event: dict):
        kind = event.get("type")
        if kind == "delta":
            text = event.get("text")
            if isinstance(text, str) and text:
                push("delta", {"text": text})
        elif kind == "status":
            push(
                "status",
                {
                    "phase": event.get("phase", "thinking"),
                    "tool": event.get("tool"),
                    "label": event.get("label", "正在处理，请稍候…"),
                },
            )
        elif kind == "reset":
            push("reset", {})

    def worker():
        try:
            turn, status_code = service.submit(
                str(conversation_id), request, factory, on_event=on_event
            )
            push(
                "done",
                {
                    "status_code": status_code,
                    "turn": turn.model_dump(mode="json"),
                },
            )
        except ServiceError as exc:
            payload = {
                "status": exc.status_code,
                "error": exc.error.model_dump(mode="json"),
            }
            for name in ("conversation_id", "turn_id"):
                if hasattr(exc, name):
                    payload[name] = getattr(exc, name)
            push("error", payload)
        except Exception:
            push(
                "error",
                {
                    "status": 502,
                    "error": {
                        "code": "conversation_execution_failed",
                        "message": "回答未能完成，请查看已保存的状态。",
                        "retryable": False,
                    },
                },
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=worker, daemon=True).start()

    async def stream():
        pending: tuple[str, dict] | None = None
        seen_delta = False
        while True:
            if pending is not None:
                item = pending
                pending = None
            else:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield b": ping\n\n"
                    continue
            if item is None:
                break
            event, payload = item
            if event == "reset":
                seen_delta = False
                yield _sse_frame(event, payload)
                continue
            if event == "delta":
                if not seen_delta:
                    seen_delta = True
                    yield _sse_frame("delta", payload)
                    continue
                chunks = [payload["text"]]
                buffered_len = len(chunks[0])
                deadline = time.monotonic() + 0.035
                stream_ended = False
                while buffered_len < 64:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        nxt = await asyncio.wait_for(queue.get(), timeout=remaining)
                    except TimeoutError:
                        break
                    if nxt is None:
                        stream_ended = True
                        break
                    if nxt[0] != "delta":
                        pending = nxt
                        break
                    text = nxt[1]["text"]
                    chunks.append(text)
                    buffered_len += len(text)
                yield _sse_frame("delta", {"text": "".join(chunks)})
                if stream_ended:
                    break
                continue
            yield _sse_frame(event, payload)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{conversation_id}/turns/{turn_id}", response_model=Turn)
def read_turn(conversation_id: UUID, turn_id: UUID, service: Service):
    return service.turn_enriched(str(conversation_id), str(turn_id))


@router.get("/{conversation_id}/turns/{turn_id}/trace", response_model=RunTrace)
def read_turn_trace(conversation_id: UUID, turn_id: UUID, service: Service):
    service.repository.turn(str(conversation_id), str(turn_id))
    if service.traces is None:
        raise ServiceError(404, "trace_not_found", "该轮次没有运行追踪记录。")
    trace = service.traces.get(str(conversation_id), str(turn_id))
    if trace is None:
        raise ServiceError(404, "trace_not_found", "该轮次没有可展示的运行追踪记录。")
    pricing, aliases = configured_pricing_snapshot()
    return enrich_trace_cost(trace, configured_pricing=pricing, model_aliases=aliases)


@router.post(
    "/{conversation_id}/turns/{turn_id}/artifacts", status_code=201, response_model=ArtifactInfo
)
def generate(conversation_id: UUID, turn_id: UUID, request: ArtifactRequest, service: Service):
    return service.artifacts.generate(str(conversation_id), str(turn_id), request)
