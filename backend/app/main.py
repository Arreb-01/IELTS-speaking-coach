"""FastAPI 应用入口。

本地开发：
    cd backend
    uvicorn app.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.services.cache import close_cache, describe_backend, init_cache
from app.services.practice_engine import registry as practice_registry
from app.services.scoring.engine import (
    recover_stale_reports,
    start_stale_sweeper,
    stop_stale_sweeper,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_cache()
    practice_registry.start_sweeper()
    start_stale_sweeper()
    yield
    stop_stale_sweeper()
    practice_registry.stop_sweeper()
    await close_cache()


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get(f"{settings.api_v1_prefix}/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "cache": describe_backend(),
        "volc_mock": "on" if settings.volc_mock else "off",
    }
