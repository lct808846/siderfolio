"""单次聊天接口，同步工作在线程池执行，不阻塞健康检查。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import ValidationError

from astroagent.agent import AstroAgent
from astroagent.config import Settings
from astroagent.errors import ServiceError
from astroagent.schemas import ChatRequest, ChatResponse, ErrorResponse
from astroagent.simbad import SimbadService

router = APIRouter(prefix="/api/v1", tags=["chat"])


def get_agent() -> AstroAgent:
    try:
        settings = Settings()
    except ValidationError as exc:
        raise ServiceError(503, "invalid_configuration", "服务配置无效，请检查环境变量。") from exc
    return AstroAgent(None, SimbadService(settings.simbad_timeout_seconds), settings)


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={code: {"model": ErrorResponse} for code in (502, 503, 504)},
    summary="自然语言天文查询",
    description="单次无状态查询。数据库失败在 results 中记录，status 可为 partial 或 error。",
)
def chat(request: ChatRequest, agent: Annotated[AstroAgent, Depends(get_agent)]) -> ChatResponse:
    return agent.chat(request.message)
