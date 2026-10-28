"""FastAPI 应用入口。"""

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from astroagent import __version__
from astroagent.api.chat import router as chat_router
from astroagent.api.exports import ExportBodyLimit
from astroagent.api.exports import router as exports_router
from astroagent.api.health import router as health_router
from astroagent.errors import ServiceError
from astroagent.export_schemas import ExportRequest

app = FastAPI(title="AstroAgent", version=__version__)
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(exports_router)
app.add_middleware(ExportBodyLimit)


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
    return JSONResponse(status_code=exc.status_code, content={"error": exc.error.model_dump()})
