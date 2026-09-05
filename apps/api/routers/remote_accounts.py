"""Administrative local APIs for the unified remote-account registry."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_erp_permission
from packages.common.database import get_db_session
from packages.common.settings import get_settings
from packages.domain.models import RemoteAccountTagSnapshot, SourceConfig
from packages.domain.schemas.remote_account import (
    ErpCompatibilityRemoteConnection,
    ErpCompatibilityRemoteCreateRequest,
    ErpCompatibilityRemoteCreateResponse,
    ErpCompatibilityRemoteDownloadRequest,
    ErpCompatibilityRemoteDownloadResponse,
    ErpCompatibilityRemoteMarket,
    ErpCompatibilityRemotePublishRequest,
    ErpCompatibilityRemotePublishResponse,
    ErpCompatibilityRemoteRegistry,
    RemoteAccountCapabilityUpdateRequest,
    RemoteAccountCreateRequest,
    RemoteAccountPatchRequest,
    RemoteAccountResponse,
    RemoteTagSnapshotResponse,
    RemoteTagSnapshotWrite,
    RemoteTagSyncRequest,
    RewardTierPresetResponse,
    RewardTierPresetWrite,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.erp_access_service import (
    ERP_PERMISSION_REDEMPTION_GENERATE,
    ERP_PERMISSION_REDEMPTION_VIEW,
    ERP_PERMISSION_REMOTE_ACCOUNT_MANAGE,
)
from packages.domain.services.erp_compatibility_id_service import (
    ErpCompatibilityIdError,
    get_erp_compatibility_ids,
)
from packages.domain.services.erp_compatibility_redemption_remote_service import (
    ErpCompatibilityRemoteExecutionError,
    execute_compatibility_remote_create,
    execute_compatibility_remote_download,
    execute_compatibility_remote_publish,
)
from packages.domain.services.erp_remote_account_tag_service import (
    RemoteAccountTagSyncError,
    sync_remote_account_tags,
)
from packages.domain.services.remote_account_service import (
    RemoteAccountError,
    RemoteAccountNotFoundError,
    RemoteAccountView,
    capability_definitions,
    create_remote_account,
    delete_legacy_remote_account,
    get_remote_tag_snapshot,
    get_reward_tier_preset,
    list_remote_accounts,
    save_remote_tag_snapshot,
    save_reward_tier_preset,
    update_remote_account,
    update_remote_account_capabilities,
)
from packages.domain.services.source_service import list_sources

router = APIRouter(prefix="/erp/remote-accounts", tags=["erp-remote-accounts"])


def _credential_configured(item: RemoteAccountView) -> bool:
    return (
        bool(item.source.encrypted_credentials)
        if item.account.credential_mode == "LEGACY_SOURCE"
        else bool(item.account.encrypted_credentials)
    )


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
        is_default=account.is_default,
        credential_mode=account.credential_mode,
        credential_configured=_credential_configured(item),
        credential_updated_at=(
            source.credential_updated_at if is_legacy else account.credential_updated_at
        ),
        last_tested_at=account.last_tested_at,
        last_test_status=account.last_test_status,
        capabilities=item.capabilities,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


@router.post(
    "/compatibility-redemption/create",
    response_model=ErpCompatibilityRemoteCreateResponse,
    include_in_schema=False,
)
async def post_compatibility_redemption_create(
    payload: ErpCompatibilityRemoteCreateRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REDEMPTION_GENERATE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpCompatibilityRemoteCreateResponse:
    """Execute one confirmed creation through the unified account executor.

    This private facade accepts only the secret-free Java compatibility
    projection and forwards no credentials back across the service boundary.
    """

    try:
        result = await execute_compatibility_remote_create(
            session,
            payload=payload,
            actor_user_id=auth.user.id,
            settings=get_settings(),
        )
    except ErpCompatibilityRemoteExecutionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ErpCompatibilityRemoteCreateResponse(
        remote_configuration_id=result.remote_configuration_id,
        remote_group_key=result.remote_group_key,
        remote_request_id=result.remote_request_id,
    )


@router.post(
    "/compatibility-redemption/publish",
    response_model=ErpCompatibilityRemotePublishResponse,
    include_in_schema=False,
)
async def post_compatibility_redemption_publish(
    payload: ErpCompatibilityRemotePublishRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REDEMPTION_GENERATE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpCompatibilityRemotePublishResponse:
    """Publish through the same unified account boundary used by creation."""

    try:
        result = await execute_compatibility_remote_publish(
            session,
            payload=payload,
            actor_user_id=auth.user.id,
            settings=get_settings(),
        )
    except ErpCompatibilityRemoteExecutionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ErpCompatibilityRemotePublishResponse(
        remote_publish_task_id=result.remote_publish_task_id,
        remote_request_id=result.remote_request_id,
    )


@router.post(
    "/compatibility-redemption/download",
    response_model=ErpCompatibilityRemoteDownloadResponse,
    include_in_schema=False,
)
async def post_compatibility_redemption_download(
    payload: ErpCompatibilityRemoteDownloadRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REDEMPTION_GENERATE)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpCompatibilityRemoteDownloadResponse:
    try:
        result = await execute_compatibility_remote_download(
            session,
            payload=payload,
            actor_user_id=auth.user.id,
            settings=get_settings(),
        )
    except ErpCompatibilityRemoteExecutionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ErpCompatibilityRemoteDownloadResponse(
        redemption_codes=result.redemption_code.splitlines(),
        remote_group_key=result.remote_group_key,
    )


def _compatibility_registry(
    items: list[RemoteAccountView],
    *,
    sources: list[SourceConfig],
    source_ids: dict[str, int],
    account_ids: dict[str, int],
    tag_ids: dict[str, list[int]] | None = None,
) -> ErpCompatibilityRemoteRegistry:
    return ErpCompatibilityRemoteRegistry(
        markets=[
            ErpCompatibilityRemoteMarket(
                id=source_ids[source.source_id],
                canonical_id=source.source_id,
                code=source.source_id.upper(),
                name=source.display_name,
                base_url=source.base_url,
                enabled=source.enabled,
                row_version=source.config_version,
                created_at=source.created_at,
                updated_at=source.updated_at,
            )
            for source in sorted(
                sources, key=lambda source: (source.display_order, source.source_id)
            )
        ],
        connections=[
            ErpCompatibilityRemoteConnection(
                id=account_ids[item.account.id],
                canonical_id=item.account.id,
                username=item.account.login_username,
                market_id=source_ids[item.source.source_id],
                canonical_market_id=item.source.source_id,
                market_code=item.source.source_id.upper(),
                market_name=item.source.display_name,
                market_enabled=item.source.enabled,
                base_url=item.source.base_url,
                has_password=_credential_configured(item),
                has_totp_secret=_credential_configured(item),
                enabled=item.account.enabled,
                is_default=item.account.is_default,
                last_checked_at=item.account.last_tested_at,
                last_error=(
                    None
                    if item.account.last_test_status in {None, "SUCCESS", "OK"}
                    else item.account.last_test_status
                ),
                row_version=item.account.credential_version,
                created_at=item.account.created_at,
                updated_at=item.account.updated_at,
                capabilities=item.capabilities,
                tag_ids=(tag_ids or {}).get(item.account.id, []),
            )
            for item in items
        ],
    )


@router.get("/capabilities", include_in_schema=False)
async def get_capabilities(
    _: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REMOTE_ACCOUNT_MANAGE)),
) -> list[dict[str, str]]:
    return capability_definitions()


@router.get(
    "/compatibility-registry",
    response_model=ErpCompatibilityRemoteRegistry,
    include_in_schema=False,
)
async def get_compatibility_remote_registry(
    _: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REDEMPTION_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpCompatibilityRemoteRegistry:
    """Return the unified account registry without credentials or live tokens."""
    items = await list_remote_accounts(session)
    sources = await list_sources(session)
    snapshots = list(await session.scalars(select(RemoteAccountTagSnapshot)))
    tag_ids = {
        snapshot.account_id: [
            int(tag["id"])
            for tag in snapshot.tags_json
            if isinstance(tag, dict) and isinstance(tag.get("id"), int)
        ]
        for snapshot in snapshots
    }
    try:
        source_ids = await get_erp_compatibility_ids(
            session,
            entity_type="source",
            canonical_ids=[source.source_id for source in sources],
        )
        account_ids = await get_erp_compatibility_ids(
            session,
            entity_type="remote_account",
            canonical_ids=[item.account.id for item in items],
        )
    except ErpCompatibilityIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return _compatibility_registry(
        items,
        sources=sources,
        source_ids=source_ids,
        account_ids=account_ids,
        tag_ids=tag_ids,
    )


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


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_remote_account(
    account_id: str,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REMOTE_ACCOUNT_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    try:
        await delete_legacy_remote_account(
            session,
            account_id=account_id,
            actor_user_id=auth.user.id,
        )
    except RemoteAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RemoteAccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{account_id}/capabilities",
    response_model=RemoteAccountResponse,
    include_in_schema=False,
)
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


@router.post("/{account_id}/tags/sync", response_model=RemoteTagSnapshotResponse)
async def post_account_tag_sync(
    account_id: str,
    payload: RemoteTagSyncRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REDEMPTION_GENERATE)),
    session: AsyncSession = Depends(get_db_session),
) -> RemoteTagSnapshotResponse:
    try:
        return await sync_remote_account_tags(
            session,
            account_id=account_id,
            actor_user_id=auth.user.id,
            execution_authorized=payload.execution_confirmed,
            settings=get_settings(),
        )
    except RemoteAccountTagSyncError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


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
    redemption_type: Literal["SEVEN_DAY_DEPOSIT", "PREVIOUS_DAY_DEPOSIT"] = "SEVEN_DAY_DEPOSIT",
    _: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REDEMPTION_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> RewardTierPresetResponse:
    try:
        return await get_reward_tier_preset(
            session, account_id=account_id, redemption_type=redemption_type
        )
    except RemoteAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{account_id}/reward-tier-preset", response_model=RewardTierPresetResponse)
async def put_account_reward_tier_preset(
    account_id: str,
    payload: RewardTierPresetWrite,
    redemption_type: Literal["SEVEN_DAY_DEPOSIT", "PREVIOUS_DAY_DEPOSIT"] = "SEVEN_DAY_DEPOSIT",
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REMOTE_ACCOUNT_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> RewardTierPresetResponse:
    try:
        return await save_reward_tier_preset(
            session,
            account_id=account_id,
            request=payload,
            actor_user_id=auth.user.id,
            redemption_type=redemption_type,
        )
    except RemoteAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RemoteAccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
