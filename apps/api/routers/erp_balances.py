"""Local ERP daily-ledger APIs with no remote business integration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context, require_admin
from packages.common.database import get_db_session
from packages.domain.schemas.erp_balance import (
    ErpBalanceCalculationPreview,
    ErpDailyBalanceListResponse,
    ErpDailyBalanceResponse,
    ErpDailyBalanceWriteRequest,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.erp_balance_service import (
    ErpBalanceConflictError,
    ErpBalanceError,
    ErpBalanceNotFoundError,
    confirm_erp_daily_balance,
    create_erp_daily_balance,
    list_erp_daily_balances,
    preview_erp_daily_balance,
    update_erp_daily_balance,
)

router = APIRouter(prefix="/erp/daily-balances", tags=["erp-balances"])


def _api_error(exc: ErpBalanceError) -> HTTPException:
    if isinstance(exc, ErpBalanceNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ErpBalanceConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=ErpDailyBalanceListResponse)
async def get_daily_balances(
    operator_line_id: str,
    month: str,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDailyBalanceListResponse:
    try:
        return await list_erp_daily_balances(
            session,
            operator_line_id=operator_line_id,
            month=month,
        )
    except ErpBalanceError as exc:
        raise _api_error(exc) from exc


@router.post("/calculation-preview", response_model=ErpBalanceCalculationPreview)
async def post_calculation_preview(
    payload: ErpDailyBalanceWriteRequest,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> ErpBalanceCalculationPreview:
    try:
        return await preview_erp_daily_balance(session, request=payload)
    except ErpBalanceError as exc:
        raise _api_error(exc) from exc


@router.post("", response_model=ErpDailyBalanceResponse, status_code=status.HTTP_201_CREATED)
async def post_daily_balance(
    payload: ErpDailyBalanceWriteRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDailyBalanceResponse:
    try:
        return await create_erp_daily_balance(
            session,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except ErpBalanceError as exc:
        raise _api_error(exc) from exc


@router.put("/{balance_id}", response_model=ErpDailyBalanceResponse)
async def put_daily_balance(
    balance_id: str,
    payload: ErpDailyBalanceWriteRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDailyBalanceResponse:
    try:
        return await update_erp_daily_balance(
            session,
            balance_id=balance_id,
            request=payload,
            actor_user_id=auth.user.id,
        )
    except ErpBalanceError as exc:
        raise _api_error(exc) from exc


@router.post("/{balance_id}/confirm", response_model=ErpDailyBalanceResponse)
async def post_confirm_daily_balance(
    balance_id: str,
    row_version: int | None = None,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpDailyBalanceResponse:
    try:
        return await confirm_erp_daily_balance(
            session,
            balance_id=balance_id,
            row_version=row_version,
            actor_user_id=auth.user.id,
        )
    except ErpBalanceError as exc:
        raise _api_error(exc) from exc
