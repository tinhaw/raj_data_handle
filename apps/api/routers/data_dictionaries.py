from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_admin
from packages.common.database import get_db_session
from packages.domain.schemas.data_dictionary import (
    ChargeStatusCreateRequest,
    ChargeStatusPatchRequest,
    DataDictionaryEntryResponse,
    UserSourceChannelSyncResponse,
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
    create_charge_status,
    create_withdraw_status,
    list_charge_statuses,
    list_payment_channel_names,
    list_payment_channels,
    list_spin_order_statuses,
    list_user_source_channels,
    list_withdraw_statuses,
    sync_remote_user_source_channels,
    sync_remote_withdraw_statuses,
    update_charge_status,
    update_withdraw_status,
)

router = APIRouter(tags=["data-dictionaries"])


@router.get(
    "/settings/data-dictionaries/spin-order-statuses",
    response_model=list[DataDictionaryEntryResponse],
)
async def spin_order_statuses(
    source_id: str | None = None,
    active: bool | None = None,
    _: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[DataDictionaryEntryResponse]:
    return await list_spin_order_statuses(session, source_id=source_id, active=active)


@router.get(
    "/settings/data-dictionaries/user-source-channels",
    response_model=list[DataDictionaryEntryResponse],
)
async def user_source_channels(
    source_id: str | None = None,
    active: bool | None = None,
    _: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[DataDictionaryEntryResponse]:
    return await list_user_source_channels(session, source_id=source_id, active=active)


@router.post(
    "/settings/data-dictionaries/user-source-channels/refresh",
    response_model=UserSourceChannelSyncResponse,
)
async def refresh_user_source_channels(
    payload: WithdrawStatusSyncRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> UserSourceChannelSyncResponse:
    try:
        result = await sync_remote_user_source_channels(
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
    return UserSourceChannelSyncResponse(
        source_id=result.source_id,
        source_display_name=result.source_display_name,
        fetched_at=result.fetched_at,
        remote_total=result.remote_total,
        replaced_entries=result.replaced_entries,
        entries=result.entries,
    )


@router.get(
    "/settings/data-dictionaries/charge-statuses",
    response_model=list[DataDictionaryEntryResponse],
)
async def charge_statuses(
    source_id: str | None = None,
    active: bool | None = None,
    _: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[DataDictionaryEntryResponse]:
    return await list_charge_statuses(
        session,
        source_id=source_id,
        active=active,
    )


@router.post(
    "/settings/data-dictionaries/charge-statuses",
    response_model=DataDictionaryEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_charge_status_entry(
    payload: ChargeStatusCreateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> DataDictionaryEntryResponse:
    try:
        return await create_charge_status(
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
    "/settings/data-dictionaries/charge-statuses/{entry_id}",
    response_model=DataDictionaryEntryResponse,
)
async def update_charge_status_entry(
    entry_id: int,
    payload: ChargeStatusPatchRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> DataDictionaryEntryResponse:
    try:
        return await update_charge_status(
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


@router.get(
    "/settings/data-dictionaries/payment-channels",
    response_model=list[DataDictionaryEntryResponse],
)
async def payment_channels(
    source_id: str | None = None,
    active: bool | None = None,
    _: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[DataDictionaryEntryResponse]:
    return await list_payment_channels(
        session,
        source_id=source_id,
        active=active,
    )


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
