"""Secret-free setup state. Credentials remain in server environment variables."""

import threading

from fastapi import APIRouter, Request

from astroagent.config import LocalSettings, Settings
from astroagent.errors import ServiceError
from astroagent.postgres import SCHEMA_VERSION, PostgresRepository
from astroagent.rag_schemas import Confirm, SetupStatus

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])
LOCK = threading.Lock()


@router.get("/status", response_model=SetupStatus)
def status(request: Request):
    try:
        local, model = LocalSettings(), Settings()
    except Exception as exc:
        raise ServiceError(
            503, "setup_configuration_invalid", "服务端配置无效；错误详情不会向浏览器暴露凭据。"
        ) from exc
    service = getattr(request.app.state, "conversation_service", None)
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
        "answering_configured": bool(model.deepseek_api_key.get_secret_value()),
        "answering_provider": str(model.deepseek_base_url).split("@").pop().split("?")[0],
        "answering_model": model.deepseek_model,
    }
    if service:
        with service.repository.connection() as db:
            value.update(
                database_schema=SCHEMA_VERSION,
                database_version=db.execute("SHOW server_version").fetchone()[0],
                vector_version=db.execute(
                    "SELECT extversion FROM pg_extension WHERE extname='vector'"
                ).fetchone()[0],
                database_used_bytes=service.repository._used(db),
            )
    return value


@router.post("/initialize", response_model=SetupStatus)
def initialize(request: Request, body: Confirm):
    if not body.confirmed:
        raise ServiceError(
            422, "setup_confirmation_required", "请确认在已配置的空数据库创建业务表与扩展。"
        )
    if not LOCK.acquire(blocking=False):
        raise ServiceError(409, "setup_busy", "初始化正在进行，请读取状态。")
    repository = None
    try:
        if getattr(request.app.state, "conversation_service", None) is None:
            from astroagent.services import compose

            settings = LocalSettings()
            repository = PostgresRepository(settings)
            repository.initialize(create=True)
            request.app.state.conversation_service = compose(repository, settings)
            request.app.state.repository = repository
        return status(request)
    except BaseException:
        if repository:
            repository.close()
            request.app.state.conversation_service = None
            request.app.state.repository = None
        raise
    finally:
        LOCK.release()
