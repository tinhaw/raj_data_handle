"""Live, read-only aggregate monitor for pending withdrawal applications.

The feature intentionally avoids the withdrawal-order cache: it asks each
selected Raj admin market for only two aggregate values, projects the response
to counts immediately, and never retains raw order data or remote payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings, get_settings
from packages.domain.models import SourceConfig
from packages.domain.schemas.system_setting import (
    WithdrawPendingMonitorQueryRange,
    normalize_withdraw_pending_monitor_query_range,
    normalize_withdraw_pending_monitor_refresh_interval,
)
from packages.domain.schemas.withdraw_order import WithdrawPendingMonitorSourceResponse
from packages.domain.services.remote_account_credentials import (
    RemoteAccountCredentialsError,
    decrypt_remote_account_credentials,
    resolve_default_remote_account_credentials,
)
from packages.domain.services.remote_account_session_service import account_session
from packages.domain.services.remote_charge_service import RemoteChargeError
from packages.domain.services.remote_withdraw_service import (
    WITHDRAW_PENDING_AUDIT_STATUS,
    WITHDRAW_PENDING_REVIEW_STATUS,
    RajAdminWithdrawClient,
)
from packages.domain.services.system_setting_service import get_retention_settings

WALL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
INDIA_TIMEZONE_NAME = "Asia/Kolkata"
INDIA_TIMEZONE = ZoneInfo(INDIA_TIMEZONE_NAME)


class WithdrawPendingMonitorValidationError(ValueError):
    """The monitor request cannot be safely run against remote markets."""


@dataclass(frozen=True, slots=True)
class WithdrawPendingMonitorResult:
    query_range: WithdrawPendingMonitorQueryRange
    refresh_interval_seconds: int
    generated_at: datetime
    successful_source_count: int
    pending_audit_total: int
    pending_review_total: int
    sources: list[WithdrawPendingMonitorSourceResponse]


def _as_utc(value: datetime | None = None) -> datetime:
    candidate = value or datetime.now(UTC)
    return candidate.replace(tzinfo=UTC) if candidate.tzinfo is None else candidate.astimezone(UTC)


def _query_window(
    *,
    query_range: WithdrawPendingMonitorQueryRange,
    now: datetime,
) -> tuple[datetime, datetime]:
    """Resolve full India calendar days, including the remainder of today."""

    india_today_start = now.astimezone(INDIA_TIMEZONE).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    india_today_end = india_today_start + timedelta(days=1) - timedelta(seconds=1)
    if query_range == "india_today":
        return india_today_start, india_today_end
    if query_range == "india_yesterday_today":
        return india_today_start - timedelta(days=1), india_today_end
    raise WithdrawPendingMonitorValidationError("提现待处理监控时间范围无效。")


def _remote_timestamp(value: datetime) -> str:
    """Use the observed admin-request timestamp form: ISO UTC with milliseconds."""

    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def _selected_sources(
    session: AsyncSession,
    *,
    source_ids: list[str] | None,
) -> list[SourceConfig]:
    statement = select(SourceConfig).order_by(
        SourceConfig.display_order.asc(), SourceConfig.source_id.asc()
    )
    if source_ids is None:
        return list(
            await session.scalars(
                statement.where(
                    SourceConfig.enabled.is_(True),
                    SourceConfig.base_url.is_not(None),
                )
            )
        )

    sources = list(await session.scalars(statement.where(SourceConfig.source_id.in_(source_ids))))
    found_ids = {source.source_id for source in sources}
    missing_ids = [source_id for source_id in source_ids if source_id not in found_ids]
    if missing_ids:
        raise WithdrawPendingMonitorValidationError("所选盘口不存在。")
    if any(not source.enabled or not source.base_url for source in sources):
        raise WithdrawPendingMonitorValidationError("所选盘口尚未启用或未配置后台地址。")
    return sources


async def _query_source(
    session: AsyncSession,
    *,
    source: SourceConfig,
    query_range: WithdrawPendingMonitorQueryRange,
    timeout_seconds: int,
    now: datetime,
    settings: Settings,
) -> WithdrawPendingMonitorSourceResponse:
    local_start, local_end = _query_window(
        query_range=query_range,
        now=now,
    )
    response_kwargs = {
        "source_id": source.source_id,
        "source_display_name": source.display_name,
        "business_timezone": INDIA_TIMEZONE_NAME,
        "create_time_start": local_start.strftime(WALL_TIME_FORMAT),
        "create_time_end": local_end.strftime(WALL_TIME_FORMAT),
        "queried_at": now,
    }
    envelope = await resolve_default_remote_account_credentials(session, source=source)
    if envelope is None:
        return WithdrawPendingMonitorSourceResponse(
            **response_kwargs,
            status="unavailable",
            message="未配置可用于数据分析读取的默认远端账号。",
        )
    try:
        credentials = decrypt_remote_account_credentials(envelope, settings=settings)
    except RemoteAccountCredentialsError:
        return WithdrawPendingMonitorSourceResponse(
            **response_kwargs,
            status="unavailable",
            message="远端读取账号凭据不可用。",
        )

    try:
        async with RajAdminWithdrawClient(
            remote_session=account_session(
                session,
                envelope=envelope,
                base_url=source.base_url or "",
                settings=settings,
            ),
            base_url=source.base_url or "",
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            timeout_seconds=timeout_seconds,
        ) as client:
            pending_audit_count = await client.fetch_withdraw_status_summary(
                create_start=_remote_timestamp(local_start),
                create_end=_remote_timestamp(local_end),
                status=WITHDRAW_PENDING_AUDIT_STATUS,
            )
            pending_review_count = await client.fetch_withdraw_status_summary(
                create_start=_remote_timestamp(local_start),
                create_end=_remote_timestamp(local_end),
                status=WITHDRAW_PENDING_REVIEW_STATUS,
            )
    except RemoteChargeError:
        # The client has already converted transport/login/response detail to
        # a safe domain error.  Keep per-market failures isolated so remaining
        # markets are still visible in the same monitoring page.
        return WithdrawPendingMonitorSourceResponse(
            **response_kwargs,
            status="failed",
            message="远端提现汇总查询失败，请稍后刷新或检查盘口连接。",
        )
    return WithdrawPendingMonitorSourceResponse(
        **response_kwargs,
        status="succeeded",
        pending_audit_count=pending_audit_count,
        pending_review_count=pending_review_count,
    )


async def query_withdraw_pending_monitor(
    session: AsyncSession,
    *,
    source_ids: list[str] | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> WithdrawPendingMonitorResult:
    """Read pending status counts source-by-source without persisting an order cache."""

    current_settings = settings or get_settings()
    query_at = _as_utc(now)
    retention = await get_retention_settings(session, defaults=current_settings)
    query_range = normalize_withdraw_pending_monitor_query_range(
        retention.withdraw_order_query_range
    )
    refresh_interval_seconds = normalize_withdraw_pending_monitor_refresh_interval(
        retention.withdraw_order_refresh_interval_hours
    )
    sources = await _selected_sources(session, source_ids=source_ids)
    results: list[WithdrawPendingMonitorSourceResponse] = []
    for source in sources:
        results.append(
            await _query_source(
                session,
                source=source,
                query_range=query_range,
                timeout_seconds=retention.remote_order_sync_timeout_seconds or 180,
                now=query_at,
                settings=current_settings,
            )
        )
    successful = [row for row in results if row.status == "succeeded"]
    return WithdrawPendingMonitorResult(
        query_range=query_range,
        refresh_interval_seconds=refresh_interval_seconds,
        generated_at=query_at,
        successful_source_count=len(successful),
        pending_audit_total=sum(row.pending_audit_count for row in successful),
        pending_review_total=sum(row.pending_review_count for row in successful),
        sources=results,
    )
