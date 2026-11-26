"""FastAPI 应用入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from astroagent import __version__
from astroagent.api.admin import router as admin_router
from astroagent.api.artifacts import router as artifacts_router
from astroagent.api.attachments import router as attachments_router
from astroagent.api.auth import router as auth_router
from astroagent.api.chat import router as chat_router
from astroagent.api.compute import router as compute_router
from astroagent.api.compute import status_router as compute_status_router
from astroagent.api.conversations import router as conversations_router
from astroagent.api.exports import ExportBodyLimit
from astroagent.api.exports import router as exports_router
from astroagent.api.external_mcp import router as external_mcp_admin_router
from astroagent.api.feedback import admin_router as admin_feedback_router
from astroagent.api.feedback import router as feedback_router
from astroagent.api.health import router as health_router
from astroagent.api.knowledge import router as knowledge_router
from astroagent.api.links import router as links_router
from astroagent.api.literature import router as literature_router
from astroagent.api.local_titles import router as local_titles_router
from astroagent.api.model_providers import router as model_providers_router
from astroagent.api.models import router as models_router
from astroagent.api.plotting import router as plotting_router
from astroagent.api.profile import router as profile_router
from astroagent.api.projects import router as projects_router
from astroagent.api.rag import router as rag_router
from astroagent.api.setup import router as setup_router
from astroagent.api.skills import router as skills_router
from astroagent.api.workflows import router as workflows_router
from astroagent.auth_access import IdentityAccess
from astroagent.config import LocalSettings, Settings
from astroagent.errors import ServiceError
from astroagent.export_schemas import ExportRequest
from astroagent.knowledge_schemas import DocumentUpload
from astroagent.local_access import LocalAccess
from astroagent.mcp_client import (
    close_mcp_runtime,
    effective_astronomy_transport,
    initialize_mcp_runtime,
    load_persisted_astronomy_transport,
)


@asynccontextmanager
async def lifespan(app):
    app.state.conversation_service = None
    app.state.repository = None
    app.state.identity = None
    dispatcher = None
    local = None
    try:
        local = LocalSettings()
        from astroagent.identity import IdentityRuntime

        app.state.identity = IdentityRuntime(local)
    except Exception as exc:
        app.state.storage_code = (
            exc.error.code if isinstance(exc, ServiceError) else "database_configuration_invalid"
        )
    if app.state.identity is not None:
        try:
            load_persisted_astronomy_transport(app.state.identity.store)
        except Exception:
            pass
    if local is not None and effective_astronomy_transport(local) == "mcp":
        try:
            initialize_mcp_runtime(local, Settings())
        except Exception:
            pass
    try:
        from astroagent.compute_tasks import Dispatcher, enabled

        if app.state.identity is not None and enabled():
            dispatcher = Dispatcher(app.state.identity.store)
            dispatcher.start()
        yield
    finally:
        close_mcp_runtime()
        if dispatcher is not None:
            dispatcher.close()
        identity = app.state.identity
        if identity is not None:
            identity.close()
        app.state.identity = None


app = FastAPI(
    title="Siderfolio", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(model_providers_router)
app.include_router(admin_router)
app.include_router(external_mcp_admin_router)
app.include_router(admin_feedback_router)
app.include_router(feedback_router)
app.include_router(chat_router)
app.include_router(attachments_router)
app.include_router(exports_router)
app.include_router(conversations_router)
app.include_router(artifacts_router)
app.include_router(projects_router)
app.include_router(compute_status_router)
app.include_router(compute_router)
app.include_router(workflows_router)
app.include_router(knowledge_router)
app.include_router(links_router)
app.include_router(rag_router)
app.include_router(setup_router)
app.include_router(skills_router)
app.include_router(models_router)
app.include_router(plotting_router)
app.include_router(local_titles_router)
app.include_router(literature_router)
app.include_router(profile_router)
app.add_middleware(ExportBodyLimit)
app.add_middleware(LocalAccess)
app.add_middleware(IdentityAccess)


def export_openapi():
    if app.openapi_schema is None:
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        request_schema = ExportRequest.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        definitions = request_schema.pop("$defs", {})
        schema.setdefault("components", {}).setdefault("schemas", {}).update(definitions)
        schema["components"]["schemas"]["ExportRequest"] = request_schema
        schema["paths"]["/api/v1/exports"]["post"]["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ExportRequest"},
                }
            },
        }
        upload_schema = DocumentUpload.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        schema["components"]["schemas"].update(upload_schema.pop("$defs", {}))
        schema["components"]["schemas"]["DocumentUpload"] = upload_schema
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = export_openapi


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError):
    content = {"error": exc.error.model_dump()}
    for name in ("conversation_id", "turn_id"):
        if hasattr(exc, name):
            content[name] = getattr(exc, name)
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith(("/api/v1/feedback", "/api/v1/admin/feedback")):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_feedback_request",
                    "message": "反馈参数无效，请核对输入内容和长度。",
                    "retryable": False,
                }
            },
        )
    if request.url.path.startswith("/api/v1/admin/model-providers"):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_provider_request",
                    "message": "模型服务参数无效，请核对地址、密钥格式及模型 ID。",
                    "retryable": False,
                }
            },
        )
    if request.url.path.startswith("/api/v1/skills"):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_skill_request",
                    "message": "技能配置参数无效，请核对输入。",
                    "retryable": False,
                }
            },
        )
    if request.url.path.startswith("/api/v1/admin/mcp"):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_mcp_admin_request",
                    "message": "外部 MCP 管理参数无效，请核对输入。",
                    "retryable": False,
                }
            },
        )
    if request.url.path.startswith(("/api/v1/auth/", "/api/v1/admin/")):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_identity_request",
                    "message": "身份请求参数无效，请核对输入。",
                    "retryable": False,
                }
            },
        )
    if request.url.path.startswith("/api/v1/literature"):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_literature_request",
                    "message": "文献请求参数无效，请核对条目编号、标签或备注。",
                    "retryable": False,
                }
            },
        )
    if request.url.path.startswith(
        (
            "/api/v1/conversations",
            "/api/v1/artifacts",
            "/api/v1/projects",
            "/api/v1/setup",
            "/api/v1/local-titles",
            "/api/v1/profile",
        )
    ):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_project_request"
                    if request.url.path.startswith("/api/v1/projects")
                    else "invalid_conversation_request",
                    "message": "项目请求参数无效。"
                    if request.url.path.startswith("/api/v1/projects")
                    else "会话请求参数无效。",
                    "retryable": False,
                }
            },
        )
    from fastapi.exception_handlers import request_validation_exception_handler

    return await request_validation_exception_handler(request, exc)
