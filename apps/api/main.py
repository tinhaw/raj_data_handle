from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers.auth import router as auth_router
from apps.api.routers.batches import router as batches_router
from apps.api.routers.data_dictionaries import router as data_dictionaries_router
from apps.api.routers.notifications import router as notifications_router
from apps.api.routers.payment_templates import router as payment_templates_router
from apps.api.routers.sources import router as sources_router
from apps.api.routers.system_settings import router as system_settings_router
from apps.api.routers.withdraw_orders import router as withdraw_orders_router
from packages.common.settings import get_settings
from packages.storage import LocalFileStorage

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.file_storage = LocalFileStorage(
        settings.storage_root,
        settings.upload_max_bytes,
    )
    yield


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(sources_router, prefix=settings.api_prefix)
app.include_router(system_settings_router, prefix=settings.api_prefix)
app.include_router(data_dictionaries_router, prefix=settings.api_prefix)
app.include_router(payment_templates_router, prefix=settings.api_prefix)
app.include_router(batches_router, prefix=settings.api_prefix)
app.include_router(notifications_router, prefix=settings.api_prefix)
app.include_router(withdraw_orders_router, prefix=settings.api_prefix)


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": settings.api_title, "version": settings.api_version}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
