from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings, get_settings
from packages.domain.models import SourceConfig, WithdrawOrderRefreshState, WithdrawOrderSnapshot
from packages.domain.services.auth_service import write_audit
from packages.domain.services.automatic_refresh_retry import (
    can_retry_failed_automatic_window,
)
from packages.domain.services.data_dictionary_service import refresh_withdraw_status_cache
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
from packages.domain.services.remote_account_credentials import (
    RemoteAccountCredentialEnvelope,
    decrypt_remote_account_credentials,
    resolve_default_remote_account_credentials,
)
from packages.domain.services.remote_withdraw_service import (
    RajAdminWithdrawClient,
    WithdrawFetchResult,
)
from packages.domain.services.scoring_review_sync_service import (
    sync_scoring_reviewed_cases_from_remote,
)
from packages.domain.services.source_service import get_source
from packages.domain.services.system_setting_service import get_retention_settings
from packages.domain.services.withdraw_order_service import WithdrawOrderCacheSchemaPendingError

WALL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
REFRESH_LEASE_DURATION = timedelta(minutes=30)
WITHDRAW_ORDER_MANUAL_REFRESH_RANGES = frozenset({"day_before_yesterday", "yesterday", "today"})


class WithdrawOrderRefreshValidationError(ValueError):
    pass


class WithdrawOrderRefreshClaimLostError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WithdrawOrderRefreshQueueResult:
    source_ids: list[str]
    requested_at: datetime
    query_range: str | None


@dataclass(frozen=True, slots=True)
class WithdrawOrderRefreshRunResult:
    source_id: str
    status: str
    remote_total: int = 0
    cached_total: int = 0


@dataclass(frozen=True, slots=True)
class _RefreshClaim:
    source_id: str
    base_url: str
    encrypted_credentials: str
    credential_scope: str
    login_username: str | None
    credential_version: int
    business_timezone: str
    started_at: datetime
    window_start: datetime
    window_end: datetime
    requested_query_range: str
    automatic: bool
    sync_run_id: str
    timeout_seconds: int


def _is_missing_refresh_schema(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    missing_table = (
        "withdraw_order_snapshots" in message
        or "withdraw_order_refresh_states" in message
        or "data_sync_runs" in message
    ) and ("does not exist" in message or "no such table" in message)
    missing_export_metric = (
        "last_export_row_count" in message
        or "last_imported_count" in message
        or "last_duplicate_count" in message
        or "pending_sync_run_id" in message
        or "active_sync_run_id" in message
        or "automatic_failure_count" in message
    ) and ("does not exist" in message or "no such column" in message)
    return missing_table or missing_export_metric


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
    if not text or text == "-":
        return None
    try:
        return (
            datetime.strptime(text, WALL_TIME_FORMAT)
            .replace(tzinfo=ZoneInfo(timezone_name))
            .astimezone(UTC)
        )
    except ValueError:
        return None


async def _credentials_for_source(
    session: AsyncSession,
    *,
    source: SourceConfig,
) -> RemoteAccountCredentialEnvelope | None:
    if not source.enabled or not source.base_url:
        return None
    return await resolve_default_remote_account_credentials(session, source=source)


async def _state(
    session: AsyncSession,
    *,
    source_id: str,
    now: datetime,
) -> WithdrawOrderRefreshState:
    existing = await session.get(
        WithdrawOrderRefreshState,
        source_id,
        with_for_update=True,
        populate_existing=True,
    )
    if existing is not None:
        return existing
    created = WithdrawOrderRefreshState(source_id=source_id, updated_at=now)
    try:
        async with session.begin_nested():
            session.add(created)
            await session.flush()
    except IntegrityError:
        existing = await session.get(
            WithdrawOrderRefreshState,
            source_id,
            with_for_update=True,
            populate_existing=True,
        )
        if existing is not None:
            return existing
        raise
    return created


def _manual_request_is_pending(state: WithdrawOrderRefreshState) -> bool:
    manual = _as_utc(state.manual_request_at)
    started = _as_utc(state.last_started_at)
    return manual is not None and (started is None or manual > started)


def _calendar_day_window(*, day: date, timezone_name: str) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(timezone_name)
    return (
        datetime.combine(day, time.min, tzinfo=timezone).astimezone(UTC),
        datetime.combine(day, time(23, 59, 59), tzinfo=timezone).astimezone(UTC),
    )


def _manual_export_day(*, query_range: str, timezone_name: str, now: datetime) -> date:
    offsets = {"day_before_yesterday": 2, "yesterday": 1, "today": 0}
    return now.astimezone(ZoneInfo(timezone_name)).date() - timedelta(days=offsets[query_range])


def _automatic_export_day(
    *,
    date_mode: str,
    specific_date: date | None,
    timezone_name: str,
    now: datetime,
) -> date:
    if date_mode == "specific_date" and specific_date is not None:
        return specific_date
    return now.astimezone(ZoneInfo(timezone_name)).date() - timedelta(days=1)


def _due(
    state: WithdrawOrderRefreshState,
    *,
    now: datetime,
    automatic_window_start: datetime,
    timezone_name: str,
    automatic_export_time: time,
    retry_limit: int,
    retry_interval_minutes: int,
) -> bool:
    lease = _as_utc(state.lease_expires_at)
    if lease is not None and lease > now:
        return False
    if state.status == "running" and lease is not None:
        return True
    if _manual_request_is_pending(state):
        return True
    if now.astimezone(ZoneInfo(timezone_name)).time() < automatic_export_time:
        return False
    if (
        state.status == "succeeded"
        and _as_utc(state.last_window_start_utc) == automatic_window_start
    ):
        return False
    if not can_retry_failed_automatic_window(
        status=state.status,
        previous_window_marker=_as_utc(state.last_window_start_utc),
        automatic_window_marker=automatic_window_start,
        last_failed_at=_as_utc(state.last_failed_at),
        automatic_failure_count=state.automatic_failure_count,
        retry_limit=retry_limit,
        retry_interval_minutes=retry_interval_minutes,
        now=now,
    ):
        return False
    return True


async def queue_withdraw_order_refreshes(
    session: AsyncSession,
    *,
    source_id: str | None,
    query_range: str | None = None,
    actor_user_id: int | None,
    now: datetime | None = None,
) -> WithdrawOrderRefreshQueueResult:
    """Queue a full local-calendar-day Excel export without remote I/O."""

    requested_query_range = query_range or "yesterday"
    if requested_query_range not in WITHDRAW_ORDER_MANUAL_REFRESH_RANGES:
        raise WithdrawOrderRefreshValidationError("不支持的提现订单刷新时间范围。")
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
                )
                .order_by(SourceConfig.source_id)
            )
        )
        sources = [
            source
            for source in sources
            if await _credentials_for_source(session, source=source) is not None
        ]
    if not sources:
        raise WithdrawOrderRefreshValidationError("没有可同步的已启用盘口。")
    if source_id and await _credentials_for_source(session, source=sources[0]) is None:
        raise WithdrawOrderRefreshValidationError("所选盘口尚未启用或缺少远端读取凭据。")

    ids: list[str] = []
    try:
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
                business_type="withdraw_orders",
                trigger_type="manual",
                requested_by_user_id=actor_user_id,
                requested_at=requested_at,
                query_range=requested_query_range,
                status="queued",
            )
            state.pending_sync_run_id = queued_run.id
            if not (
                state.status == "running"
                and (_as_utc(state.lease_expires_at) or requested_at) > requested_at
            ):
                state.status = "queued"
            state.updated_at = requested_at
            ids.append(source.source_id)
        await write_audit(
            session,
            action="withdraw_order.refresh.queue",
            actor_user_id=actor_user_id,
            target_type="withdraw_order_refresh",
            target_id=source_id or "all",
            metadata={"sourceIds": ids, "queryRange": requested_query_range},
        )
        await session.commit()
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_refresh_schema(exc):
            raise
        await session.rollback()
        raise WithdrawOrderCacheSchemaPendingError(
            "提现订单本地缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc
    return WithdrawOrderRefreshQueueResult(ids, requested_at, requested_query_range)


async def _claim_due(
    session: AsyncSession,
    *,
    now: datetime,
    settings: Settings,
) -> _RefreshClaim | None:
    retention = await get_retention_settings(session, defaults=settings)
    sources = list(
        await session.scalars(
            select(SourceConfig)
            .where(
                SourceConfig.enabled.is_(True),
                SourceConfig.base_url.is_not(None),
            )
            .order_by(SourceConfig.source_id)
        )
    )
    for source in sources:
        credential_envelope = await _credentials_for_source(session, source=source)
        if credential_envelope is None:
            continue
        state = await _state(session, source_id=source.source_id, now=now)
        automatic_day = _automatic_export_day(
            date_mode=retention.withdraw_order_export_date_mode,
            specific_date=retention.withdraw_order_export_specific_date,
            timezone_name=source.business_timezone,
            now=now,
        )
        automatic_window_start, _ = _calendar_day_window(
            day=automatic_day,
            timezone_name=source.business_timezone,
        )
        manual_requested = _manual_request_is_pending(state)
        if (
            not manual_requested
            and _as_utc(state.last_window_start_utc) != automatic_window_start
        ):
            state.automatic_failure_count = 0
        if not _due(
            state,
            now=now,
            automatic_window_start=automatic_window_start,
            timezone_name=source.business_timezone,
            automatic_export_time=retention.withdraw_order_export_time or time(0, 5, 1),
            retry_limit=retention.automatic_sync_retry_limit,
            retry_interval_minutes=retention.automatic_sync_retry_interval_minutes,
        ):
            continue
        requested_query_range = state.manual_query_range or "yesterday"
        export_day = (
            _manual_export_day(
                query_range=requested_query_range,
                timezone_name=source.business_timezone,
                now=now,
            )
            if manual_requested
            else automatic_day
        )
        window_start, window_end = _calendar_day_window(
            day=export_day,
            timezone_name=source.business_timezone,
        )
        state.status = "running"
        state.last_started_at = now
        state.last_window_start_utc = window_start
        state.last_window_end_utc = window_end
        state.lease_expires_at = now + REFRESH_LEASE_DURATION
        state.last_error = None
        state.updated_at = now
        if manual_requested:
            sync_run = (
                await get_sync_run_for_update(session, run_id=state.pending_sync_run_id)
                if state.pending_sync_run_id
                else None
            )
            if sync_run is None:
                # Preserve refresh behavior while supporting an upgrade from a
                # pre-log queued request.
                sync_run = await create_sync_run(
                    session,
                    source=source,
                    business_type="withdraw_orders",
                    trigger_type="manual",
                    requested_at=now,
                    query_range=requested_query_range,
                    status="queued",
                )
            await mark_sync_run_running(
                session,
                run=sync_run,
                started_at=now,
                window_start_utc=window_start,
                window_end_utc=window_end,
                query_range=requested_query_range,
            )
        else:
            sync_run = await create_sync_run(
                session,
                source=source,
                business_type="withdraw_orders",
                trigger_type="automatic",
                requested_at=now,
                window_start_utc=window_start,
                window_end_utc=window_end,
                status="running",
            )
        state.pending_sync_run_id = None
        state.active_sync_run_id = sync_run.id
        await session.commit()
        return _RefreshClaim(
            source_id=source.source_id,
            base_url=source.base_url or "",
            encrypted_credentials=credential_envelope.encrypted_credentials,
            credential_scope=credential_envelope.credential_scope,
            login_username=credential_envelope.login_username,
            credential_version=credential_envelope.credential_version,
            business_timezone=source.business_timezone,
            started_at=now,
            window_start=window_start,
            window_end=window_end,
            requested_query_range=requested_query_range,
            automatic=not manual_requested,
            sync_run_id=sync_run.id,
            timeout_seconds=(
                retention.remote_order_sync_timeout_seconds
                or settings.remote_order_sync_timeout_seconds
            ),
        )
    await session.commit()
    return None


async def _renew(session: AsyncSession, *, claim: _RefreshClaim) -> None:
    state = await session.get(
        WithdrawOrderRefreshState,
        claim.source_id,
        with_for_update=True,
        populate_existing=True,
    )
    if (
        state is None
        or state.status != "running"
        or _as_utc(state.last_started_at) != claim.started_at
    ):
        raise WithdrawOrderRefreshClaimLostError("提现订单同步租约已失效。")
    renewed_at = datetime.now(UTC)
    state.lease_expires_at = renewed_at + REFRESH_LEASE_DURATION
    state.updated_at = renewed_at
    await session.commit()


async def _rows_by_id(
    session: AsyncSession,
    *,
    source_id: str,
    remote_ids: list[str],
) -> dict[str, WithdrawOrderSnapshot]:
    existing: dict[str, WithdrawOrderSnapshot] = {}
    for offset in range(0, len(remote_ids), 500):
        rows = list(
            await session.scalars(
                select(WithdrawOrderSnapshot).where(
                    WithdrawOrderSnapshot.source_id == source_id,
                    WithdrawOrderSnapshot.remote_order_id.in_(remote_ids[offset : offset + 500]),
                )
            )
        )
        existing.update({row.remote_order_id: row for row in rows})
    return existing


def _apply(
    snapshot: WithdrawOrderSnapshot,
    *,
    order: dict[str, Any],
    claim: _RefreshClaim,
    now: datetime,
) -> None:
    """Persist only the approved Excel white-list projection."""

    snapshot.uid = _safe_text(order.get("uid"), limit=64) or ""
    snapshot.order_num = _safe_text(order.get("order_num"), limit=160)
    snapshot.out_trade_no = _safe_text(order.get("out_trade_no"), limit=160)
    snapshot.pay_channel_name = _safe_text(order.get("pay_channel_name"), limit=160)
    snapshot.pay_channel = _safe_text(order.get("pay_channel"), limit=120)
    snapshot.amount = _safe_text(order.get("amount"), limit=64)
    snapshot.fee = _safe_text(order.get("fee"), limit=64)
    snapshot.real_amount = _safe_text(order.get("real_amount"), limit=64)
    snapshot.create_time = _safe_text(order.get("create_time"), limit=32)
    snapshot.create_time_utc = _parse_wall_time(
        snapshot.create_time,
        timezone_name=claim.business_timezone,
    )
    snapshot.submit_time = _safe_text(order.get("submit_time"), limit=32)
    snapshot.update_time = _safe_text(order.get("update_time"), limit=32)
    snapshot.audit_admin = _safe_text(order.get("audit_person"), limit=160)
    snapshot.status = _safe_text(order.get("status"), limit=40) or ""
    snapshot.status_label = _safe_text(order.get("status_label"), limit=120)
    snapshot.is_first = _safe_text(order.get("is_first"), limit=40)
    snapshot.channel = _safe_text(order.get("channel"), limit=120)
    snapshot.last_seen_at = now
    snapshot.synced_at = now


def _apply_status_dictionary(
    orders: list[dict[str, Any]],
    statuses: list[dict[str, str]],
) -> None:
    """Map export labels through the source's actual status dictionary.

    The spreadsheet retains the source-provided label in ``status_label``.  A
    normalized code is separately stored for stable filtering and aggregation.
    Duplicate labels are rejected because choosing one code would be unsafe.
    """

    label_to_code: dict[str, str] = {}
    code_to_label: dict[str, str] = {}
    for entry in statuses:
        code = _safe_text(entry.get("code"), limit=40)
        label = _safe_text(entry.get("label"), limit=120)
        if not code or not label:
            raise WithdrawOrderRefreshValidationError("远端提现状态字典不完整。")
        previous = label_to_code.get(label)
        if previous is not None and previous != code:
            raise WithdrawOrderRefreshValidationError("远端提现状态字典存在重复状态文案。")
        label_to_code[label] = code
        code_to_label[code] = label
    if not label_to_code:
        raise WithdrawOrderRefreshValidationError("远端提现状态字典为空。")
    for order in orders:
        raw_status = _safe_text(order.get("status_label"), limit=120)
        if not raw_status:
            raise WithdrawOrderRefreshValidationError("提现订单导出表格包含空状态。")
        if raw_status in code_to_label:
            order["status"] = raw_status
            # Some export variants contain the status code instead of its
            # Chinese label.  Preserve a display label from the source
            # dictionary so the detail page and summaries remain consistent.
            order["status_label"] = code_to_label[raw_status]
            continue
        mapped = label_to_code.get(raw_status)
        if mapped is None:
            raise WithdrawOrderRefreshValidationError("提现订单导出表格包含未映射的订单状态。")
        order["status"] = mapped


def _scoring_review_sync_enabled(source: SourceConfig | None) -> bool:
    """Whether this source has a separately tested scoring API integration."""

    return bool(
        source
        and source.scoring_api_base_url
        and source.encrypted_scoring_api_key
        and source.scoring_api_last_test_status == "passed"
    )


async def _persist_success(
    session: AsyncSession,
    *,
    claim: _RefreshClaim,
    fetched: WithdrawFetchResult,
    remote_statuses: list[dict[str, str]],
    finished_at: datetime,
) -> WithdrawOrderRefreshRunResult:
    state = await session.get(
        WithdrawOrderRefreshState,
        claim.source_id,
        with_for_update=True,
        populate_existing=True,
    )
    if state is None or _as_utc(state.last_started_at) != claim.started_at:
        return WithdrawOrderRefreshRunResult(claim.source_id, "superseded")
    sync_run = await get_sync_run_for_update(session, run_id=claim.sync_run_id)

    await refresh_withdraw_status_cache(
        session,
        source_id=claim.source_id,
        statuses=remote_statuses,
        now=finished_at,
    )
    by_id = {
        remote_id: order
        for order in fetched.orders
        if (remote_id := _safe_text(order.get("remote_order_id"), limit=120))
    }
    existing = await _rows_by_id(session, source_id=claim.source_id, remote_ids=list(by_id))
    created_count = sum(1 for remote_id in by_id if remote_id not in existing)
    updated_count = len(by_id) - created_count
    for remote_id, order in by_id.items():
        snapshot = existing.get(remote_id)
        if snapshot is None:
            snapshot = WithdrawOrderSnapshot(
                source_id=claim.source_id,
                remote_order_id=remote_id,
                first_seen_at=finished_at,
                last_seen_at=finished_at,
                synced_at=finished_at,
            )
            session.add(snapshot)
        _apply(snapshot, order=order, claim=claim, now=finished_at)
    await session.flush()

    deleted_count = 0
    if fetched.complete:
        rows = list(
            await session.scalars(
                select(WithdrawOrderSnapshot).where(
                    WithdrawOrderSnapshot.source_id == claim.source_id,
                    WithdrawOrderSnapshot.create_time_utc.is_not(None),
                    WithdrawOrderSnapshot.create_time_utc >= claim.window_start,
                    WithdrawOrderSnapshot.create_time_utc <= claim.window_end,
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
            .select_from(WithdrawOrderSnapshot)
            .where(
                WithdrawOrderSnapshot.source_id == claim.source_id,
                WithdrawOrderSnapshot.create_time_utc.is_not(None),
                WithdrawOrderSnapshot.create_time_utc >= claim.window_start,
                WithdrawOrderSnapshot.create_time_utc <= claim.window_end,
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
    state.last_export_row_count = fetched.export_row_count
    state.last_imported_count = len(by_id)
    state.last_duplicate_count = fetched.duplicate_count
    state.last_error = None
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
        await complete_sync_run(
            session,
            run=sync_run,
            complete=fetched.complete,
            metrics=SyncRunMetrics(
                remote_total=fetched.remote_total,
                export_row_count=fetched.export_row_count,
                cached_total=cached_total,
                fetched_pages=fetched.fetched_pages,
                imported_count=len(by_id),
                created_count=created_count,
                updated_count=updated_count,
                duplicate_count=fetched.duplicate_count,
            ),
            finished_at=finished_at,
            metadata={"deletedCount": deleted_count},
        )
    await session.commit()
    return WithdrawOrderRefreshRunResult(
        claim.source_id,
        "succeeded",
        fetched.remote_total,
        cached_total,
    )


async def _failure(
    session: AsyncSession,
    *,
    claim: _RefreshClaim,
    finished_at: datetime,
) -> WithdrawOrderRefreshRunResult:
    state = await session.get(
        WithdrawOrderRefreshState,
        claim.source_id,
        with_for_update=True,
        populate_existing=True,
    )
    if state is None or _as_utc(state.last_started_at) != claim.started_at:
        return WithdrawOrderRefreshRunResult(claim.source_id, state.status if state else "failed")
    sync_run = await get_sync_run_for_update(session, run_id=claim.sync_run_id)
    state.status = "failed"
    state.last_failed_at = finished_at
    if claim.automatic:
        state.automatic_failure_count += 1
    state.last_error = "远端提现订单 Excel 导出或校验失败，请稍后重试。"
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
            error_code="remote_withdraw_sync_failed",
            error_message=state.last_error,
            finished_at=finished_at,
        )
    await session.commit()
    return WithdrawOrderRefreshRunResult(claim.source_id, "failed")


async def _record_scoring_sync_failure(
    session: AsyncSession,
    *,
    claim: _RefreshClaim,
) -> None:
    """Audit a score-sync failure without invalidating a saved withdrawal refresh.

    The scoring run has its own durable terminal record.  Marking the parent
    withdrawal state failed would immediately repeat the entire remote Excel
    export, even though that export and its local cache have already succeeded.
    """

    await write_audit(
        session,
        action="withdraw_scoring.auto_sync_failed",
        target_type="source",
        target_id=claim.source_id,
        result="failure",
        metadata={
            "createTimeStart": claim.window_start.astimezone(
                ZoneInfo(claim.business_timezone)
            ).strftime(WALL_TIME_FORMAT),
            "createTimeEnd": claim.window_end.astimezone(
                ZoneInfo(claim.business_timezone)
            ).strftime(WALL_TIME_FORMAT),
        },
    )
    await session.commit()


async def _sync_scoring_reviews_after_withdraw_refresh(
    session: AsyncSession,
    *,
    claim: _RefreshClaim,
    settings: Settings,
    withdraw_result: WithdrawOrderRefreshRunResult,
) -> WithdrawOrderRefreshRunResult:
    """Enrich a refreshed withdrawal window only when scoring API setup is valid.

    No scoring base URL, key, or successful independent connection test means
    the withdrawal cache remains the complete outcome of this refresh.  A
    configured scoring API is deliberately invoked only *after* the master
    withdrawal rows are committed, so new cases can join immediately.
    """

    if withdraw_result.status != "succeeded":
        return withdraw_result
    source = await session.get(SourceConfig, claim.source_id)
    if not _scoring_review_sync_enabled(source):
        return withdraw_result
    timezone = ZoneInfo(claim.business_timezone)
    try:
        await sync_scoring_reviewed_cases_from_remote(
            session,
            source_id=claim.source_id,
            create_time_start=claim.window_start.astimezone(timezone).strftime(WALL_TIME_FORMAT),
            create_time_end=claim.window_end.astimezone(timezone).strftime(WALL_TIME_FORMAT),
            actor_user_id=None,
            settings=settings,
            trigger_type="automatic",
        )
    except asyncio.CancelledError:
        await session.rollback()
        await _record_scoring_sync_failure(
            session,
            claim=claim,
        )
        raise
    except Exception:
        # ``sync_scoring_reviewed_cases_from_remote`` intentionally exposes
        # only safe business errors.  Do not persist or log an exception text,
        # because a transport failure could include upstream request details.
        await session.rollback()
        await _record_scoring_sync_failure(
            session,
            claim=claim,
        )
    return withdraw_result


async def _requeue_cancelled(
    session: AsyncSession,
    *,
    claim: _RefreshClaim,
    cancelled_at: datetime,
) -> None:
    state = await session.get(
        WithdrawOrderRefreshState,
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
            message="后台工作进程在同步完成前停止，任务已重新排队。",
        )
    state.status = "queued"
    state.active_sync_run_id = None
    state.lease_expires_at = None
    state.last_error = "后台同步在工作进程停止前中断，已重新排队。"
    if (
        _as_utc(state.manual_request_at) is None
        or _as_utc(state.manual_request_at) <= claim.started_at
    ):
        state.manual_request_at = cancelled_at
        state.manual_query_range = claim.requested_query_range
    state.updated_at = cancelled_at
    await session.commit()


async def _execute(
    session: AsyncSession,
    *,
    claim: _RefreshClaim,
    settings: Settings,
) -> WithdrawOrderRefreshRunResult:
    try:
        credentials = decrypt_remote_account_credentials(
            RemoteAccountCredentialEnvelope(
                source_id=claim.source_id,
                account_id=None,
                login_username=claim.login_username,
                encrypted_credentials=claim.encrypted_credentials,
                credential_scope=claim.credential_scope,
                credential_version=claim.credential_version,
                credential_mode="CLAIM",
            ),
            settings=settings,
        )
        async with RajAdminWithdrawClient(
            base_url=claim.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            timeout_seconds=claim.timeout_seconds,
        ) as client:
            sync_run = await get_sync_run_for_update(session, run_id=claim.sync_run_id)
            if sync_run is not None:
                await add_sync_run_event(
                    session,
                    run=sync_run,
                    event_type="withdraw_status_dictionary_started",
                    status="running",
                    message="开始读取远端提现状态字典。",
                )
            await _renew(session, claim=claim)
            remote_statuses = await client.fetch_withdraw_statuses()
            sync_run = await get_sync_run_for_update(session, run_id=claim.sync_run_id)
            if sync_run is not None:
                await add_sync_run_event(
                    session,
                    run=sync_run,
                    event_type="withdraw_status_dictionary_fetched",
                    status="running",
                    message="远端提现状态字典读取完成。",
                    metadata={"statusCount": len(remote_statuses)},
                )
            await _renew(session, claim=claim)
            sync_run = await get_sync_run_for_update(session, run_id=claim.sync_run_id)
            if sync_run is not None:
                await add_sync_run_event(
                    session,
                    run=sync_run,
                    event_type="remote_export_started",
                    status="running",
                    message="开始读取远端提现订单 Excel 导出。",
                )
            fetched = await client.export_withdraw_orders(
                create_start=claim.window_start.astimezone(
                    ZoneInfo(claim.business_timezone)
                ).strftime(WALL_TIME_FORMAT),
                create_end=claim.window_end.astimezone(ZoneInfo(claim.business_timezone)).strftime(
                    WALL_TIME_FORMAT
                ),
            )
            _apply_status_dictionary(fetched.orders, remote_statuses)
            sync_run = await get_sync_run_for_update(session, run_id=claim.sync_run_id)
            if sync_run is not None:
                await add_sync_run_event(
                    session,
                    run=sync_run,
                    event_type="remote_export_fetched",
                    status="running",
                    message="远端提现订单导出读取并校验完成，准备更新本地缓存。",
                    metadata={
                        "remoteTotal": fetched.remote_total,
                        "exportRowCount": fetched.export_row_count,
                        "fetchedPages": fetched.fetched_pages,
                    },
                )
            await _renew(session, claim=claim)
    except asyncio.CancelledError:
        try:
            await session.rollback()
            await _requeue_cancelled(
                session,
                claim=claim,
                cancelled_at=datetime.now(UTC),
            )
        except Exception:
            await session.rollback()
        raise
    except Exception:
        await session.rollback()
        return await _failure(session, claim=claim, finished_at=datetime.now(UTC))
    withdraw_result = await _persist_success(
        session,
        claim=claim,
        fetched=fetched,
        remote_statuses=remote_statuses,
        finished_at=datetime.now(UTC),
    )
    return await _sync_scoring_reviews_after_withdraw_refresh(
        session,
        claim=claim,
        settings=settings,
        withdraw_result=withdraw_result,
    )


async def run_due_withdraw_order_refreshes(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[WithdrawOrderRefreshRunResult]:
    current_settings = settings or get_settings()
    run_at = _now(now)
    results: list[WithdrawOrderRefreshRunResult] = []
    while True:
        try:
            claim = await _claim_due(session, now=run_at, settings=current_settings)
        except (OperationalError, ProgrammingError) as exc:
            if not _is_missing_refresh_schema(exc):
                raise
            await session.rollback()
            return results
        if claim is None:
            return results
        results.append(await _execute(session, claim=claim, settings=current_settings))
        # Keep an explicitly supplied clock stable.  Besides making callers
        # deterministic, this prevents a failed historic due run from being
        # claimed twice in the same scheduler pass merely because its retry
        # timestamp is based on the real clock.
        run_at = datetime.now(UTC) if now is None else run_at
