from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import DataDictionaryRefreshConfig, SourceConfig
from packages.domain.schemas.data_dictionary import (
    DataDictionaryRefreshConfigResponse,
    RemoteDataDictionaryType,
)
from packages.domain.services.auth_service import write_audit
from packages.domain.services.data_dictionary_service import (
    PAYMENT_CHANNEL_DICTIONARY,
    PAYMENT_CHANNEL_NAME_DICTIONARY,
    REMOTE_DATA_DICTIONARY_TYPES,
    USER_SOURCE_CHANNEL_DICTIONARY,
    WITHDRAW_STATUS_DICTIONARY,
    DataDictionaryNotFoundError,
    DataDictionaryValidationError,
    sync_remote_payment_dictionary,
    sync_remote_user_source_channels,
    sync_remote_withdraw_statuses,
)
from packages.domain.services.remote_account_credentials import (
    resolve_default_remote_account_credentials,
)

DEFAULT_REFRESH_INTERVAL_MINUTES = 360
ALLOWED_REFRESH_INTERVAL_MINUTES = frozenset({15, 30, 60, 180, 360, 720, 1440})
REFRESH_LEASE_DURATION = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class DataDictionaryRefreshOutcome:
    source_id: str
    dictionary_type: str
    status: str


@dataclass(frozen=True, slots=True)
class _RefreshClaim:
    source_id: str
    dictionary_type: str


def _now(value: datetime | None = None) -> datetime:
    candidate = value or datetime.now(UTC)
    return candidate if candidate.tzinfo else candidate.replace(tzinfo=UTC)


def _validate_dictionary_type(dictionary_type: str) -> str:
    if dictionary_type not in REMOTE_DATA_DICTIONARY_TYPES:
        raise DataDictionaryValidationError("该字典未配置可自动刷新的远端数据接口。")
    return dictionary_type


def _response(
    *,
    source: SourceConfig,
    dictionary_type: str,
    config: DataDictionaryRefreshConfig | None,
) -> DataDictionaryRefreshConfigResponse:
    return DataDictionaryRefreshConfigResponse(
        source_id=source.source_id,
        source_display_name=source.display_name,
        dictionary_type=cast(RemoteDataDictionaryType, dictionary_type),
        enabled=config.enabled if config is not None else False,
        interval_minutes=(
            config.interval_minutes if config is not None else DEFAULT_REFRESH_INTERVAL_MINUTES
        ),
        status=config.status if config is not None else "idle",
        last_started_at=config.last_started_at if config is not None else None,
        last_succeeded_at=config.last_succeeded_at if config is not None else None,
        last_failed_at=config.last_failed_at if config is not None else None,
        last_error=config.last_error if config is not None else None,
        next_refresh_at=config.next_refresh_at if config is not None else None,
        updated_at=config.updated_at if config is not None else None,
    )


async def get_data_dictionary_refresh_config(
    session: AsyncSession,
    *,
    source_id: str,
    dictionary_type: str,
) -> DataDictionaryRefreshConfigResponse:
    dictionary_type = _validate_dictionary_type(dictionary_type)
    source = await session.get(SourceConfig, source_id)
    if source is None:
        raise DataDictionaryNotFoundError("盘口配置不存在。")
    config = await session.get(DataDictionaryRefreshConfig, (source_id, dictionary_type))
    return _response(source=source, dictionary_type=dictionary_type, config=config)


async def update_data_dictionary_refresh_config(
    session: AsyncSession,
    *,
    source_id: str,
    dictionary_type: str,
    enabled: bool,
    interval_minutes: int,
    actor_user_id: int,
    now: datetime | None = None,
) -> DataDictionaryRefreshConfigResponse:
    dictionary_type = _validate_dictionary_type(dictionary_type)
    if interval_minutes not in ALLOWED_REFRESH_INTERVAL_MINUTES:
        raise DataDictionaryValidationError("不支持的自动刷新时间间隔。")
    source = await session.get(SourceConfig, source_id)
    if source is None:
        raise DataDictionaryNotFoundError("盘口配置不存在。")
    if enabled:
        if not source.enabled or not source.base_url:
            raise DataDictionaryValidationError("所选盘口尚未启用或缺少远端地址。")
        credentials = await resolve_default_remote_account_credentials(session, source=source)
        if credentials is None:
            raise DataDictionaryValidationError("所选盘口缺少已启用的默认远端账号。")

    updated_at = _now(now)
    config = await session.get(
        DataDictionaryRefreshConfig,
        (source_id, dictionary_type),
        with_for_update=True,
    )
    if config is None:
        config = DataDictionaryRefreshConfig(
            source_id=source_id,
            dictionary_type=dictionary_type,
            created_at=updated_at,
        )
        session.add(config)
    config.enabled = enabled
    config.interval_minutes = interval_minutes
    config.updated_by = actor_user_id
    config.updated_at = updated_at
    config.lease_expires_at = None
    if enabled:
        # Saving settings must not unexpectedly call a remote system. The first
        # automatic run starts after one complete configured interval.
        config.next_refresh_at = updated_at + timedelta(minutes=interval_minutes)
        if config.status == "running":
            config.status = "idle"
    else:
        config.next_refresh_at = None
        if config.status == "running":
            config.status = "idle"
    await write_audit(
        session,
        action="data_dictionary.auto_refresh_config.update",
        actor_user_id=actor_user_id,
        target_type="data_dictionary_refresh_config",
        target_id=f"{source_id}:{dictionary_type}",
        metadata={
            "source_id": source_id,
            "dictionary_type": dictionary_type,
            "enabled": enabled,
            "interval_minutes": interval_minutes,
        },
    )
    await session.commit()
    return _response(source=source, dictionary_type=dictionary_type, config=config)


async def _claim_due_config(
    session: AsyncSession,
    *,
    now: datetime,
) -> _RefreshClaim | None:
    config = await session.scalar(
        select(DataDictionaryRefreshConfig)
        .where(
            DataDictionaryRefreshConfig.enabled.is_(True),
            DataDictionaryRefreshConfig.next_refresh_at.is_not(None),
            DataDictionaryRefreshConfig.next_refresh_at <= now,
            or_(
                DataDictionaryRefreshConfig.lease_expires_at.is_(None),
                DataDictionaryRefreshConfig.lease_expires_at <= now,
            ),
        )
        .order_by(
            DataDictionaryRefreshConfig.next_refresh_at,
            DataDictionaryRefreshConfig.source_id,
            DataDictionaryRefreshConfig.dictionary_type,
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if config is None:
        return None
    config.status = "running"
    config.last_started_at = now
    config.lease_expires_at = now + REFRESH_LEASE_DURATION
    config.updated_at = now
    claim = _RefreshClaim(config.source_id, config.dictionary_type)
    await session.commit()
    return claim


async def _execute_claim(
    session: AsyncSession,
    *,
    claim: _RefreshClaim,
    now: datetime | None = None,
) -> DataDictionaryRefreshOutcome:
    try:
        if claim.dictionary_type == WITHDRAW_STATUS_DICTIONARY:
            await sync_remote_withdraw_statuses(
                session,
                source_id=claim.source_id,
                actor_user_id=None,
                trigger_type="automatic",
            )
        elif claim.dictionary_type == USER_SOURCE_CHANNEL_DICTIONARY:
            await sync_remote_user_source_channels(
                session,
                source_id=claim.source_id,
                actor_user_id=None,
                trigger_type="automatic",
            )
        elif claim.dictionary_type in {
            PAYMENT_CHANNEL_DICTIONARY,
            PAYMENT_CHANNEL_NAME_DICTIONARY,
        }:
            await sync_remote_payment_dictionary(
                session,
                source_id=claim.source_id,
                dictionary_type=claim.dictionary_type,
                actor_user_id=None,
                trigger_type="automatic",
            )
        else:
            raise DataDictionaryValidationError("不支持的远端字典类型。")
    except Exception:
        await session.rollback()
        finished_at = _now(now)
        config = await session.get(
            DataDictionaryRefreshConfig,
            (claim.source_id, claim.dictionary_type),
            with_for_update=True,
            populate_existing=True,
        )
        if config is not None:
            config.status = "failed"
            config.last_failed_at = finished_at
            config.last_error = "自动刷新失败，本地字典保持不变。"
            config.lease_expires_at = None
            config.next_refresh_at = (
                finished_at + timedelta(minutes=config.interval_minutes) if config.enabled else None
            )
            config.updated_at = finished_at
            await write_audit(
                session,
                action="data_dictionary.auto_refresh.failure",
                target_type="data_dictionary_refresh_config",
                target_id=f"{claim.source_id}:{claim.dictionary_type}",
                result="failure",
                metadata={
                    "source_id": claim.source_id,
                    "dictionary_type": claim.dictionary_type,
                },
            )
            await session.commit()
        return DataDictionaryRefreshOutcome(
            claim.source_id,
            claim.dictionary_type,
            "failed",
        )

    finished_at = _now(now)
    config = await session.get(
        DataDictionaryRefreshConfig,
        (claim.source_id, claim.dictionary_type),
        with_for_update=True,
        populate_existing=True,
    )
    if config is not None:
        config.status = "succeeded"
        config.last_succeeded_at = finished_at
        config.last_error = None
        config.lease_expires_at = None
        config.next_refresh_at = (
            finished_at + timedelta(minutes=config.interval_minutes) if config.enabled else None
        )
        config.updated_at = finished_at
        await session.commit()
    return DataDictionaryRefreshOutcome(
        claim.source_id,
        claim.dictionary_type,
        "succeeded",
    )


async def run_due_data_dictionary_refreshes(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    max_runs: int = 20,
) -> list[DataDictionaryRefreshOutcome]:
    outcomes: list[DataDictionaryRefreshOutcome] = []
    for _ in range(max_runs):
        claim = await _claim_due_config(session, now=_now(now))
        if claim is None:
            break
        outcomes.append(await _execute_claim(session, claim=claim, now=now))
    return outcomes
