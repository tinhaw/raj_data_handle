"""Local ERP daily-ledger APIs with no remote business integration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_erp_permission
from packages.common.database import get_db_session
from packages.domain.models import ErpDailyBalance
from packages.domain.schemas.erp_balance import (
    ErpBalanceCalculationPreview,
    ErpBalanceImpactPreview,
    ErpDailyBalanceBatchRequest,
    ErpDailyBalanceListResponse,
    ErpDailyBalanceReopenRequest,
    ErpDailyBalanceResponse,
    ErpDailyBalanceWriteRequest,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.erp_access_service import (
    ERP_PERMISSION_LEDGER_CONFIRM,
    ERP_PERMISSION_LEDGER_REOPEN,
    ERP_PERMISSION_LEDGER_VIEW,
    ERP_PERMISSION_LEDGER_WRITE,
    ErpScopePermissionError,
    assert_erp_operator_scope,
)
from packages.domain.services.erp_balance_service import (
    ErpBalanceConflictError,
    ErpBalanceError,
    ErpBalanceNotFoundError,
    batch_erp_daily_balances,
    confirm_erp_daily_balance,
    create_erp_daily_balance,
    list_erp_daily_balances,
    preview_erp_daily_balance,
    preview_erp_daily_balance_impact,
    reopen_erp_daily_balance,
    update_erp_daily_balance,
)
from packages.domain.services.erp_operator_service import get_erp_operator_line

router = APIRouter(prefix="/erp/daily-balances", tags=["erp-balances"])


def _api_error(exc: ErpBalanceError | ErpScopePermissionError) -> HTTPException:
    if isinstance(exc, ErpScopePermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ErpBalanceNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ErpBalanceConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


async def _assert_line_scope(
    session: AsyncSession, *, user_id: int, line_id: str
) -> None:
    line = await get_erp_operator_line(session, line_id=line_id)
    await assert_erp_operator_scope(session, user_id=user_id, operator_id=line.operator_id)


async def _assert_balance_scope(
    session: AsyncSession, *, user_id: int, balance_id: str
) -> None:
    balance = await session.get(ErpDailyBalance, balance_id)
    if balance is None:
        raise ErpBalanceNotFoundError("日结记录不存在。")
    await _assert_line_scope(session, user_id=user_id, line_id=balance.operator_line_id)


@router.get("", response_model=ErpDailyBalanceListResponse)
async def get_daily_balances(
    operator_line_id: str,
    month: str,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_LEDGER_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDailyBalanceListResponse:
    try:
        await _assert_line_scope(session, user_id=auth.user.id, line_id=operator_line_id)
        return await list_erp_daily_balances(
            session,
            operator_line_id=operator_line_id,
            month=month,
        )
    except (ErpBalanceError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.post("/calculation-preview", response_model=ErpBalanceCalculationPreview)
async def post_calculation_preview(
    payload: ErpDailyBalanceWriteRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_LEDGER_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpBalanceCalculationPreview:
    try:
        await _assert_line_scope(session, user_id=auth.user.id, line_id=payload.operator_line_id)
        return await preview_erp_daily_balance(session, request=payload)
    except (ErpBalanceError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.post("/impact-preview", response_model=ErpBalanceImpactPreview)
async def post_impact_preview(
    payload: ErpDailyBalanceWriteRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_LEDGER_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpBalanceImpactPreview:
    try:
        await _assert_line_scope(session, user_id=auth.user.id, line_id=payload.operator_line_id)
        return await preview_erp_daily_balance_impact(session, request=payload)
    except (ErpBalanceError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.post("/batch", response_model=list[ErpDailyBalanceResponse])
async def post_daily_balance_batch(
    payload: ErpDailyBalanceBatchRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_LEDGER_WRITE)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ErpDailyBalanceResponse]:
    try:
        for record in payload.records:
            await _assert_line_scope(
                session, user_id=auth.user.id, line_id=record.operator_line_id
            )
        return await batch_erp_daily_balances(
            session,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except (ErpBalanceError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.post("", response_model=ErpDailyBalanceResponse, status_code=status.HTTP_201_CREATED)
async def post_daily_balance(
    payload: ErpDailyBalanceWriteRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_LEDGER_WRITE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDailyBalanceResponse:
    try:
        await _assert_line_scope(session, user_id=auth.user.id, line_id=payload.operator_line_id)
        return await create_erp_daily_balance(
            session,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except (ErpBalanceError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.put("/{balance_id}", response_model=ErpDailyBalanceResponse)
async def put_daily_balance(
    balance_id: str,
    payload: ErpDailyBalanceWriteRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_LEDGER_WRITE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDailyBalanceResponse:
    try:
        await _assert_balance_scope(session, user_id=auth.user.id, balance_id=balance_id)
        await _assert_line_scope(session, user_id=auth.user.id, line_id=payload.operator_line_id)
        return await update_erp_daily_balance(
            session,
            balance_id=balance_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except (ErpBalanceError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.post("/{balance_id}/confirm", response_model=ErpDailyBalanceResponse)
async def post_confirm_daily_balance(
    balance_id: str,
    row_version: int | None = None,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_LEDGER_CONFIRM)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDailyBalanceResponse:
    try:
        await _assert_balance_scope(session, user_id=auth.user.id, balance_id=balance_id)
        return await confirm_erp_daily_balance(
            session,
            balance_id=balance_id,
            row_version=row_version,
            actor_user_id=auth.user.id,
        )
    except (ErpBalanceError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc


@router.post("/{balance_id}/reopen", response_model=ErpDailyBalanceResponse)
async def post_reopen_daily_balance(
    balance_id: str,
    payload: ErpDailyBalanceReopenRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_LEDGER_REOPEN)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDailyBalanceResponse:
    try:
        await _assert_balance_scope(session, user_id=auth.user.id, balance_id=balance_id)
        return await reopen_erp_daily_balance(
            session,
            balance_id=balance_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except (ErpBalanceError, ErpScopePermissionError) as exc:
        raise _api_error(exc) from exc
