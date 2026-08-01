from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.security import decrypt_credentials
from packages.common.settings import Settings, get_settings
from packages.domain.models import (
    SourceConfig,
    SpinOrderRefreshState,
    SpinOrderSnapshot,
    UserChannelCache,
)
from packages.domain.services.auth_service import write_audit
from packages.domain.services.automatic_refresh_retry import (
    can_retry_failed_automatic_window,
)
from packages.domain.services.data_dictionary_service import ensure_spin_order_statuses
from packages.domain.services.data_sync_run_service import (
    SyncRunMetrics,
    add_sync_run_event,
    cancel_sync_run,
    complete_sync_run,
    create_sync_run,
    fail_sync_run,
    get_sync_run_for_update,
    mark_sync_run_running,
    supersede_sync_run,
)
from packages.domain.services.remote_spin_service import RajAdminSpinClient, SpinFetchResult
from packages.domain.services.source_service import get_source
from packages.domain.services.spin_order_service import SPIN_CONFIG_LABELS
from packages.domain.services.system_setting_service import get_retention_settings

WALL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
REFRESH_LEASE_DURATION = timedelta(minutes=45)
CHANNEL_RETRY_DELAY = timedelta(minutes=30)
CHANNEL_LOOKUP_CONCURRENCY = 8
SPIN_MANUAL_REFRESH_RANGES = frozenset({"day_before_yesterday", "yesterday", "today"})
SPIN_AUTOMATIC_QUERY_RANGES = frozenset(
    {
        "last_completed_slot",
        "business_day_to_completed_slot",
        "previous_business_day_to_completed_slot",
        "last_2_hours",
        "last_3_hours",
        "last_6_hours",
        "last_12_hours",
        "previous_day",
    }
)
SPIN_RECENT_HOUR_RANGES = {
    "last_2_hours": 2,
    "last_3_hours": 3,
    "last_6_hours": 6,
    "last_12_hours": 12,
}
AUTOMATIC_SLOT_GRACE = timedelta(minutes=5)


class SpinOrderRefreshValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SpinOrderRefreshQueueResult:
    source_ids: list[str]
    requested_at: datetime
    query_range: str | None


@dataclass(frozen=True, slots=True)
class SpinOrderRefreshRunResult:
    source_id: str
    status: str
    remote_total: int = 0
    cached_total: int = 0


@dataclass(frozen=True, slots=True)
class _Claim:
    source_id: str
    base_url: str
    encrypted_credentials: str
    credential_version: int
    business_timezone: str
    started_at: datetime
    window_start: datetime
    window_end: datetime
    query_range: str | None
    page_size: int
    sync_run_id: str


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _now(value: datetime | None = None) -> datetime:
    return _as_utc(value or datetime.now(UTC)) or datetime.now(UTC)


def _safe_text(value: object, *, limit: int) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:limit] if text else None


def _parse_wall_time(value: str | None, *, timezone_name: str) -> datetime | None:
    if not value:
        return None
    try:
        return (
            datetime.strptime(value, WALL_TIME_FORMAT)
            .replace(tzinfo=ZoneInfo(timezone_name))
            .astimezone(UTC)
        )
    except ValueError:
        return None


def _missing_schema(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    missing_table = (
        "spin_order_snapshots" in message
        or "spin_order_refresh_states" in message
        or "data_sync_runs" in message
        or "data_sync_run_events" in message
    ) and ("does not exist" in message or "no such table" in message)
    missing_pointer = (
        "pending_sync_run_id" in message
        or "active_sync_run_id" in message
        or "automatic_failure_count" in message
    ) and (
        "does not exist" in message
        or "no such table" in message
        or "no such column" in message
    )
    return missing_table or missing_pointer


async def _state(
    session: AsyncSession,
    *,
    source_id: str,
    now: datetime,
) -> SpinOrderRefreshState:
    state = await session.get(
        SpinOrderRefreshState, source_id, with_for_update=True, populate_existing=True
    )
    if state is not None:
        return state
    created = SpinOrderRefreshState(source_id=source_id, updated_at=now)
    try:
        async with session.begin_nested():
            session.add(created)
            await session.flush()
    except IntegrityError:
        state = await session.get(
            SpinOrderRefreshState, source_id, with_for_update=True, populate_existing=True
        )
        if state is not None:
            return state
        raise
    return created


def _eligible(source: SourceConfig) -> bool:
    return bool(source.enabled and source.base_url and source.encrypted_credentials)


def _manual_pending(state: SpinOrderRefreshState) -> bool:
    return _as_utc(state.manual_request_at) is not None and (
        _as_utc(state.last_started_at) is None
        or _as_utc(state.manual_request_at) > _as_utc(state.last_started_at)
    )


def _day_window(*, day: date, timezone_name: str) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(timezone_name)
    return (
        datetime.combine(day, time.min, tzinfo=timezone).astimezone(UTC),
        datetime.combine(day, time(23, 59, 59), tzinfo=timezone).astimezone(UTC),
    )


def _automatic_slot_start(*, local_now: datetime, interval_hours: int) -> datetime:
    return local_now.replace(
        hour=(local_now.hour // interval_hours) * interval_hours,
        minute=0,
        second=0,
        microsecond=0,
    )


def _automatic_window(
    *,
    timezone_name: str,
    now: datetime,
    interval_hours: int,
    query_range: str,
) -> tuple[datetime, datetime]:
    """Return the configured completed-slot review window.

    The end is always the last second before the currently running slot, so a
    refresh never reads orders whose state is still changing. The selected
    range controls how far back the cache is reconciled, while keeping a
    stable scheduling key for the whole current slot.
    """

    if query_range not in SPIN_AUTOMATIC_QUERY_RANGES:
        raise SpinOrderRefreshValidationError("不支持的转盘订单自动查询范围。")

    local_now = now.astimezone(ZoneInfo(timezone_name))
    current_slot_start = _automatic_slot_start(
        local_now=local_now,
        interval_hours=interval_hours,
    )
    completed_start_local = current_slot_start - timedelta(hours=interval_hours)
    completed_end_local = current_slot_start - timedelta(seconds=1)
    if query_range in SPIN_RECENT_HOUR_RANGES:
        review_start_local = current_slot_start - timedelta(
            hours=SPIN_RECENT_HOUR_RANGES[query_range]
        )
    elif query_range == "previous_day":
        review_start_local = (local_now - timedelta(days=1)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        completed_end_local = review_start_local.replace(
            hour=23,
            minute=59,
            second=59,
        )
    elif query_range == "last_completed_slot":
        review_start_local = completed_start_local
    elif query_range == "business_day_to_completed_slot":
        review_start_local = completed_end_local.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    else:
        review_start_local = (completed_end_local - timedelta(days=1)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    return review_start_local.astimezone(UTC), completed_end_local.astimezone(UTC)


def _automatic_slot_is_ready(
    *, timezone_name: str, now: datetime, interval_hours: int
) -> bool:
    """Wait briefly after a configured time-slot boundary before refreshing."""

    local_now = now.astimezone(ZoneInfo(timezone_name))
    current_slot_start = _automatic_slot_start(
        local_now=local_now,
        interval_hours=interval_hours,
    )
    return local_now >= current_slot_start + AUTOMATIC_SLOT_GRACE


def _manual_window(
    *,
    query_range: str,
    timezone_name: str,
    now: datetime,
) -> tuple[datetime, datetime]:
    offsets = {"day_before_yesterday": 2, "yesterday": 1, "today": 0}
    local_now = now.astimezone(ZoneInfo(timezone_name))
    selected_day = local_now.date() - timedelta(days=offsets[query_range])
    start, end = _day_window(day=selected_day, timezone_name=timezone_name)
    return start, min(end, now) if query_range == "today" else end


def _due(
    state: SpinOrderRefreshState,
    *,
    now: datetime,
    window_end: datetime,
    retry_limit: int,
    retry_interval_minutes: int,
) -> bool:
    lease = _as_utc(state.lease_expires_at)
    if lease is not None and lease > now:
        return False
    if state.status == "running" and lease is not None:
        return True
    if _manual_pending(state):
        return True
    previous_end = _as_utc(state.last_window_end_utc)
    if state.status == "succeeded" and previous_end == window_end:
        return False
    if not can_retry_failed_automatic_window(
        status=state.status,
        previous_window_marker=previous_end,
        automatic_window_marker=window_end,
        last_failed_at=_as_utc(state.last_failed_at),
        automatic_failure_count=state.automatic_failure_count,
        retry_limit=retry_limit,
        retry_interval_minutes=retry_interval_minutes,
        now=now,
    ):
        return False
    return True


async def queue_spin_order_refreshes(
    session: AsyncSession,
    *,
    source_id: str | None,
    query_range: str | None = None,
    actor_user_id: int | None,
    now: datetime | None = None,
) -> SpinOrderRefreshQueueResult:
    requested_query_range = query_range or "today"
    if requested_query_range not in SPIN_MANUAL_REFRESH_RANGES:
        raise SpinOrderRefreshValidationError("不支持的转盘订单刷新时间范围。")
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
        raise SpinOrderRefreshValidationError("没有可同步的已启用盘口。")
    if source_id and not _eligible(sources[0]):
        raise SpinOrderRefreshValidationError("所选盘口尚未启用或缺少远端读取凭据。")
    try:
        source_ids: list[str] = []
        for source in sources:
            state = await _state(session, source_id=source.source_id, now=requested_at)
            if state.pending_sync_run_id:
                pending_run = await get_sync_run_for_update(
                    session,
                    run_id=state.pending_sync_run_id,
                )
                if pending_run is not None and pending_run.status == "queued":
                    await supersede_sync_run(session, run=pending_run, finished_at=requested_at)
            state.manual_request_at = requested_at
            state.manual_query_range = requested_query_range
            queued_run = await create_sync_run(
                session,
                source=source,
                business_type="spin_orders",
                trigger_type="manual",
                requested_by_user_id=actor_user_id,
                requested_at=requested_at,
                query_range=requested_query_range,
                status="queued",
            )
            state.pending_sync_run_id = queued_run.id
            lease = _as_utc(state.lease_expires_at) or requested_at
            if state.status != "running" or lease <= requested_at:
                state.status = "queued"
            state.updated_at = requested_at
            source_ids.append(source.source_id)
        await write_audit(
            session,
            action="spin_order.refresh.queue",
            actor_user_id=actor_user_id,
            target_type="spin_order_refresh",
            target_id=source_id or "all",
            metadata={"sourceIds": source_ids, "queryRange": requested_query_range},
        )
        await session.commit()
    except (OperationalError, ProgrammingError) as exc:
        if not _missing_schema(exc):
            raise
        await session.rollback()
        raise SpinOrderRefreshValidationError(
            "转盘订单本地缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc
    return SpinOrderRefreshQueueResult(source_ids, requested_at, requested_query_range)


async def _claim_due(
    session: AsyncSession,
    *,
    now: datetime,
    settings: Settings,
) -> _Claim | None:
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
        manual = _manual_pending(state)
        if not manual and not _automatic_slot_is_ready(
            timezone_name=source.business_timezone,
            now=now,
            interval_hours=retention.spin_order_refresh_interval_hours,
        ):
            continue
        automatic_start, automatic_end = _automatic_window(
            timezone_name=source.business_timezone,
            now=now,
            interval_hours=retention.spin_order_refresh_interval_hours,
            query_range=retention.spin_order_query_range,
        )
        if not manual and _as_utc(state.last_window_end_utc) != automatic_end:
            state.automatic_failure_count = 0
        if not _due(
            state,
            now=now,
            window_end=automatic_end,
            retry_limit=retention.automatic_sync_retry_limit,
            retry_interval_minutes=retention.automatic_sync_retry_interval_minutes,
        ):
            continue
        manual_query_range = state.manual_query_range or "today"
        window_start, window_end = (
            _manual_window(
                query_range=manual_query_range,
                timezone_name=source.business_timezone,
                now=now,
            )
            if manual
            else (automatic_start, automatic_end)
        )
        state.status = "running"
        state.last_started_at = now
        state.last_window_start_utc = window_start
        state.last_window_end_utc = window_end
        state.lease_expires_at = now + REFRESH_LEASE_DURATION
        state.last_error = None
        state.updated_at = now
        if manual:
            sync_run = (
                await get_sync_run_for_update(session, run_id=state.pending_sync_run_id)
                if state.pending_sync_run_id
                else None
            )
            if sync_run is None or sync_run.status != "queued":
                # A request created during a rolling release may not have a
                # corresponding log row yet. Preserve the refresh and start a
                # fully tracked manual run from this claim instead.
                sync_run = await create_sync_run(
                    session,
                    source=source,
                    business_type="spin_orders",
                    trigger_type="manual",
                    requested_at=now,
                    query_range=manual_query_range,
                    status="queued",
                )
            await mark_sync_run_running(
                session,
                run=sync_run,
                started_at=now,
                window_start_utc=window_start,
                window_end_utc=window_end,
                query_range=manual_query_range,
                page_size=retention.spin_order_refresh_page_size,
            )
        else:
            sync_run = await create_sync_run(
                session,
                source=source,
                business_type="spin_orders",
                trigger_type="automatic",
                requested_at=now,
                window_start_utc=window_start,
                window_end_utc=window_end,
                query_range=retention.spin_order_query_range,
                page_size=retention.spin_order_refresh_page_size,
                status="running",
            )
        state.pending_sync_run_id = None
        state.active_sync_run_id = sync_run.id
        await session.commit()
        return _Claim(
            source_id=source.source_id,
            base_url=source.base_url or "",
            encrypted_credentials=source.encrypted_credentials or "",
            credential_version=source.credential_version,
            business_timezone=source.business_timezone,
            started_at=now,
            window_start=window_start,
            window_end=window_end,
            query_range=manual_query_range if manual else None,
            page_size=retention.spin_order_refresh_page_size,
            sync_run_id=sync_run.id,
        )
    await session.commit()
    return None


async def _renew(session: AsyncSession, *, claim: _Claim) -> None:
    state = await session.get(
        SpinOrderRefreshState, claim.source_id, with_for_update=True, populate_existing=True
    )
    if (
        state is None
        or state.status != "running"
        or _as_utc(state.last_started_at) != claim.started_at
    ):
        raise RuntimeError("转盘订单同步租约已失效。")
    now = datetime.now(UTC)
    state.lease_expires_at = now + REFRESH_LEASE_DURATION
    state.updated_at = now
    await session.commit()


async def _existing_by_key(
    session: AsyncSession,
    *,
    model: type[SpinOrderSnapshot] | type[UserChannelCache],
    source_id: str,
    values: list[str],
    field: Any,
) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for offset in range(0, len(values), 500):
        selected = list(
            await session.scalars(
                select(model).where(
                    model.source_id == source_id,
                    field.in_(values[offset : offset + 500]),
                )
            )
        )
        rows.update({str(getattr(row, field.key)): row for row in selected})
    return rows


async def _resolve_user_channels(
    session: AsyncSession,
    *,
    source_id: str,
    orders: list[dict[str, Any]],
    client: RajAdminSpinClient,
    now: datetime,
) -> tuple[dict[str, str | None], int, int]:
    uids = sorted({str(order.get("uid") or "").strip() for order in orders if order.get("uid")})
    existing = await _existing_by_key(
        session,
        model=UserChannelCache,
        source_id=source_id,
        values=uids,
        field=UserChannelCache.uid,
    )
    resolved: dict[str, str | None] = {}
    pending: list[str] = []
    for uid in uids:
        cache = existing.get(uid)
        if cache is not None and cache.resolution_status == "resolved":
            resolved[uid] = cache.channel_id
        elif cache is None or (_as_utc(cache.next_retry_at) or now) <= now:
            pending.append(uid)
    if pending:
        await client.login()
        semaphore = asyncio.Semaphore(CHANNEL_LOOKUP_CONCURRENCY)

        async def lookup(uid: str) -> tuple[str, str | None, bool]:
            try:
                async with semaphore:
                    return uid, await client.fetch_user_channel(uid=uid), True
            except Exception:
                return uid, None, False

        for uid, channel_id, valid in await asyncio.gather(*(lookup(uid) for uid in pending)):
            cache = existing.get(uid)
            if cache is None:
                cache = UserChannelCache(source_id=source_id, uid=uid)
                session.add(cache)
                existing[uid] = cache
            cache.channel_id = channel_id
            cache.resolution_status = "resolved" if valid and channel_id else "unresolved"
            cache.last_checked_at = now
            cache.next_retry_at = (
                None if cache.resolution_status == "resolved" else now + CHANNEL_RETRY_DELAY
            )
            cache.updated_at = now
            resolved[uid] = channel_id if cache.resolution_status == "resolved" else None
    for uid, cache in existing.items():
        if uid not in resolved and cache.resolution_status == "resolved":
            resolved[uid] = cache.channel_id
    resolved_count = sum(1 for uid in uids if resolved.get(uid))
    return resolved, resolved_count, len(uids) - resolved_count


def _apply(
    snapshot: SpinOrderSnapshot,
    *,
    order: dict[str, Any],
    claim: _Claim,
    channel_id: str | None,
    now: datetime,
) -> None:
    snapshot.uid = _safe_text(order.get("uid"), limit=64) or ""
    snapshot.vip_level = _safe_text(order.get("vip_level"), limit=40)
    snapshot.agent_total_count = _safe_text(order.get("agent_total_count"), limit=64)
    snapshot.amount = _safe_text(order.get("amount"), limit=64)
    snapshot.spin_config_id = _safe_text(order.get("spin_config_id"), limit=40) or ""
    if snapshot.spin_config_id not in SPIN_CONFIG_LABELS:
        raise SpinOrderRefreshValidationError("转盘订单包含未识别的转盘配置 ID。")
    snapshot.round_number = _safe_text(order.get("round_number"), limit=40)
    snapshot.invite_count = _safe_text(order.get("invite_count"), limit=64)
    snapshot.status = _safe_text(order.get("status"), limit=40) or ""
    snapshot.create_time = _safe_text(order.get("create_time"), limit=32)
    snapshot.create_time_utc = _parse_wall_time(
        snapshot.create_time,
        timezone_name=claim.business_timezone,
    )
    snapshot.audit_time = _safe_text(order.get("audit_time"), limit=32)
    snapshot.audit_time_utc = _parse_wall_time(
        snapshot.audit_time,
        timezone_name=claim.business_timezone,
    )
    if channel_id:
        snapshot.channel_id = _safe_text(channel_id, limit=120)
    snapshot.last_seen_at = now
    snapshot.synced_at = now


async def _persist_success(
    session: AsyncSession,
    *,
    claim: _Claim,
    fetched: SpinFetchResult,
    channels: dict[str, str | None],
    resolved_uid_count: int,
    unresolved_uid_count: int,
    finished_at: datetime,
) -> SpinOrderRefreshRunResult:
    state = await session.get(
        SpinOrderRefreshState, claim.source_id, with_for_update=True, populate_existing=True
    )
    if state is None or _as_utc(state.last_started_at) != claim.started_at:
        return SpinOrderRefreshRunResult(claim.source_id, "superseded")
    sync_run = await get_sync_run_for_update(session, run_id=claim.sync_run_id)
    await ensure_spin_order_statuses(session, source_id=claim.source_id, now=finished_at)
    by_id = {str(order["remote_order_id"]): order for order in fetched.orders}
    existing = await _existing_by_key(
        session,
        model=SpinOrderSnapshot,
        source_id=claim.source_id,
        values=list(by_id),
        field=SpinOrderSnapshot.remote_order_id,
    )
    created_count = sum(1 for remote_order_id in by_id if remote_order_id not in existing)
    updated_count = len(by_id) - created_count
    for remote_order_id, order in by_id.items():
        snapshot = existing.get(remote_order_id)
        if snapshot is None:
            snapshot = SpinOrderSnapshot(
                source_id=claim.source_id,
                remote_order_id=remote_order_id,
                first_seen_at=finished_at,
                last_seen_at=finished_at,
                synced_at=finished_at,
            )
            session.add(snapshot)
        _apply(
            snapshot,
            order=order,
            claim=claim,
            channel_id=channels.get(str(order.get("uid") or "")),
            now=finished_at,
        )
    await session.flush()
    deleted_count = 0
    if fetched.complete:
        rows = list(
            await session.scalars(
                select(SpinOrderSnapshot).where(
                    SpinOrderSnapshot.source_id == claim.source_id,
                    SpinOrderSnapshot.create_time_utc.is_not(None),
                    SpinOrderSnapshot.create_time_utc >= claim.window_start,
                    SpinOrderSnapshot.create_time_utc <= claim.window_end,
                )
            )
        )
        for row in rows:
            if row.remote_order_id not in by_id:
                await session.delete(row)
                deleted_count += 1
    cached_total = int(
        await session.scalar(
            select(func.count())
            .select_from(SpinOrderSnapshot)
            .where(
                SpinOrderSnapshot.source_id == claim.source_id,
                SpinOrderSnapshot.create_time_utc.is_not(None),
                SpinOrderSnapshot.create_time_utc >= claim.window_start,
                SpinOrderSnapshot.create_time_utc <= claim.window_end,
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
    state.automatic_failure_count = 0
    state.last_resolved_uid_count = resolved_uid_count
    state.last_unresolved_uid_count = unresolved_uid_count
    state.last_error = None
    state.lease_expires_at = None
    state.active_sync_run_id = None
    manual_requested_at = _as_utc(state.manual_request_at)
    if manual_requested_at is not None and manual_requested_at <= claim.started_at:
        state.manual_request_at = None
        state.manual_query_range = None
    state.updated_at = finished_at
    if sync_run is not None:
        await complete_sync_run(
            session,
            run=sync_run,
            complete=fetched.complete,
            metrics=SyncRunMetrics(
                remote_total=fetched.remote_total,
                cached_total=cached_total,
                fetched_pages=fetched.fetched_pages,
                imported_count=len(by_id),
                created_count=created_count,
                updated_count=updated_count,
                duplicate_count=fetched.duplicate_count,
                resolved_uid_count=resolved_uid_count,
                unresolved_uid_count=unresolved_uid_count,
            ),
            finished_at=finished_at,
            metadata={"deletedCount": deleted_count},
        )
    await session.commit()
    return SpinOrderRefreshRunResult(
        claim.source_id,
        "succeeded",
        fetched.remote_total,
        cached_total,
    )


async def _failure(
    session: AsyncSession,
    *,
    claim: _Claim,
    finished_at: datetime,
) -> SpinOrderRefreshRunResult:
    state = await session.get(
        SpinOrderRefreshState, claim.source_id, with_for_update=True, populate_existing=True
    )
    if state is None or _as_utc(state.last_started_at) != claim.started_at:
        return SpinOrderRefreshRunResult(claim.source_id, state.status if state else "failed")
    sync_run = await get_sync_run_for_update(session, run_id=claim.sync_run_id)
    state.status = "failed"
    state.last_failed_at = finished_at
    if claim.query_range is None:
        state.automatic_failure_count += 1
    state.last_error = "远端转盘订单列表读取或校验失败，请稍后重试。"
    state.lease_expires_at = None
    state.active_sync_run_id = None
    if (
        _as_utc(state.manual_request_at) is not None
        and _as_utc(state.manual_request_at) <= claim.started_at
    ):
        state.manual_request_at = None
        state.manual_query_range = None
    state.updated_at = finished_at
    if sync_run is not None:
        await fail_sync_run(
            session,
            run=sync_run,
            error_code="remote_spin_sync_failed",
            error_message=state.last_error,
            finished_at=finished_at,
        )
    await session.commit()
    return SpinOrderRefreshRunResult(claim.source_id, "failed")


async def _cancelled(
    session: AsyncSession,
    *,
    claim: _Claim,
    cancelled_at: datetime,
) -> None:
    """Close the run safely and preserve an interrupted manual request."""

    state = await session.get(
        SpinOrderRefreshState,
        claim.source_id,
        with_for_update=True,
        populate_existing=True,
    )
    if state is None or _as_utc(state.last_started_at) != claim.started_at:
        return
    sync_run = await get_sync_run_for_update(session, run_id=claim.sync_run_id)
    if sync_run is not None:
        await cancel_sync_run(
            session,
            run=sync_run,
            finished_at=cancelled_at,
            message="后台工作进程在转盘订单同步完成前停止。",
        )
    state.status = "queued"
    state.active_sync_run_id = None
    state.lease_expires_at = None
    state.last_error = "后台同步在工作进程停止前中断。"
    if claim.query_range is not None and (
        _as_utc(state.manual_request_at) is None
        or _as_utc(state.manual_request_at) <= claim.started_at
    ):
        state.manual_request_at = cancelled_at
        state.manual_query_range = claim.query_range
    state.updated_at = cancelled_at
    await session.commit()


async def _execute(
    session: AsyncSession,
    *,
    claim: _Claim,
    settings: Settings,
) -> SpinOrderRefreshRunResult:
    try:
        credentials = decrypt_credentials(
            claim.encrypted_credentials,
            source_id=claim.source_id,
            credential_version=claim.credential_version,
            settings=settings,
        )
        async with RajAdminSpinClient(
            base_url=claim.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            page_size=claim.page_size,
        ) as client:
            sync_run = await get_sync_run_for_update(session, run_id=claim.sync_run_id)
            if sync_run is not None:
                await add_sync_run_event(
                    session,
                    run=sync_run,
                    event_type="remote_fetch_started",
                    status="running",
                    message="开始读取远端转盘订单列表。",
                )
            await _renew(session, claim=claim)
            fetched = await client.fetch_spin_orders(
                create_start=(
                    claim.window_start.astimezone(ZoneInfo(claim.business_timezone)).strftime(
                        WALL_TIME_FORMAT
                    )
                ),
                create_end=(
                    claim.window_end.astimezone(ZoneInfo(claim.business_timezone)).strftime(
                        WALL_TIME_FORMAT
                    )
                ),
                on_page_fetched=lambda: _renew(session, claim=claim),
            )
            sync_run = await get_sync_run_for_update(session, run_id=claim.sync_run_id)
            if sync_run is not None:
                await add_sync_run_event(
                    session,
                    run=sync_run,
                    event_type="remote_fetch_completed",
                    status="running",
                    message="远端转盘订单读取并校验完成，准备解析渠道来源。",
                    metadata={
                        "remoteTotal": fetched.remote_total,
                        "fetchedPages": fetched.fetched_pages,
                        "duplicateCount": fetched.duplicate_count,
                    },
                )
            await _renew(session, claim=claim)
            sync_run = await get_sync_run_for_update(session, run_id=claim.sync_run_id)
            if sync_run is not None:
                await add_sync_run_event(
                    session,
                    run=sync_run,
                    event_type="uid_channel_resolution_started",
                    status="running",
                    message="开始解析转盘订单的用户渠道来源。",
                    metadata={"orderCount": len(fetched.orders)},
                )
            channels, resolved, unresolved = await _resolve_user_channels(
                session,
                source_id=claim.source_id,
                orders=fetched.orders,
                client=client,
                now=datetime.now(UTC),
            )
            sync_run = await get_sync_run_for_update(session, run_id=claim.sync_run_id)
            if sync_run is not None:
                await add_sync_run_event(
                    session,
                    run=sync_run,
                    event_type="uid_channel_resolution_completed",
                    status="running",
                    message="用户渠道来源解析完成，准备更新本地缓存。",
                    metadata={
                        "resolvedUidCount": resolved,
                        "unresolvedUidCount": unresolved,
                    },
                )
            await _renew(session, claim=claim)
    except asyncio.CancelledError:
        await session.rollback()
        try:
            await _cancelled(session, claim=claim, cancelled_at=datetime.now(UTC))
        except Exception:
            await session.rollback()
        raise
    except Exception:
        await session.rollback()
        return await _failure(session, claim=claim, finished_at=datetime.now(UTC))
    return await _persist_success(
        session,
        claim=claim,
        fetched=fetched,
        channels=channels,
        resolved_uid_count=resolved,
        unresolved_uid_count=unresolved,
        finished_at=datetime.now(UTC),
    )


async def run_due_spin_order_refreshes(
    session: AsyncSession, *, now: datetime | None = None, settings: Settings | None = None
) -> list[SpinOrderRefreshRunResult]:
    run_at = _now(now)
    current_settings = settings or get_settings()
    results: list[SpinOrderRefreshRunResult] = []
    while True:
        try:
            claim = await _claim_due(session, now=run_at, settings=current_settings)
        except (OperationalError, ProgrammingError) as exc:
            if not _missing_schema(exc):
                raise
            await session.rollback()
            return results
        if claim is None:
            return results
        results.append(await _execute(session, claim=claim, settings=current_settings))
        run_at = datetime.now(UTC) if now is None else run_at
