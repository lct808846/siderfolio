"""单次聊天接口，同步工作在线程池执行，不阻塞健康检查。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import ValidationError

from astroagent.ads import AdsService
from astroagent.agent import AstroAgent
from astroagent.config import Settings
from astroagent.errors import ServiceError
from astroagent.gaia import GaiaService
from astroagent.schemas import ChatRequest, ChatResponse, ErrorResponse
from astroagent.simbad import SimbadService

router = APIRouter(prefix="/api/v1", tags=["chat"])


def get_agent() -> AstroAgent:
    try:
        settings = Settings()
    except ValidationError as exc:
        raise ServiceError(503, "invalid_configuration", "服务配置无效，请检查环境变量。") from exc
    return AstroAgent(
        None,
        SimbadService(settings.simbad_timeout_seconds),
        settings,
        AdsService(settings.ads_api_token, settings.ads_timeout_seconds),
        GaiaService(settings.gaia_timeout_seconds),
    )


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={code: {"model": ErrorResponse} for code in (502, 503, 504)},
    summary="自然语言天文查询",
    description=(
        "单次无状态 SIMBAD、ADS 与 Gaia DR3 查询。天体结果在 results，"
        "文献结果在 literature_results，Gaia 数据与程序统计在 gaia_results；"
        "数据库失败也逐次保留，status 可为 partial 或 error。"
    ),
)
def chat(request: ChatRequest, agent: Annotated[AstroAgent, Depends(get_agent)]) -> ChatResponse:
    return agent.chat(request.message)
