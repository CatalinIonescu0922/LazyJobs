from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .config import settings
from .logging import logger
from .routers.auth import router as auth_router
from .routers.profile import router as profile_router
from .routers.sources import router as sources_router

app = FastAPI(title="CV Applier")


@app.middleware("http")
async def log_requests(request: Request, call_next) -> Response:
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled request error: %s %s", request.method, request.url.path)
        raise
    logger.info("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(sources_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    logger.debug("Health check requested")
    return {"status": "ok"}
