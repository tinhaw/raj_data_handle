"""Administrative local APIs for the unified remote-account registry."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_erp_permission
from packages.common.database import get_db_session
from packages.domain.schemas.remote_account import (
    RemoteAccountCapabilityUpdateRequest,
    RemoteAccountCreateRequest,
    RemoteAccountPatchRequest,
    RemoteAccountResponse,
    RemoteTagSnapshotResponse,
    RemoteTagSnapshotWrite,
    RewardTierPresetResponse,
    RewardTierPresetWrite,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.erp_access_service import (
    ERP_PERMISSION_REDEMPTION_VIEW,
    ERP_PERMISSION_REMOTE_ACCOUNT_MANAGE,
)
from packages.domain.services.remote_account_service import (
    RemoteAccountError,
    RemoteAccountNotFoundError,
    RemoteAccountView,
    capability_definitions,
    create_remote_account,
    get_remote_tag_snapshot,
    get_reward_tier_preset,
    list_remote_accounts,
    save_remote_tag_snapshot,
    save_reward_tier_preset,
    update_remote_account,
    update_remote_account_capabilities,
)

router = APIRouter(prefix="/erp/remote-accounts", tags=["erp-remote-accounts"])


def _response(item: RemoteAccountView) -> RemoteAccountResponse:
    account = item.account
    source = item.source
    is_legacy = account.credential_mode == "LEGACY_SOURCE"
    return RemoteAccountResponse(
        id=account.id,
        source_id=account.source_id,
        source_display_name=source.display_name,
        source_base_url=source.base_url,
        source_enabled=source.enabled,
        login_username=account.login_username,
        display_name=account.display_name,
        enabled=account.enabled,
        credential_mode=account.credential_mode,
        credential_configured=(
            bool(source.encrypted_credentials) if is_legacy else bool(account.encrypted_credentials)
        ),
        credential_updated_at=(
            source.credential_updated_at if is_legacy else account.credential_updated_at
        ),
        last_tested_at=account.last_tested_at,
        last_test_status=account.last_test_status,
        capabilities=item.capabilities,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


@router.get("/capabilities")
async def get_capabilities(
    _: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REMOTE_ACCOUNT_MANAGE)),
) -> list[dict[str, str]]:
    return capability_definitions()


@router.get("", response_model=list[RemoteAccountResponse])
async def get_remote_accounts(
    _: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REDEMPTION_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> list[RemoteAccountResponse]:
    return [_response(item) for item in await list_remote_accounts(session)]


@router.post("", response_model=RemoteAccountResponse, status_code=status.HTTP_201_CREATED)
async def post_remote_account(
    payload: RemoteAccountCreateRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REMOTE_ACCOUNT_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> RemoteAccountResponse:
    try:
        return _response(
            await create_remote_account(session, request=payload, actor_user_id=auth.user.id)
        )
    except RemoteAccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{account_id}", response_model=RemoteAccountResponse)
async def patch_remote_account(
    account_id: str,
    payload: RemoteAccountPatchRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REMOTE_ACCOUNT_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> RemoteAccountResponse:
    try:
        return _response(
            await update_remote_account(
                session,
                account_id=account_id,
                request=payload,
                actor_user_id=auth.user.id,
            )
        )
    except RemoteAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RemoteAccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/{account_id}/capabilities", response_model=RemoteAccountResponse)
async def put_remote_account_capabilities(
    account_id: str,
    payload: RemoteAccountCapabilityUpdateRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REMOTE_ACCOUNT_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> RemoteAccountResponse:
    try:
        return _response(
            await update_remote_account_capabilities(
                session,
                account_id=account_id,
                request=payload,
                actor_user_id=auth.user.id,
            )
        )
    except RemoteAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RemoteAccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{account_id}/tags", response_model=RemoteTagSnapshotResponse)
async def get_account_tags(
    account_id: str,
    _: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REDEMPTION_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> RemoteTagSnapshotResponse:
    try:
        return await get_remote_tag_snapshot(session, account_id=account_id)
    except RemoteAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{account_id}/tags/snapshot", response_model=RemoteTagSnapshotResponse)
async def put_account_tag_snapshot(
    account_id: str,
    payload: RemoteTagSnapshotWrite,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REMOTE_ACCOUNT_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> RemoteTagSnapshotResponse:
    try:
        return await save_remote_tag_snapshot(
            session, account_id=account_id, request=payload, actor_user_id=auth.user.id
        )
    except RemoteAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RemoteAccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{account_id}/reward-tier-preset", response_model=RewardTierPresetResponse)
async def get_account_reward_tier_preset(
    account_id: str,
    _: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REDEMPTION_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> RewardTierPresetResponse:
    try:
        return await get_reward_tier_preset(session, account_id=account_id)
    except RemoteAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{account_id}/reward-tier-preset", response_model=RewardTierPresetResponse)
async def put_account_reward_tier_preset(
    account_id: str,
    payload: RewardTierPresetWrite,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REMOTE_ACCOUNT_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> RewardTierPresetResponse:
    try:
        return await save_reward_tier_preset(
            session, account_id=account_id, request=payload, actor_user_id=auth.user.id
        )
    except RemoteAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RemoteAccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
