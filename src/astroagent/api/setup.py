"""Secret-free setup state. Credentials remain in server environment variables."""

from fastapi import APIRouter, Request

from astroagent.api.admin import admin
from astroagent.api.auth import runtime, source
from astroagent.api.model_providers import writable
from astroagent.auth_store import AUTH_LOCK
from astroagent.config import LocalSettings, Settings
from astroagent.errors import ServiceError
from astroagent.execution import MODEL_TASK_SLOTS
from astroagent.mcp_client import (
    effective_astronomy_transport,
    get_mcp_runtime_status,
    set_persisted_astronomy_transport,
    switch_astronomy_transport,
    write_persisted_astronomy_transport,
)
from astroagent.postgres import SCHEMA_VERSION
from astroagent.rag_schemas import AstronomyTransportUpdate, Confirm, SetupStatus

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
        **get_mcp_runtime_status(local),
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


@router.put("/astronomy-transport", response_model=SetupStatus)
def update_astronomy_transport(request: Request, body: AstronomyTransportUpdate):
    user = admin(request)
    store = runtime(request).store
    store.rate("astronomy_transport", source(request), user["id"], limit=20)
    try:
        local, model = LocalSettings(), Settings()
    except Exception as exc:
        raise ServiceError(
            503, "setup_configuration_invalid", "服务端配置无效；错误详情不会向浏览器暴露凭据。"
        ) from exc

    acquired = 0
    try:
        while acquired < 2 and MODEL_TASK_SLOTS.acquire(blocking=False):
            acquired += 1
        if acquired < 2:
            raise ServiceError(
                409,
                "transport_switch_busy",
                "有请求正在处理，请等待完成后再切换天文查询通道。",
                retryable=True,
            )
        with store.connect() as db:
            writable(db, user)
        previous = effective_astronomy_transport(local)
        if body.transport == "mcp":
            switch_astronomy_transport(local, model, "mcp")
        try:
            with store.connect() as db:
                db.execute("SELECT pg_advisory_xact_lock(%s)", (AUTH_LOCK,))
                writable(db, user)
                write_persisted_astronomy_transport(db, body.transport)
                store.audit(
                    db,
                    user["id"],
                    "astronomy_transport_changed",
                    "ok",
                    reason=body.transport,
                )
        except Exception:
            if body.transport == "mcp":
                if previous == "direct":
                    switch_astronomy_transport(local, model, "direct")
                else:
                    set_persisted_astronomy_transport(previous)
            raise
        if body.transport == "direct":
            switch_astronomy_transport(local, model, "direct")
    finally:
        for _ in range(acquired):
            MODEL_TASK_SLOTS.release()
    return status(request)
