from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings, get_settings
from packages.domain.models import SpinOrderRefreshState, SpinOrderSnapshot
from packages.domain.schemas.spin_order import SpinChannelSummaryRequest, SpinOrderQueryRequest
from packages.domain.services.data_dictionary_service import (
    SPIN_ORDER_STATUS_ENTRIES,
    list_spin_order_statuses,
    list_user_source_channels,
)
from packages.domain.services.source_service import get_source
from packages.domain.services.system_setting_service import get_retention_settings

WALL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SPIN_CONFIG_LABELS = {"10001": "200转盘", "10002": "500转盘"}
PASSED_STATUS_CODES = frozenset({"1", "101"})


class SpinOrderValidationError(ValueError):
    pass


class SpinOrderCacheSchemaPendingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SpinOrderQueryResult:
    items: list[dict[str, Any]]
    total: int
    source_id: str
    source_display_name: str
    business_timezone: str
    fetched_at: datetime
    local_updated_at: datetime | None
    last_refreshed_at: datetime | None
    refresh_status: str
    remote_total: int
    fetched_pages: int
    complete: bool
    resolved_uid_count: int
    unresolved_uid_count: int
    status_dictionary: list[dict[str, object]]
    channel_dictionary: list[dict[str, str]]
    summary: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SpinChannelSummaryResult:
    items: list[dict[str, Any]]
    total: int
    source_id: str
    source_display_name: str
    business_timezone: str
    fetched_at: datetime
    local_updated_at: datetime | None
    channel_dictionary: list[dict[str, str]]
    time_series: list[dict[str, Any]]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _is_missing_schema(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    return ("spin_order_snapshots" in message or "spin_order_refresh_states" in message) and (
        "does not exist" in message or "no such table" in message
    )


def _parse_window(
    *,
    start: str | None,
    end: str | None,
    timezone_name: str,
    cache_start: datetime,
    cache_end: datetime,
) -> tuple[datetime, datetime]:
    if start is None and end is None:
        return cache_start, cache_end
    if start is None or end is None:
        raise SpinOrderValidationError("申请时间范围必须同时提供开始和结束时间。")
    try:
        timezone = ZoneInfo(timezone_name)
        start_utc = (
            datetime.strptime(start, WALL_TIME_FORMAT).replace(tzinfo=timezone).astimezone(UTC)
        )
        end_utc = datetime.strptime(end, WALL_TIME_FORMAT).replace(tzinfo=timezone).astimezone(UTC)
    except ValueError as exc:
        raise SpinOrderValidationError("申请时间必须使用 YYYY-MM-DD HH:mm:ss 格式。") from exc
    if start_utc > end_utc:
        raise SpinOrderValidationError("申请时间范围的开始时间不能晚于结束时间。")
    return max(start_utc, cache_start), min(end_utc, cache_end)


async def _context(
    session: AsyncSession,
    *,
    source_id: str,
    create_time_start: str | None,
    create_time_end: str | None,
    settings: Settings | None,
    now: datetime | None,
) -> tuple[str, str, str, datetime, datetime, datetime, SpinOrderRefreshState | None]:
    source = await get_source(session, source_id)
    if not source.enabled:
        raise SpinOrderValidationError("所选盘口尚未启用。")
    query_at = now or datetime.now(UTC)
    query_at = _as_utc(query_at) or datetime.now(UTC)
    retention = await get_retention_settings(session, defaults=settings or get_settings())
    timezone = ZoneInfo(source.business_timezone)
    local_now = query_at.astimezone(timezone)
    cache_start = (
        (local_now - timedelta(days=retention.remote_cache_retention_days))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
    )
    cache_end = local_now.replace(hour=23, minute=59, second=59, microsecond=0).astimezone(UTC)
    try:
        window_start, window_end = _parse_window(
            start=create_time_start,
            end=create_time_end,
            timezone_name=source.business_timezone,
            cache_start=cache_start,
            cache_end=cache_end,
        )
        state = await session.get(SpinOrderRefreshState, source.source_id)
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_schema(exc):
            raise
        await session.rollback()
        raise SpinOrderCacheSchemaPendingError(
            "转盘订单本地缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc
    return (
        source.source_id,
        source.display_name,
        source.business_timezone,
        query_at,
        window_start,
        window_end,
        state,
    )


async def _snapshots(
    session: AsyncSession,
    *,
    source_id: str,
    window_start: datetime,
    window_end: datetime,
    uid: str | None = None,
    status: str | None = None,
    spin_config_id: str | None = None,
    channel_id: str | None = None,
) -> list[SpinOrderSnapshot]:
    statement = select(SpinOrderSnapshot).where(
        SpinOrderSnapshot.source_id == source_id,
        SpinOrderSnapshot.create_time_utc.is_not(None),
        SpinOrderSnapshot.create_time_utc >= window_start,
        SpinOrderSnapshot.create_time_utc <= window_end,
    )
    if uid:
        statement = statement.where(SpinOrderSnapshot.uid == uid)
    if status:
        statement = statement.where(SpinOrderSnapshot.status == status)
    if spin_config_id:
        statement = statement.where(SpinOrderSnapshot.spin_config_id == spin_config_id)
    if channel_id:
        statement = statement.where(SpinOrderSnapshot.channel_id == channel_id)
    statement = statement.order_by(
        desc(SpinOrderSnapshot.create_time_utc),
        desc(SpinOrderSnapshot.remote_order_id),
    )
    try:
        return list(await session.scalars(statement))
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_schema(exc):
            raise
        await session.rollback()
        raise SpinOrderCacheSchemaPendingError(
            "转盘订单本地缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc


async def _status_dictionary(session: AsyncSession, *, source_id: str) -> list[dict[str, object]]:
    entries = await list_spin_order_statuses(session, source_id=source_id)
    by_code = {
        entry.entry_code: {
            "code": entry.entry_code,
            "label": entry.entry_label,
            "active": entry.active,
        }
        for entry in entries
    }
    for code, label in SPIN_ORDER_STATUS_ENTRIES:
        by_code.setdefault(code, {"code": code, "label": label, "active": True})
    return [by_code[code] for code in ("0", "1", "101", "2", "3")]


async def _channel_dictionary(session: AsyncSession, *, source_id: str) -> list[dict[str, str]]:
    entries = await list_user_source_channels(session, source_id=source_id, active=True)
    rows = [
        {"code": entry.entry_code, "label": entry.entry_label}
        for entry in entries
        if entry.entry_code != "-"
    ]
    return sorted(rows, key=lambda value: (value["label"], value["code"]))


def _channel_name(channel_id: str | None, labels: dict[str, str]) -> str:
    normalized = str(channel_id or "").strip()
    if not normalized:
        return "渠道待解析"
    return labels.get(normalized, "未登记渠道")


def _status_label(status: str, labels: dict[str, str]) -> str:
    return labels.get(status, f"状态 {status}")


def snapshot_to_spin_order(
    snapshot: SpinOrderSnapshot,
    *,
    channel_labels: dict[str, str],
    status_labels: dict[str, str],
) -> dict[str, Any]:
    config_id = snapshot.spin_config_id
    return {
        "id": snapshot.remote_order_id,
        "uid": snapshot.uid,
        "vip_level": snapshot.vip_level,
        "agent_total_count": snapshot.agent_total_count,
        "amount": snapshot.amount,
        "spin_config_id": config_id,
        "spin_config_label": SPIN_CONFIG_LABELS.get(config_id, config_id),
        "round_number": snapshot.round_number,
        "invite_count": snapshot.invite_count,
        "status": snapshot.status,
        "status_label": _status_label(snapshot.status, status_labels),
        "create_time": snapshot.create_time,
        "audit_time": snapshot.audit_time,
        "channel_id": snapshot.channel_id,
        "channel_name": _channel_name(snapshot.channel_id, channel_labels),
    }


def summarize_spin_orders(orders: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = defaultdict(int)
    uid_set: set[str] = set()
    passed_uids: set[str] = set()
    for order in orders:
        status = str(order.get("status") or "")
        status_counts[status] += 1
        uid = str(order.get("uid") or "")
        if uid:
            uid_set.add(uid)
            if status in PASSED_STATUS_CODES:
                passed_uids.add(uid)
    total = len(orders)
    passed = sum(status_counts[code] for code in PASSED_STATUS_CODES)

    def pct(numerator: int, denominator: int) -> str:
        return f"{numerator * 100 / denominator:.2f}" if denominator else "—"

    return {
        "order_count": total,
        "passed_order_count": passed,
        "pending_order_count": status_counts["0"],
        "rejected_order_count": status_counts["2"],
        "suspended_order_count": status_counts["3"],
        "approval_rate": pct(passed, total),
        "winner_count": len(uid_set),
        "passed_winner_count": len(passed_uids),
        "person_approval_rate": pct(len(passed_uids), len(uid_set)),
        "status_distribution": [
            {"status": code, "count": status_counts[code]} for code, _ in SPIN_ORDER_STATUS_ENTRIES
        ],
    }


async def query_spin_orders(
    session: AsyncSession,
    *,
    request: SpinOrderQueryRequest,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> SpinOrderQueryResult:
    source_id, source_name, timezone_name, query_at, start, end, state = await _context(
        session,
        source_id=request.source_id,
        create_time_start=request.create_time_start,
        create_time_end=request.create_time_end,
        settings=settings,
        now=now,
    )
    snapshots = await _snapshots(
        session,
        source_id=source_id,
        window_start=start,
        window_end=end,
        uid=request.uid,
        status=request.status,
        spin_config_id=request.spin_config_id,
        channel_id=request.channel_id,
    )
    status_dictionary = await _status_dictionary(session, source_id=source_id)
    channel_dictionary = await _channel_dictionary(session, source_id=source_id)
    status_labels = {str(row["code"]): str(row["label"]) for row in status_dictionary}
    channel_labels = {row["code"]: row["label"] for row in channel_dictionary}
    orders = [
        snapshot_to_spin_order(
            row,
            channel_labels=channel_labels,
            status_labels=status_labels,
        )
        for row in snapshots
    ]
    offset = (request.page - 1) * request.page_size
    return SpinOrderQueryResult(
        items=orders[offset : offset + request.page_size],
        total=len(orders),
        source_id=source_id,
        source_display_name=source_name,
        business_timezone=timezone_name,
        fetched_at=query_at,
        local_updated_at=max((_as_utc(row.synced_at) for row in snapshots), default=None),
        last_refreshed_at=_as_utc(state.last_succeeded_at) if state else None,
        refresh_status=state.status if state else "not_started",
        remote_total=state.last_remote_total if state else len(orders),
        fetched_pages=state.last_fetched_pages if state else 0,
        complete=state.last_complete if state else False,
        resolved_uid_count=state.last_resolved_uid_count if state else 0,
        unresolved_uid_count=state.last_unresolved_uid_count if state else 0,
        status_dictionary=status_dictionary,
        channel_dictionary=channel_dictionary,
        summary=summarize_spin_orders(orders),
    )


async def query_spin_channel_summary(
    session: AsyncSession,
    *,
    request: SpinChannelSummaryRequest,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> SpinChannelSummaryResult:
    source_id, source_name, timezone_name, query_at, start, end, _state = await _context(
        session,
        source_id=request.source_id,
        create_time_start=request.create_time_start,
        create_time_end=request.create_time_end,
        settings=settings,
        now=now,
    )
    snapshots = await _snapshots(
        session,
        source_id=source_id,
        window_start=start,
        window_end=end,
        spin_config_id=request.spin_config_id,
        channel_id=request.channel_id,
    )
    channel_dictionary = await _channel_dictionary(session, source_id=source_id)
    labels = {row["code"]: row["label"] for row in channel_dictionary}
    timezone = ZoneInfo(timezone_name)
    groups: dict[tuple[str, str, str | None], list[SpinOrderSnapshot]] = defaultdict(list)
    time_groups: dict[tuple[str, str, str, str | None], set[str]] = defaultdict(set)
    for snapshot in snapshots:
        created_at = _as_utc(snapshot.create_time_utc)
        if created_at is None:
            continue
        local = created_at.astimezone(timezone)
        business_date = local.date().isoformat()
        channel_id = snapshot.channel_id
        groups[(business_date, snapshot.spin_config_id, channel_id)].append(snapshot)
        bucket = f"{local.hour // 2 * 2:02d}:00-{local.hour // 2 * 2 + 1:02d}:59"
        if snapshot.uid:
            time_groups[(business_date, bucket, snapshot.spin_config_id, channel_id)].add(
                snapshot.uid
            )
    rows: list[dict[str, Any]] = []
    for (business_date, config_id, channel_id), group in groups.items():
        order_rows = [{"uid": row.uid, "status": row.status} for row in group]
        summary = summarize_spin_orders(order_rows)
        rows.append(
            {
                "date": business_date,
                "spin_config_id": config_id,
                "spin_config_label": SPIN_CONFIG_LABELS.get(config_id, config_id),
                "channel_id": channel_id,
                "channel_name": _channel_name(channel_id, labels),
                "application_order_count": summary["order_count"],
                "passed_order_count": summary["passed_order_count"],
                "pending_order_count": summary["pending_order_count"],
                "rejected_order_count": summary["rejected_order_count"],
                "suspended_order_count": summary["suspended_order_count"],
                "approval_rate": summary["approval_rate"],
                "winner_count": summary["winner_count"],
                "passed_winner_count": summary["passed_winner_count"],
                "person_approval_rate": summary["person_approval_rate"],
            }
        )
    rows.sort(
        key=lambda row: (
            row["date"],
            row["application_order_count"],
            row["channel_name"],
        ),
        reverse=True,
    )
    series = [
        {
            "date": date,
            "bucket": bucket,
            "spin_config_id": config_id,
            "spin_config_label": SPIN_CONFIG_LABELS.get(config_id, config_id),
            "channel_id": channel_id,
            "channel_name": _channel_name(channel_id, labels),
            "applicant_count": len(uids),
        }
        for (date, bucket, config_id, channel_id), uids in sorted(
            time_groups.items(),
            key=lambda item: (
                item[0][0],
                item[0][1],
                item[0][2],
                item[0][3] or "",
            ),
        )
    ]
    offset = (request.page - 1) * request.page_size
    return SpinChannelSummaryResult(
        items=rows[offset : offset + request.page_size],
        total=len(rows),
        source_id=source_id,
        source_display_name=source_name,
        business_timezone=timezone_name,
        fetched_at=query_at,
        local_updated_at=max((_as_utc(row.synced_at) for row in snapshots), default=None),
        channel_dictionary=channel_dictionary,
        time_series=series,
    )
