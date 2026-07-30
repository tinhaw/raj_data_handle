from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context
from packages.common.database import get_db_session
from packages.domain.schemas.withdraw_order import (
    WithdrawOperatorSummaryRequest,
    WithdrawOperatorSummaryResponse,
    WithdrawOrderQueryRequest,
    WithdrawOrderQueryResponse,
    WithdrawOrderRefreshRequest,
    WithdrawOrderRefreshResponse,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.source_service import SourceNotFoundError
from packages.domain.services.system_setting_service import SystemSettingsSchemaPendingError
from packages.domain.services.withdraw_order_refresh_service import (
    WithdrawOrderRefreshValidationError,
    queue_withdraw_order_refreshes,
)
from packages.domain.services.withdraw_order_service import (
    WithdrawOrderCacheSchemaPendingError,
    WithdrawOrderValidationError,
    query_withdraw_operator_summary,
    query_withdraw_orders,
)

router = APIRouter(prefix="/withdraw-orders", tags=["withdraw-orders"])


@router.post("/query", response_model=WithdrawOrderQueryResponse)
async def withdraw_order_query(
    payload: WithdrawOrderQueryRequest,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> WithdrawOrderQueryResponse:
    try:
        result = await query_withdraw_orders(session, request=payload)
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WithdrawOrderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (WithdrawOrderCacheSchemaPendingError, SystemSettingsSchemaPendingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return WithdrawOrderQueryResponse(
        items=result.items,
        total=result.total,
        remote_total=result.remote_total,
        page=payload.page,
        page_size=payload.page_size,
        fetched_pages=result.fetched_pages,
        complete=result.complete,
        source_id=result.source_id,
        source_display_name=result.source_display_name,
        business_timezone=result.business_timezone,
        currency=result.currency,
        effective_create_time_end=result.effective_create_time_end,
        fetched_at=result.fetched_at,
        local_updated_at=result.local_updated_at,
        last_refreshed_at=result.last_refreshed_at,
        refresh_status=result.refresh_status,
        status_dictionary=result.status_dictionary,
        summary=result.summary,
    )


@router.post("/operator-summary", response_model=WithdrawOperatorSummaryResponse)
async def withdraw_operator_summary(
    payload: WithdrawOperatorSummaryRequest,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> WithdrawOperatorSummaryResponse:
    """Return a paginated, local-only withdrawal aggregation by operator."""

    try:
        result = await query_withdraw_operator_summary(session, request=payload)
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WithdrawOrderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (WithdrawOrderCacheSchemaPendingError, SystemSettingsSchemaPendingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return WithdrawOperatorSummaryResponse(
        items=result.items,
        total=result.total,
        page=payload.page,
        page_size=payload.page_size,
        source_id=result.source_id,
        source_display_name=result.source_display_name,
        business_timezone=result.business_timezone,
        effective_create_time_end=result.effective_create_time_end,
        fetched_at=result.fetched_at,
        local_updated_at=result.local_updated_at,
        status_columns=result.status_columns,
        status_dictionary=result.status_dictionary,
        selected_order_total=result.selected_order_total,
    )


@router.post(
    "/refresh",
    response_model=WithdrawOrderRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_withdraw_order_refresh(
    payload: WithdrawOrderRefreshRequest = WithdrawOrderRefreshRequest(),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> WithdrawOrderRefreshResponse:
    """Queue a worker-owned read-only cache refresh without remote I/O in API."""

    try:
        result = await queue_withdraw_order_refreshes(
            session,
            source_id=payload.source_id,
            actor_user_id=auth.user.id,
        )
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WithdrawOrderRefreshValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WithdrawOrderCacheSchemaPendingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return WithdrawOrderRefreshResponse(
        status="queued",
        source_ids=result.source_ids,
        requested_at=result.requested_at,
        message=f"已提交 {len(result.source_ids)} 个盘口的后台同步任务。",
    )
