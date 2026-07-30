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
from packages.domain.models import (
    SourceConfig,
    WithdrawOrderRefreshState,
    WithdrawOrderSnapshot,
)
from packages.domain.services.auth_service import write_audit
from packages.domain.services.remote_withdraw_service import (
    RajAdminWithdrawClient,
    WithdrawFetchResult,
)
from packages.domain.services.source_service import get_source
from packages.domain.services.system_setting_service import get_retention_settings
from packages.domain.services.withdraw_order_service import (
    WithdrawOrderCacheSchemaPendingError,
    withdraw_order_query_window,
)

REMOTE_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.000Z"
WALL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
# A remote traversal may visit up to 200 pages.  The client renews this lease
# after each successfully received page; 30 minutes leaves ample room for the
# bounded authentication-retry path of one page while keeping a crashed worker
# reclaimable promptly.
REFRESH_LEASE_DURATION = timedelta(minutes=30)


class WithdrawOrderRefreshValidationError(ValueError):
    pass


class WithdrawOrderRefreshClaimLostError(RuntimeError):
    """A lease was superseded while a client was traversing remote pages."""


@dataclass(frozen=True, slots=True)
class WithdrawOrderRefreshQueueResult:
    source_ids: list[str]
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class WithdrawOrderRefreshRunResult:
    source_id: str
    status: str
    remote_total: int = 0
    cached_total: int = 0


@dataclass(frozen=True, slots=True)
class _RefreshClaim:
    source_id: str
    source_display_name: str
    base_url: str
    encrypted_credentials: str
    credential_version: int
    business_timezone: str
    page_size: int
    query_range: str
    started_at: datetime
    lease_expires_at: datetime
    window_start: datetime
    window_end: datetime


def _is_missing_refresh_schema(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    return (
        "withdraw_order_snapshots" in message
        or "withdraw_order_refresh_states" in message
    ) and ("does not exist" in message or "no such table" in message)


def _coerce_now(value: datetime | None = None) -> datetime:
    now = value or datetime.now(UTC)
    return now if now.tzinfo else now.replace(tzinfo=UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize SQLite's timezone-naive round trips for portable comparisons."""

    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _parse_remote_wall_time(value: object, *, timezone_name: str) -> datetime | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    try:
        return datetime.strptime(text, WALL_TIME_FORMAT).replace(
            tzinfo=ZoneInfo(timezone_name)
        ).astimezone(UTC)
    except ValueError:
        return None


def _safe_text(value: object, *, limit: int) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:limit] if text else None


def _eligible_source(source: SourceConfig) -> bool:
    return bool(source.enabled and source.base_url and source.encrypted_credentials)


def _state_is_due(
    state: WithdrawOrderRefreshState,
    *,
    interval_hours: int,
    now: datetime,
) -> bool:
    # An active lease belongs to a worker that is currently handling this
    # source.  A later manual click remains recorded and will be picked up once
    # that lease completes.
    lease_expires_at = _as_utc(state.lease_expires_at)
    last_started_at = _as_utc(state.last_started_at)
    manual_request_at = _as_utc(state.manual_request_at)
    if lease_expires_at is not None and lease_expires_at > now:
        return False
    if state.status == "running" and lease_expires_at is not None:
        # A dead worker's expired lease is reclaimed immediately.
        return True
    if manual_request_at is not None and (
        last_started_at is None or manual_request_at > last_started_at
    ):
        return True
    # Failed initial refreshes must not cause a 30-second retry storm.  The
    # interval is used as a backoff until an operator explicitly queues a run.
    anchor = _as_utc(state.last_succeeded_at) or _as_utc(state.last_failed_at)
    return anchor is None or now >= anchor + timedelta(hours=interval_hours)


async def _get_or_create_refresh_state(
    session: AsyncSession,
    *,
    source_id: str,
    now: datetime,
) -> WithdrawOrderRefreshState:
    """Lock a refresh state, tolerating concurrent first use of a source."""

    state = await session.get(
        WithdrawOrderRefreshState,
        source_id,
        with_for_update=True,
        populate_existing=True,
    )
    if state is not None:
        return state

    created = WithdrawOrderRefreshState(source_id=source_id, updated_at=now)
    try:
        # The savepoint keeps a unique-key collision from rolling back other
        # queued sources or the audit row in the surrounding transaction.
        async with session.begin_nested():
            session.add(created)
            await session.flush()
    except IntegrityError:
        state = await session.get(
            WithdrawOrderRefreshState,
            source_id,
            with_for_update=True,
            populate_existing=True,
        )
        if state is not None:
            return state
        raise
    return created


async def queue_withdraw_order_refreshes(
    session: AsyncSession,
    *,
    source_id: str | None,
    actor_user_id: int | None,
    now: datetime | None = None,
) -> WithdrawOrderRefreshQueueResult:
    """Persist a manual refresh request; never contact a remote source here."""

    requested_at = _coerce_now(now)
    if source_id:
        source = await get_source(session, source_id)
        sources = [source]
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
        raise WithdrawOrderRefreshValidationError("没有可同步的已启用盘口。")
    if source_id and not _eligible_source(sources[0]):
        raise WithdrawOrderRefreshValidationError("所选盘口尚未启用或缺少远端读取凭据。")

    queued_ids: list[str] = []
    try:
        for source in sources:
            state = await _get_or_create_refresh_state(
                session,
                source_id=source.source_id,
                now=requested_at,
            )
            state.manual_request_at = requested_at
            # Do not overwrite an active lease.  The run completion keeps a
            # newer request marker and the worker will immediately queue it.
            if not (
                state.status == "running"
                and _as_utc(state.lease_expires_at) is not None
                and _as_utc(state.lease_expires_at) > requested_at
            ):
                state.status = "queued"
            state.updated_at = requested_at
            queued_ids.append(source.source_id)
        await write_audit(
            session,
            action="withdraw_order.refresh.queue",
            actor_user_id=actor_user_id,
            target_type="withdraw_order_refresh",
            target_id=source_id or "all",
            metadata={"sourceIds": queued_ids},
        )
        await session.commit()
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_refresh_schema(exc):
            raise
        await session.rollback()
        raise WithdrawOrderCacheSchemaPendingError(
            "提现订单本地缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc
    return WithdrawOrderRefreshQueueResult(source_ids=queued_ids, requested_at=requested_at)


async def _claim_next_due_refresh(
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
                SourceConfig.encrypted_credentials.is_not(None),
            )
            .order_by(SourceConfig.source_id)
        )
    )
    for source in sources:
        state = await _get_or_create_refresh_state(
            session,
            source_id=source.source_id,
            now=now,
        )
        if not _state_is_due(
            state,
            interval_hours=retention.withdraw_order_refresh_interval_hours,
            now=now,
        ):
            continue
        window_start, window_end = withdraw_order_query_window(
            query_range=retention.withdraw_order_query_range,
            timezone_name=source.business_timezone,
            now=now,
        )
        lease_expires_at = now + REFRESH_LEASE_DURATION
        state.status = "running"
        state.last_started_at = now
        state.last_window_start_utc = window_start
        state.last_window_end_utc = window_end
        state.lease_expires_at = lease_expires_at
        state.last_error = None
        state.updated_at = now
        await session.commit()
        return _RefreshClaim(
            source_id=source.source_id,
            source_display_name=source.display_name,
            base_url=source.base_url or "",
            encrypted_credentials=source.encrypted_credentials or "",
            credential_version=source.credential_version,
            business_timezone=source.business_timezone,
            page_size=retention.withdraw_order_refresh_page_size,
            query_range=retention.withdraw_order_query_range,
            started_at=now,
            lease_expires_at=lease_expires_at,
            window_start=window_start,
            window_end=window_end,
        )
    await session.commit()
    return None


async def _record_refresh_failure(
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
    if state is None:
        return WithdrawOrderRefreshRunResult(source_id=claim.source_id, status="failed")
    # Do not clobber a newer worker claim after this lease expired.
    if _as_utc(state.last_started_at) != claim.started_at:
        return WithdrawOrderRefreshRunResult(source_id=claim.source_id, status=state.status)
    state.status = "failed"
    state.last_failed_at = finished_at
    state.last_error = "远端提现订单读取失败，请稍后重试。"
    state.lease_expires_at = None
    if (
        _as_utc(state.manual_request_at) is not None
        and _as_utc(state.manual_request_at) <= claim.started_at
    ):
        state.manual_request_at = None
    state.updated_at = finished_at
    await session.commit()
    return WithdrawOrderRefreshRunResult(source_id=claim.source_id, status="failed")


async def _requeue_cancelled_refresh(
    session: AsyncSession,
    *,
    claim: _RefreshClaim,
    cancelled_at: datetime,
) -> None:
    """Release a local cancellation promptly so a restarted worker resumes it."""

    state = await session.get(
        WithdrawOrderRefreshState,
        claim.source_id,
        with_for_update=True,
        populate_existing=True,
    )
    if state is None or _as_utc(state.last_started_at) != claim.started_at:
        return
    state.status = "queued"
    state.lease_expires_at = None
    state.last_error = "后台同步在工作进程停止前中断，已重新排队。"
    if (
        _as_utc(state.manual_request_at) is None
        or _as_utc(state.manual_request_at) <= claim.started_at
    ):
        state.manual_request_at = cancelled_at
    state.updated_at = cancelled_at
    await session.commit()


async def _renew_refresh_lease(
    session: AsyncSession,
    *,
    claim: _RefreshClaim,
) -> None:
    """Extend an active claim after a bounded remote-page request completes."""

    renewed_at = datetime.now(UTC)
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
    state.lease_expires_at = renewed_at + REFRESH_LEASE_DURATION
    state.updated_at = renewed_at
    await session.commit()


async def _snapshot_rows_by_remote_id(
    session: AsyncSession,
    *,
    source_id: str,
    remote_ids: list[str],
) -> dict[str, WithdrawOrderSnapshot]:
    existing: dict[str, WithdrawOrderSnapshot] = {}
    # Keep each IN predicate comfortably below SQLite and Postgres parameter
    # limits while retaining portable SQLAlchemy behavior.
    for offset in range(0, len(remote_ids), 500):
        chunk = remote_ids[offset : offset + 500]
        if not chunk:
            continue
        rows = list(
            await session.scalars(
                select(WithdrawOrderSnapshot).where(
                    WithdrawOrderSnapshot.source_id == source_id,
                    WithdrawOrderSnapshot.remote_order_id.in_(chunk),
                )
            )
        )
        existing.update({row.remote_order_id: row for row in rows})
    return existing


def _apply_snapshot_values(
    snapshot: WithdrawOrderSnapshot,
    *,
    order: dict[str, Any],
    timezone_name: str,
    synced_at: datetime,
) -> None:
    """Copy only approved, normalized fields from the remote client result."""

    snapshot.uid = _safe_text(order.get("uid"), limit=64) or ""
    snapshot.amount = _safe_text(order.get("amount"), limit=64)
    snapshot.real_amount = _safe_text(order.get("real_amount"), limit=64)
    snapshot.create_time = _safe_text(order.get("create_time"), limit=32)
    snapshot.create_time_utc = _parse_remote_wall_time(
        snapshot.create_time,
        timezone_name=timezone_name,
    )
    snapshot.update_time = _safe_text(order.get("update_time"), limit=32)
    snapshot.submit_time = _safe_text(order.get("submit_time"), limit=32)
    snapshot.audit_admin = _safe_text(order.get("audit_admin"), limit=160)
    snapshot.status = _safe_text(order.get("status"), limit=40) or ""
    snapshot.last_seen_at = synced_at
    snapshot.synced_at = synced_at


async def _persist_refresh_success(
    session: AsyncSession,
    *,
    claim: _RefreshClaim,
    fetched: WithdrawFetchResult,
    finished_at: datetime,
) -> WithdrawOrderRefreshRunResult:
    state = await session.get(
        WithdrawOrderRefreshState,
        claim.source_id,
        with_for_update=True,
        populate_existing=True,
    )
    if state is None or _as_utc(state.last_started_at) != claim.started_at:
        return WithdrawOrderRefreshRunResult(source_id=claim.source_id, status="superseded")

    normalized_by_id: dict[str, dict[str, Any]] = {}
    for item in fetched.orders:
        remote_order_id = _safe_text(item.get("id"), limit=120)
        if remote_order_id:
            normalized_by_id[remote_order_id] = item
    remote_ids = list(normalized_by_id)
    existing = await _snapshot_rows_by_remote_id(
        session,
        source_id=claim.source_id,
        remote_ids=remote_ids,
    )
    for remote_order_id, order in normalized_by_id.items():
        snapshot = existing.get(remote_order_id)
        if snapshot is None:
            snapshot = WithdrawOrderSnapshot(
                source_id=claim.source_id,
                remote_order_id=remote_order_id,
                first_seen_at=finished_at,
                last_seen_at=finished_at,
                synced_at=finished_at,
            )
            session.add(snapshot)
        _apply_snapshot_values(
            snapshot,
            order=order,
            timezone_name=claim.business_timezone,
            synced_at=finished_at,
        )
    await session.flush()

    # A complete remote page traversal is authoritative for its requested
    # window.  Remove cache rows no longer returned there; never delete on a
    # partial fetch because that would turn a remote pagination issue into data
    # loss in the local view.
    if fetched.complete:
        in_window = list(
            await session.scalars(
                select(WithdrawOrderSnapshot).where(
                    WithdrawOrderSnapshot.source_id == claim.source_id,
                    WithdrawOrderSnapshot.create_time_utc.is_not(None),
                    WithdrawOrderSnapshot.create_time_utc >= claim.window_start,
                    WithdrawOrderSnapshot.create_time_utc <= claim.window_end,
                )
            )
        )
        stale_rows = [row for row in in_window if row.remote_order_id not in normalized_by_id]
        for stale in stale_rows:
            await session.delete(stale)
        if stale_rows:
            await session.flush()

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
    state.last_error = None
    state.lease_expires_at = None
    if (
        _as_utc(state.manual_request_at) is not None
        and _as_utc(state.manual_request_at) <= claim.started_at
    ):
        state.manual_request_at = None
    state.updated_at = finished_at
    await session.commit()
    return WithdrawOrderRefreshRunResult(
        source_id=claim.source_id,
        status="succeeded",
        remote_total=fetched.remote_total,
        cached_total=cached_total,
    )


async def _execute_refresh_claim(
    session: AsyncSession,
    *,
    claim: _RefreshClaim,
    settings: Settings,
) -> WithdrawOrderRefreshRunResult:
    try:
        credentials = decrypt_credentials(
            claim.encrypted_credentials,
            source_id=claim.source_id,
            credential_version=claim.credential_version,
            settings=settings,
        )
        username = credentials["username"]
        password = credentials["password"]
        totp_secret = credentials["totp_secret"]
        async with RajAdminWithdrawClient(
            base_url=claim.base_url,
            username=username,
            password=password,
            totp_secret=totp_secret,
            page_size=claim.page_size,
        ) as client:
            async def renew_lease() -> None:
                await _renew_refresh_lease(session, claim=claim)

            fetched = await client.fetch_all_withdraw_orders(
                create_start=claim.window_start.strftime(REMOTE_TIME_FORMAT),
                create_end=claim.window_end.strftime(REMOTE_TIME_FORMAT),
                on_page_fetched=renew_lease,
            )
    except asyncio.CancelledError:
        # ``CancelledError`` is not an Exception on supported Python versions.
        # Releasing the durable lease lets the next worker run resume promptly
        # after an intentional process restart.
        try:
            await session.rollback()
            await _requeue_cancelled_refresh(
                session,
                claim=claim,
                cancelled_at=datetime.now(UTC),
            )
        except Exception:
            await session.rollback()
        raise
    except Exception:
        # Remote errors and credential problems are deliberately collapsed to a
        # fixed state message.  Raw upstream bodies and credential context must
        # never be persisted or exposed to the page.
        return await _record_refresh_failure(
            session,
            claim=claim,
            finished_at=datetime.now(UTC),
        )
    return await _persist_refresh_success(
        session,
        claim=claim,
        fetched=fetched,
        finished_at=datetime.now(UTC),
    )


async def run_due_withdraw_order_refreshes(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[WithdrawOrderRefreshRunResult]:
    """Run due source refreshes sequentially without holding DB locks remotely."""

    current_settings = settings or get_settings()
    run_now = _coerce_now(now)
    results: list[WithdrawOrderRefreshRunResult] = []
    while True:
        try:
            claim = await _claim_next_due_refresh(
                session,
                now=run_now,
                settings=current_settings,
            )
        except (OperationalError, ProgrammingError) as exc:
            if not _is_missing_refresh_schema(exc):
                raise
            await session.rollback()
            return results
        if claim is None:
            return results
        try:
            results.append(
                await _execute_refresh_claim(
                    session,
                    claim=claim,
                    settings=current_settings,
                )
            )
        except (OperationalError, ProgrammingError):
            await session.rollback()
            raise
        # The next claim uses a fresh timestamp so a long remote call does not
        # cause the following source's schedule to appear prematurely due.
        run_now = datetime.now(UTC)
