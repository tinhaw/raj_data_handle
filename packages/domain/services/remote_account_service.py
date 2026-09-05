"""Local management of unified remote-market accounts and capability grants.

There are deliberately no HTTP clients or remote actions here. A capability
records explicit local authorization; future adapters must also enforce their
separately approved execution authorization before any remote call.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.security import (
    SecurityValidationError,
    decrypt_credentials,
    encrypt_credentials,
)
from packages.common.settings import Settings
from packages.domain.models import (
    ErpRedemptionCodeBatch,
    ErpRedemptionRemotePlan,
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
    return [{"code": code, "label": label} for code, label in REMOTE_ACCOUNT_CAPABILITIES.items()]


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


async def _default_account(
    session: AsyncSession,
    *,
    source_id: str,
) -> RemoteAccount | None:
    return await session.scalar(
        select(RemoteAccount).where(
            RemoteAccount.source_id == source_id,
            RemoteAccount.is_default.is_(True),
        )
    )


def _grant_all_capabilities(
    session: AsyncSession,
    *,
    account_id: str,
    actor_user_id: int,
) -> None:
    session.add_all(
        [
            RemoteAccountCapability(
                account_id=account_id,
                capability=capability,
                enabled=True,
                updated_by=actor_user_id,
            )
            for capability in REMOTE_ACCOUNT_CAPABILITIES
        ]
    )


async def _ensure_all_capabilities(
    session: AsyncSession,
    *,
    account_id: str,
    actor_user_id: int,
) -> bool:
    rows = {
        row.capability: row
        for row in await session.scalars(
            select(RemoteAccountCapability).where(RemoteAccountCapability.account_id == account_id)
        )
    }
    changed = False
    for capability in REMOTE_ACCOUNT_CAPABILITIES:
        row = rows.get(capability)
        if row is None:
            session.add(
                RemoteAccountCapability(
                    account_id=account_id,
                    capability=capability,
                    enabled=True,
                    updated_by=actor_user_id,
                )
            )
            changed = True
        elif not row.enabled:
            row.enabled = True
            row.updated_by = actor_user_id
            changed = True
    return changed


async def _make_default(
    session: AsyncSession,
    *,
    account: RemoteAccount,
) -> None:
    current = await _default_account(session, source_id=account.source_id)
    if current is not None and current.id != account.id:
        current.is_default = False
        await session.flush()
    account.is_default = True


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
    if request.is_default and not request.enabled:
        raise RemoteAccountValidationError("默认账号必须处于启用状态。")
    current_default = await _default_account(session, source_id=source.source_id)
    make_default = bool(request.is_default) or (request.enabled and current_default is None)
    account = RemoteAccount(
        id=str(uuid.uuid4()),
        source_id=source.source_id,
        login_username=login_username,
        display_name=_normalize_display_name(request.display_name),
        enabled=request.enabled,
        is_default=False,
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
    _grant_all_capabilities(
        session,
        account_id=account.id,
        actor_user_id=actor_user_id,
    )
    if make_default:
        await _make_default(session, account=account)
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
        metadata={
            "source_id": account.source_id,
            "credential_mode": account.credential_mode,
            "is_default": account.is_default,
            "capabilities": "ALL",
        },
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
    source = await _get_source(session, account.source_id)
    changed_fields: list[str] = []
    if request.display_name is not None:
        display_name = _normalize_display_name(request.display_name)
        if display_name != account.display_name:
            account.display_name = display_name
            changed_fields.append("display_name")
    if request.login_username is not None:
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
            if request.login_username is None or set(credentials) != {
                "password",
                "totp_secret",
            }:
                raise RemoteAccountValidationError(
                    "接管历史账号必须同时填写登录账号、密码和 TOTP Secret。"
                )
            account.credential_mode = MANAGED_CREDENTIAL_MODE
            account.credential_version = 1
            account.encrypted_credentials = encrypt_credentials(
                credentials,
                source_id=remote_account_credential_scope(account.id),
                credential_version=account.credential_version,
                settings=settings,
            )
            account.credential_updated_at = datetime.now(UTC)
            account.last_test_status = None
            changed_fields.extend(["credential_mode", "credentials"])
            credentials = {}
        existing: dict[str, str] = {}
        if credentials and account.encrypted_credentials:
            try:
                existing = decrypt_credentials(
                    account.encrypted_credentials,
                    source_id=remote_account_credential_scope(account.id),
                    credential_version=account.credential_version,
                    settings=settings,
                )
            except SecurityValidationError as exc:
                raise RemoteAccountValidationError("已保存凭据无法解密，请重新完整配置。") from exc
        if credentials:
            existing.update(credentials)
            if set(existing) != {"password", "totp_secret"}:
                raise RemoteAccountValidationError("远端账号必须同时保存密码和 TOTP Secret。")
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

    if request.enabled is not None and request.enabled != account.enabled:
        if not request.enabled and account.is_default:
            raise RemoteAccountValidationError("默认账号不能直接停用，请先将其他账号设为默认账号。")
        account.enabled = request.enabled
        changed_fields.append("enabled")

    if account.enabled:
        configured = bool(
            source.encrypted_credentials
            if account.credential_mode == LEGACY_SOURCE_CREDENTIAL_MODE
            else account.login_username and account.encrypted_credentials
        )
        if not configured:
            raise RemoteAccountValidationError("凭据未完整配置的账号不能启用。")
        if (
            not account.is_default
            and await _default_account(
                session,
                source_id=account.source_id,
            )
            is None
        ):
            await _make_default(session, account=account)
            changed_fields.append("is_default")

    if request.is_default is not None and request.is_default != account.is_default:
        if not request.is_default:
            raise RemoteAccountValidationError("请将另一个账号设为默认账号，系统会自动完成切换。")
        if not account.enabled:
            raise RemoteAccountValidationError("默认账号必须处于启用状态。")
        await _make_default(session, account=account)
        changed_fields.append("is_default")

    if await _ensure_all_capabilities(
        session,
        account_id=account.id,
        actor_user_id=actor_user_id,
    ):
        changed_fields.append("capabilities")

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
    if any(not enabled for enabled in request.capabilities.values()):
        raise RemoteAccountValidationError("统一远端账号固定拥有全部业务能力，不能单独停用能力。")
    rows = {
        row.capability: row
        for row in await session.scalars(
            select(RemoteAccountCapability).where(RemoteAccountCapability.account_id == account.id)
        )
    }
    changed: list[str] = []
    for capability in REMOTE_ACCOUNT_CAPABILITIES:
        enabled = True
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


async def delete_legacy_remote_account(
    session: AsyncSession,
    *,
    account_id: str,
    actor_user_id: int,
) -> None:
    """Retire a migrated legacy placeholder after a managed default is ready.

    Existing local tag and reward-tier data must already match the managed
    replacement, or it is copied when the replacement has no data yet. Main
    application task references block deletion so historical work is never
    detached silently.
    """

    account = await _get_account(session, account_id)
    if account.credential_mode != LEGACY_SOURCE_CREDENTIAL_MODE:
        raise RemoteAccountValidationError("这里只能删除待重新配置的历史账号。")
    if account.is_default:
        raise RemoteAccountValidationError("历史账号仍是默认账号，请先将当前账号设为默认。")

    replacement = await _default_account(session, source_id=account.source_id)
    if (
        replacement is None
        or replacement.id == account.id
        or replacement.credential_mode != MANAGED_CREDENTIAL_MODE
        or not replacement.enabled
        or not replacement.login_username
        or not replacement.encrypted_credentials
    ):
        raise RemoteAccountValidationError("请先配置并启用该盘口的当前默认账号。")

    capability_rows = list(
        await session.scalars(
            select(RemoteAccountCapability).where(
                RemoteAccountCapability.account_id == replacement.id
            )
        )
    )
    if not all(_capability_map(capability_rows).values()):
        raise RemoteAccountValidationError("当前默认账号尚未获得全部功能，不能删除历史账号。")

    batch_references = int(
        await session.scalar(
            select(func.count(ErpRedemptionCodeBatch.id)).where(
                ErpRedemptionCodeBatch.remote_account_id == account.id
            )
        )
        or 0
    )
    plan_references = int(
        await session.scalar(
            select(func.count(ErpRedemptionRemotePlan.id)).where(
                ErpRedemptionRemotePlan.remote_account_id == account.id
            )
        )
        or 0
    )
    if batch_references or plan_references:
        raise RemoteAccountConflictError("历史账号仍被兑换码任务引用，暂不能删除。")

    legacy_snapshot = await session.get(RemoteAccountTagSnapshot, account.id)
    replacement_snapshot = await session.get(RemoteAccountTagSnapshot, replacement.id)
    migrated_snapshot = False
    if legacy_snapshot is not None:
        if replacement_snapshot is None:
            session.add(
                RemoteAccountTagSnapshot(
                    account_id=replacement.id,
                    tags_json=list(legacy_snapshot.tags_json),
                    source="MIGRATED",
                    stale=legacy_snapshot.stale,
                    synced_at=legacy_snapshot.synced_at,
                    updated_by=actor_user_id,
                    row_version=legacy_snapshot.row_version,
                )
            )
            migrated_snapshot = True
        elif replacement_snapshot.tags_json != legacy_snapshot.tags_json:
            raise RemoteAccountConflictError("当前账号与历史账号的标签快照不一致，请先核对并迁移。")

    migrated_preset = False
    for redemption_type in ("SEVEN_DAY_DEPOSIT", "PREVIOUS_DAY_DEPOSIT"):
        legacy_preset = await session.get(
            RemoteAccountRewardTierPreset, (account.id, redemption_type)
        )
        replacement_preset = await session.get(
            RemoteAccountRewardTierPreset, (replacement.id, redemption_type)
        )
        if legacy_preset is None:
            continue
        if replacement_preset is None:
            session.add(
                RemoteAccountRewardTierPreset(
                    account_id=replacement.id,
                    redemption_type=redemption_type,
                    tiers_json=list(legacy_preset.tiers_json),
                    tag_snapshot_json=list(legacy_preset.tag_snapshot_json),
                    saved_by=actor_user_id,
                    saved_at=legacy_preset.saved_at,
                    row_version=legacy_preset.row_version,
                )
            )
            migrated_preset = True
        elif (
            replacement_preset.tiers_json != legacy_preset.tiers_json
            or replacement_preset.tag_snapshot_json != legacy_preset.tag_snapshot_json
        ):
            raise RemoteAccountConflictError(
                "当前账号与历史账号的兑换档位预设不一致，请先核对并迁移。"
            )

    await write_audit(
        session,
        action="remote_account.legacy_delete",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={
            "source_id": account.source_id,
            "replacement_account_id": replacement.id,
            "migrated_tag_snapshot": migrated_snapshot,
            "migrated_reward_tier_preset": migrated_preset,
        },
    )
    await session.execute(
        delete(RemoteAccountCapability).where(RemoteAccountCapability.account_id == account.id)
    )
    await session.execute(
        delete(RemoteAccountTagSnapshot).where(RemoteAccountTagSnapshot.account_id == account.id)
    )
    await session.execute(
        delete(RemoteAccountRewardTierPreset).where(
            RemoteAccountRewardTierPreset.account_id == account.id
        )
    )
    await session.delete(account)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise RemoteAccountConflictError("历史账号仍被业务数据引用，暂不能删除。") from exc


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
            for redemption_type in ("SEVEN_DAY_DEPOSIT", "PREVIOUS_DAY_DEPOSIT"):
                preset = await session.get(
                    RemoteAccountRewardTierPreset, (account_id, redemption_type)
                )
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
    session: AsyncSession, *, account_id: str, redemption_type: str = "SEVEN_DAY_DEPOSIT"
) -> RewardTierPresetResponse:
    await _get_account(session, account_id)
    if redemption_type not in ("SEVEN_DAY_DEPOSIT", "PREVIOUS_DAY_DEPOSIT"):
        raise RemoteAccountValidationError("不支持的兑换码类型。")
    row = await session.get(RemoteAccountRewardTierPreset, (account_id, redemption_type))
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
    redemption_type: str = "SEVEN_DAY_DEPOSIT",
) -> RewardTierPresetResponse:
    await _get_account(session, account_id)
    allowed_labels = {tag.id for tag in request.tag_snapshot}
    used_labels = {label for tier in request.tiers for label in tier.label_ids}
    if not used_labels.issubset(allowed_labels):
        raise RemoteAccountValidationError("档位引用了标签快照中不存在的标签 ID。")
    if redemption_type not in ("SEVEN_DAY_DEPOSIT", "PREVIOUS_DAY_DEPOSIT"):
        raise RemoteAccountValidationError("不支持的兑换码类型。")
    row = await session.get(RemoteAccountRewardTierPreset, (account_id, redemption_type))
    tiers_json = [tier.model_dump(mode="json") for tier in request.tiers]
    tags_json = [tag.model_dump(mode="json") for tag in request.tag_snapshot]
    if row is None:
        row = RemoteAccountRewardTierPreset(
            account_id=account_id,
            tiers_json=tiers_json,
            redemption_type=redemption_type,
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
    return await get_reward_tier_preset(
        session, account_id=account_id, redemption_type=redemption_type
    )


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
