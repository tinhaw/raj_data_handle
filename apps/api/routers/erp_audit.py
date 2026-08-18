"""Local ERP audit-log API; never exposes remote credentials or actions."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_erp_permission
from packages.common.database import get_db_session
from packages.domain.schemas.erp_audit import ErpAuditLogList
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.erp_access_service import (
    ERP_PERMISSION_AUDIT_VIEW,
    ErpScopePermissionError,
    assert_erp_operator_scope,
    resolve_erp_operator_scope,
)
from packages.domain.services.erp_audit_service import list_erp_audit_logs

router = APIRouter(prefix="/erp/audit-logs", tags=["erp-audit"])


@router.get("", response_model=ErpAuditLogList)
async def get_erp_audit_logs(
    date_from: date | None = None,
    date_to: date | None = None,
    action: str | None = None,
    operator_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_AUDIT_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpAuditLogList:
    if page < 1 or page_size < 1 or page_size > 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="分页参数不合法。",
        )
    try:
        if operator_id:
            await assert_erp_operator_scope(
                session, user_id=auth.user.id, operator_id=operator_id
            )
        return await list_erp_audit_logs(
            session,
            date_from=date_from,
            date_to=date_to,
            action=action,
            operator_ids=await resolve_erp_operator_scope(session, user_id=auth.user.id),
            operator_id=operator_id,
            page=page,
            page_size=page_size,
        )
    except ErpScopePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
