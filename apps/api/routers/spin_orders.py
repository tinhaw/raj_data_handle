from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context
from packages.common.database import get_db_session
from packages.domain.schemas.spin_order import (
    SpinChannelSummaryRequest,
    SpinChannelSummaryResponse,
    SpinOrderQueryRequest,
    SpinOrderQueryResponse,
    SpinOrderRefreshRequest,
    SpinOrderRefreshResponse,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.source_service import SourceNotFoundError
from packages.domain.services.spin_order_refresh_service import (
    SpinOrderRefreshValidationError,
    queue_spin_order_refreshes,
)
from packages.domain.services.spin_order_service import (
    SpinOrderCacheSchemaPendingError,
    SpinOrderValidationError,
    query_spin_channel_summary,
    query_spin_orders,
)
from packages.domain.services.system_setting_service import SystemSettingsSchemaPendingError

router = APIRouter(prefix="/spin-orders", tags=["spin-orders"])


@router.post("/query", response_model=SpinOrderQueryResponse)
async def spin_order_query(
    payload: SpinOrderQueryRequest,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> SpinOrderQueryResponse:
    try:
        result = await query_spin_orders(session, request=payload)
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SpinOrderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (SpinOrderCacheSchemaPendingError, SystemSettingsSchemaPendingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return SpinOrderQueryResponse(
        items=result.items,
        total=result.total,
        page=payload.page,
        page_size=payload.page_size,
        source_id=result.source_id,
        source_display_name=result.source_display_name,
        business_timezone=result.business_timezone,
        fetched_at=result.fetched_at,
        local_updated_at=result.local_updated_at,
        last_refreshed_at=result.last_refreshed_at,
        refresh_status=result.refresh_status,
        remote_total=result.remote_total,
        fetched_pages=result.fetched_pages,
        complete=result.complete,
        resolved_uid_count=result.resolved_uid_count,
        unresolved_uid_count=result.unresolved_uid_count,
        status_dictionary=result.status_dictionary,
        channel_dictionary=result.channel_dictionary,
        summary=result.summary,
    )


@router.post("/channel-summary", response_model=SpinChannelSummaryResponse)
async def spin_channel_summary(
    payload: SpinChannelSummaryRequest,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> SpinChannelSummaryResponse:
    try:
        result = await query_spin_channel_summary(session, request=payload)
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SpinOrderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (SpinOrderCacheSchemaPendingError, SystemSettingsSchemaPendingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return SpinChannelSummaryResponse(
        items=result.items,
        total=result.total,
        page=payload.page,
        page_size=payload.page_size,
        source_id=result.source_id,
        source_display_name=result.source_display_name,
        business_timezone=result.business_timezone,
        fetched_at=result.fetched_at,
        local_updated_at=result.local_updated_at,
        channel_dictionary=result.channel_dictionary,
        time_series=result.time_series,
    )


@router.post(
    "/refresh",
    response_model=SpinOrderRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_spin_order_refresh(
    payload: SpinOrderRefreshRequest = SpinOrderRefreshRequest(),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> SpinOrderRefreshResponse:
    """Queue a worker-owned refresh; this web request never reads remote orders."""

    try:
        result = await queue_spin_order_refreshes(
            session,
            source_id=payload.source_id,
            query_range=payload.query_range,
            actor_user_id=auth.user.id,
        )
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SpinOrderRefreshValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SpinOrderRefreshResponse(
        status="queued",
        source_ids=result.source_ids,
        requested_at=result.requested_at,
        query_range=result.query_range,
        message=f"已提交 {len(result.source_ids)} 个盘口的转盘订单同步任务。",
    )
