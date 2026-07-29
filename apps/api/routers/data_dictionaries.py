from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_admin
from packages.common.database import get_db_session
from packages.domain.schemas.data_dictionary import (
    DataDictionaryEntryResponse,
    WithdrawStatusCreateRequest,
    WithdrawStatusPatchRequest,
    WithdrawStatusSyncRequest,
    WithdrawStatusSyncResponse,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.data_dictionary_service import (
    DataDictionaryConflictError,
    DataDictionaryNotFoundError,
    DataDictionaryRemoteSyncError,
    DataDictionaryValidationError,
    create_withdraw_status,
    list_payment_channel_names,
    list_withdraw_statuses,
    sync_remote_withdraw_statuses,
    update_withdraw_status,
)

router = APIRouter(tags=["data-dictionaries"])


@router.get(
    "/settings/data-dictionaries/payment-channel-names",
    response_model=list[DataDictionaryEntryResponse],
)
async def payment_channel_names(
    source_id: str | None = None,
    active: bool | None = None,
    _: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[DataDictionaryEntryResponse]:
    return await list_payment_channel_names(
        session,
        source_id=source_id,
        active=active,
    )


@router.get(
    "/settings/data-dictionaries/withdraw-statuses",
    response_model=list[DataDictionaryEntryResponse],
)
async def withdraw_statuses(
    source_id: str | None = None,
    active: bool | None = None,
    _: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[DataDictionaryEntryResponse]:
    return await list_withdraw_statuses(
        session,
        source_id=source_id,
        active=active,
    )


@router.post(
    "/settings/data-dictionaries/withdraw-statuses/sync",
    response_model=WithdrawStatusSyncResponse,
)
async def sync_withdraw_status_entries(
    payload: WithdrawStatusSyncRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> WithdrawStatusSyncResponse:
    try:
        result = await sync_remote_withdraw_statuses(
            session,
            source_id=payload.source_id,
            actor_user_id=auth.user.id,
        )
    except DataDictionaryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DataDictionaryRemoteSyncError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except DataDictionaryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return WithdrawStatusSyncResponse(
        source_id=result.source_id,
        source_display_name=result.source_display_name,
        fetched_at=result.fetched_at,
        remote_total=result.remote_total,
        created_entries=result.created_entries,
        refreshed_entries=result.refreshed_entries,
        entries=result.entries,
    )


@router.post(
    "/settings/data-dictionaries/withdraw-statuses",
    response_model=DataDictionaryEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_withdraw_status_entry(
    payload: WithdrawStatusCreateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> DataDictionaryEntryResponse:
    try:
        return await create_withdraw_status(
            session,
            source_id=payload.source_id,
            entry_code=payload.entry_code,
            entry_label=payload.entry_label,
            active=payload.active,
            actor_user_id=auth.user.id,
        )
    except DataDictionaryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DataDictionaryConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DataDictionaryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch(
    "/settings/data-dictionaries/withdraw-statuses/{entry_id}",
    response_model=DataDictionaryEntryResponse,
)
async def update_withdraw_status_entry(
    entry_id: int,
    payload: WithdrawStatusPatchRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> DataDictionaryEntryResponse:
    try:
        return await update_withdraw_status(
            session,
            entry_id=entry_id,
            entry_label=payload.entry_label,
            active=payload.active,
            actor_user_id=auth.user.id,
        )
    except DataDictionaryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DataDictionaryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
