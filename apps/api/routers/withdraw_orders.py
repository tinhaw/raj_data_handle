from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context
from packages.common.database import get_db_session
from packages.domain.schemas.withdraw_order import (
    WithdrawOrderQueryRequest,
    WithdrawOrderQueryResponse,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.remote_charge_service import RemoteChargeError
from packages.domain.services.source_service import SourceNotFoundError
from packages.domain.services.withdraw_order_service import (
    WithdrawOrderValidationError,
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
    except RemoteChargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
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
        status_dictionary=result.status_dictionary,
        summary=result.summary,
    )
