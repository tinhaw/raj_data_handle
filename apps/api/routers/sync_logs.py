"""Read-only API for operational data synchronization history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context
from packages.common.database import get_db_session
from packages.domain.schemas.sync_log import (
    SyncLogDetailResponse,
    SyncLogQueryRequest,
    SyncLogQueryResponse,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.data_sync_run_service import (
    DataSyncRunNotFoundError,
    DataSyncRunSchemaPendingError,
    get_sync_run_detail,
    query_sync_runs,
)

router = APIRouter(prefix="/sync-logs", tags=["sync-logs"])


@router.post("/query", response_model=SyncLogQueryResponse)
async def sync_log_query(
    payload: SyncLogQueryRequest,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> SyncLogQueryResponse:
    try:
        result = await query_sync_runs(session, request=payload)
    except DataSyncRunSchemaPendingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return SyncLogQueryResponse(
        items=result.items,
        total=result.total,
        page=payload.page,
        page_size=payload.page_size,
        summary=result.summary,
        trend=result.trend,
        generated_at=result.generated_at,
    )


@router.get("/{run_id}", response_model=SyncLogDetailResponse)
async def sync_log_detail(
    run_id: str,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> SyncLogDetailResponse:
    try:
        result = await get_sync_run_detail(session, run_id=run_id)
    except DataSyncRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DataSyncRunSchemaPendingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return SyncLogDetailResponse(run=result.run, events=result.events)
