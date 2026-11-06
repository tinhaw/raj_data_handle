"""Read-only local ERP workbench API."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_erp_permission
from packages.common.database import get_db_session
from packages.domain.schemas.erp_dashboard import ErpDashboardResponse
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.erp_access_service import (
    ERP_PERMISSION_WORKSPACE_VIEW,
    resolve_erp_operator_scope,
)
from packages.domain.services.erp_dashboard_service import build_erp_dashboard

router = APIRouter(prefix="/erp/dashboard", tags=["erp-dashboard"])


@router.get("", response_model=ErpDashboardResponse)
async def get_erp_dashboard(
    business_date: date | None = None,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_WORKSPACE_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDashboardResponse:
    return await build_erp_dashboard(
        session,
        business_date=business_date or date.today(),
        operator_ids=await resolve_erp_operator_scope(session, user_id=auth.user.id),
    )
