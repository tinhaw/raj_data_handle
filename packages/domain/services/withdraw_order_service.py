from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings, get_settings
from packages.domain.models import WithdrawOrderRefreshState, WithdrawOrderSnapshot
from packages.domain.schemas.withdraw_order import WithdrawOrderQueryRequest
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


class WithdrawOrderValidationError(ValueError):
    pass


class WithdrawOrderCacheSchemaPendingError(RuntimeError):
    """The application is running before migration 0006 has been applied."""


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
    summary: dict[str, Any]


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def normalize_withdraw_order_query_range(value: str | None) -> WithdrawOrderQueryRange:
    """Use the safe default if a legacy row contains an invalid preset."""

    if value in WITHDRAW_ORDER_QUERY_RANGES:
        return value  # type: ignore[return-value]
    return "today"


def withdraw_order_query_window(
    *,
    query_range: str,
    timezone_name: str,
    now: datetime,
) -> tuple[datetime, datetime]:
    """Return the effective UTC cache window for one source.

    ``today`` is defined in the source business timezone.  Its configured end
    is 23:59:59, but querying a future timestamp offers no value and was not
    supported by every remote source, so the effective end is capped at the
    refresh/query time.  Rolling presets end at that same time.
    """

    effective_now = now if now.tzinfo else now.replace(tzinfo=UTC)
    business_timezone = ZoneInfo(timezone_name)
    local_now = effective_now.astimezone(business_timezone)
    normalized_range = normalize_withdraw_order_query_range(query_range)
    if normalized_range == "today":
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_day_end = local_now.replace(hour=23, minute=59, second=59, microsecond=0)
        local_end = min(local_day_end, local_now)
        return local_start.astimezone(UTC), local_end.astimezone(UTC)
    duration = timedelta(hours=WITHDRAW_ORDER_ROLLING_RANGE_HOURS[normalized_range])
    utc_end = effective_now.astimezone(UTC)
    return utc_end - duration, utc_end


def local_withdraw_order_query_window(
    *,
    create_time_start: str | None,
    create_time_end: str | None,
    timezone_name: str,
    cache_window_start: datetime,
    cache_window_end: datetime,
) -> tuple[datetime, datetime]:
    """Intersect an optional page-local wall-time filter with cached data.

    The page's time range is expressed in the selected source's business
    timezone.  It never changes the worker's remote query: this helper only
    narrows the already configured local cache window.
    """

    if create_time_start is None and create_time_end is None:
        return cache_window_start, cache_window_end
    if create_time_start is None or create_time_end is None:
        raise WithdrawOrderValidationError("创建时间范围必须同时提供开始和结束时间。")
    try:
        business_timezone = ZoneInfo(timezone_name)
        requested_start = datetime.strptime(create_time_start, WALL_TIME_FORMAT).replace(
            tzinfo=business_timezone
        )
        requested_end = datetime.strptime(create_time_end, WALL_TIME_FORMAT).replace(
            tzinfo=business_timezone
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
    amount_total = sum((_decimal(item.get("amount")) for item in orders), Decimal("0"))
    real_amount_total = sum(
        (_decimal(item.get("real_amount")) for item in orders),
        Decimal("0"),
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
    """Project a cache row onto the only fields allowed in the UI/API."""

    return {
        "id": snapshot.remote_order_id,
        "uid": snapshot.uid,
        "amount": snapshot.amount,
        "real_amount": snapshot.real_amount,
        "create_time": snapshot.create_time,
        "update_time": snapshot.update_time,
        "submit_time": snapshot.submit_time,
        "audit_admin": snapshot.audit_admin,
        "status": snapshot.status,
    }


def _is_missing_withdraw_cache_schema(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    return (
        "withdraw_order_snapshots" in message
        or "withdraw_order_refresh_states" in message
    ) and ("does not exist" in message or "no such table" in message)


async def query_withdraw_orders(
    session: AsyncSession,
    *,
    request: WithdrawOrderQueryRequest,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> WithdrawOrderQueryResult:
    """Query the local cache only; remote calls are worker-owned.

    The active global query range bounds every local result, ensuring a prior
    wider cache cannot leak into a page after an administrator narrows the
    refresh policy.  A page-provided creation-time range can only narrow that
    local window; it never triggers or changes a remote request.
    """

    source = await get_source(session, request.source_id)
    if not source.enabled:
        raise WithdrawOrderValidationError("所选盘口尚未启用。")
    # Loading retention settings can fall back after a database rollback while
    # a newly released refresh-policy column is still awaiting migration.  A
    # rollback expires ORM instances, so retain the source values needed by
    # this local-only query before that compatibility path runs.
    source_id = source.source_id
    source_display_name = source.display_name
    business_timezone = source.business_timezone
    currency = source.currency
    current_settings = settings or get_settings()
    query_at = now or datetime.now(UTC)
    if query_at.tzinfo is None:
        query_at = query_at.replace(tzinfo=UTC)
    retention = await get_retention_settings(session, defaults=current_settings)
    cache_window_start, cache_window_end = withdraw_order_query_window(
        query_range=retention.withdraw_order_query_range,
        timezone_name=business_timezone,
        now=query_at,
    )
    window_start, window_end = local_withdraw_order_query_window(
        create_time_start=request.create_time_start,
        create_time_end=request.create_time_end,
        timezone_name=business_timezone,
        cache_window_start=cache_window_start,
        cache_window_end=cache_window_end,
    )

    statement = select(WithdrawOrderSnapshot).where(
        WithdrawOrderSnapshot.source_id == source_id,
        WithdrawOrderSnapshot.create_time_utc.is_not(None),
        WithdrawOrderSnapshot.create_time_utc >= window_start,
        WithdrawOrderSnapshot.create_time_utc <= window_end,
    )
    if request.uid:
        statement = statement.where(WithdrawOrderSnapshot.uid == request.uid)
    if request.status:
        statement = statement.where(WithdrawOrderSnapshot.status == request.status)
    if request.audit_admin:
        statement = statement.where(
            func.lower(WithdrawOrderSnapshot.audit_admin).contains(request.audit_admin.casefold())
        )
    statement = statement.order_by(
        WithdrawOrderSnapshot.create_time_utc.is_(None),
        desc(WithdrawOrderSnapshot.create_time_utc),
        desc(WithdrawOrderSnapshot.remote_order_id),
    )

    try:
        snapshots = list(await session.scalars(statement))
        refresh_state = await session.get(WithdrawOrderRefreshState, source_id)
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_withdraw_cache_schema(exc):
            raise
        await session.rollback()
        raise WithdrawOrderCacheSchemaPendingError(
            "提现订单本地缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc

    orders = [snapshot_to_withdraw_order(snapshot) for snapshot in snapshots]
    summary = summarize_withdraw_orders(
        orders,
        window_start=window_start,
        window_end=window_end,
    )
    offset = (request.page - 1) * request.page_size
    status_dictionary = await withdraw_status_dictionary(session, source_id=source_id)
    local_updated_at = max(
        (_as_utc(item.synced_at) for item in snapshots),
        default=None,
    )
    return WithdrawOrderQueryResult(
        items=orders[offset : offset + request.page_size],
        total=len(orders),
        remote_total=(
            refresh_state.last_remote_total if refresh_state is not None else len(orders)
        ),
        fetched_pages=refresh_state.last_fetched_pages if refresh_state is not None else 0,
        complete=refresh_state.last_complete if refresh_state is not None else False,
        source_id=source_id,
        source_display_name=source_display_name,
        business_timezone=business_timezone,
        currency=currency,
        effective_create_time_end=window_end.astimezone(
            ZoneInfo(business_timezone)
        ).strftime(WALL_TIME_FORMAT),
        fetched_at=query_at,
        local_updated_at=local_updated_at,
        last_refreshed_at=(
            _as_utc(refresh_state.last_succeeded_at)
            if refresh_state is not None
            else None
        ),
        refresh_status=refresh_state.status if refresh_state is not None else "not_started",
        status_dictionary=status_dictionary,
        summary=summary,
    )
