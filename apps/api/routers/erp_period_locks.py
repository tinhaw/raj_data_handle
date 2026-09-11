"""Local ERP accounting-period lock APIs with no remote side effects."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_erp_permission
from packages.common.database import get_db_session
from packages.domain.schemas.erp_period_lock import (
    ErpPeriodLockRequest,
    ErpPeriodLockResponse,
    ErpPeriodLockValidationResponse,
    ErpPeriodUnlockRequest,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.erp_access_service import (
    ERP_PERMISSION_LEDGER_VIEW,
    ERP_PERMISSION_PERIOD_LOCK,
    ErpScopePermissionError,
    assert_erp_operator_scope,
    resolve_erp_operator_scope,
)
from packages.domain.services.erp_operator_service import get_erp_operator_line
from packages.domain.services.erp_period_lock_service import (
    ErpPeriodLockConflictError,
    ErpPeriodLockError,
    ErpPeriodLockNotFoundError,
    list_erp_period_locks,
    lock_erp_period,
    unlock_erp_period,
    validate_erp_period_lock,
)

router = APIRouter(prefix="/erp/period-locks", tags=["erp-period-locks"])


def _api_error(exc: ErpPeriodLockError) -> HTTPException:
    if isinstance(exc, ErpPeriodLockNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ErpPeriodLockConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


async def _assert_request_scope(
    session: AsyncSession,
    *,
    user_id: int,
    request: ErpPeriodLockRequest,
) -> None:
    await resolve_erp_operator_scope(
        session, user_id=user_id, requested_operator_ids=request.operator_ids
    )
    for line_id in request.operator_line_ids:
        line = await get_erp_operator_line(session, line_id=line_id)
        await assert_erp_operator_scope(
            session, user_id=user_id, operator_id=line.operator_id
        )


@router.get("", response_model=list[ErpPeriodLockResponse])
async def get_period_locks(
    month: date,
    operator_ids: list[str] | None = None,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_LEDGER_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ErpPeriodLockResponse]:
    try:
        safe_ids = await resolve_erp_operator_scope(
            session, user_id=auth.user.id, requested_operator_ids=operator_ids
        )
    except ErpScopePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return await list_erp_period_locks(session, month=month, operator_ids=safe_ids)


@router.post("/validate", response_model=ErpPeriodLockValidationResponse)
async def post_validate_period_lock(
    payload: ErpPeriodLockRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_PERIOD_LOCK)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpPeriodLockValidationResponse:
    try:
        await _assert_request_scope(session, user_id=auth.user.id, request=payload)
        return await validate_erp_period_lock(session, request=payload)
    except ErpScopePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ErpPeriodLockError as exc:
        raise _api_error(exc) from exc


@router.post("/lock", response_model=list[ErpPeriodLockResponse])
async def post_lock_period(
    payload: ErpPeriodLockRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_PERIOD_LOCK)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ErpPeriodLockResponse]:
    try:
        await _assert_request_scope(session, user_id=auth.user.id, request=payload)
        return await lock_erp_period(session, request=payload, actor_user_id=auth.user.id)
    except ErpScopePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ErpPeriodLockError as exc:
        raise _api_error(exc) from exc


@router.post("/unlock", response_model=list[ErpPeriodLockResponse])
async def post_unlock_period(
    payload: ErpPeriodUnlockRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_PERIOD_LOCK)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ErpPeriodLockResponse]:
    try:
        await _assert_request_scope(session, user_id=auth.user.id, request=payload)
        return await unlock_erp_period(session, request=payload, actor_user_id=auth.user.id)
    except ErpScopePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ErpPeriodLockError as exc:
        raise _api_error(exc) from exc
