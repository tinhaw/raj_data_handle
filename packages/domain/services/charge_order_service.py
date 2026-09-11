from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings, get_settings
from packages.domain.models import ChargeOrderRefreshState, ChargeOrderSnapshot
from packages.domain.schemas.charge_order import (
    ChargeChannelSummaryRequest,
    ChargeOrderQueryRequest,
)
from packages.domain.services.data_dictionary_service import (
    list_charge_statuses,
    list_payment_channel_names,
    list_payment_channels,
)
from packages.domain.services.source_service import get_source
from packages.domain.services.system_setting_service import get_retention_settings
from packages.domain.services.withdraw_order_service import (
    WALL_TIME_FORMAT,
    local_withdraw_order_query_window,
)


class ChargeOrderValidationError(ValueError):
    pass


class ChargeOrderCacheSchemaPendingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ChargeOrderQueryResult:
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
    status_dictionary: list[dict[str, str]]
    channel_dictionary: list[dict[str, str]]
    channel_name_dictionary: list[dict[str, str]]
    summary: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChargeChannelSummaryResult:
    items: list[dict[str, Any]]
    denomination_distribution: list[dict[str, Any]]
    total: int
    source_id: str
    source_display_name: str
    business_timezone: str
    effective_create_time_end: str
    fetched_at: datetime
    local_updated_at: datetime | None


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _valid_decimal(value: object) -> Decimal | None:
    raw = "" if value is None else str(value).strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _denomination_text(value: Decimal) -> str:
    """Return a stable exact denomination label without applying a display bucket."""
    normalized = value.normalize()
    return format(normalized, "f")


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _percent(numerator: int | Decimal, denominator: int | Decimal) -> str:
    if not denominator:
        return "0.00"
    return _decimal_text(Decimal(numerator) * Decimal("100") / Decimal(denominator))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _is_missing_charge_cache_schema(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    return ("charge_order_snapshots" in message or "charge_order_refresh_states" in message) and (
        "does not exist" in message or "no such table" in message
    )


def _status_sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


async def _status_dictionary(
    session: AsyncSession,
    *,
    source_id: str,
    observed: set[str],
) -> list[dict[str, str]]:
    entries = await list_charge_statuses(session, source_id=source_id, active=True)
    labels = {entry.entry_code: entry.entry_label for entry in entries}
    codes = sorted(set(labels).union(observed), key=_status_sort_key)
    return [
        {"code": code, "label": labels.get(code, f"状态 {code}")}
        for code in codes
    ]


def _missing_third_party_order(order: dict[str, Any]) -> bool:
    return str(order.get("out_trade_no") or "").strip().lower() in {"", "0", "-"}


def snapshot_to_charge_order(snapshot: ChargeOrderSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.remote_order_id,
        "uid": snapshot.uid,
        "order_num": snapshot.order_num,
        "charge_product_id": snapshot.charge_product_id,
        "product_name": snapshot.product_name,
        "out_trade_no": snapshot.out_trade_no,
        "pay_method": snapshot.pay_method,
        "pay_channel_name": snapshot.pay_channel_name,
        "pay_type": snapshot.pay_type,
        "amount": snapshot.amount,
        "balance": snapshot.balance,
        "extra": snapshot.extra,
        "status": snapshot.status,
        "create_time": snapshot.create_time,
        "pay_time": snapshot.pay_time,
        "update_time": snapshot.update_time,
        "first_pay": snapshot.first_pay,
        "notified": snapshot.notified,
        "charge_type": snapshot.charge_type,
        "fill_order_num": snapshot.fill_order_num,
        "fill_order_admin": snapshot.fill_order_admin,
        "channel": snapshot.channel,
    }


def summarize_charge_orders(orders: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [order for order in orders if str(order.get("status") or "") == "1"]
    return {
        "order_count": len(orders),
        "successful_order_count": len(successful),
        "successful_amount": _decimal_text(
            sum((_decimal(order.get("amount")) for order in successful), Decimal("0"))
        ),
        "unpaid_order_count": sum(1 for order in orders if str(order.get("status") or "") == "0"),
        "no_third_party_order_count": sum(
            1 for order in orders if _missing_third_party_order(order)
        ),
    }


async def _query_context(
    session: AsyncSession,
    *,
    source_id: str,
    create_time_start: str | None,
    create_time_end: str | None,
    settings: Settings | None,
    now: datetime | None,
) -> tuple[str, str, str, str, datetime, datetime, datetime, ChargeOrderRefreshState | None]:
    source = await get_source(session, source_id)
    if not source.enabled:
        raise ChargeOrderValidationError("所选盘口尚未启用。")
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
        refresh_state = await session.get(ChargeOrderRefreshState, selected_id)
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_charge_cache_schema(exc):
            raise
        await session.rollback()
        raise ChargeOrderCacheSchemaPendingError(
            "充值订单本地缓存正在初始化，请在数据库迁移完成后重试。"
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


async def _filtered_orders(
    session: AsyncSession,
    *,
    request: ChargeOrderQueryRequest,
    source_id: str,
    window_start: datetime,
    window_end: datetime,
) -> list[ChargeOrderSnapshot]:
    statement = select(ChargeOrderSnapshot).where(
        ChargeOrderSnapshot.source_id == source_id,
        ChargeOrderSnapshot.create_time_utc.is_not(None),
        ChargeOrderSnapshot.create_time_utc >= window_start,
        ChargeOrderSnapshot.create_time_utc <= window_end,
    )
    if request.uid:
        statement = statement.where(ChargeOrderSnapshot.uid == request.uid)
    if request.status:
        statement = statement.where(ChargeOrderSnapshot.status == request.status)
    if request.pay_method:
        statement = statement.where(ChargeOrderSnapshot.pay_method == request.pay_method)
    if request.order_num:
        statement = statement.where(
            func.lower(ChargeOrderSnapshot.order_num).contains(request.order_num.casefold())
        )
    statement = statement.order_by(
        ChargeOrderSnapshot.create_time_utc.is_(None),
        desc(ChargeOrderSnapshot.create_time_utc),
        desc(ChargeOrderSnapshot.remote_order_id),
    )
    try:
        return list(await session.scalars(statement))
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_charge_cache_schema(exc):
            raise
        await session.rollback()
        raise ChargeOrderCacheSchemaPendingError(
            "充值订单本地缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc


async def _channel_dictionary(session: AsyncSession, source_id: str) -> list[dict[str, str]]:
    entries = await list_payment_channels(session, source_id=source_id, active=True)
    return [{"code": entry.entry_code, "label": entry.entry_label} for entry in entries]


async def _channel_name_dictionary(
    session: AsyncSession,
    source_id: str,
) -> list[dict[str, str]]:
    entries = await list_payment_channel_names(session, source_id=source_id, active=True)
    return [{"code": entry.entry_code, "label": entry.entry_label} for entry in entries]


async def query_charge_orders(
    session: AsyncSession,
    *,
    request: ChargeOrderQueryRequest,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> ChargeOrderQueryResult:
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
    snapshots = await _filtered_orders(
        session,
        request=request,
        source_id=source_id,
        window_start=window_start,
        window_end=window_end,
    )
    orders = [snapshot_to_charge_order(snapshot) for snapshot in snapshots]
    offset = (request.page - 1) * request.page_size
    return ChargeOrderQueryResult(
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
            observed={order["status"] for order in orders},
        ),
        channel_dictionary=await _channel_dictionary(session, source_id),
        channel_name_dictionary=await _channel_name_dictionary(session, source_id),
        summary=summarize_charge_orders(orders),
    )


async def query_charge_channel_summary(
    session: AsyncSession,
    *,
    request: ChargeChannelSummaryRequest,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> ChargeChannelSummaryResult:
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
    snapshots = await _filtered_orders(
        session,
        request=request,
        source_id=source_id,
        window_start=window_start,
        window_end=window_end,
    )
    payment_channel_labels = {
        entry["code"]: entry["label"] for entry in await _channel_dictionary(session, source_id)
    }
    channel_name_labels = {
        entry["code"]: entry["label"]
        for entry in await _channel_name_dictionary(session, source_id)
    }
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    local_updated_at: datetime | None = None
    for snapshot in snapshots:
        order = snapshot_to_charge_order(snapshot)
        groups[str(order.get("pay_method") or "")].append(order)
        synced_at = _as_utc(snapshot.synced_at)
        if synced_at and (local_updated_at is None or synced_at > local_updated_at):
            local_updated_at = synced_at

    rows: list[dict[str, Any]] = []
    denomination_groups: dict[Decimal, list[dict[str, Any]]] = defaultdict(list)
    successful_total = 0
    successful_amount_total = Decimal("0")
    staged: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]] = []
    for code, orders in groups.items():
        successful = [order for order in orders if str(order.get("status") or "") == "1"]
        for order in successful:
            amount = _valid_decimal(order.get("amount"))
            if amount is not None:
                denomination_groups[amount].append(order)
        successful_total += len(successful)
        successful_amount_total += sum(
            (_decimal(order.get("amount")) for order in successful), Decimal("0")
        )
        staged.append((code, orders, successful))
    for code, orders, successful in staged:
        successful_amount = sum(
            (_decimal(order.get("amount")) for order in successful), Decimal("0")
        )
        raw_name_code = next(
            (
                str(order.get("pay_channel_name") or "").strip()
                for order in orders
                if order.get("pay_channel_name")
            ),
            "",
        )
        rows.append(
            {
                "pay_method": code,
                "pay_channel_name": (
                    channel_name_labels.get(raw_name_code)
                    or payment_channel_labels.get(code)
                    or raw_name_code
                    or code
                    or "未识别渠道"
                ),
                "order_count": len(orders),
                "successful_order_count": len(successful),
                "successful_amount": _decimal_text(successful_amount),
                "unpaid_order_count": sum(
                    1 for order in orders if str(order.get("status") or "") == "0"
                ),
                "no_third_party_order_count": sum(
                    1 for order in orders if _missing_third_party_order(order)
                ),
                "successful_order_share": _percent(len(successful), successful_total),
                "successful_amount_share": _percent(successful_amount, successful_amount_total),
                "success_rate": _percent(len(successful), len(orders)),
            }
        )
    rows.sort(key=lambda item: (-item["successful_order_count"], item["pay_channel_name"]))
    denomination_distribution = [
        {
            "amount": _denomination_text(amount),
            "successful_order_count": len(orders),
            "successful_amount": _decimal_text(
                sum((_decimal(order.get("amount")) for order in orders), Decimal("0"))
            ),
        }
        for amount, orders in sorted(denomination_groups.items(), key=lambda item: item[0])
    ]
    offset = (request.page - 1) * request.page_size
    return ChargeChannelSummaryResult(
        items=rows[offset : offset + request.page_size],
        denomination_distribution=denomination_distribution,
        total=len(rows),
        source_id=source_id,
        source_display_name=source_display_name,
        business_timezone=timezone_name,
        effective_create_time_end=window_end.astimezone(ZoneInfo(timezone_name)).strftime(
            WALL_TIME_FORMAT
        ),
        fetched_at=query_at,
        local_updated_at=local_updated_at,
    )
