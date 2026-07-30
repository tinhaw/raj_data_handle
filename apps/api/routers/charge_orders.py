from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context
from packages.common.database import get_db_session
from packages.domain.schemas.charge_order import (
    ChargeChannelSummaryRequest,
    ChargeChannelSummaryResponse,
    ChargeOrderQueryRequest,
    ChargeOrderQueryResponse,
    ChargeOrderRefreshRequest,
    ChargeOrderRefreshResponse,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.charge_order_refresh_service import (
    ChargeOrderRefreshValidationError,
    queue_charge_order_refreshes,
)
from packages.domain.services.charge_order_service import (
    ChargeOrderCacheSchemaPendingError,
    ChargeOrderValidationError,
    query_charge_channel_summary,
    query_charge_orders,
)
from packages.domain.services.source_service import SourceNotFoundError
from packages.domain.services.system_setting_service import SystemSettingsSchemaPendingError

router = APIRouter(prefix="/charge-orders", tags=["charge-orders"])


@router.post("/query", response_model=ChargeOrderQueryResponse)
async def charge_order_query(
    payload: ChargeOrderQueryRequest,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> ChargeOrderQueryResponse:
    try:
        result = await query_charge_orders(session, request=payload)
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ChargeOrderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (ChargeOrderCacheSchemaPendingError, SystemSettingsSchemaPendingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return ChargeOrderQueryResponse(
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
        channel_dictionary=result.channel_dictionary,
        channel_name_dictionary=result.channel_name_dictionary,
        summary=result.summary,
    )


@router.post("/channel-summary", response_model=ChargeChannelSummaryResponse)
async def charge_channel_summary(
    payload: ChargeChannelSummaryRequest,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> ChargeChannelSummaryResponse:
    try:
        result = await query_charge_channel_summary(session, request=payload)
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ChargeOrderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (ChargeOrderCacheSchemaPendingError, SystemSettingsSchemaPendingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return ChargeChannelSummaryResponse(
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
    )


@router.post(
    "/refresh",
    response_model=ChargeOrderRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_charge_order_refresh(
    payload: ChargeOrderRefreshRequest = ChargeOrderRefreshRequest(),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> ChargeOrderRefreshResponse:
    try:
        result = await queue_charge_order_refreshes(
            session,
            source_id=payload.source_id,
            query_range=payload.query_range,
            actor_user_id=auth.user.id,
        )
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ChargeOrderRefreshValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ChargeOrderCacheSchemaPendingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return ChargeOrderRefreshResponse(
        status="queued",
        source_ids=result.source_ids,
        requested_at=result.requested_at,
        query_range=result.query_range,
        message=(
            f"已提交 {len(result.source_ids)} 个盘口的充值订单后台同步任务，将按所选时间范围刷新。"
            if result.query_range
            else f"已提交 {len(result.source_ids)} 个盘口的充值订单后台同步任务。"
        ),
    )
