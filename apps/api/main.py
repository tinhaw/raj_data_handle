from __future__ import annotations

import re
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers.auth import router as auth_router
from apps.api.routers.batches import router as batches_router
from apps.api.routers.charge_orders import router as charge_orders_router
from apps.api.routers.data_dictionaries import router as data_dictionaries_router
from apps.api.routers.erp_access import router as erp_access_router
from apps.api.routers.erp_audit import router as erp_audit_router
from apps.api.routers.erp_balances import router as erp_balances_router
from apps.api.routers.erp_dashboard import router as erp_dashboard_router
from apps.api.routers.erp_imports import router as erp_imports_router
from apps.api.routers.erp_operators import router as erp_operators_router
from apps.api.routers.erp_period_locks import router as erp_period_locks_router
from apps.api.routers.erp_redemption import router as erp_redemption_router
from apps.api.routers.erp_reports import router as erp_reports_router
from apps.api.routers.notifications import router as notifications_router
from apps.api.routers.payment_templates import router as payment_templates_router
from apps.api.routers.remote_accounts import router as remote_accounts_router
from apps.api.routers.sources import router as sources_router
from apps.api.routers.spin_orders import router as spin_orders_router
from apps.api.routers.sync_logs import router as sync_logs_router
from apps.api.routers.system_settings import router as system_settings_router
from apps.api.routers.totp_codes import router as totp_codes_router
from apps.api.routers.withdraw_orders import router as withdraw_orders_router
from packages.common.request_context import reset_request_id, set_request_id
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


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    supplied = request.headers.get("X-Request-Id", "").strip()
    request_id = supplied if re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", supplied) else uuid.uuid4().hex
    token = set_request_id(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response
    finally:
        reset_request_id(token)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(sources_router, prefix=settings.api_prefix)
app.include_router(system_settings_router, prefix=settings.api_prefix)
app.include_router(totp_codes_router, prefix=settings.api_prefix)
app.include_router(data_dictionaries_router, prefix=settings.api_prefix)
app.include_router(erp_access_router, prefix=settings.api_prefix)
app.include_router(erp_audit_router, prefix=settings.api_prefix)
app.include_router(erp_operators_router, prefix=settings.api_prefix)
app.include_router(erp_period_locks_router, prefix=settings.api_prefix)
app.include_router(erp_dashboard_router, prefix=settings.api_prefix)
app.include_router(erp_balances_router, prefix=settings.api_prefix)
app.include_router(erp_imports_router, prefix=settings.api_prefix)
app.include_router(erp_reports_router, prefix=settings.api_prefix)
app.include_router(erp_redemption_router, prefix=settings.api_prefix)
app.include_router(remote_accounts_router, prefix=settings.api_prefix)
app.include_router(payment_templates_router, prefix=settings.api_prefix)
app.include_router(batches_router, prefix=settings.api_prefix)
app.include_router(notifications_router, prefix=settings.api_prefix)
app.include_router(withdraw_orders_router, prefix=settings.api_prefix)
app.include_router(charge_orders_router, prefix=settings.api_prefix)
app.include_router(spin_orders_router, prefix=settings.api_prefix)
app.include_router(sync_logs_router, prefix=settings.api_prefix)


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": settings.api_title, "version": settings.api_version}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
