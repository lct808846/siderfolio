"""FastAPI 应用入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from astroagent import __version__
from astroagent.api.artifacts import router as artifacts_router
from astroagent.api.chat import router as chat_router
from astroagent.api.conversations import router as conversations_router
from astroagent.api.exports import ExportBodyLimit
from astroagent.api.exports import router as exports_router
from astroagent.api.health import router as health_router
from astroagent.api.projects import router as projects_router
from astroagent.api.workflows import router as workflows_router
from astroagent.artifacts import ArtifactCache
from astroagent.config import LocalSettings
from astroagent.conversation_service import ConversationService
from astroagent.conversations import ConversationRepository
from astroagent.errors import ServiceError
from astroagent.export_schemas import ExportRequest
from astroagent.local_access import LocalAccess
from astroagent.project_service import ProjectService
from astroagent.workflow_service import WorkflowService


@asynccontextmanager
async def lifespan(app):
    repository = None
    app.state.conversation_service = None
    try:
        settings = LocalSettings()
        repository = ConversationRepository(settings)
        repository.initialize()
        service = ConversationService(repository)
        ArtifactCache(service, settings)
        service.projects = ProjectService(service)
        service.workflows = WorkflowService(service)
        app.state.conversation_service = service
    except Exception:
        if repository is not None:
            repository.close()
    try:
        yield
    finally:
        app.state.conversation_service = None
        if repository is not None:
            repository.close()


app = FastAPI(title="AstroAgent", version=__version__, lifespan=lifespan)
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(exports_router)
app.include_router(conversations_router)
app.include_router(artifacts_router)
app.include_router(projects_router)
app.include_router(workflows_router)
app.add_middleware(ExportBodyLimit)
app.add_middleware(LocalAccess)


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
    if request.url.path.startswith(
        ("/api/v1/conversations", "/api/v1/artifacts", "/api/v1/projects")
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
