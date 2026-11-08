"""Configured model allowlist without contacting the external provider."""

from fastapi import APIRouter
from pydantic import ValidationError

from astroagent.config import Settings
from astroagent.errors import ServiceError
from astroagent.model_schemas import ChatModelCatalog

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@router.get("", response_model=ChatModelCatalog)
def catalog():
    try:
        settings = Settings()
    except ValidationError as exc:
        raise ServiceError(
            503, "invalid_configuration", "模型配置无效，请检查服务端设置。"
        ) from exc
    return ChatModelCatalog(
        configured=bool(settings.deepseek_api_key.get_secret_value().strip()),
        default_model=settings.deepseek_model,
        models=settings.available_models,
    )
