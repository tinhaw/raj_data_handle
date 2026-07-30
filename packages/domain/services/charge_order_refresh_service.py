from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.security import decrypt_credentials
from packages.common.settings import Settings, get_settings
from packages.domain.models import ChargeOrderRefreshState, ChargeOrderSnapshot, SourceConfig
from packages.domain.services.auth_service import write_audit
from packages.domain.services.data_dictionary_service import (
    sync_payment_channel_names,
    sync_payment_channels,
)
from packages.domain.services.remote_charge_service import ChargeFetchResult, RajAdminChargeClient
from packages.domain.services.source_service import get_source
from packages.domain.services.system_setting_service import get_retention_settings
from packages.domain.services.withdraw_order_service import (
    WITHDRAW_ORDER_QUERY_RANGES,
    withdraw_order_query_window,
)

WALL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
REFRESH_LEASE_DURATION = timedelta(minutes=30)


class ChargeOrderRefreshValidationError(ValueError):
    pass


class ChargeOrderRefreshClaimLostError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ChargeOrderRefreshQueueResult:
    source_ids: list[str]
    requested_at: datetime
    query_range: str | None


@dataclass(frozen=True, slots=True)
class ChargeOrderRefreshRunResult:
    source_id: str
    status: str
    remote_total: int = 0
    cached_total: int = 0


@dataclass(frozen=True, slots=True)
class _RefreshClaim:
    source_id: str
    base_url: str
    encrypted_credentials: str
    credential_version: int
    business_timezone: str
    page_size: int
    query_range: str
    started_at: datetime
    window_start: datetime
    window_end: datetime


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _now(value: datetime | None = None) -> datetime:
    candidate = value or datetime.now(UTC)
    return candidate if candidate.tzinfo else candidate.replace(tzinfo=UTC)


def _safe_text(value: object, *, limit: int) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized[:limit] if normalized else None


def _parse_wall_time(value: object, *, timezone_name: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return (
            datetime.strptime(text, WALL_TIME_FORMAT)
            .replace(tzinfo=ZoneInfo(timezone_name))
            .astimezone(UTC)
        )
    except ValueError:
        return None


def _is_missing_charge_schema(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    return ("charge_order_snapshots" in message or "charge_order_refresh_states" in message) and (
        "does not exist" in message or "no such table" in message
    )


def _eligible(source: SourceConfig) -> bool:
    return bool(source.enabled and source.base_url and source.encrypted_credentials)


async def _state(
    session: AsyncSession, *, source_id: str, now: datetime
) -> ChargeOrderRefreshState:
    existing = await session.get(
        ChargeOrderRefreshState,
        source_id,
        with_for_update=True,
        populate_existing=True,
    )
    if existing is not None:
        return existing
    created = ChargeOrderRefreshState(source_id=source_id, updated_at=now)
    try:
        async with session.begin_nested():
            session.add(created)
            await session.flush()
    except IntegrityError:
        existing = await session.get(
            ChargeOrderRefreshState,
            source_id,
            with_for_update=True,
            populate_existing=True,
        )
        if existing is not None:
            return existing
        raise
    return created


def _due(state: ChargeOrderRefreshState, *, interval_hours: int, now: datetime) -> bool:
    lease = _as_utc(state.lease_expires_at)
    started = _as_utc(state.last_started_at)
    manual = _as_utc(state.manual_request_at)
    if lease is not None and lease > now:
        return False
    if state.status == "running" and lease is not None:
        return True
    if manual is not None and (started is None or manual > started):
        return True
    anchor = _as_utc(state.last_succeeded_at) or _as_utc(state.last_failed_at)
    return anchor is None or now >= anchor + timedelta(hours=interval_hours)


async def queue_charge_order_refreshes(
    session: AsyncSession,
    *,
    source_id: str | None,
    query_range: str | None = None,
    actor_user_id: int | None,
    now: datetime | None = None,
) -> ChargeOrderRefreshQueueResult:
    if query_range is not None and query_range not in WITHDRAW_ORDER_QUERY_RANGES:
        raise ChargeOrderRefreshValidationError("不支持的充值订单刷新时间范围。")
    requested_at = _now(now)
    if source_id:
        sources = [await get_source(session, source_id)]
    else:
        sources = list(
            await session.scalars(
                select(SourceConfig)
                .where(
                    SourceConfig.enabled.is_(True),
                    SourceConfig.base_url.is_not(None),
                    SourceConfig.encrypted_credentials.is_not(None),
                )
                .order_by(SourceConfig.source_id)
            )
        )
    if not sources:
        raise ChargeOrderRefreshValidationError("没有可同步的已启用盘口。")
    if source_id and not _eligible(sources[0]):
        raise ChargeOrderRefreshValidationError("所选盘口尚未启用或缺少远端读取凭据。")
    ids: list[str] = []
    try:
        for source in sources:
            state = await _state(session, source_id=source.source_id, now=requested_at)
            state.manual_request_at = requested_at
            state.manual_query_range = query_range
            if not (
                state.status == "running"
                and (_as_utc(state.lease_expires_at) or requested_at) > requested_at
            ):
                state.status = "queued"
            state.updated_at = requested_at
            ids.append(source.source_id)
        await write_audit(
            session,
            action="charge_order.refresh.queue",
            actor_user_id=actor_user_id,
            target_type="charge_order_refresh",
            target_id=source_id or "all",
            metadata={"sourceIds": ids, "queryRange": query_range},
        )
        await session.commit()
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_charge_schema(exc):
            raise
        await session.rollback()
        from packages.domain.services.charge_order_service import ChargeOrderCacheSchemaPendingError

        raise ChargeOrderCacheSchemaPendingError(
            "充值订单本地缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc
    return ChargeOrderRefreshQueueResult(ids, requested_at, query_range)


async def _claim_due(
    session: AsyncSession, *, now: datetime, settings: Settings
) -> _RefreshClaim | None:
    retention = await get_retention_settings(session, defaults=settings)
    sources = list(
        await session.scalars(
            select(SourceConfig)
            .where(
                SourceConfig.enabled.is_(True),
                SourceConfig.base_url.is_not(None),
                SourceConfig.encrypted_credentials.is_not(None),
            )
            .order_by(SourceConfig.source_id)
        )
    )
    for source in sources:
        state = await _state(session, source_id=source.source_id, now=now)
        if not _due(
            state,
            interval_hours=retention.charge_order_refresh_interval_hours,
            now=now,
        ):
            continue
        manual = _as_utc(state.manual_request_at)
        started = _as_utc(state.last_started_at)
        manual_requested = manual is not None and (started is None or manual > started)
        query_range = (
            state.manual_query_range
            if manual_requested and state.manual_query_range
            else retention.charge_order_query_range
        )
        window_start, window_end = withdraw_order_query_window(
            query_range=query_range,
            timezone_name=source.business_timezone,
            now=now,
        )
        state.status = "running"
        state.last_started_at = now
        state.last_window_start_utc = window_start
        state.last_window_end_utc = window_end
        state.lease_expires_at = now + REFRESH_LEASE_DURATION
        state.last_error = None
        state.updated_at = now
        await session.commit()
        return _RefreshClaim(
            source_id=source.source_id,
            base_url=source.base_url or "",
            encrypted_credentials=source.encrypted_credentials or "",
            credential_version=source.credential_version,
            business_timezone=source.business_timezone,
            page_size=retention.charge_order_refresh_page_size,
            query_range=query_range,
            started_at=now,
            window_start=window_start,
            window_end=window_end,
        )
    await session.commit()
    return None


async def _renew(session: AsyncSession, *, claim: _RefreshClaim) -> None:
    state = await session.get(
        ChargeOrderRefreshState,
        claim.source_id,
        with_for_update=True,
        populate_existing=True,
    )
    if (
        state is None
        or state.status != "running"
        or _as_utc(state.last_started_at) != claim.started_at
    ):
        raise ChargeOrderRefreshClaimLostError("充值订单同步租约已失效。")
    now = datetime.now(UTC)
    state.lease_expires_at = now + REFRESH_LEASE_DURATION
    state.updated_at = now
    await session.commit()


async def _rows_by_id(
    session: AsyncSession, *, source_id: str, remote_ids: list[str]
) -> dict[str, ChargeOrderSnapshot]:
    existing: dict[str, ChargeOrderSnapshot] = {}
    for offset in range(0, len(remote_ids), 500):
        rows = list(
            await session.scalars(
                select(ChargeOrderSnapshot).where(
                    ChargeOrderSnapshot.source_id == source_id,
                    ChargeOrderSnapshot.remote_order_id.in_(remote_ids[offset : offset + 500]),
                )
            )
        )
        existing.update({row.remote_order_id: row for row in rows})
    return existing


def _apply(
    snapshot: ChargeOrderSnapshot,
    *,
    order: dict[str, Any],
    claim: _RefreshClaim,
    now: datetime,
) -> None:
    snapshot.uid = _safe_text(order.get("uid"), limit=64) or ""
    snapshot.order_num = _safe_text(order.get("order_num"), limit=160)
    snapshot.out_trade_no = _safe_text(order.get("out_trade_no"), limit=160)
    snapshot.pay_method = _safe_text(order.get("pay_method"), limit=120)
    snapshot.pay_channel_name = _safe_text(order.get("pay_channel_name"), limit=160)
    snapshot.amount = _safe_text(order.get("amount"), limit=64)
    snapshot.balance = _safe_text(order.get("balance"), limit=64)
    snapshot.extra = _safe_text(order.get("extra"), limit=64)
    snapshot.status = _safe_text(order.get("status"), limit=40) or ""
    snapshot.create_time = _safe_text(order.get("create_time"), limit=32)
    snapshot.create_time_utc = _parse_wall_time(
        snapshot.create_time,
        timezone_name=claim.business_timezone,
    )
    snapshot.pay_time = _safe_text(order.get("pay_time"), limit=32)
    snapshot.update_time = _safe_text(order.get("update_time"), limit=32)
    snapshot.first_pay = _safe_text(order.get("first_pay"), limit=40)
    snapshot.notified = _safe_text(order.get("notified"), limit=40)
    snapshot.charge_type = _safe_text(order.get("charge_type"), limit=80)
    snapshot.channel = _safe_text(order.get("channel"), limit=120)
    snapshot.fill_order_id = _safe_text(order.get("fill_order_id"), limit=120)
    snapshot.fill_order_num = _safe_text(order.get("fill_order_num"), limit=160)
    snapshot.fill_order_admin = _safe_text(order.get("fill_order_admin"), limit=160)
    snapshot.last_seen_at = now
    snapshot.synced_at = now


async def _persist_success(
    session: AsyncSession,
    *,
    claim: _RefreshClaim,
    fetched: ChargeFetchResult,
    finished_at: datetime,
) -> ChargeOrderRefreshRunResult:
    state = await session.get(
        ChargeOrderRefreshState,
        claim.source_id,
        with_for_update=True,
        populate_existing=True,
    )
    if state is None or _as_utc(state.last_started_at) != claim.started_at:
        return ChargeOrderRefreshRunResult(claim.source_id, "superseded")
    by_id = {
        remote_id: order
        for order in fetched.orders
        if (remote_id := _safe_text(order.get("id"), limit=120))
    }
    existing = await _rows_by_id(session, source_id=claim.source_id, remote_ids=list(by_id))
    for remote_id, order in by_id.items():
        snapshot = existing.get(remote_id)
        if snapshot is None:
            snapshot = ChargeOrderSnapshot(
                source_id=claim.source_id,
                remote_order_id=remote_id,
                first_seen_at=finished_at,
                last_seen_at=finished_at,
                synced_at=finished_at,
            )
            session.add(snapshot)
        _apply(snapshot, order=order, claim=claim, now=finished_at)
    await session.flush()
    if fetched.complete:
        rows = list(
            await session.scalars(
                select(ChargeOrderSnapshot).where(
                    ChargeOrderSnapshot.source_id == claim.source_id,
                    ChargeOrderSnapshot.create_time_utc.is_not(None),
                    ChargeOrderSnapshot.create_time_utc >= claim.window_start,
                    ChargeOrderSnapshot.create_time_utc <= claim.window_end,
                )
            )
        )
        for row in rows:
            if row.remote_order_id not in by_id:
                await session.delete(row)
    cached_total = int(
        await session.scalar(
            select(func.count())
            .select_from(ChargeOrderSnapshot)
            .where(
                ChargeOrderSnapshot.source_id == claim.source_id,
                ChargeOrderSnapshot.create_time_utc.is_not(None),
                ChargeOrderSnapshot.create_time_utc >= claim.window_start,
                ChargeOrderSnapshot.create_time_utc <= claim.window_end,
            )
        )
        or 0
    )
    state.status = "succeeded"
    state.last_succeeded_at = finished_at
    state.last_remote_total = fetched.remote_total
    state.last_cached_total = cached_total
    state.last_fetched_pages = fetched.fetched_pages
    state.last_complete = fetched.complete
    state.last_error = None
    state.lease_expires_at = None
    if (
        _as_utc(state.manual_request_at) is not None
        and _as_utc(state.manual_request_at) <= claim.started_at
    ):
        state.manual_request_at = None
        state.manual_query_range = None
    state.updated_at = finished_at
    await session.commit()
    return ChargeOrderRefreshRunResult(
        claim.source_id,
        "succeeded",
        fetched.remote_total,
        cached_total,
    )


async def _failure(
    session: AsyncSession, *, claim: _RefreshClaim, finished_at: datetime
) -> ChargeOrderRefreshRunResult:
    state = await session.get(
        ChargeOrderRefreshState,
        claim.source_id,
        with_for_update=True,
        populate_existing=True,
    )
    if state is None or _as_utc(state.last_started_at) != claim.started_at:
        return ChargeOrderRefreshRunResult(claim.source_id, state.status if state else "failed")
    state.status = "failed"
    state.last_failed_at = finished_at
    state.last_error = "远端充值订单读取失败，请稍后重试。"
    state.lease_expires_at = None
    if (
        _as_utc(state.manual_request_at) is not None
        and _as_utc(state.manual_request_at) <= claim.started_at
    ):
        state.manual_request_at = None
        state.manual_query_range = None
    state.updated_at = finished_at
    await session.commit()
    return ChargeOrderRefreshRunResult(claim.source_id, "failed")


async def _execute(
    session: AsyncSession, *, claim: _RefreshClaim, settings: Settings
) -> ChargeOrderRefreshRunResult:
    try:
        credentials = decrypt_credentials(
            claim.encrypted_credentials,
            source_id=claim.source_id,
            credential_version=claim.credential_version,
            settings=settings,
        )
        async with RajAdminChargeClient(
            base_url=claim.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            page_size=claim.page_size,
        ) as client:
            channel_names = await client.fetch_channels()
            payment_channels = await client.fetch_payment_channels()
            fetched = await client.fetch_all_charge_orders(
                channels=payment_channels,
                create_start=claim.window_start.astimezone(
                    ZoneInfo(claim.business_timezone)
                ).strftime(WALL_TIME_FORMAT),
                create_end=claim.window_end.astimezone(ZoneInfo(claim.business_timezone)).strftime(
                    WALL_TIME_FORMAT
                ),
                on_page_fetched=lambda: _renew(session, claim=claim),
            )
        await sync_payment_channels(
            session,
            source_id=claim.source_id,
            channels=payment_channels,
        )
        await sync_payment_channel_names(
            session,
            source_id=claim.source_id,
            channels=channel_names,
        )
    except asyncio.CancelledError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        return await _failure(session, claim=claim, finished_at=datetime.now(UTC))
    return await _persist_success(
        session,
        claim=claim,
        fetched=fetched,
        finished_at=datetime.now(UTC),
    )


async def run_due_charge_order_refreshes(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[ChargeOrderRefreshRunResult]:
    current_settings = settings or get_settings()
    run_at = _now(now)
    results: list[ChargeOrderRefreshRunResult] = []
    while True:
        try:
            claim = await _claim_due(session, now=run_at, settings=current_settings)
        except (OperationalError, ProgrammingError) as exc:
            if not _is_missing_charge_schema(exc):
                raise
            await session.rollback()
            return results
        if claim is None:
            return results
        results.append(await _execute(session, claim=claim, settings=current_settings))
        run_at = datetime.now(UTC)
