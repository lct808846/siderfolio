"""FastAPI 应用入口。"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from astroagent import __version__
from astroagent.api.chat import router as chat_router
from astroagent.api.health import router as health_router
from astroagent.errors import ServiceError

app = FastAPI(title="AstroAgent", version=__version__)
app.include_router(health_router)
app.include_router(chat_router)


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.error.model_dump()})
