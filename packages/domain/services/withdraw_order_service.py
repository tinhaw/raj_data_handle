from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.security import SecurityValidationError, decrypt_credentials
from packages.common.settings import Settings, get_settings
from packages.domain.schemas.withdraw_order import WithdrawOrderQueryRequest
from packages.domain.services.data_dictionary_service import withdraw_status_dictionary
from packages.domain.services.remote_withdraw_service import RajAdminWithdrawClient
from packages.domain.services.source_service import get_source

MAX_QUERY_WINDOW = timedelta(days=31)
REMOTE_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.000Z"
WALL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class WithdrawOrderValidationError(ValueError):
    pass


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
    status_dictionary: list[dict[str, object]]
    summary: dict[str, Any]


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _parse_window(
    start_value: str,
    end_value: str,
    *,
    timezone_name: str,
    now: datetime,
) -> tuple[datetime, datetime]:
    try:
        business_timezone = ZoneInfo(timezone_name)
        start = datetime.strptime(start_value, WALL_TIME_FORMAT).replace(tzinfo=business_timezone)
        end = datetime.strptime(end_value, WALL_TIME_FORMAT).replace(tzinfo=business_timezone)
    except ValueError as exc:
        raise WithdrawOrderValidationError("查询时间必须使用 YYYY-MM-DD HH:mm:ss 格式。") from exc
    if end < start:
        raise WithdrawOrderValidationError("查询结束时间不能早于开始时间。")
    if end - start > MAX_QUERY_WINDOW:
        raise WithdrawOrderValidationError("提现订单查询时间范围不能超过 31 天。")
    now_utc = now.astimezone(UTC)
    start_utc = start.astimezone(UTC)
    end_utc = min(end.astimezone(UTC), now_utc)
    if start_utc > now_utc:
        raise WithdrawOrderValidationError("查询开始时间不能晚于当前时间。")
    return start_utc, end_utc


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


async def query_withdraw_orders(
    session: AsyncSession,
    *,
    request: WithdrawOrderQueryRequest,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> WithdrawOrderQueryResult:
    source = await get_source(session, request.source_id)
    if not source.enabled:
        raise WithdrawOrderValidationError("所选盘口尚未启用。")
    if not source.base_url or not source.encrypted_credentials:
        raise WithdrawOrderValidationError("所选盘口缺少远端地址或凭据。")
    current_settings = settings or get_settings()
    query_started_at = now or datetime.now(UTC)
    start_utc, end_utc = _parse_window(
        request.create_time_start,
        request.create_time_end,
        timezone_name=source.business_timezone,
        now=query_started_at,
    )
    try:
        credentials = decrypt_credentials(
            source.encrypted_credentials,
            source_id=source.source_id,
            credential_version=source.credential_version,
            settings=current_settings,
        )
    except SecurityValidationError as exc:
        raise WithdrawOrderValidationError("已保存的盘口凭据无法解密。") from exc
    try:
        username = credentials["username"]
        password = credentials["password"]
        totp_secret = credentials["totp_secret"]
    except KeyError as exc:
        raise WithdrawOrderValidationError("已保存的盘口凭据不完整。") from exc

    async with RajAdminWithdrawClient(
        base_url=source.base_url,
        username=username,
        password=password,
        totp_secret=totp_secret,
    ) as client:
        fetched = await client.fetch_all_withdraw_orders(
            create_start=start_utc.strftime(REMOTE_TIME_FORMAT),
            create_end=end_utc.strftime(REMOTE_TIME_FORMAT),
            uid=request.uid or "",
            status=request.status or "",
        )

    filtered_orders = fetched.orders
    if request.audit_admin:
        expected_operator = request.audit_admin.casefold()
        filtered_orders = [
            order
            for order in filtered_orders
            if expected_operator in str(order.get("audit_admin") or "").casefold()
        ]
    summary = summarize_withdraw_orders(
        filtered_orders,
        window_start=start_utc,
        window_end=end_utc,
    )
    status_dictionary = await withdraw_status_dictionary(
        session,
        source_id=source.source_id,
    )
    offset = (request.page - 1) * request.page_size
    return WithdrawOrderQueryResult(
        items=filtered_orders[offset : offset + request.page_size],
        total=len(filtered_orders),
        remote_total=fetched.remote_total,
        fetched_pages=fetched.fetched_pages,
        complete=fetched.complete,
        source_id=source.source_id,
        source_display_name=source.display_name,
        business_timezone=source.business_timezone,
        currency=source.currency,
        effective_create_time_end=end_utc.astimezone(ZoneInfo(source.business_timezone)).strftime(
            WALL_TIME_FORMAT
        ),
        fetched_at=datetime.now(UTC),
        status_dictionary=status_dictionary,
        summary=summary,
    )
