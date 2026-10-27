from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers.auth import router as auth_router
from .routers.profile import router as profile_router
from .routers.sources import router as sources_router

app = FastAPI(title="CV Applier")

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
    return {"status": "ok"}
