"""Secret-free setup state. Credentials remain in server environment variables."""

from fastapi import APIRouter, Request

from astroagent.config import LocalSettings, Settings
from astroagent.errors import ServiceError
from astroagent.postgres import SCHEMA_VERSION
from astroagent.rag_schemas import Confirm, SetupStatus

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


@router.get("/status", response_model=SetupStatus)
def status(request: Request):
    try:
        local, model = LocalSettings(), Settings()
    except Exception as exc:
        raise ServiceError(
            503, "setup_configuration_invalid", "服务端配置无效；错误详情不会向浏览器暴露凭据。"
        ) from exc
    from astroagent.api.conversations import get_service

    service = get_service(request)
    from astroagent.model_providers import ProviderRegistry

    registry = ProviderRegistry(request.app.state.identity.store, model)
    catalog = registry.catalog()
    resolved = registry.resolve(catalog.default_model) if catalog.configured else None
    value = {
        "deployment_mode": local.deployment_mode,
        "configured": bool(local.database_url.get_secret_value()),
        "ready": service is not None,
        "code": "ready"
        if service
        else getattr(request.app.state, "storage_code", "database_not_configured"),
        "message": "PostgreSQL业务服务已就绪；此状态不验证外部科研服务或RAG回答质量。"
        if service
        else "请配置本机数据库并重启，再显式初始化；不会使用SQLite回退。",
        "business_budget_bytes": local.storage_bytes,
        "vector_budget_bytes": local.rag_vector_bytes,
        "embedding_configured": local.rag_model_path is not None and bool(local.rag_model_sha256),
        "embedding_model": local.rag_model_name,
        "embedding_dimension": local.rag_dimension,
        "answering_configured": catalog.configured,
        "answering_provider": str(resolved.deepseek_base_url) if resolved else "",
        "answering_model": catalog.default_model,
    }
    if service:
        with service.repository.connection() as db:
            value.update(
                database_schema=SCHEMA_VERSION,
                database_version=db.execute("SHOW server_version").fetchone()[0],
                vector_version=db.execute(
                    "SELECT extversion FROM pg_extension WHERE extname=?", ("vector",)
                ).fetchone()[0],
                database_used_bytes=service.repository._used(db),
            )
    return value


@router.post("/initialize", response_model=SetupStatus)
def initialize(request: Request, body: Confirm):
    # Global identity/legacy initialization is deliberately offline in V1.6.
    # This request only reports this authenticated user's already scoped service.
    if not body.confirmed:
        raise ServiceError(422, "setup_confirmation_required", "请确认初始化操作。")
    return status(request)
