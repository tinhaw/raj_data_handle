from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import case, desc, false, func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings, get_settings
from packages.domain.models import WithdrawOrderRefreshState, WithdrawOrderSnapshot
from packages.domain.schemas.withdraw_order import (
    WithdrawChannelSummaryRequest,
    WithdrawOperatorSummaryRequest,
    WithdrawOrderQueryRequest,
)
from packages.domain.services.data_dictionary_service import withdraw_status_dictionary
from packages.domain.services.source_service import get_source
from packages.domain.services.system_setting_service import get_retention_settings

WALL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
WITHDRAW_ORDER_QUERY_RANGES = {
    "today",
    "last_1_hour",
    "last_2_hours",
    "last_3_hours",
    "last_6_hours",
    "last_12_hours",
    "last_24_hours",
    "last_48_hours",
}
WITHDRAW_ORDER_ROLLING_RANGE_HOURS = {
    "last_1_hour": 1,
    "last_2_hours": 2,
    "last_3_hours": 3,
    "last_6_hours": 6,
    "last_12_hours": 12,
    "last_24_hours": 24,
    "last_48_hours": 48,
}
OPERATOR_SUMMARY_EXCLUDED_STATUS_CODES = frozenset({"0", "4", "5"})
OPERATOR_SUMMARY_EXCLUDED_STATUS_LABELS = frozenset({"待审核", "待审查", "提交中"})


class WithdrawOrderValidationError(ValueError):
    pass


class WithdrawOrderCacheSchemaPendingError(RuntimeError):
    """The application is running before withdrawal cache migration completes."""


WithdrawOrderQueryRange = Literal[
    "today",
    "last_1_hour",
    "last_2_hours",
    "last_3_hours",
    "last_6_hours",
    "last_12_hours",
    "last_24_hours",
    "last_48_hours",
]


@dataclass(frozen=True, slots=True)
class WithdrawOrderQueryResult:
    items: list[dict[str, Any]]
    total: int
    remote_total: int
    fetched_pages: int
    complete: bool
    source_id: str
    source_display_name: str
    business_timezone: str
    currency: str
    effective_create_time_end: str
    fetched_at: datetime
    local_updated_at: datetime | None
    last_refreshed_at: datetime | None
    refresh_status: str
    status_dictionary: list[dict[str, object]]
    channel_dictionary: list[dict[str, str]]
    summary: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WithdrawChannelSummaryResult:
    items: list[dict[str, Any]]
    total: int
    source_id: str
    source_display_name: str
    business_timezone: str
    currency: str
    effective_create_time_end: str
    fetched_at: datetime
    local_updated_at: datetime | None
    channel_dictionary: list[dict[str, str]]


@dataclass(frozen=True, slots=True)
class WithdrawOperatorSummaryResult:
    items: list[dict[str, Any]]
    total: int
    source_id: str
    source_display_name: str
    business_timezone: str
    effective_create_time_end: str
    fetched_at: datetime
    local_updated_at: datetime | None
    status_columns: list[str]
    status_dictionary: list[dict[str, object]]
    selected_order_total: int


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _percent(numerator: int | Decimal, denominator: int | Decimal) -> str:
    if not denominator:
        return "—"
    return _decimal_text(Decimal(numerator) * Decimal("100") / Decimal(denominator))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _is_operator_summary_excluded_status(entry: dict[str, object]) -> bool:
    return (
        str(entry.get("code") or "").strip() in OPERATOR_SUMMARY_EXCLUDED_STATUS_CODES
        or str(entry.get("label") or "").strip() in OPERATOR_SUMMARY_EXCLUDED_STATUS_LABELS
    )


def normalize_withdraw_order_query_range(value: str | None) -> WithdrawOrderQueryRange:
    """Normalize a legacy page-window value during staged upgrades.

    The active detail and summary APIs now use cache-retention bounds plus the
    user's own time filter; this helper is retained for older integrations and
    is intentionally not read by the export scheduler.
    """

    if value in WITHDRAW_ORDER_QUERY_RANGES:
        return value  # type: ignore[return-value]
    return "today"


def withdraw_order_query_window(
    *,
    query_range: str,
    timezone_name: str,
    now: datetime,
) -> tuple[datetime, datetime]:
    """Return a legacy rolling window without affecting current cache queries."""

    effective_now = now if now.tzinfo else now.replace(tzinfo=UTC)
    timezone = ZoneInfo(timezone_name)
    local_now = effective_now.astimezone(timezone)
    normalized_range = normalize_withdraw_order_query_range(query_range)
    if normalized_range == "today":
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end = min(
            local_now.replace(hour=23, minute=59, second=59, microsecond=0),
            local_now,
        )
        return local_start.astimezone(UTC), local_end.astimezone(UTC)
    utc_end = effective_now.astimezone(UTC)
    return utc_end - timedelta(hours=WITHDRAW_ORDER_ROLLING_RANGE_HOURS[normalized_range]), utc_end


def local_withdraw_order_query_window(
    *,
    create_time_start: str | None,
    create_time_end: str | None,
    timezone_name: str,
    cache_window_start: datetime,
    cache_window_end: datetime,
) -> tuple[datetime, datetime]:
    """Resolve a page-local business-time range within cache retention bounds."""

    if create_time_start is None and create_time_end is None:
        return cache_window_start, cache_window_end
    if create_time_start is None or create_time_end is None:
        raise WithdrawOrderValidationError("创建时间范围必须同时提供开始和结束时间。")
    try:
        timezone = ZoneInfo(timezone_name)
        requested_start = datetime.strptime(create_time_start, WALL_TIME_FORMAT).replace(
            tzinfo=timezone
        )
        requested_end = datetime.strptime(create_time_end, WALL_TIME_FORMAT).replace(
            tzinfo=timezone
        )
    except ValueError as exc:
        raise WithdrawOrderValidationError(
            "创建时间必须使用 YYYY-MM-DD HH:mm:ss 格式。"
        ) from exc
    if requested_start > requested_end:
        raise WithdrawOrderValidationError("创建时间范围的开始时间不能晚于结束时间。")
    return (
        max(cache_window_start, requested_start.astimezone(UTC)),
        min(cache_window_end, requested_end.astimezone(UTC)),
    )


def summarize_withdraw_orders(
    orders: list[dict[str, Any]],
    *,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    amount_total = sum((_decimal(order.get("amount")) for order in orders), Decimal("0"))
    real_amount_total = sum(
        (_decimal(order.get("real_amount")) for order in orders), Decimal("0")
    )
    status_rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "amount": Decimal("0"), "real_amount": Decimal("0")}
    )
    use_hour_bucket = window_end - window_start <= timedelta(days=2)
    time_rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "amount": Decimal("0"), "real_amount": Decimal("0")}
    )
    for order in orders:
        status = str(order.get("status") or "")
        amount = _decimal(order.get("amount"))
        real_amount = _decimal(order.get("real_amount"))
        status_rows[status]["count"] += 1
        status_rows[status]["amount"] += amount
        status_rows[status]["real_amount"] += real_amount
        create_time = str(order.get("create_time") or "")
        bucket = create_time[:13] + ":00" if use_hour_bucket else create_time[:10]
        if bucket:
            time_rows[bucket]["count"] += 1
            time_rows[bucket]["amount"] += amount
            time_rows[bucket]["real_amount"] += real_amount
    order_count = len(orders)
    return {
        "order_count": order_count,
        "amount": _decimal_text(amount_total),
        "real_amount": _decimal_text(real_amount_total),
        "average_amount": _decimal_text(
            amount_total / order_count if order_count else Decimal("0")
        ),
        "status_distribution": [
            {
                "status": status,
                "count": values["count"],
                "amount": _decimal_text(values["amount"]),
                "real_amount": _decimal_text(values["real_amount"]),
            }
            for status, values in sorted(status_rows.items())
        ],
        "time_series": [
            {
                "bucket": bucket,
                "count": values["count"],
                "amount": _decimal_text(values["amount"]),
                "real_amount": _decimal_text(values["real_amount"]),
            }
            for bucket, values in sorted(time_rows.items())
        ],
    }


def snapshot_to_withdraw_order(snapshot: WithdrawOrderSnapshot) -> dict[str, Any]:
    """Project a local cache row to approved detail fields only."""

    return {
        "id": snapshot.remote_order_id,
        "uid": snapshot.uid,
        "order_num": snapshot.order_num,
        "out_trade_no": snapshot.out_trade_no,
        "pay_channel_name": snapshot.pay_channel_name,
        "pay_channel": snapshot.pay_channel,
        "amount": snapshot.amount,
        "real_amount": snapshot.real_amount,
        "fee": snapshot.fee,
        "create_time": snapshot.create_time,
        "update_time": snapshot.update_time,
        "submit_time": snapshot.submit_time,
        "audit_admin": snapshot.audit_admin,
        "status": snapshot.status,
        "status_label": snapshot.status_label,
        "is_first": snapshot.is_first,
        "channel": snapshot.channel,
    }


def _is_missing_withdraw_cache_schema(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    missing_table = (
        "withdraw_order_snapshots" in message
        or "withdraw_order_refresh_states" in message
    ) and ("does not exist" in message or "no such table" in message)
    missing_export_columns = any(
        column in message
        for column in (
            "order_num",
            "out_trade_no",
            "pay_channel_name",
            "pay_channel",
            "status_label",
            "is_first",
        )
    ) and ("does not exist" in message or "no such column" in message)
    return missing_table or missing_export_columns


async def _query_context(
    session: AsyncSession,
    *,
    source_id: str,
    create_time_start: str | None,
    create_time_end: str | None,
    settings: Settings | None,
    now: datetime | None,
) -> tuple[str, str, str, str, datetime, datetime, datetime, WithdrawOrderRefreshState | None]:
    source = await get_source(session, source_id)
    if not source.enabled:
        raise WithdrawOrderValidationError("所选盘口尚未启用。")
    selected_id = source.source_id
    display_name = source.display_name
    timezone_name = source.business_timezone
    currency = source.currency
    query_at = now or datetime.now(UTC)
    if query_at.tzinfo is None:
        query_at = query_at.replace(tzinfo=UTC)
    retention = await get_retention_settings(session, defaults=settings or get_settings())
    business_now = query_at.astimezone(ZoneInfo(timezone_name))
    earliest_cached_day = business_now - timedelta(days=retention.remote_cache_retention_days)
    cache_window_start = earliest_cached_day.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ).astimezone(UTC)
    cache_window_end = business_now.replace(
        hour=23,
        minute=59,
        second=59,
        microsecond=0,
    ).astimezone(UTC)
    try:
        window_start, window_end = local_withdraw_order_query_window(
            create_time_start=create_time_start,
            create_time_end=create_time_end,
            timezone_name=timezone_name,
            cache_window_start=cache_window_start,
            cache_window_end=cache_window_end,
        )
        refresh_state = await session.get(WithdrawOrderRefreshState, selected_id)
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_withdraw_cache_schema(exc):
            raise
        await session.rollback()
        raise WithdrawOrderCacheSchemaPendingError(
            "提现订单本地缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc
    return (
        selected_id,
        display_name,
        timezone_name,
        currency,
        query_at,
        window_start,
        window_end,
        refresh_state,
    )


async def _filtered_snapshots(
    session: AsyncSession,
    *,
    source_id: str,
    window_start: datetime,
    window_end: datetime,
    uid: str | None = None,
    status: str | None = None,
    audit_admin: str | None = None,
    order_num: str | None = None,
    out_trade_no: str | None = None,
    pay_channel: str | None = None,
) -> list[WithdrawOrderSnapshot]:
    statement = select(WithdrawOrderSnapshot).where(
        WithdrawOrderSnapshot.source_id == source_id,
        WithdrawOrderSnapshot.create_time_utc.is_not(None),
        WithdrawOrderSnapshot.create_time_utc >= window_start,
        WithdrawOrderSnapshot.create_time_utc <= window_end,
    )
    if uid:
        statement = statement.where(WithdrawOrderSnapshot.uid == uid)
    if status:
        statement = statement.where(WithdrawOrderSnapshot.status == status)
    if audit_admin:
        statement = statement.where(
            func.lower(WithdrawOrderSnapshot.audit_admin).contains(audit_admin.casefold())
        )
    if order_num:
        statement = statement.where(
            func.lower(WithdrawOrderSnapshot.order_num).contains(order_num.casefold())
        )
    if out_trade_no:
        statement = statement.where(
            func.lower(WithdrawOrderSnapshot.out_trade_no).contains(out_trade_no.casefold())
        )
    if pay_channel:
        statement = statement.where(WithdrawOrderSnapshot.pay_channel == pay_channel)
    statement = statement.order_by(
        WithdrawOrderSnapshot.create_time_utc.is_(None),
        desc(WithdrawOrderSnapshot.create_time_utc),
        desc(WithdrawOrderSnapshot.remote_order_id),
    )
    try:
        return list(await session.scalars(statement))
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_withdraw_cache_schema(exc):
            raise
        await session.rollback()
        raise WithdrawOrderCacheSchemaPendingError(
            "提现订单本地缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc


async def _status_dictionary(
    session: AsyncSession,
    *,
    source_id: str,
    orders: list[dict[str, Any]],
) -> list[dict[str, object]]:
    entries = await withdraw_status_dictionary(session, source_id=source_id)
    by_code = {str(entry["code"]): entry for entry in entries}
    for order in orders:
        code = str(order.get("status") or "").strip()
        if not code or code in by_code:
            continue
        label = str(order.get("status_label") or "").strip() or f"状态 {code}"
        by_code[code] = {"code": code, "label": label, "active": False}
    return [
        by_code[code]
        for code in sorted(by_code, key=lambda value: (not value.lstrip("-").isdigit(), value))
    ]


async def _channel_dictionary(
    session: AsyncSession,
    *,
    source_id: str,
) -> list[dict[str, str]]:
    """Return every locally observed channel for the selected source.

    The selector must not collapse to a single option after a user narrows a
    detail query by channel or date.  It remains a local-cache dictionary and
    never triggers a remote call.
    """

    try:
        snapshots = list(
            await session.scalars(
                select(WithdrawOrderSnapshot)
                .where(
                    WithdrawOrderSnapshot.source_id == source_id,
                    WithdrawOrderSnapshot.pay_channel.is_not(None),
                )
                .order_by(
                    WithdrawOrderSnapshot.pay_channel,
                    desc(WithdrawOrderSnapshot.synced_at),
                )
            )
        )
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_withdraw_cache_schema(exc):
            raise
        await session.rollback()
        raise WithdrawOrderCacheSchemaPendingError(
            "提现订单本地缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc
    labels: dict[str, str] = {}
    for snapshot in snapshots:
        code = str(snapshot.pay_channel or "").strip()
        if not code:
            continue
        label = str(snapshot.pay_channel_name or "").strip() or code
        labels.setdefault(code, label)
    return [
        {"code": code, "label": label}
        for code, label in sorted(labels.items(), key=lambda item: (item[1], item[0]))
    ]


async def query_withdraw_orders(
    session: AsyncSession,
    *,
    request: WithdrawOrderQueryRequest,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> WithdrawOrderQueryResult:
    (
        source_id,
        source_display_name,
        timezone_name,
        currency,
        query_at,
        window_start,
        window_end,
        refresh_state,
    ) = await _query_context(
        session,
        source_id=request.source_id,
        create_time_start=request.create_time_start,
        create_time_end=request.create_time_end,
        settings=settings,
        now=now,
    )
    snapshots = await _filtered_snapshots(
        session,
        source_id=source_id,
        window_start=window_start,
        window_end=window_end,
        uid=request.uid,
        status=request.status,
        audit_admin=request.audit_admin,
        order_num=request.order_num,
        out_trade_no=request.out_trade_no,
        pay_channel=request.pay_channel,
    )
    orders = [snapshot_to_withdraw_order(snapshot) for snapshot in snapshots]
    offset = (request.page - 1) * request.page_size
    return WithdrawOrderQueryResult(
        items=orders[offset : offset + request.page_size],
        total=len(orders),
        remote_total=refresh_state.last_remote_total if refresh_state else len(orders),
        fetched_pages=refresh_state.last_fetched_pages if refresh_state else 0,
        complete=refresh_state.last_complete if refresh_state else False,
        source_id=source_id,
        source_display_name=source_display_name,
        business_timezone=timezone_name,
        currency=currency,
        effective_create_time_end=window_end.astimezone(ZoneInfo(timezone_name)).strftime(
            WALL_TIME_FORMAT
        ),
        fetched_at=query_at,
        local_updated_at=max((_as_utc(row.synced_at) for row in snapshots), default=None),
        last_refreshed_at=_as_utc(refresh_state.last_succeeded_at) if refresh_state else None,
        refresh_status=refresh_state.status if refresh_state else "not_started",
        status_dictionary=await _status_dictionary(
            session,
            source_id=source_id,
            orders=orders,
        ),
        channel_dictionary=await _channel_dictionary(session, source_id=source_id),
        summary=summarize_withdraw_orders(
            orders,
            window_start=window_start,
            window_end=window_end,
        ),
    )


def _status_codes_for_label(
    status_dictionary: list[dict[str, object]],
    label: str,
) -> set[str]:
    return {
        str(entry.get("code") or "").strip()
        for entry in status_dictionary
        if str(entry.get("label") or "").strip() == label
    }


def _has_status(order: dict[str, Any], *, codes: set[str], label: str) -> bool:
    return (
        str(order.get("status") or "").strip() in codes
        or str(order.get("status_label") or "").strip() == label
    )


async def query_withdraw_channel_summary(
    session: AsyncSession,
    *,
    request: WithdrawChannelSummaryRequest,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> WithdrawChannelSummaryResult:
    (
        source_id,
        source_display_name,
        timezone_name,
        currency,
        query_at,
        window_start,
        window_end,
        _refresh_state,
    ) = await _query_context(
        session,
        source_id=request.source_id,
        create_time_start=request.create_time_start,
        create_time_end=request.create_time_end,
        settings=settings,
        now=now,
    )
    # Do not apply the selected channel here: the selected row's shares must
    # retain all channels of the same source/day as their denominator.
    snapshots = await _filtered_snapshots(
        session,
        source_id=source_id,
        window_start=window_start,
        window_end=window_end,
    )
    orders = [snapshot_to_withdraw_order(snapshot) for snapshot in snapshots]
    status_dictionary = await _status_dictionary(session, source_id=source_id, orders=orders)
    success_codes = _status_codes_for_label(status_dictionary, "代付成功")
    failed_codes = _status_codes_for_label(status_dictionary, "代付失败")
    submitted_codes = _status_codes_for_label(status_dictionary, "已提交代付")
    rejected_codes = _status_codes_for_label(status_dictionary, "审核拒绝")

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    labels: dict[tuple[str, str], str] = {}
    for snapshot, order in zip(snapshots, orders, strict=True):
        created_at = _as_utc(snapshot.create_time_utc)
        if created_at is None:
            continue
        business_date = created_at.astimezone(ZoneInfo(timezone_name)).date().isoformat()
        channel_code = str(order.get("pay_channel") or "").strip()
        group_key = (business_date, channel_code)
        groups[group_key].append(order)
        labels.setdefault(
            group_key,
            str(order.get("pay_channel_name") or "").strip() or channel_code or "未识别渠道",
        )

    daily_success_orders: dict[str, int] = defaultdict(int)
    daily_success_amounts: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    staged: list[tuple[tuple[str, str], list[dict[str, Any]], list[dict[str, Any]]]] = []
    for group_key, group_orders in groups.items():
        successful = [
            order
            for order in group_orders
            if _has_status(order, codes=success_codes, label="代付成功")
        ]
        daily_success_orders[group_key[0]] += len(successful)
        daily_success_amounts[group_key[0]] += sum(
            (_decimal(order.get("real_amount")) for order in successful), Decimal("0")
        )
        staged.append((group_key, group_orders, successful))

    rows: list[dict[str, Any]] = []
    for (business_date, channel_code), group_orders, successful in staged:
        success_amount = sum(
            (_decimal(order.get("real_amount")) for order in successful), Decimal("0")
        )
        success_fee = sum(
            (_decimal(order.get("fee")) for order in successful), Decimal("0")
        )
        failed_count = sum(
            1
            for order in group_orders
            if _has_status(order, codes=failed_codes, label="代付失败")
        )
        submitted_count = sum(
            1
            for order in group_orders
            if _has_status(order, codes=submitted_codes, label="已提交代付")
        )
        rejected_count = sum(
            1
            for order in group_orders
            if _has_status(order, codes=rejected_codes, label="审核拒绝")
        )
        rows.append(
            {
                "date": business_date,
                "pay_channel": channel_code,
                "pay_channel_name": labels[(business_date, channel_code)],
                "order_count": len(group_orders),
                "successful_order_count": len(successful),
                "successful_amount": _decimal_text(success_amount),
                "successful_fee": _decimal_text(success_fee),
                "failed_order_count": failed_count,
                "submitted_order_count": submitted_count,
                "rejected_order_count": rejected_count,
                "successful_order_share": _percent(
                    len(successful), daily_success_orders[business_date]
                ),
                "successful_amount_share": _percent(
                    success_amount, daily_success_amounts[business_date]
                ),
                "stuck_rate": _percent(submitted_count, len(group_orders)),
                "success_rate": _percent(len(successful), len(group_orders)),
            }
        )
    if request.pay_channel:
        rows = [row for row in rows if row["pay_channel"] == request.pay_channel]
    rows.sort(
        key=lambda item: (
            item["date"],
            item["successful_order_count"],
            item["pay_channel_name"],
        ),
        reverse=True,
    )
    offset = (request.page - 1) * request.page_size
    return WithdrawChannelSummaryResult(
        items=rows[offset : offset + request.page_size],
        total=len(rows),
        source_id=source_id,
        source_display_name=source_display_name,
        business_timezone=timezone_name,
        currency=currency,
        effective_create_time_end=window_end.astimezone(ZoneInfo(timezone_name)).strftime(
            WALL_TIME_FORMAT
        ),
        fetched_at=query_at,
        local_updated_at=max((_as_utc(row.synced_at) for row in snapshots), default=None),
        channel_dictionary=await _channel_dictionary(session, source_id=source_id),
    )


async def query_withdraw_operator_summary(
    session: AsyncSession,
    *,
    request: WithdrawOperatorSummaryRequest,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> WithdrawOperatorSummaryResult:
    (
        source_id,
        source_display_name,
        timezone_name,
        _currency,
        query_at,
        window_start,
        window_end,
        _refresh_state,
    ) = await _query_context(
        session,
        source_id=request.source_id,
        create_time_start=request.create_time_start,
        create_time_end=request.create_time_end,
        settings=settings,
        now=now,
    )
    base_conditions = [
        WithdrawOrderSnapshot.source_id == source_id,
        WithdrawOrderSnapshot.create_time_utc.is_not(None),
        WithdrawOrderSnapshot.create_time_utc >= window_start,
        WithdrawOrderSnapshot.create_time_utc <= window_end,
    ]
    if request.audit_admin:
        base_conditions.append(
            func.lower(WithdrawOrderSnapshot.audit_admin).contains(request.audit_admin.casefold())
        )
    normalized_audit_admin = func.trim(func.coalesce(WithdrawOrderSnapshot.audit_admin, ""))
    audit_admin_missing = case((normalized_audit_admin == "", True), else_=False).label(
        "audit_admin_missing"
    )
    displayed_audit_admin = case(
        (normalized_audit_admin == "", "系统"),
        else_=normalized_audit_admin,
    ).label("audit_admin")
    selected_total_expression = func.count(WithdrawOrderSnapshot.id).label("selected_total")
    try:
        raw_status_dictionary = await withdraw_status_dictionary(session, source_id=source_id)
        excluded_statuses = {
            str(entry["code"]).strip()
            for entry in raw_status_dictionary
            if _is_operator_summary_excluded_status(entry)
        }
        status_dictionary = [
            entry
            for entry in raw_status_dictionary
            if not _is_operator_summary_excluded_status(entry)
        ]
        selected_conditions = [*base_conditions]
        selected_statuses = (
            [status for status in request.statuses if status not in excluded_statuses]
            if request.statuses is not None
            else None
        )
        if selected_statuses is not None:
            if selected_statuses:
                selected_conditions.append(WithdrawOrderSnapshot.status.in_(selected_statuses))
            else:
                selected_conditions.append(false())
        elif excluded_statuses:
            selected_conditions.append(WithdrawOrderSnapshot.status.not_in(excluded_statuses))

        if selected_statuses is not None:
            status_columns = list(selected_statuses)
        else:
            observed_statuses = [
                str(status)
                for status in await session.scalars(
                    select(WithdrawOrderSnapshot.status)
                    .where(*selected_conditions)
                    .distinct()
                    .order_by(WithdrawOrderSnapshot.status)
                )
            ]
            status_columns = [
                str(entry["code"])
                for entry in status_dictionary
                if bool(entry["active"])
            ]
            status_columns.extend(
                status for status in observed_statuses if status not in status_columns
            )
        metrics = (
            await session.execute(
                select(
                    func.count(WithdrawOrderSnapshot.id).label("selected_order_total"),
                    func.count(func.distinct(normalized_audit_admin)).label("operator_total"),
                    func.max(WithdrawOrderSnapshot.synced_at).label("local_updated_at"),
                ).where(*selected_conditions)
            )
        ).mappings().one()
        status_count_expressions = [
            func.count(case((WithdrawOrderSnapshot.status == status, 1))).label(
                f"status_count_{index}"
            )
            for index, status in enumerate(status_columns)
        ]
        rows = (
            await session.execute(
                select(
                    displayed_audit_admin,
                    audit_admin_missing,
                    selected_total_expression,
                    *status_count_expressions,
                )
                .where(*selected_conditions)
                .group_by(normalized_audit_admin, displayed_audit_admin, audit_admin_missing)
                .order_by(desc(selected_total_expression), normalized_audit_admin)
                .offset((request.page - 1) * request.page_size)
                .limit(request.page_size)
            )
        ).mappings().all()
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_withdraw_cache_schema(exc):
            raise
        await session.rollback()
        raise WithdrawOrderCacheSchemaPendingError(
            "提现订单本地缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc
    return WithdrawOperatorSummaryResult(
        items=[
            {
                "audit_admin": str(row["audit_admin"]),
                "audit_admin_missing": bool(row["audit_admin_missing"]),
                "status_counts": [
                    {"status": status, "count": int(row[f"status_count_{index}"] or 0)}
                    for index, status in enumerate(status_columns)
                ],
                "selected_total": int(row["selected_total"] or 0),
            }
            for row in rows
        ],
        total=int(metrics["operator_total"] or 0),
        source_id=source_id,
        source_display_name=source_display_name,
        business_timezone=timezone_name,
        effective_create_time_end=window_end.astimezone(ZoneInfo(timezone_name)).strftime(
            WALL_TIME_FORMAT
        ),
        fetched_at=query_at,
        local_updated_at=_as_utc(metrics["local_updated_at"]),
        status_columns=status_columns,
        status_dictionary=status_dictionary,
        selected_order_total=int(metrics["selected_order_total"] or 0),
    )
