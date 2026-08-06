from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.security import SecurityValidationError, decrypt_credentials
from packages.common.settings import Settings, get_settings
from packages.domain.models import DataDictionaryEntry, SourceConfig
from packages.domain.schemas.data_dictionary import DataDictionaryEntryResponse
from packages.domain.services.auth_service import write_audit
from packages.domain.services.remote_charge_service import RemoteChargeError
from packages.domain.services.remote_spin_service import RajAdminSpinClient
from packages.domain.services.remote_withdraw_service import RajAdminWithdrawClient

CHARGE_STATUS_DICTIONARY = "charge_status"
CHARGE_STATUS_ENTRIES = (
    ("-1", "已失效"),
    ("0", "待支付"),
    ("1", "已支付"),
    ("2", "已退款"),
)
PAYMENT_CHANNEL_DICTIONARY = "payment_channel"
PAYMENT_CHANNEL_NAME_DICTIONARY = "payment_channel_name"
WITHDRAW_STATUS_DICTIONARY = "withdraw_status"
SPIN_ORDER_STATUS_DICTIONARY = "spin_order_status"
SPIN_ORDER_STATUS_ENTRIES = (
    ("0", "待审核"),
    ("1", "审核通过"),
    ("101", "自动审核通过"),
    ("2", "已拒绝"),
    ("3", "已挂起"),
)
USER_SOURCE_CHANNEL_DICTIONARY = "user_source_channel"


class DataDictionarySyncError(ValueError):
    pass


class DataDictionaryValidationError(ValueError):
    pass


class DataDictionaryConflictError(DataDictionaryValidationError):
    pass


class DataDictionaryNotFoundError(DataDictionaryValidationError):
    pass


class DataDictionaryRemoteSyncError(DataDictionaryValidationError):
    pass


@dataclass(frozen=True, slots=True)
class DictionarySyncResult:
    active_entries: int
    created_entries: int
    updated_entries: int
    deactivated_entries: int


@dataclass(frozen=True, slots=True)
class WithdrawStatusCacheRefreshResult:
    remote_total: int
    created_entries: int
    refreshed_entries: int


@dataclass(frozen=True, slots=True)
class WithdrawStatusRemoteSyncResult:
    source_id: str
    source_display_name: str
    fetched_at: datetime
    remote_total: int
    created_entries: int
    refreshed_entries: int
    entries: list[DataDictionaryEntryResponse]


@dataclass(frozen=True, slots=True)
class UserSourceChannelRemoteSyncResult:
    source_id: str
    source_display_name: str
    fetched_at: datetime
    remote_total: int
    replaced_entries: int
    entries: list[DataDictionaryEntryResponse]


async def ensure_charge_statuses(
    session: AsyncSession,
    *,
    source_id: str,
    now: datetime | None = None,
) -> int:
    """Insert the manually verified recharge statuses missing for a source."""

    source = await session.get(SourceConfig, source_id)
    if source is None:
        raise DataDictionaryNotFoundError("盘口配置不存在。")
    existing = list(
        await session.scalars(
            select(DataDictionaryEntry).where(
                DataDictionaryEntry.source_id == source_id,
                DataDictionaryEntry.dictionary_type == CHARGE_STATUS_DICTIONARY,
            )
        )
    )
    existing_by_code = {entry.entry_code: entry for entry in existing}
    inserted_at = now or datetime.now(UTC)
    created = 0
    for code, label in CHARGE_STATUS_ENTRIES:
        entry = existing_by_code.get(code)
        if entry is not None:
            if entry.entry_label != label or not entry.active:
                entry.entry_label = label
                entry.active = True
                entry.last_seen_at = inserted_at
                entry.updated_at = inserted_at
            continue
        session.add(
            DataDictionaryEntry(
                source_id=source_id,
                dictionary_type=CHARGE_STATUS_DICTIONARY,
                entry_code=code,
                entry_label=label,
                active=True,
                first_seen_at=inserted_at,
                last_seen_at=inserted_at,
                updated_at=inserted_at,
            )
        )
        created += 1
    await session.flush()
    return created


async def list_charge_statuses(
    session: AsyncSession,
    *,
    source_id: str | None = None,
    active: bool | None = None,
) -> list[DataDictionaryEntryResponse]:
    statement = (
        select(DataDictionaryEntry, SourceConfig)
        .join(SourceConfig, SourceConfig.source_id == DataDictionaryEntry.source_id)
        .where(DataDictionaryEntry.dictionary_type == CHARGE_STATUS_DICTIONARY)
        .order_by(
            SourceConfig.display_name,
            DataDictionaryEntry.entry_code,
        )
    )
    if source_id:
        statement = statement.where(DataDictionaryEntry.source_id == source_id)
    if active is not None:
        statement = statement.where(DataDictionaryEntry.active.is_(active))
    rows = (await session.execute(statement)).all()
    return [
        _entry_response(entry, source_display_name=source.display_name) for entry, source in rows
    ]


async def ensure_spin_order_statuses(
    session: AsyncSession,
    *,
    source_id: str,
    now: datetime | None = None,
) -> int:
    """Seed the confirmed fixed spin-review status dictionary for one source."""

    source = await session.get(SourceConfig, source_id)
    if source is None:
        raise DataDictionaryNotFoundError("盘口配置不存在。")
    existing = list(
        await session.scalars(
            select(DataDictionaryEntry).where(
                DataDictionaryEntry.source_id == source_id,
                DataDictionaryEntry.dictionary_type == SPIN_ORDER_STATUS_DICTIONARY,
            )
        )
    )
    by_code = {entry.entry_code: entry for entry in existing}
    observed_at = now or datetime.now(UTC)
    created = 0
    for code, label in SPIN_ORDER_STATUS_ENTRIES:
        entry = by_code.get(code)
        if entry is None:
            session.add(
                DataDictionaryEntry(
                    source_id=source_id,
                    dictionary_type=SPIN_ORDER_STATUS_DICTIONARY,
                    entry_code=code,
                    entry_label=label,
                    active=True,
                    first_seen_at=observed_at,
                    last_seen_at=observed_at,
                    updated_at=observed_at,
                )
            )
            created += 1
            continue
        # The status code is the reporting semantic.  Keep the fixed label
        # and enabled state aligned with the confirmed source contract.
        entry.entry_label = label
        entry.active = True
        entry.last_seen_at = observed_at
        entry.updated_at = observed_at
    await session.flush()
    return created


async def list_spin_order_statuses(
    session: AsyncSession,
    *,
    source_id: str | None = None,
    active: bool | None = None,
) -> list[DataDictionaryEntryResponse]:
    statement = (
        select(DataDictionaryEntry, SourceConfig)
        .join(SourceConfig, SourceConfig.source_id == DataDictionaryEntry.source_id)
        .where(DataDictionaryEntry.dictionary_type == SPIN_ORDER_STATUS_DICTIONARY)
        .order_by(SourceConfig.display_name, DataDictionaryEntry.entry_code)
    )
    if source_id:
        statement = statement.where(DataDictionaryEntry.source_id == source_id)
    if active is not None:
        statement = statement.where(DataDictionaryEntry.active.is_(active))
    rows = (await session.execute(statement)).all()
    return [
        _entry_response(entry, source_display_name=source.display_name) for entry, source in rows
    ]


async def list_user_source_channels(
    session: AsyncSession,
    *,
    source_id: str | None = None,
    active: bool | None = None,
) -> list[DataDictionaryEntryResponse]:
    statement = (
        select(DataDictionaryEntry, SourceConfig)
        .join(SourceConfig, SourceConfig.source_id == DataDictionaryEntry.source_id)
        .where(DataDictionaryEntry.dictionary_type == USER_SOURCE_CHANNEL_DICTIONARY)
        .order_by(
            SourceConfig.display_name,
            DataDictionaryEntry.entry_label,
            DataDictionaryEntry.entry_code,
        )
    )
    if source_id:
        statement = statement.where(DataDictionaryEntry.source_id == source_id)
    if active is not None:
        statement = statement.where(DataDictionaryEntry.active.is_(active))
    rows = (await session.execute(statement)).all()
    return [
        _entry_response(entry, source_display_name=source.display_name) for entry, source in rows
    ]


async def replace_user_source_channels(
    session: AsyncSession,
    *,
    source_id: str,
    channels: list[dict[str, str]],
    now: datetime | None = None,
) -> int:
    """Replace the entire source-scoped channel_id dictionary in one transaction."""

    source = await session.get(SourceConfig, source_id)
    if source is None:
        raise DataDictionaryNotFoundError("盘口配置不存在。")
    normalized: dict[str, str] = {}
    for channel in channels:
        code = str(channel.get("code") or "").strip()
        label = str(channel.get("label") or "").strip()
        if not code or not label:
            raise DataDictionarySyncError("渠道来源字典包含空代码或展示名称。")
        if code in normalized:
            raise DataDictionarySyncError("渠道来源字典包含重复代码。")
        normalized[code] = label
    if not normalized:
        raise DataDictionarySyncError("渠道来源字典为空，未覆盖本地字典。")
    refreshed_at = now or datetime.now(UTC)
    # The caller has completed remote validation before this point.  Delete
    # and insert remain in the current transaction, so a later error rolls
    # back to the untouched prior dictionary.
    await session.execute(
        delete(DataDictionaryEntry).where(
            DataDictionaryEntry.source_id == source_id,
            DataDictionaryEntry.dictionary_type == USER_SOURCE_CHANNEL_DICTIONARY,
        )
    )
    session.add_all(
        [
            DataDictionaryEntry(
                source_id=source_id,
                dictionary_type=USER_SOURCE_CHANNEL_DICTIONARY,
                entry_code=code,
                entry_label=label,
                active=True,
                first_seen_at=refreshed_at,
                last_seen_at=refreshed_at,
                updated_at=refreshed_at,
            )
            for code, label in normalized.items()
        ]
    )
    await session.flush()
    return len(normalized)


async def sync_remote_user_source_channels(
    session: AsyncSession,
    *,
    source_id: str,
    actor_user_id: int,
    settings: Settings | None = None,
) -> UserSourceChannelRemoteSyncResult:
    """User-triggered, transactional full replacement of channel_id mappings."""

    source = await session.get(SourceConfig, source_id)
    if source is None:
        raise DataDictionaryNotFoundError("盘口配置不存在。")
    if not source.enabled:
        raise DataDictionaryValidationError("所选盘口尚未启用。")
    if not source.base_url or not source.encrypted_credentials:
        raise DataDictionaryValidationError("所选盘口缺少远端地址或凭据。")
    current_settings = settings or get_settings()
    try:
        credentials = decrypt_credentials(
            source.encrypted_credentials,
            source_id=source.source_id,
            credential_version=source.credential_version,
            settings=current_settings,
        )
        async with RajAdminSpinClient(
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
        ) as client:
            channels = await client.fetch_user_source_channels()
        fetched_at = datetime.now(UTC)
        replaced_entries = await replace_user_source_channels(
            session,
            source_id=source.source_id,
            channels=channels,
            now=fetched_at,
        )
    except (KeyError, SecurityValidationError) as exc:
        raise DataDictionaryValidationError("已保存的盘口凭据不完整或无法解密。") from exc
    except (DataDictionarySyncError, RemoteChargeError) as exc:
        raise DataDictionaryRemoteSyncError(
            "远端渠道来源字典读取或校验失败，本地字典未覆盖。"
        ) from exc
    await write_audit(
        session,
        action="data_dictionary.user_source_channel.replace",
        actor_user_id=actor_user_id,
        target_type="source",
        target_id=source.source_id,
        metadata={"remote_total": len(channels), "replaced_entries": replaced_entries},
    )
    await session.commit()
    return UserSourceChannelRemoteSyncResult(
        source_id=source.source_id,
        source_display_name=source.display_name,
        fetched_at=fetched_at,
        remote_total=len(channels),
        replaced_entries=replaced_entries,
        entries=await list_user_source_channels(session, source_id=source.source_id),
    )


async def sync_payment_channel_names(
    session: AsyncSession,
    *,
    source_id: str,
    channels: list[dict[str, str]],
) -> DictionarySyncResult:
    normalized: dict[str, str] = {}
    for channel in channels:
        code = str(channel.get("code") or "").strip()
        label = str(channel.get("label") or "").strip()
        if not code or not label:
            raise DataDictionarySyncError("支付渠道名称字典包含空 ID 或名称。")
        previous = normalized.get(code)
        if previous is not None and previous != label:
            raise DataDictionarySyncError("支付渠道名称字典中同一 ID 对应多个名称。")
        normalized[code] = label
    if not normalized:
        raise DataDictionarySyncError("支付渠道名称字典为空。")

    existing = list(
        await session.scalars(
            select(DataDictionaryEntry).where(
                DataDictionaryEntry.source_id == source_id,
                DataDictionaryEntry.dictionary_type == PAYMENT_CHANNEL_NAME_DICTIONARY,
            )
        )
    )
    existing_by_code = {entry.entry_code: entry for entry in existing}
    now = datetime.now(UTC)
    created = 0
    updated = 0
    deactivated = 0

    for code, label in normalized.items():
        entry = existing_by_code.pop(code, None)
        if entry is None:
            session.add(
                DataDictionaryEntry(
                    source_id=source_id,
                    dictionary_type=PAYMENT_CHANNEL_NAME_DICTIONARY,
                    entry_code=code,
                    entry_label=label,
                    active=True,
                    first_seen_at=now,
                    last_seen_at=now,
                    updated_at=now,
                )
            )
            created += 1
            continue
        changed = entry.entry_label != label or not entry.active
        entry.entry_label = label
        entry.active = True
        entry.last_seen_at = now
        entry.updated_at = now
        if changed:
            updated += 1

    for entry in existing_by_code.values():
        if entry.active:
            entry.active = False
            entry.updated_at = now
            deactivated += 1

    await session.flush()
    return DictionarySyncResult(
        active_entries=len(normalized),
        created_entries=created,
        updated_entries=updated,
        deactivated_entries=deactivated,
    )


async def sync_payment_channels(
    session: AsyncSession,
    *,
    source_id: str,
    channels: list[dict[str, str]],
) -> DictionarySyncResult:
    """Persist the remote pay_channel key/title mapping used by pay_method."""

    normalized: dict[str, str] = {}
    for channel in channels:
        code = str(channel.get("code") or "").strip()
        label = str(channel.get("label") or "").strip()
        if not code or not label:
            raise DataDictionarySyncError("支付渠道字典包含空 pay_method 值或展示内容。")
        previous = normalized.get(code)
        if previous is not None and previous != label:
            raise DataDictionarySyncError("支付渠道字典中同一 pay_method 对应多个展示内容。")
        normalized[code] = label
    if not normalized:
        raise DataDictionarySyncError("支付渠道字典为空。")

    existing = list(
        await session.scalars(
            select(DataDictionaryEntry).where(
                DataDictionaryEntry.source_id == source_id,
                DataDictionaryEntry.dictionary_type == PAYMENT_CHANNEL_DICTIONARY,
            )
        )
    )
    existing_by_code = {entry.entry_code: entry for entry in existing}
    now = datetime.now(UTC)
    created = 0
    updated = 0
    deactivated = 0

    for code, label in normalized.items():
        entry = existing_by_code.pop(code, None)
        if entry is None:
            session.add(
                DataDictionaryEntry(
                    source_id=source_id,
                    dictionary_type=PAYMENT_CHANNEL_DICTIONARY,
                    entry_code=code,
                    entry_label=label,
                    active=True,
                    first_seen_at=now,
                    last_seen_at=now,
                    updated_at=now,
                )
            )
            created += 1
            continue
        changed = entry.entry_label != label or not entry.active
        entry.entry_label = label
        entry.active = True
        entry.last_seen_at = now
        entry.updated_at = now
        if changed:
            updated += 1

    for entry in existing_by_code.values():
        if entry.active:
            entry.active = False
            entry.updated_at = now
            deactivated += 1

    await session.flush()
    return DictionarySyncResult(
        active_entries=len(normalized),
        created_entries=created,
        updated_entries=updated,
        deactivated_entries=deactivated,
    )


async def list_payment_channels(
    session: AsyncSession,
    *,
    source_id: str | None = None,
    active: bool | None = None,
) -> list[DataDictionaryEntryResponse]:
    statement = (
        select(DataDictionaryEntry, SourceConfig)
        .join(SourceConfig, SourceConfig.source_id == DataDictionaryEntry.source_id)
        .where(
            DataDictionaryEntry.dictionary_type == PAYMENT_CHANNEL_DICTIONARY,
        )
        .order_by(
            SourceConfig.display_name,
            DataDictionaryEntry.entry_label,
            DataDictionaryEntry.entry_code,
        )
    )
    if source_id:
        statement = statement.where(DataDictionaryEntry.source_id == source_id)
    if active is not None:
        statement = statement.where(DataDictionaryEntry.active.is_(active))
    rows = (await session.execute(statement)).all()
    return [
        _entry_response(entry, source_display_name=source.display_name) for entry, source in rows
    ]


async def list_payment_channel_names(
    session: AsyncSession,
    *,
    source_id: str | None = None,
    active: bool | None = None,
) -> list[DataDictionaryEntryResponse]:
    statement = (
        select(DataDictionaryEntry, SourceConfig)
        .join(SourceConfig, SourceConfig.source_id == DataDictionaryEntry.source_id)
        .where(
            DataDictionaryEntry.dictionary_type == PAYMENT_CHANNEL_NAME_DICTIONARY,
        )
        .order_by(
            SourceConfig.display_name,
            DataDictionaryEntry.entry_label,
            DataDictionaryEntry.entry_code,
        )
    )
    if source_id:
        statement = statement.where(DataDictionaryEntry.source_id == source_id)
    if active is not None:
        statement = statement.where(DataDictionaryEntry.active.is_(active))
    rows = (await session.execute(statement)).all()
    return [
        _entry_response(entry, source_display_name=source.display_name) for entry, source in rows
    ]


def _entry_response(
    entry: DataDictionaryEntry,
    *,
    source_display_name: str,
) -> DataDictionaryEntryResponse:
    return DataDictionaryEntryResponse(
        id=entry.id,
        source_id=entry.source_id,
        source_display_name=source_display_name,
        dictionary_type=entry.dictionary_type,
        entry_code=entry.entry_code,
        entry_label=entry.entry_label,
        active=entry.active,
        first_seen_at=entry.first_seen_at,
        last_seen_at=entry.last_seen_at,
        updated_at=entry.updated_at,
    )


async def list_withdraw_statuses(
    session: AsyncSession,
    *,
    source_id: str | None = None,
    active: bool | None = None,
) -> list[DataDictionaryEntryResponse]:
    statement = (
        select(DataDictionaryEntry, SourceConfig)
        .join(SourceConfig, SourceConfig.source_id == DataDictionaryEntry.source_id)
        .where(DataDictionaryEntry.dictionary_type == WITHDRAW_STATUS_DICTIONARY)
        .order_by(
            SourceConfig.display_name,
            DataDictionaryEntry.entry_code,
            DataDictionaryEntry.entry_label,
        )
    )
    if source_id:
        statement = statement.where(DataDictionaryEntry.source_id == source_id)
    if active is not None:
        statement = statement.where(DataDictionaryEntry.active.is_(active))
    rows = (await session.execute(statement)).all()
    return [
        _entry_response(entry, source_display_name=source.display_name) for entry, source in rows
    ]


async def withdraw_status_dictionary(
    session: AsyncSession,
    *,
    source_id: str,
) -> list[dict[str, object]]:
    rows = await session.execute(
        select(
            DataDictionaryEntry.entry_code,
            DataDictionaryEntry.entry_label,
            DataDictionaryEntry.active,
        )
        .where(
            DataDictionaryEntry.source_id == source_id,
            DataDictionaryEntry.dictionary_type == WITHDRAW_STATUS_DICTIONARY,
        )
        .order_by(DataDictionaryEntry.entry_code)
    )
    return [
        {"code": str(code), "label": str(label), "active": bool(active)}
        for code, label, active in rows
    ]


def _normalize_withdraw_statuses(statuses: list[dict[str, str]]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for status in statuses:
        raw_code = status.get("code")
        raw_label = status.get("label")
        code = str(raw_code).strip() if raw_code is not None else ""
        label = str(raw_label).strip() if raw_label is not None else ""
        if not code or not label:
            raise DataDictionarySyncError("提现状态字典包含空状态值或展示文案。")
        previous = normalized.get(code)
        if previous is not None and previous != label:
            raise DataDictionarySyncError("提现状态字典中同一状态值对应多个文案。")
        normalized[code] = label
    if not normalized:
        raise DataDictionarySyncError("提现状态字典为空。")
    return normalized


async def refresh_withdraw_status_cache(
    session: AsyncSession,
    *,
    source_id: str,
    statuses: list[dict[str, str]],
    now: datetime | None = None,
) -> WithdrawStatusCacheRefreshResult:
    """Import only missing remote status codes and refresh existing codes' last-seen time.

    The local ``withdraw_status`` record is also the operator-managed override.  A
    remote import must never change its display label or enabled state, and remote
    omissions must not deactivate it.
    """

    source = await session.get(SourceConfig, source_id)
    if source is None:
        raise DataDictionaryNotFoundError("盘口配置不存在。")
    normalized = _normalize_withdraw_statuses(statuses)
    existing = list(
        await session.scalars(
            select(DataDictionaryEntry).where(
                DataDictionaryEntry.source_id == source_id,
                DataDictionaryEntry.dictionary_type == WITHDRAW_STATUS_DICTIONARY,
            )
        )
    )
    existing_by_code = {entry.entry_code: entry for entry in existing}
    seen_at = now or datetime.now(UTC)
    created_entries = 0
    refreshed_entries = 0

    for code, label in normalized.items():
        entry = existing_by_code.get(code)
        if entry is None:
            session.add(
                DataDictionaryEntry(
                    source_id=source_id,
                    dictionary_type=WITHDRAW_STATUS_DICTIONARY,
                    entry_code=code,
                    entry_label=label,
                    active=True,
                    first_seen_at=seen_at,
                    last_seen_at=seen_at,
                    updated_at=seen_at,
                )
            )
            created_entries += 1
            continue
        entry.last_seen_at = seen_at
        refreshed_entries += 1

    await session.flush()
    return WithdrawStatusCacheRefreshResult(
        remote_total=len(normalized),
        created_entries=created_entries,
        refreshed_entries=refreshed_entries,
    )


async def sync_remote_withdraw_statuses(
    session: AsyncSession,
    *,
    source_id: str,
    actor_user_id: int,
    settings: Settings | None = None,
) -> WithdrawStatusRemoteSyncResult:
    """Manually refresh a source's local withdrawal-status cache from its remote API."""

    source = await session.get(SourceConfig, source_id)
    if source is None:
        raise DataDictionaryNotFoundError("盘口配置不存在。")
    if not source.enabled:
        raise DataDictionaryValidationError("所选盘口尚未启用。")
    if not source.base_url or not source.encrypted_credentials:
        raise DataDictionaryValidationError("所选盘口缺少远端地址或凭据。")

    current_settings = settings or get_settings()
    try:
        credentials = decrypt_credentials(
            source.encrypted_credentials,
            source_id=source.source_id,
            credential_version=source.credential_version,
            settings=current_settings,
        )
    except SecurityValidationError as exc:
        raise DataDictionaryValidationError("已保存的盘口凭据无法解密。") from exc
    try:
        username = credentials["username"]
        password = credentials["password"]
        totp_secret = credentials["totp_secret"]
    except KeyError as exc:
        raise DataDictionaryValidationError("已保存的盘口凭据不完整。") from exc
    credential_values = (username, password, totp_secret)
    if not all(isinstance(value, str) and value.strip() for value in credential_values):
        raise DataDictionaryValidationError("已保存的盘口凭据不完整。")

    try:
        async with RajAdminWithdrawClient(
            base_url=source.base_url,
            username=username,
            password=password,
            totp_secret=totp_secret,
        ) as client:
            statuses = await client.fetch_withdraw_statuses()
        fetched_at = datetime.now(UTC)
        refresh_result = await refresh_withdraw_status_cache(
            session,
            source_id=source.source_id,
            statuses=statuses,
            now=fetched_at,
        )
    except (DataDictionarySyncError, RemoteChargeError) as exc:
        raise DataDictionaryRemoteSyncError("远端提现状态字典读取或校验失败。") from exc

    await write_audit(
        session,
        action="data_dictionary.withdraw_status.sync",
        actor_user_id=actor_user_id,
        target_type="source",
        target_id=source.source_id,
        metadata={
            "remote_total": refresh_result.remote_total,
            "created_entries": refresh_result.created_entries,
            "refreshed_entries": refresh_result.refreshed_entries,
        },
    )
    await session.commit()
    entries = await list_withdraw_statuses(session, source_id=source.source_id)
    return WithdrawStatusRemoteSyncResult(
        source_id=source.source_id,
        source_display_name=source.display_name,
        fetched_at=fetched_at,
        remote_total=refresh_result.remote_total,
        created_entries=refresh_result.created_entries,
        refreshed_entries=refresh_result.refreshed_entries,
        entries=entries,
    )


async def create_withdraw_status(
    session: AsyncSession,
    *,
    source_id: str,
    entry_code: str,
    entry_label: str,
    active: bool,
    actor_user_id: int,
) -> DataDictionaryEntryResponse:
    return await _create_status_entry(
        session,
        source_id=source_id,
        entry_code=entry_code,
        entry_label=entry_label,
        active=active,
        actor_user_id=actor_user_id,
        dictionary_type=WITHDRAW_STATUS_DICTIONARY,
        status_name="提现状态",
        audit_action="data_dictionary.withdraw_status.create",
    )


async def create_charge_status(
    session: AsyncSession,
    *,
    source_id: str,
    entry_code: str,
    entry_label: str,
    active: bool,
    actor_user_id: int,
) -> DataDictionaryEntryResponse:
    return await _create_status_entry(
        session,
        source_id=source_id,
        entry_code=entry_code,
        entry_label=entry_label,
        active=active,
        actor_user_id=actor_user_id,
        dictionary_type=CHARGE_STATUS_DICTIONARY,
        status_name="充值订单状态",
        audit_action="data_dictionary.charge_status.create",
    )


async def _create_status_entry(
    session: AsyncSession,
    *,
    source_id: str,
    entry_code: str,
    entry_label: str,
    active: bool,
    actor_user_id: int,
    dictionary_type: str,
    status_name: str,
    audit_action: str,
) -> DataDictionaryEntryResponse:
    source = await session.get(SourceConfig, source_id)
    if source is None:
        raise DataDictionaryNotFoundError("盘口配置不存在。")
    existing = await session.scalar(
        select(DataDictionaryEntry).where(
            DataDictionaryEntry.source_id == source_id,
            DataDictionaryEntry.dictionary_type == dictionary_type,
            DataDictionaryEntry.entry_code == entry_code,
        )
    )
    if existing is not None:
        raise DataDictionaryConflictError(f"该盘口的{status_name}值已存在，请直接编辑展示文案。")
    now = datetime.now(UTC)
    entry = DataDictionaryEntry(
        source_id=source_id,
        dictionary_type=dictionary_type,
        entry_code=entry_code,
        entry_label=entry_label,
        active=active,
        first_seen_at=now,
        last_seen_at=now,
        updated_at=now,
    )
    session.add(entry)
    await write_audit(
        session,
        action=audit_action,
        actor_user_id=actor_user_id,
        target_type="data_dictionary_entry",
        target_id=f"{source_id}:{dictionary_type}:{entry_code}",
        metadata={"active": active},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DataDictionaryConflictError(f"该盘口的{status_name}值已存在，请刷新后重试。") from exc
    await session.refresh(entry)
    return _entry_response(entry, source_display_name=source.display_name)


async def update_withdraw_status(
    session: AsyncSession,
    *,
    entry_id: int,
    entry_label: str | None,
    active: bool | None,
    actor_user_id: int,
) -> DataDictionaryEntryResponse:
    return await _update_status_entry(
        session,
        entry_id=entry_id,
        entry_label=entry_label,
        active=active,
        actor_user_id=actor_user_id,
        dictionary_type=WITHDRAW_STATUS_DICTIONARY,
        status_name="提现状态",
        audit_action="data_dictionary.withdraw_status.update",
    )


async def update_charge_status(
    session: AsyncSession,
    *,
    entry_id: int,
    entry_label: str | None,
    active: bool | None,
    actor_user_id: int,
) -> DataDictionaryEntryResponse:
    return await _update_status_entry(
        session,
        entry_id=entry_id,
        entry_label=entry_label,
        active=active,
        actor_user_id=actor_user_id,
        dictionary_type=CHARGE_STATUS_DICTIONARY,
        status_name="充值订单状态",
        audit_action="data_dictionary.charge_status.update",
    )


async def _update_status_entry(
    session: AsyncSession,
    *,
    entry_id: int,
    entry_label: str | None,
    active: bool | None,
    actor_user_id: int,
    dictionary_type: str,
    status_name: str,
    audit_action: str,
) -> DataDictionaryEntryResponse:
    if entry_label is None and active is None:
        raise DataDictionaryValidationError("请至少修改展示文案或启用状态。")
    entry = await session.scalar(
        select(DataDictionaryEntry).where(
            DataDictionaryEntry.id == entry_id,
            DataDictionaryEntry.dictionary_type == dictionary_type,
        )
    )
    if entry is None:
        raise DataDictionaryNotFoundError(f"{status_name}字典条目不存在。")
    source = await session.get(SourceConfig, entry.source_id)
    if source is None:
        raise DataDictionaryNotFoundError("关联的盘口配置不存在。")
    changed_fields: list[str] = []
    if entry_label is not None and entry.entry_label != entry_label:
        entry.entry_label = entry_label
        changed_fields.append("entry_label")
    if active is not None and entry.active != active:
        entry.active = active
        changed_fields.append("active")
    if changed_fields:
        entry.updated_at = datetime.now(UTC)
        await write_audit(
            session,
            action=audit_action,
            actor_user_id=actor_user_id,
            target_type="data_dictionary_entry",
            target_id=f"{entry.source_id}:{dictionary_type}:{entry.entry_code}",
            metadata={"changed_fields": changed_fields},
        )
        await session.commit()
    return _entry_response(entry, source_display_name=source.display_name)
