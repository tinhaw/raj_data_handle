"""Local management of unified remote-market accounts and capability grants.

There are deliberately no HTTP clients or remote actions here. A capability
records explicit local authorization; future adapters must also enforce their
separately approved execution authorization before any remote call.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.security import (
    SecurityValidationError,
    decrypt_credentials,
    encrypt_credentials,
)
from packages.common.settings import Settings
from packages.domain.models import (
    RemoteAccount,
    RemoteAccountCapability,
    RemoteAccountRewardTierPreset,
    RemoteAccountTagSnapshot,
    SourceConfig,
)
from packages.domain.schemas.remote_account import (
    RemoteAccountCapabilityUpdateRequest,
    RemoteAccountCreateRequest,
    RemoteAccountPatchRequest,
    RemoteTag,
    RemoteTagSnapshotResponse,
    RemoteTagSnapshotWrite,
    RewardTierPresetResponse,
    RewardTierPresetTier,
    RewardTierPresetWrite,
)
from packages.domain.services.auth_service import write_audit
from packages.domain.services.erp_compatibility_id_service import (
    register_erp_compatibility_id,
)
from packages.domain.services.remote_account_identity import (
    RemoteAccountIdentityValidationError,
    normalize_remote_username,
    remote_account_credential_scope,
)
from packages.domain.services.source_service import validate_source_id

REMOTE_ACCOUNT_CAPABILITIES: dict[str, str] = {
    "ANALYSIS_READ": "分析只读",
    "ERP_REMOTE_CHECK": "ERP 远端连接检测",
    "ERP_TAG_READ": "ERP 标签读取",
    "ERP_TAG_SYNC": "ERP 标签同步",
    "ERP_REDEMPTION_CREATE": "ERP 兑换码远端创建",
    "ERP_REDEMPTION_PUBLISH": "ERP 兑换码远端发布",
    "ERP_REDEMPTION_CANCEL": "ERP 兑换码远端取消发布",
    "ERP_REDEMPTION_DOWNLOAD": "ERP 兑换码下载",
}
MANAGED_CREDENTIAL_MODE = "MANAGED"
LEGACY_SOURCE_CREDENTIAL_MODE = "LEGACY_SOURCE"


class RemoteAccountError(ValueError):
    pass


class RemoteAccountNotFoundError(RemoteAccountError):
    pass


class RemoteAccountConflictError(RemoteAccountError):
    pass


class RemoteAccountValidationError(RemoteAccountError):
    pass


@dataclass(frozen=True, slots=True)
class RemoteAccountView:
    account: RemoteAccount
    source: SourceConfig
    capabilities: dict[str, bool]


def capability_definitions() -> list[dict[str, str]]:
    return [
        {"code": code, "label": label}
        for code, label in REMOTE_ACCOUNT_CAPABILITIES.items()
    ]


def _normalize_display_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise RemoteAccountValidationError("远端账号显示名称不能为空。")
    return normalized


def _credentials_input(request: object | None) -> dict[str, str]:
    if request is None:
        return {}
    return {
        field: value.strip()
        for field in ("password", "totp_secret")
        if isinstance((value := getattr(request, field, None)), str) and value.strip()
    }


def _capability_map(rows: list[RemoteAccountCapability]) -> dict[str, bool]:
    stored = {row.capability: row.enabled for row in rows}
    return {capability: stored.get(capability, False) for capability in REMOTE_ACCOUNT_CAPABILITIES}


async def _get_account(session: AsyncSession, account_id: str) -> RemoteAccount:
    account = await session.get(RemoteAccount, account_id)
    if account is None:
        raise RemoteAccountNotFoundError("远端账号不存在。")
    return account


async def _get_source(session: AsyncSession, source_id: str) -> SourceConfig:
    source = await session.get(SourceConfig, source_id)
    if source is None:
        raise RemoteAccountValidationError("所属盘口不存在。")
    return source


async def list_remote_accounts(session: AsyncSession) -> list[RemoteAccountView]:
    rows = (
        await session.execute(
            select(RemoteAccount, SourceConfig)
            .join(SourceConfig, SourceConfig.source_id == RemoteAccount.source_id)
            .order_by(
                SourceConfig.display_order.asc(),
                SourceConfig.source_id.asc(),
                RemoteAccount.created_at.asc(),
            )
        )
    ).all()
    if not rows:
        return []
    account_ids = [account.id for account, _ in rows]
    capability_rows = list(
        await session.scalars(
            select(RemoteAccountCapability).where(
                RemoteAccountCapability.account_id.in_(account_ids)
            )
        )
    )
    by_account: dict[str, list[RemoteAccountCapability]] = {
        account_id: [] for account_id in account_ids
    }
    for capability in capability_rows:
        by_account[capability.account_id].append(capability)
    return [
        RemoteAccountView(
            account=account,
            source=source,
            capabilities=_capability_map(by_account[account.id]),
        )
        for account, source in rows
    ]


async def get_remote_account(session: AsyncSession, *, account_id: str) -> RemoteAccountView:
    account = await _get_account(session, account_id)
    source = await _get_source(session, account.source_id)
    capabilities = list(
        await session.scalars(
            select(RemoteAccountCapability).where(RemoteAccountCapability.account_id == account.id)
        )
    )
    return RemoteAccountView(
        account=account,
        source=source,
        capabilities=_capability_map(capabilities),
    )


async def create_remote_account(
    session: AsyncSession,
    *,
    request: RemoteAccountCreateRequest,
    actor_user_id: int,
    settings: Settings | None = None,
) -> RemoteAccountView:
    try:
        source_id = validate_source_id(request.source_id)
        login_username = normalize_remote_username(request.login_username)
    except (ValueError, RemoteAccountIdentityValidationError) as exc:
        raise RemoteAccountValidationError(str(exc)) from exc
    source = await _get_source(session, source_id)
    credentials = _credentials_input(request.credentials)
    if set(credentials) != {"password", "totp_secret"}:
        raise RemoteAccountValidationError("新建远端账号必须同时填写密码和 TOTP Secret。")
    account = RemoteAccount(
        id=str(uuid.uuid4()),
        source_id=source.source_id,
        login_username=login_username,
        display_name=_normalize_display_name(request.display_name),
        enabled=request.enabled,
        credential_mode=MANAGED_CREDENTIAL_MODE,
        created_by=actor_user_id,
        updated_by=actor_user_id,
        credential_version=1,
    )
    account.encrypted_credentials = encrypt_credentials(
        credentials,
        source_id=remote_account_credential_scope(account.id),
        credential_version=account.credential_version,
        settings=settings,
    )
    account.credential_updated_at = datetime.now(UTC)
    session.add(account)
    try:
        await session.flush()
        await register_erp_compatibility_id(
            session,
            entity_type="remote_account",
            canonical_id=account.id,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise RemoteAccountConflictError("该盘口下的远端登录账号已存在。") from exc
    await write_audit(
        session,
        action="remote_account.create",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={"source_id": account.source_id, "credential_mode": account.credential_mode},
    )
    await session.commit()
    return await get_remote_account(session, account_id=account.id)


async def update_remote_account(
    session: AsyncSession,
    *,
    account_id: str,
    request: RemoteAccountPatchRequest,
    actor_user_id: int,
    settings: Settings | None = None,
) -> RemoteAccountView:
    account = await _get_account(session, account_id)
    changed_fields: list[str] = []
    if request.display_name is not None:
        display_name = _normalize_display_name(request.display_name)
        if display_name != account.display_name:
            account.display_name = display_name
            changed_fields.append("display_name")
    if request.enabled is not None and request.enabled != account.enabled:
        account.enabled = request.enabled
        changed_fields.append("enabled")
    if request.login_username is not None:
        if account.credential_mode == LEGACY_SOURCE_CREDENTIAL_MODE:
            raise RemoteAccountValidationError("历史默认账号不能在此修改登录名，请先完成凭据接管。")
        try:
            login_username = normalize_remote_username(request.login_username)
        except RemoteAccountIdentityValidationError as exc:
            raise RemoteAccountValidationError(str(exc)) from exc
        if login_username != account.login_username:
            account.login_username = login_username
            changed_fields.append("login_username")

    credentials = _credentials_input(request.credentials)
    if request.credentials is not None:
        if account.credential_mode == LEGACY_SOURCE_CREDENTIAL_MODE:
            raise RemoteAccountValidationError(
                "历史默认账号仍引用原数据源凭据，当前阶段不能复制或重写。"
            )
        existing: dict[str, str] = {}
        if account.encrypted_credentials:
            try:
                existing = decrypt_credentials(
                    account.encrypted_credentials,
                    source_id=remote_account_credential_scope(account.id),
                    credential_version=account.credential_version,
                    settings=settings,
                )
            except SecurityValidationError as exc:
                raise RemoteAccountValidationError("已保存凭据无法解密，请重新完整配置。") from exc
        existing.update(credentials)
        if set(existing) != {"password", "totp_secret"}:
            raise RemoteAccountValidationError("远端账号必须同时保存密码和 TOTP Secret。")
        if credentials:
            account.credential_version += 1
            account.encrypted_credentials = encrypt_credentials(
                existing,
                source_id=remote_account_credential_scope(account.id),
                credential_version=account.credential_version,
                settings=settings,
            )
            account.credential_updated_at = datetime.now(UTC)
            account.last_test_status = None
            changed_fields.append("credentials")

    if changed_fields:
        account.updated_by = actor_user_id
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            raise RemoteAccountConflictError("该盘口下的远端登录账号已存在。") from exc
        await write_audit(
            session,
            action="remote_account.update",
            actor_user_id=actor_user_id,
            target_type="remote_account",
            target_id=account.id,
            metadata={"changed_fields": sorted(changed_fields)},
        )
        await session.commit()
    return await get_remote_account(session, account_id=account.id)


async def update_remote_account_capabilities(
    session: AsyncSession,
    *,
    account_id: str,
    request: RemoteAccountCapabilityUpdateRequest,
    actor_user_id: int,
) -> RemoteAccountView:
    account = await _get_account(session, account_id)
    unknown = set(request.capabilities) - set(REMOTE_ACCOUNT_CAPABILITIES)
    if unknown:
        raise RemoteAccountValidationError("包含不支持的远端账号能力。")
    rows = {
        row.capability: row
        for row in await session.scalars(
            select(RemoteAccountCapability).where(RemoteAccountCapability.account_id == account.id)
        )
    }
    changed: list[str] = []
    for capability, enabled in request.capabilities.items():
        row = rows.get(capability)
        if row is None:
            session.add(
                RemoteAccountCapability(
                    account_id=account.id,
                    capability=capability,
                    enabled=enabled,
                    updated_by=actor_user_id,
                )
            )
            changed.append(capability)
        elif row.enabled != enabled:
            row.enabled = enabled
            row.updated_by = actor_user_id
            changed.append(capability)
    if changed:
        await write_audit(
            session,
            action="remote_account.capability.update",
            actor_user_id=actor_user_id,
            target_type="remote_account",
            target_id=account.id,
            metadata={"capabilities": sorted(changed)},
        )
        await session.commit()
    return await get_remote_account(session, account_id=account.id)


async def get_remote_tag_snapshot(
    session: AsyncSession, *, account_id: str
) -> RemoteTagSnapshotResponse:
    await _get_account(session, account_id)
    row = await session.get(RemoteAccountTagSnapshot, account_id)
    if row is None:
        return RemoteTagSnapshotResponse(
            exists=False,
            tags=[],
            source=None,
            stale=False,
            synced_at=None,
            updated_at=None,
            row_version=None,
        )
    return RemoteTagSnapshotResponse(
        exists=True,
        tags=[RemoteTag.model_validate(tag) for tag in row.tags_json],
        source=row.source,
        stale=row.stale,
        synced_at=row.synced_at,
        updated_at=row.updated_at,
        row_version=row.row_version,
    )


async def save_remote_tag_snapshot(
    session: AsyncSession,
    *,
    account_id: str,
    request: RemoteTagSnapshotWrite,
    actor_user_id: int,
) -> RemoteTagSnapshotResponse:
    await _get_account(session, account_id)
    row = await session.get(RemoteAccountTagSnapshot, account_id)
    tags_json = [tag.model_dump(mode="json") for tag in request.tags]
    now = datetime.now(UTC)
    if row is None:
        row = RemoteAccountTagSnapshot(
            account_id=account_id,
            tags_json=tags_json,
            source=request.source,
            synced_at=now,
            updated_by=actor_user_id,
        )
        session.add(row)
    else:
        changed = row.tags_json != tags_json
        row.tags_json = tags_json
        row.source = request.source
        row.synced_at = now
        row.updated_by = actor_user_id
        row.stale = False
        if changed:
            row.row_version += 1
            preset = await session.get(RemoteAccountRewardTierPreset, account_id)
            if preset is not None and preset.tag_snapshot_json != tags_json:
                row.stale = True
    await write_audit(
        session,
        action="remote_account.tags_snapshot_save",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account_id,
        metadata={"tag_count": len(tags_json), "source": request.source},
    )
    await session.commit()
    return await get_remote_tag_snapshot(session, account_id=account_id)


async def get_reward_tier_preset(
    session: AsyncSession, *, account_id: str
) -> RewardTierPresetResponse:
    await _get_account(session, account_id)
    row = await session.get(RemoteAccountRewardTierPreset, account_id)
    current = await session.get(RemoteAccountTagSnapshot, account_id)
    if row is None:
        return RewardTierPresetResponse(
            exists=False, stale=False, tiers=[], tag_snapshot=[], saved_at=None, row_version=None
        )
    stale = bool(current and current.tags_json != row.tag_snapshot_json)
    return RewardTierPresetResponse(
        exists=True,
        stale=stale,
        tiers=[RewardTierPresetTier.model_validate(tier) for tier in row.tiers_json],
        tag_snapshot=[RemoteTag.model_validate(tag) for tag in row.tag_snapshot_json],
        saved_at=row.saved_at,
        row_version=row.row_version,
    )


async def save_reward_tier_preset(
    session: AsyncSession,
    *,
    account_id: str,
    request: RewardTierPresetWrite,
    actor_user_id: int,
) -> RewardTierPresetResponse:
    await _get_account(session, account_id)
    allowed_labels = {tag.id for tag in request.tag_snapshot}
    used_labels = {label for tier in request.tiers for label in tier.label_ids}
    if not used_labels.issubset(allowed_labels):
        raise RemoteAccountValidationError("档位引用了标签快照中不存在的标签 ID。")
    row = await session.get(RemoteAccountRewardTierPreset, account_id)
    tiers_json = [tier.model_dump(mode="json") for tier in request.tiers]
    tags_json = [tag.model_dump(mode="json") for tag in request.tag_snapshot]
    if row is None:
        row = RemoteAccountRewardTierPreset(
            account_id=account_id,
            tiers_json=tiers_json,
            tag_snapshot_json=tags_json,
            saved_by=actor_user_id,
        )
        session.add(row)
    else:
        row.tiers_json = tiers_json
        row.tag_snapshot_json = tags_json
        row.saved_by = actor_user_id
        row.saved_at = datetime.now(UTC)
        row.row_version += 1
    await write_audit(
        session,
        action="remote_account.reward_tier_preset_save",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account_id,
        metadata={"tier_count": len(tiers_json), "tag_count": len(tags_json)},
    )
    await session.commit()
    return await get_reward_tier_preset(session, account_id=account_id)


async def remote_account_has_capability(
    session: AsyncSession,
    *,
    account_id: str,
    capability: str,
) -> bool:
    if capability not in REMOTE_ACCOUNT_CAPABILITIES:
        return False
    account = await _get_account(session, account_id)
    enabled = await session.scalar(
        select(RemoteAccountCapability.enabled).where(
            RemoteAccountCapability.account_id == account_id,
            RemoteAccountCapability.capability == capability,
        )
    )
    return bool(account.enabled and enabled)
