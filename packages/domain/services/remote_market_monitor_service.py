"""Durable, read-only remote-market monitoring and Telegram outbox delivery.

This module deliberately keeps remote reads, state transitions, and Telegram
delivery separate.  A remote request never modifies a Raj/RajLuck resource;
the only external write is an optional Telegram notification released from the
database-backed outbox.
"""

from __future__ import annotations

import html
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from string import Formatter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings, get_settings
from packages.domain.models import (
    MonitorNotificationAttempt,
    MonitorNotificationDestination,
    MonitorNotificationOutbox,
    MonitorNotificationTemplateSet,
    RemoteMarketMonitorCheckRun,
    RemoteMarketMonitorIncident,
    RemoteMarketMonitorMetricPolicy,
    RemoteMarketMonitorSetting,
    RemoteMarketMonitorState,
    RemoteMarketMonitorTargetDestination,
    RemoteMarketMonitorTargetSetting,
    SecurityAuditLog,
    SourceConfig,
)
from packages.domain.schemas.remote_market_monitor import (
    MonitorNotificationDestinationCreateRequest,
    MonitorNotificationDestinationUpdateRequest,
    MonitorNotificationTemplateSetCreateRequest,
    MonitorNotificationTemplateSetUpdateRequest,
    RemoteMarketMonitorSettingsUpdateRequest,
    RemoteMarketMonitorTargetUpdateRequest,
)
from packages.domain.services.remote_account_credentials import (
    RemoteAccountCredentialsError,
    decrypt_remote_account_credentials,
    resolve_default_remote_account_credentials,
)
from packages.domain.services.remote_account_session_service import account_session
from packages.domain.services.remote_charge_service import (
    RemoteAuthenticationError,
    RemoteChargeError,
    RemoteResponseError,
)
from packages.domain.services.remote_withdraw_service import (
    WITHDRAW_PENDING_AUDIT_STATUS,
    WITHDRAW_PENDING_REVIEW_STATUS,
    RajAdminWithdrawClient,
)

METRICS = ("pending_audit", "pending_review")
INCIDENT_THRESHOLD = "PENDING_THRESHOLD"
INCIDENT_SOURCE = "SOURCE_UNAVAILABLE"
STATUS_PENDING = "pending"
STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
DEFAULT_TEMPLATE_SET_ID = "default-zh"
TEMPLATE_KEYS = frozenset(
    {
        "threshold_opened",
        "threshold_reminder",
        "threshold_recovered",
        "source_unavailable",
        "source_reminder",
        "source_recovered",
        "monitor_stale",
        "monitor_recovered",
        "test_message",
    }
)
TEMPLATE_VARIABLES = frozenset(
    {
        "source_display_name",
        "source_id",
        "metric_name",
        "metric_label",
        "metric_count",
        "pending_audit_count",
        "pending_review_count",
        "comparison_label",
        "threshold",
        "recovery_threshold",
        "checked_at_local",
        "query_range_local",
        "incident_id",
        "incident_started_at_local",
        "incident_duration",
        "peak_count",
        "error_code",
        "safe_error_message",
    }
)
DEFAULT_TEMPLATES: dict[str, str] = {
    "threshold_opened": (
        "<b>[远端盘口积压] {source_display_name}</b>\n"
        "指标：{metric_label}\n当前数量：{metric_count}\n"
        "告警条件：{comparison_label} {threshold}\n"
        "检查时间：{checked_at_local}\n查询范围：{query_range_local}\n"
        "事件编号：{incident_id}"
    ),
    "threshold_reminder": (
        "<b>[远端盘口积压持续] {source_display_name}</b>\n"
        "指标：{metric_label}\n当前数量：{metric_count}\n峰值：{peak_count}\n"
        "持续时间：{incident_duration}\n事件编号：{incident_id}"
    ),
    "threshold_recovered": (
        "<b>[远端盘口积压恢复] {source_display_name}</b>\n"
        "指标：{metric_label}\n恢复时数量：{metric_count}\n峰值：{peak_count}\n"
        "持续时间：{incident_duration}\n事件编号：{incident_id}"
    ),
    "source_unavailable": (
        "<b>[远端盘口不可用] {source_display_name}</b>\n"
        "错误：{error_code}\n说明：{safe_error_message}\n"
        "检查时间：{checked_at_local}\n事件编号：{incident_id}"
    ),
    "source_reminder": (
        "<b>[远端盘口仍不可用] {source_display_name}</b>\n"
        "错误：{error_code}\n说明：{safe_error_message}\n"
        "持续时间：{incident_duration}\n事件编号：{incident_id}"
    ),
    "source_recovered": (
        "<b>[远端盘口恢复] {source_display_name}</b>\n"
        "恢复检查时间：{checked_at_local}\n事件编号：{incident_id}"
    ),
    "monitor_stale": "<b>[远端盘口监控过期] {source_display_name}</b>\n事件编号：{incident_id}",
    "monitor_recovered": "<b>[远端盘口监控恢复] {source_display_name}</b>\n事件编号：{incident_id}",
    "test_message": "<b>[远端盘口监控测试]</b>\n目的地：{source_display_name}",
}


class RemoteMarketMonitorError(ValueError):
    pass


class RemoteMarketMonitorSchemaPendingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MonitorSample:
    status: str
    started_at: datetime
    finished_at: datetime
    query_range_start: datetime | None
    query_range_end: datetime | None
    pending_audit_count: int | None = None
    pending_review_count: int | None = None
    error_code: str | None = None
    safe_error_message: str | None = None

    @property
    def latency_ms(self) -> int:
        return max(0, int((self.finished_at - self.started_at).total_seconds() * 1000))


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _mark_initial_notification(
    incident: RemoteMarketMonitorIncident, notified_at: datetime
) -> None:
    incident.metadata_json = {
        **(incident.metadata_json or {}),
        "initial_notification_at": _as_utc(notified_at).isoformat(),
    }


def _reminder_bucket(
    incident: RemoteMarketMonitorIncident,
    *,
    observed_at: datetime,
    interval_seconds: int,
) -> int:
    anchor = incident.opened_at
    raw_anchor = (incident.metadata_json or {}).get("initial_notification_at")
    if isinstance(raw_anchor, str):
        try:
            anchor = datetime.fromisoformat(raw_anchor)
        except ValueError:
            pass
    return int(
        (_as_utc(observed_at) - _as_utc(anchor)).total_seconds() // interval_seconds
    )


def _remote_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _default_template_set() -> MonitorNotificationTemplateSet:
    return MonitorNotificationTemplateSet(
        id=DEFAULT_TEMPLATE_SET_ID,
        display_name="中文默认模板",
        templates_json=dict(DEFAULT_TEMPLATES),
        is_builtin=True,
    )


async def get_monitor_settings(session: AsyncSession) -> RemoteMarketMonitorSetting:
    row = await session.get(RemoteMarketMonitorSetting, 1)
    if row is None:
        row = RemoteMarketMonitorSetting(id=1)
        session.add(row)
        await session.flush()
    template = await session.get(MonitorNotificationTemplateSet, DEFAULT_TEMPLATE_SET_ID)
    if template is None:
        session.add(_default_template_set())
        await session.flush()
    return row


async def commit_monitor_defaults(session: AsyncSession) -> RemoteMarketMonitorSetting:
    """Initialize singleton/template rows without coupling them to legacy settings."""

    row = await get_monitor_settings(session)
    await session.commit()
    return row


def validate_template_map(templates: dict[str, str]) -> dict[str, str]:
    missing = TEMPLATE_KEYS.difference(templates)
    extra = set(templates).difference(TEMPLATE_KEYS)
    if missing or extra:
        raise RemoteMarketMonitorError("模板必须包含且仅包含规定的事件模板键。")
    normalized: dict[str, str] = {}
    for key, raw in templates.items():
        value = raw.strip()
        if not value or len(value) > 4000:
            raise RemoteMarketMonitorError("通知模板不能为空且不能超过 4000 个字符。")
        try:
            variables = {
                field_name
                for _, field_name, _, _ in Formatter().parse(value)
                if field_name is not None
            }
        except ValueError as exc:
            raise RemoteMarketMonitorError("通知模板格式无效。") from exc
        if not variables.issubset(TEMPLATE_VARIABLES):
            raise RemoteMarketMonitorError("通知模板包含不支持的变量。")
        normalized[key] = value
    return normalized


def _policy_defaults(
    settings: RemoteMarketMonitorSetting, metric: str
) -> RemoteMarketMonitorMetricPolicy:
    return RemoteMarketMonitorMetricPolicy(
        metric=metric,
        enabled=True,
        comparison="gt",
        threshold=100,
        recovery_threshold=90,
        breach_consecutive_checks=settings.default_breach_consecutive_checks,
        recovery_consecutive_checks=settings.default_recovery_consecutive_checks,
    )


async def ensure_target_settings(
    session: AsyncSession,
    *,
    source: SourceConfig,
    commit: bool = False,
) -> tuple[
    RemoteMarketMonitorTargetSetting,
    list[RemoteMarketMonitorMetricPolicy],
    RemoteMarketMonitorState,
]:
    settings = await get_monitor_settings(session)
    target = await session.get(RemoteMarketMonitorTargetSetting, source.source_id)
    if target is None:
        target = RemoteMarketMonitorTargetSetting(
            source_id=source.source_id,
            check_interval_seconds=settings.default_check_interval_seconds,
            next_check_at=_utc_now(),
        )
        session.add(target)
    policies = list(
        await session.scalars(
            select(RemoteMarketMonitorMetricPolicy).where(
                RemoteMarketMonitorMetricPolicy.source_id == source.source_id
            )
        )
    )
    by_metric = {policy.metric: policy for policy in policies}
    for metric in METRICS:
        if metric not in by_metric:
            policy = _policy_defaults(settings, metric)
            policy.source_id = source.source_id
            session.add(policy)
            by_metric[metric] = policy
    state = await session.get(RemoteMarketMonitorState, source.source_id)
    if state is None:
        state = RemoteMarketMonitorState(source_id=source.source_id)
        session.add(state)
    await session.flush()
    result = [by_metric[metric] for metric in METRICS]
    if commit:
        await session.commit()
    return target, result, state


async def ensure_monitor_targets(session: AsyncSession) -> None:
    sources = list(
        await session.scalars(select(SourceConfig).where(SourceConfig.base_url.is_not(None)))
    )
    for source in sources:
        await ensure_target_settings(session, source=source)
    await session.commit()


async def update_monitor_settings(
    session: AsyncSession,
    *,
    payload: RemoteMarketMonitorSettingsUpdateRequest,
    actor_user_id: int,
) -> RemoteMarketMonitorSetting:
    row = await get_monitor_settings(session)
    previous = {
        "monitorEnabled": row.monitor_enabled,
        "deliveryMode": row.delivery_mode,
        "defaultCheckIntervalSeconds": row.default_check_interval_seconds,
    }
    for name, value in payload.model_dump().items():
        setattr(row, name, value)
    row.config_version += 1
    row.updated_by = actor_user_id
    row.updated_at = _utc_now()
    session.add(
        SecurityAuditLog(
            actor_user_id=actor_user_id,
            action="remote_market_monitor.settings.update",
            target_type="remote_market_monitor_settings",
            target_id="1",
            metadata_json={"previous": previous, "configVersion": row.config_version},
        )
    )
    await session.commit()
    return row


def _destination_response_values(destination: MonitorNotificationDestination) -> dict[str, object]:
    return {
        "id": destination.id,
        "display_name": destination.display_name,
        "channel": destination.channel,
        "enabled": destination.enabled,
        "template_set_id": destination.template_set_id,
        "bot_token_configured": bool(destination.bot_token_secret_ref),
        "chat_id_configured": bool(destination.chat_id_secret_ref),
        "updated_at": destination.updated_at,
    }


async def list_notification_destinations(
    session: AsyncSession,
) -> list[MonitorNotificationDestination]:
    await get_monitor_settings(session)
    return list(
        await session.scalars(
            select(MonitorNotificationDestination).order_by(
                MonitorNotificationDestination.display_name
            )
        )
    )


async def create_notification_destination(
    session: AsyncSession,
    *,
    payload: MonitorNotificationDestinationCreateRequest,
    actor_user_id: int,
) -> MonitorNotificationDestination:
    await get_monitor_settings(session)
    if await session.get(MonitorNotificationTemplateSet, payload.template_set_id) is None:
        raise RemoteMarketMonitorError("通知模板集不存在。")
    destination = MonitorNotificationDestination(
        display_name=payload.display_name.strip(),
        enabled=payload.enabled,
        bot_token_secret_ref=payload.bot_token_secret_ref,
        chat_id_secret_ref=payload.chat_id_secret_ref,
        template_set_id=payload.template_set_id,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(destination)
    session.add(
        SecurityAuditLog(
            actor_user_id=actor_user_id,
            action="remote_market_monitor.destination.create",
            target_type="monitor_notification_destination",
            target_id=destination.id,
            metadata_json={"displayName": destination.display_name},
        )
    )
    await session.commit()
    return destination


async def update_notification_destination(
    session: AsyncSession,
    *,
    destination_id: str,
    payload: MonitorNotificationDestinationUpdateRequest,
    actor_user_id: int,
) -> MonitorNotificationDestination:
    destination = await session.get(MonitorNotificationDestination, destination_id)
    if destination is None:
        raise RemoteMarketMonitorError("通知目的地不存在。")
    values = payload.model_dump(exclude_none=True)
    if (
        "template_set_id" in values
        and await session.get(MonitorNotificationTemplateSet, str(values["template_set_id"]))
        is None
    ):
        raise RemoteMarketMonitorError("通知模板集不存在。")
    for name, value in values.items():
        setattr(destination, name, value.strip() if isinstance(value, str) else value)
    destination.updated_by = actor_user_id
    destination.updated_at = _utc_now()
    session.add(
        SecurityAuditLog(
            actor_user_id=actor_user_id,
            action="remote_market_monitor.destination.update",
            target_type="monitor_notification_destination",
            target_id=destination.id,
            metadata_json={"changed": sorted(values)},
        )
    )
    await session.commit()
    return destination


async def list_template_sets(session: AsyncSession) -> list[MonitorNotificationTemplateSet]:
    await get_monitor_settings(session)
    return list(
        await session.scalars(
            select(MonitorNotificationTemplateSet).order_by(MonitorNotificationTemplateSet.id)
        )
    )


async def create_template_set(
    session: AsyncSession,
    *,
    payload: MonitorNotificationTemplateSetCreateRequest,
    actor_user_id: int,
) -> MonitorNotificationTemplateSet:
    await get_monitor_settings(session)
    if await session.get(MonitorNotificationTemplateSet, payload.id) is not None:
        raise RemoteMarketMonitorError("模板集 ID 已存在。")
    row = MonitorNotificationTemplateSet(
        id=payload.id,
        display_name=payload.display_name.strip(),
        templates_json=validate_template_map(payload.templates),
        updated_by=actor_user_id,
    )
    session.add(row)
    session.add(
        SecurityAuditLog(
            actor_user_id=actor_user_id,
            action="remote_market_monitor.template.create",
            target_type="monitor_notification_template_set",
            target_id=row.id,
            metadata_json={},
        )
    )
    await session.commit()
    return row


async def update_template_set(
    session: AsyncSession,
    *,
    template_set_id: str,
    payload: MonitorNotificationTemplateSetUpdateRequest,
    actor_user_id: int,
) -> MonitorNotificationTemplateSet:
    row = await session.get(MonitorNotificationTemplateSet, template_set_id)
    if row is None:
        raise RemoteMarketMonitorError("模板集不存在。")
    if row.is_builtin:
        raise RemoteMarketMonitorError("内置模板不可修改，请复制后编辑。")
    if payload.display_name is not None:
        row.display_name = payload.display_name.strip()
    if payload.templates is not None:
        row.templates_json = validate_template_map(payload.templates)
    row.config_version += 1
    row.updated_by = actor_user_id
    row.updated_at = _utc_now()
    session.add(
        SecurityAuditLog(
            actor_user_id=actor_user_id,
            action="remote_market_monitor.template.update",
            target_type="monitor_notification_template_set",
            target_id=row.id,
            metadata_json={},
        )
    )
    await session.commit()
    return row


async def _get_source(session: AsyncSession, source_id: str) -> SourceConfig:
    source = await session.get(SourceConfig, source_id)
    if source is None or not source.base_url:
        raise RemoteMarketMonitorError("盘口不存在或尚未配置后台地址。")
    return source


async def _destination_ids_for_source(session: AsyncSession, source_id: str) -> list[str]:
    return list(
        await session.scalars(
            select(RemoteMarketMonitorTargetDestination.destination_id).where(
                RemoteMarketMonitorTargetDestination.source_id == source_id
            )
        )
    )


async def update_target_settings(
    session: AsyncSession,
    *,
    source_id: str,
    payload: RemoteMarketMonitorTargetUpdateRequest,
    actor_user_id: int,
) -> RemoteMarketMonitorTargetSetting:
    source = await _get_source(session, source_id)
    if payload.enabled and not source.enabled:
        raise RemoteMarketMonitorError("盘口主配置尚未启用，不能启用后台监控。")
    target, policies, _ = await ensure_target_settings(session, source=source)
    existing_destinations = set(
        await session.scalars(
            select(MonitorNotificationDestination.id).where(
                MonitorNotificationDestination.id.in_(payload.destination_ids)
            )
        )
    )
    if existing_destinations != set(payload.destination_ids):
        raise RemoteMarketMonitorError("选择的 Telegram 通知目的地不存在。")
    target.enabled = payload.enabled
    target.check_interval_seconds = payload.check_interval_seconds
    target.query_window_mode = payload.query_window_mode
    target.previous_days = payload.previous_days
    target.source_failure_consecutive_checks = payload.source_failure_consecutive_checks
    target.source_reminder_interval_minutes = payload.source_reminder_interval_minutes
    target.next_check_at = _utc_now() if target.enabled else None
    target.config_version += 1
    target.updated_by = actor_user_id
    target.updated_at = _utc_now()
    current_policies = {policy.metric: policy for policy in policies}
    for policy_input in payload.policies:
        policy = current_policies[policy_input.metric]
        for name, value in policy_input.model_dump().items():
            setattr(policy, name, value)
        policy.updated_by = actor_user_id
        policy.updated_at = _utc_now()
    await session.execute(
        delete(RemoteMarketMonitorTargetDestination).where(
            RemoteMarketMonitorTargetDestination.source_id == source_id
        )
    )
    await session.flush()
    for destination_id in payload.destination_ids:
        session.add(
            RemoteMarketMonitorTargetDestination(
                source_id=source_id,
                destination_id=destination_id,
            )
        )
    session.add(
        SecurityAuditLog(
            actor_user_id=actor_user_id,
            action="remote_market_monitor.target.update",
            target_type="source_config",
            target_id=source_id,
            metadata_json={
                "enabled": target.enabled,
                "checkIntervalSeconds": target.check_interval_seconds,
                "destinationCount": len(payload.destination_ids),
            },
        )
    )
    await session.commit()
    return target


async def get_target_snapshot(
    session: AsyncSession,
    *,
    source: SourceConfig,
    persist_defaults: bool = False,
) -> dict[str, object]:
    target, policies, state = await ensure_target_settings(session, source=source)
    if persist_defaults:
        await session.commit()
    return {
        "source_id": source.source_id,
        "source_display_name": source.display_name,
        "business_timezone": source.business_timezone,
        "source_enabled": source.enabled,
        "enabled": target.enabled,
        "check_interval_seconds": target.check_interval_seconds,
        "query_window_mode": target.query_window_mode,
        "previous_days": target.previous_days,
        "source_failure_consecutive_checks": target.source_failure_consecutive_checks,
        "source_reminder_interval_minutes": target.source_reminder_interval_minutes,
        "destination_ids": await _destination_ids_for_source(session, source.source_id),
        "policies": [
            {
                "metric": policy.metric,
                "enabled": policy.enabled,
                "comparison": policy.comparison,
                "threshold": policy.threshold,
                "recovery_threshold": policy.recovery_threshold,
                "breach_consecutive_checks": policy.breach_consecutive_checks,
                "recovery_consecutive_checks": policy.recovery_consecutive_checks,
                "reminder_interval_minutes": policy.reminder_interval_minutes,
            }
            for policy in policies
        ],
        "next_check_at": target.next_check_at,
        "last_check_at": state.last_check_at,
        "last_success_at": state.last_success_at,
        "last_pending_audit_count": state.last_pending_audit_count,
        "last_pending_review_count": state.last_pending_review_count,
        "source_health": state.source_health,
        "consecutive_source_failure_count": state.consecutive_source_failure_count,
        "last_error_code": state.last_error_code,
        "last_safe_error_message": state.last_safe_error_message,
    }


async def get_monitor_overview(session: AsyncSession) -> dict[str, object]:
    settings = await get_monitor_settings(session)
    sources = list(
        await session.scalars(
            select(SourceConfig)
            .where(SourceConfig.base_url.is_not(None))
            .order_by(SourceConfig.display_order, SourceConfig.source_id)
        )
    )
    targets = [await get_target_snapshot(session, source=source) for source in sources]
    # The displayed defaults are persisted so a freshly migrated database has
    # a stable singleton/template set before an administrator saves settings.
    await session.commit()
    open_incident_count = int(
        await session.scalar(
            select(func.count())
            .select_from(RemoteMarketMonitorIncident)
            .where(RemoteMarketMonitorIncident.status == STATUS_OPEN)
        )
        or 0
    )
    pending_outbox_count = int(
        await session.scalar(
            select(func.count())
            .select_from(MonitorNotificationOutbox)
            .where(MonitorNotificationOutbox.status.in_(("pending", "processing")))
        )
        or 0
    )
    return {
        "generated_at": _utc_now(),
        "settings": settings,
        "targets": targets,
        "open_incident_count": open_incident_count,
        "pending_outbox_count": pending_outbox_count,
    }


def _query_window(
    *,
    mode: str,
    previous_days: int,
    timezone_name: str,
    now: datetime,
) -> tuple[datetime, datetime]:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RemoteMarketMonitorError("盘口业务时区无效。") from exc
    start_today = now.astimezone(timezone).replace(hour=0, minute=0, second=0, microsecond=0)
    if mode == "business_today":
        start = start_today
    elif mode == "business_today_and_previous_days":
        start = start_today - timedelta(days=previous_days)
    else:
        raise RemoteMarketMonitorError("监控查询时间范围无效。")
    end = start_today + timedelta(days=1) - timedelta(seconds=1)
    return start.astimezone(UTC), end.astimezone(UTC)


async def fetch_remote_monitor_sample(
    session: AsyncSession,
    *,
    source: SourceConfig,
    target: RemoteMarketMonitorTargetSetting,
    timeout_seconds: int,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> MonitorSample:
    """Fetch only two remote aggregate counts; never retain an order payload."""

    started_at = _as_utc(now or _utc_now())
    try:
        range_start, range_end = _query_window(
            mode=target.query_window_mode,
            previous_days=target.previous_days,
            timezone_name=source.business_timezone,
            now=started_at,
        )
    except RemoteMarketMonitorError as exc:
        return MonitorSample(
            status="source_unavailable",
            started_at=started_at,
            finished_at=_utc_now(),
            query_range_start=None,
            query_range_end=None,
            error_code="INVALID_CONFIGURATION",
            safe_error_message=str(exc),
        )
    envelope = await resolve_default_remote_account_credentials(session, source=source)
    if envelope is None:
        return MonitorSample(
            status="source_unavailable",
            started_at=started_at,
            finished_at=_utc_now(),
            query_range_start=range_start,
            query_range_end=range_end,
            error_code="AUTH_FAILED",
            safe_error_message="未配置可用于数据分析读取的默认远端账号。",
        )
    try:
        credentials = decrypt_remote_account_credentials(
            envelope, settings=settings or get_settings()
        )
    except RemoteAccountCredentialsError:
        return MonitorSample(
            status="source_unavailable",
            started_at=started_at,
            finished_at=_utc_now(),
            query_range_start=range_start,
            query_range_end=range_end,
            error_code="AUTH_FAILED",
            safe_error_message="远端读取账号凭据不可用。",
        )
    try:
        async with RajAdminWithdrawClient(
            remote_session=account_session(
                session,
                envelope=envelope,
                base_url=source.base_url or "",
                settings=settings or get_settings(),
            ),
            base_url=source.base_url or "",
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            timeout_seconds=timeout_seconds,
        ) as client:
            pending_audit_count = await client.fetch_withdraw_status_summary(
                create_start=_remote_timestamp(range_start),
                create_end=_remote_timestamp(range_end),
                status=WITHDRAW_PENDING_AUDIT_STATUS,
            )
            pending_review_count = await client.fetch_withdraw_status_summary(
                create_start=_remote_timestamp(range_start),
                create_end=_remote_timestamp(range_end),
                status=WITHDRAW_PENDING_REVIEW_STATUS,
            )
    except RemoteAuthenticationError:
        error_code, safe_message = "AUTH_FAILED", "远端读取账号鉴权失败。"
    except RemoteResponseError:
        error_code, safe_message = "INVALID_RESPONSE_CONTRACT", "远端提现汇总响应不符合约定。"
    except RemoteChargeError:
        error_code, safe_message = "REMOTE_UNAVAILABLE", "远端提现汇总查询失败。"
    except Exception:
        # Do not expose a remote exception string; it can include request or
        # response material that is outside this monitor's data boundary.
        error_code, safe_message = "INTERNAL_ERROR", "远端监控查询发生内部错误。"
    else:
        return MonitorSample(
            status="ok",
            started_at=started_at,
            finished_at=_utc_now(),
            query_range_start=range_start,
            query_range_end=range_end,
            pending_audit_count=pending_audit_count,
            pending_review_count=pending_review_count,
        )
    return MonitorSample(
        status="source_unavailable",
        started_at=started_at,
        finished_at=_utc_now(),
        query_range_start=range_start,
        query_range_end=range_end,
        error_code=error_code,
        safe_error_message=safe_message,
    )


def _metric_label(metric: str) -> str:
    return "待审核" if metric == "pending_audit" else "待审查"


def _comparison_label(comparison: str) -> str:
    return "大于" if comparison == "gt" else "大于等于"


def _is_breach(*, value: int, comparison: str, threshold: int) -> bool:
    return value > threshold if comparison == "gt" else value >= threshold


def _format_duration(started_at: datetime, now: datetime) -> str:
    seconds = max(0, int((_as_utc(now) - _as_utc(started_at)).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours} 小时 {minutes} 分钟"
    return f"{minutes} 分钟"


def _format_context_time(value: datetime | None, timezone_name: str) -> str:
    if value is None:
        return "—"
    try:
        return _as_utc(value).astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M:%S")
    except ZoneInfoNotFoundError:
        return _as_utc(value).strftime("%Y-%m-%d %H:%M:%S UTC")


async def _find_active_incident(
    session: AsyncSession,
    *,
    source_id: str,
    metric: str,
    incident_type: str,
) -> RemoteMarketMonitorIncident | None:
    return await session.scalar(
        select(RemoteMarketMonitorIncident)
        .where(
            RemoteMarketMonitorIncident.source_id == source_id,
            RemoteMarketMonitorIncident.metric == metric,
            RemoteMarketMonitorIncident.incident_type == incident_type,
            RemoteMarketMonitorIncident.status.in_((STATUS_PENDING, STATUS_OPEN)),
        )
        .order_by(RemoteMarketMonitorIncident.opened_at.desc())
        .limit(1)
    )


async def _render_destination_message(
    session: AsyncSession,
    *,
    destination: MonitorNotificationDestination,
    template_key: str,
    context: dict[str, object],
) -> str:
    template_set = await session.get(MonitorNotificationTemplateSet, destination.template_set_id)
    templates = template_set.templates_json if template_set is not None else DEFAULT_TEMPLATES
    template = templates.get(template_key, DEFAULT_TEMPLATES[template_key])
    escaped_context = {
        key: html.escape(str(value if value is not None else "—")) for key, value in context.items()
    }
    try:
        return template.format(**escaped_context)
    except (KeyError, ValueError) as exc:
        raise RemoteMarketMonitorError("通知模板无法渲染。") from exc


async def _enqueue_event_for_destinations(
    session: AsyncSession,
    *,
    settings: RemoteMarketMonitorSetting,
    source: SourceConfig,
    incident: RemoteMarketMonitorIncident,
    event_type: str,
    template_key: str,
    context: dict[str, object],
    reminder_bucket: int = 0,
) -> None:
    destinations = list(
        await session.scalars(
            select(MonitorNotificationDestination)
            .join(
                RemoteMarketMonitorTargetDestination,
                RemoteMarketMonitorTargetDestination.destination_id
                == MonitorNotificationDestination.id,
            )
            .where(
                RemoteMarketMonitorTargetDestination.source_id == source.source_id,
                MonitorNotificationDestination.enabled.is_(True),
            )
        )
    )
    for destination in destinations:
        idempotency_key = (
            f"{source.source_id}:{incident.metric}:{incident.id}:{event_type}:"
            f"{destination.id}:{reminder_bucket}"
        )
        exists = await session.scalar(
            select(MonitorNotificationOutbox.id).where(
                MonitorNotificationOutbox.idempotency_key == idempotency_key
            )
        )
        if exists is not None:
            continue
        try:
            text = await _render_destination_message(
                session,
                destination=destination,
                template_key=template_key,
                context=context,
            )
        except RemoteMarketMonitorError:
            # A bad custom template must not block source state persistence or
            # a second destination.  Surface it in the outbox as a durable,
            # non-deliverable record for administrator review.
            status, last_error = "failed", "通知模板无法渲染。"
            text = ""
        else:
            status = "pending" if settings.delivery_mode == "telegram" else "recorded"
            last_error = None
        session.add(
            MonitorNotificationOutbox(
                incident_id=incident.id,
                destination_id=destination.id,
                event_type=event_type,
                idempotency_key=idempotency_key,
                payload_json={"text": text},
                status=status,
                available_at=_utc_now(),
                max_attempts=settings.notification_max_attempts,
                last_error=last_error,
            )
        )


def _event_context(
    *,
    source: SourceConfig,
    incident: RemoteMarketMonitorIncident,
    checked_at: datetime,
    range_start: datetime | None,
    range_end: datetime | None,
    pending_audit_count: int | None,
    pending_review_count: int | None,
    policy: RemoteMarketMonitorMetricPolicy | None = None,
    error_code: str | None = None,
    safe_error_message: str | None = None,
) -> dict[str, object]:
    current_count = (
        pending_audit_count
        if incident.metric == "pending_audit"
        else pending_review_count
        if incident.metric == "pending_review"
        else None
    )
    range_text = (
        f"{_format_context_time(range_start, source.business_timezone)} — "
        f"{_format_context_time(range_end, source.business_timezone)}"
        if range_start is not None and range_end is not None
        else "—"
    )
    return {
        "source_display_name": source.display_name,
        "source_id": source.source_id,
        "metric_name": incident.metric,
        "metric_label": _metric_label(incident.metric) if incident.metric in METRICS else "数据源",
        "metric_count": current_count,
        "pending_audit_count": pending_audit_count,
        "pending_review_count": pending_review_count,
        "comparison_label": _comparison_label(policy.comparison) if policy else "—",
        "threshold": policy.threshold if policy else "—",
        "recovery_threshold": policy.recovery_threshold if policy else "—",
        "checked_at_local": _format_context_time(checked_at, source.business_timezone),
        "query_range_local": range_text,
        "incident_id": incident.id,
        "incident_started_at_local": _format_context_time(
            incident.opened_at, source.business_timezone
        ),
        "incident_duration": _format_duration(incident.opened_at, checked_at),
        "peak_count": incident.peak_count,
        "error_code": error_code or incident.last_error_code or "—",
        "safe_error_message": safe_error_message or "—",
    }


async def _advance_metric_incident(
    session: AsyncSession,
    *,
    settings: RemoteMarketMonitorSetting,
    source: SourceConfig,
    policy: RemoteMarketMonitorMetricPolicy,
    count: int,
    sample: MonitorSample,
) -> None:
    if not policy.enabled:
        return
    now = sample.finished_at
    incident = await _find_active_incident(
        session,
        source_id=source.source_id,
        metric=policy.metric,
        incident_type=INCIDENT_THRESHOLD,
    )
    breached = _is_breach(value=count, comparison=policy.comparison, threshold=policy.threshold)
    if breached:
        if incident is None:
            incident = RemoteMarketMonitorIncident(
                source_id=source.source_id,
                metric=policy.metric,
                incident_type=INCIDENT_THRESHOLD,
                status=STATUS_PENDING,
                opened_at=now,
                last_observed_at=now,
                opening_count=count,
                latest_count=count,
                peak_count=count,
                consecutive_hit_count=1,
            )
            session.add(incident)
            return
        incident.last_observed_at = now
        incident.latest_count = count
        incident.peak_count = max(incident.peak_count or count, count)
        incident.consecutive_hit_count += 1
        incident.consecutive_recovery_count = 0
        if (
            incident.status == STATUS_PENDING
            and incident.consecutive_hit_count >= policy.breach_consecutive_checks
        ):
            incident.status = STATUS_OPEN
            _mark_initial_notification(incident, now)
            context = _event_context(
                source=source,
                incident=incident,
                policy=policy,
                checked_at=now,
                range_start=sample.query_range_start,
                range_end=sample.query_range_end,
                pending_audit_count=sample.pending_audit_count,
                pending_review_count=sample.pending_review_count,
            )
            await _enqueue_event_for_destinations(
                session,
                settings=settings,
                source=source,
                incident=incident,
                event_type="PENDING_THRESHOLD_BREACHED",
                template_key="threshold_opened",
                context=context,
            )
        elif incident.status == STATUS_OPEN:
            interval_seconds = (
                policy.reminder_interval_minutes or settings.default_reminder_interval_minutes
            ) * 60
            bucket = _reminder_bucket(
                incident,
                observed_at=now,
                interval_seconds=interval_seconds,
            )
            if bucket > 0:
                context = _event_context(
                    source=source,
                    incident=incident,
                    policy=policy,
                    checked_at=now,
                    range_start=sample.query_range_start,
                    range_end=sample.query_range_end,
                    pending_audit_count=sample.pending_audit_count,
                    pending_review_count=sample.pending_review_count,
                )
                await _enqueue_event_for_destinations(
                    session,
                    settings=settings,
                    source=source,
                    incident=incident,
                    event_type="PENDING_THRESHOLD_REMINDER",
                    template_key="threshold_reminder",
                    context=context,
                    reminder_bucket=bucket,
                )
        return

    if incident is None:
        return
    incident.last_observed_at = now
    incident.latest_count = count
    if incident.status == STATUS_PENDING:
        incident.status = STATUS_CLOSED
        incident.closed_at = now
        return
    incident.consecutive_hit_count = 0
    if count <= policy.recovery_threshold:
        incident.consecutive_recovery_count += 1
    else:
        incident.consecutive_recovery_count = 0
    if incident.consecutive_recovery_count >= policy.recovery_consecutive_checks:
        incident.status = STATUS_CLOSED
        incident.closed_at = now
        context = _event_context(
            source=source,
            incident=incident,
            policy=policy,
            checked_at=now,
            range_start=sample.query_range_start,
            range_end=sample.query_range_end,
            pending_audit_count=sample.pending_audit_count,
            pending_review_count=sample.pending_review_count,
        )
        await _enqueue_event_for_destinations(
            session,
            settings=settings,
            source=source,
            incident=incident,
            event_type="PENDING_THRESHOLD_RECOVERED",
            template_key="threshold_recovered",
            context=context,
        )
    else:
        interval_seconds = (
            policy.reminder_interval_minutes or settings.default_reminder_interval_minutes
        ) * 60
        bucket = _reminder_bucket(
            incident,
            observed_at=now,
            interval_seconds=interval_seconds,
        )
        if bucket > 0:
            context = _event_context(
                source=source,
                incident=incident,
                policy=policy,
                checked_at=now,
                range_start=sample.query_range_start,
                range_end=sample.query_range_end,
                pending_audit_count=sample.pending_audit_count,
                pending_review_count=sample.pending_review_count,
            )
            await _enqueue_event_for_destinations(
                session,
                settings=settings,
                source=source,
                incident=incident,
                event_type="PENDING_THRESHOLD_REMINDER",
                template_key="threshold_reminder",
                context=context,
                reminder_bucket=bucket,
            )


async def _advance_source_health(
    session: AsyncSession,
    *,
    settings: RemoteMarketMonitorSetting,
    source: SourceConfig,
    target: RemoteMarketMonitorTargetSetting,
    state: RemoteMarketMonitorState,
    sample: MonitorSample,
) -> None:
    now = sample.finished_at
    incident = await _find_active_incident(
        session,
        source_id=source.source_id,
        metric="source",
        incident_type=INCIDENT_SOURCE,
    )
    if sample.status == "ok":
        state.source_health = "healthy"
        state.consecutive_source_failure_count = 0
        state.last_error_code = None
        state.last_safe_error_message = None
        if incident is not None:
            incident.last_observed_at = now
            was_open = incident.status == STATUS_OPEN
            incident.status = STATUS_CLOSED
            incident.closed_at = now
            if was_open:
                context = _event_context(
                    source=source,
                    incident=incident,
                    checked_at=now,
                    range_start=sample.query_range_start,
                    range_end=sample.query_range_end,
                    pending_audit_count=sample.pending_audit_count,
                    pending_review_count=sample.pending_review_count,
                )
                await _enqueue_event_for_destinations(
                    session,
                    settings=settings,
                    source=source,
                    incident=incident,
                    event_type="SOURCE_RECOVERED",
                    template_key="source_recovered",
                    context=context,
                )
        return

    state.consecutive_source_failure_count += 1
    state.last_error_code = sample.error_code
    state.last_safe_error_message = sample.safe_error_message
    threshold = (
        1
        if sample.error_code == "AUTH_FAILED"
        else target.source_failure_consecutive_checks or settings.source_failure_consecutive_checks
    )
    state.source_health = (
        "unavailable" if state.consecutive_source_failure_count >= threshold else "failing"
    )
    if incident is None:
        incident = RemoteMarketMonitorIncident(
            source_id=source.source_id,
            metric="source",
            incident_type=INCIDENT_SOURCE,
            status=STATUS_PENDING,
            opened_at=now,
            last_observed_at=now,
            consecutive_hit_count=state.consecutive_source_failure_count,
            last_error_code=sample.error_code,
            metadata_json={},
        )
        session.add(incident)
        if threshold > 1:
            return
    else:
        incident.last_observed_at = now
        incident.consecutive_hit_count = state.consecutive_source_failure_count
        incident.last_error_code = sample.error_code
    if incident.status == STATUS_PENDING and state.consecutive_source_failure_count >= threshold:
        incident.status = STATUS_OPEN
        _mark_initial_notification(incident, now)
        context = _event_context(
            source=source,
            incident=incident,
            checked_at=now,
            range_start=sample.query_range_start,
            range_end=sample.query_range_end,
            pending_audit_count=None,
            pending_review_count=None,
            error_code=sample.error_code,
            safe_error_message=sample.safe_error_message,
        )
        await _enqueue_event_for_destinations(
            session,
            settings=settings,
            source=source,
            incident=incident,
            event_type="SOURCE_UNAVAILABLE",
            template_key="source_unavailable",
            context=context,
        )
    elif incident.status == STATUS_OPEN:
        interval_seconds = (
            target.source_reminder_interval_minutes or settings.source_reminder_interval_minutes
        ) * 60
        bucket = _reminder_bucket(
            incident,
            observed_at=now,
            interval_seconds=interval_seconds,
        )
        if bucket > 0:
            context = _event_context(
                source=source,
                incident=incident,
                checked_at=now,
                range_start=sample.query_range_start,
                range_end=sample.query_range_end,
                pending_audit_count=None,
                pending_review_count=None,
                error_code=sample.error_code,
                safe_error_message=sample.safe_error_message,
            )
            await _enqueue_event_for_destinations(
                session,
                settings=settings,
                source=source,
                incident=incident,
                event_type="SOURCE_REMINDER",
                template_key="source_reminder",
                context=context,
                reminder_bucket=bucket,
            )


async def _record_check_run(
    session: AsyncSession,
    *,
    source_id: str,
    run_mode: str,
    sample: MonitorSample,
) -> RemoteMarketMonitorCheckRun:
    row = RemoteMarketMonitorCheckRun(
        source_id=source_id,
        run_mode=run_mode,
        status=sample.status,
        pending_audit_count=sample.pending_audit_count,
        pending_review_count=sample.pending_review_count,
        query_range_start=sample.query_range_start,
        query_range_end=sample.query_range_end,
        started_at=sample.started_at,
        finished_at=sample.finished_at,
        latency_ms=sample.latency_ms,
        error_code=sample.error_code,
        safe_error_message=sample.safe_error_message,
    )
    session.add(row)
    return row


async def run_manual_monitor_query(
    session: AsyncSession,
    *,
    source_id: str,
    settings: Settings | None = None,
) -> MonitorSample:
    """Run a read-only diagnostic query without changing alert state."""

    source = await _get_source(session, source_id)
    target, _, _ = await ensure_target_settings(session, source=source)
    monitor_settings = await get_monitor_settings(session)
    sample = await fetch_remote_monitor_sample(
        session,
        source=source,
        target=target,
        timeout_seconds=monitor_settings.source_request_timeout_seconds,
        settings=settings,
    )
    await _record_check_run(session, source_id=source_id, run_mode="manual", sample=sample)
    await session.commit()
    return sample


async def _claim_due_target_ids(
    session: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
) -> list[str]:
    settings = await get_monitor_settings(session)
    if not settings.monitor_enabled:
        await session.commit()
        return []
    targets = list(
        await session.scalars(
            select(RemoteMarketMonitorTargetSetting)
            .join(
                SourceConfig,
                SourceConfig.source_id == RemoteMarketMonitorTargetSetting.source_id,
            )
            .where(
                RemoteMarketMonitorTargetSetting.enabled.is_(True),
                SourceConfig.enabled.is_(True),
                SourceConfig.base_url.is_not(None),
                or_(
                    RemoteMarketMonitorTargetSetting.next_check_at.is_(None),
                    RemoteMarketMonitorTargetSetting.next_check_at <= now,
                ),
            )
            .order_by(RemoteMarketMonitorTargetSetting.next_check_at)
            .with_for_update(skip_locked=True)
            .limit(16)
        )
    )
    claimed: list[str] = []
    for target in targets:
        state = await session.get(RemoteMarketMonitorState, target.source_id)
        if state is None:
            state = RemoteMarketMonitorState(source_id=target.source_id)
            session.add(state)
            await session.flush()
        if state.lease_expires_at is not None and _as_utc(state.lease_expires_at) > now:
            continue
        lease_seconds = max(
            target.check_interval_seconds,
            settings.source_request_timeout_seconds * 2,
        )
        state.lease_owner = worker_id
        state.lease_expires_at = now + timedelta(seconds=lease_seconds)
        target.next_check_at = now + timedelta(seconds=target.check_interval_seconds)
        claimed.append(target.source_id)
    await session.commit()
    return claimed


async def run_automatic_monitor_check(
    session: AsyncSession,
    *,
    source_id: str,
    worker_id: str,
    settings: Settings | None = None,
) -> MonitorSample | None:
    """Complete one pre-claimed target tick and commit its event transition."""

    source = await _get_source(session, source_id)
    target, policies, state = await ensure_target_settings(session, source=source)
    if not target.enabled or state.lease_owner != worker_id:
        await session.commit()
        return None
    monitor_settings = await get_monitor_settings(session)
    sample = await fetch_remote_monitor_sample(
        session,
        source=source,
        target=target,
        timeout_seconds=monitor_settings.source_request_timeout_seconds,
        settings=settings,
    )
    await _record_check_run(session, source_id=source_id, run_mode="automatic", sample=sample)
    state.last_check_at = sample.finished_at
    state.lease_owner = None
    state.lease_expires_at = None
    if sample.status == "ok":
        state.last_success_at = sample.finished_at
        state.last_pending_audit_count = sample.pending_audit_count
        state.last_pending_review_count = sample.pending_review_count
        await _advance_source_health(
            session,
            settings=monitor_settings,
            source=source,
            target=target,
            state=state,
            sample=sample,
        )
        values = {
            "pending_audit": sample.pending_audit_count,
            "pending_review": sample.pending_review_count,
        }
        for policy in policies:
            await _advance_metric_incident(
                session,
                settings=monitor_settings,
                source=source,
                policy=policy,
                count=values[policy.metric] or 0,
                sample=sample,
            )
    else:
        await _advance_source_health(
            session,
            settings=monitor_settings,
            source=source,
            target=target,
            state=state,
            sample=sample,
        )
    await session.commit()
    return sample


async def run_due_remote_market_monitor_checks(
    session: AsyncSession,
    *,
    worker_id: str,
    settings: Settings | None = None,
) -> int:
    now = _utc_now()
    source_ids = await _claim_due_target_ids(session, worker_id=worker_id, now=now)
    completed = 0
    for source_id in source_ids:
        result = await run_automatic_monitor_check(
            session,
            source_id=source_id,
            worker_id=worker_id,
            settings=settings,
        )
        if result is not None:
            completed += 1
    return completed


def _resolve_env_secret(reference: str) -> str | None:
    if not reference.startswith("env://"):
        return None
    value = os.environ.get(reference[len("env://") :])
    return value.strip() if value and value.strip() else None


async def _claim_next_outbox(
    session: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
) -> MonitorNotificationOutbox | None:
    row = await session.scalar(
        select(MonitorNotificationOutbox)
        .where(
            MonitorNotificationOutbox.status == "pending",
            MonitorNotificationOutbox.available_at <= now,
            or_(
                MonitorNotificationOutbox.lease_expires_at.is_(None),
                MonitorNotificationOutbox.lease_expires_at <= now,
            ),
        )
        .order_by(MonitorNotificationOutbox.available_at, MonitorNotificationOutbox.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row is None:
        return None
    row.status = "processing"
    row.lease_owner = worker_id
    row.lease_expires_at = now + timedelta(seconds=90)
    await session.commit()
    return row


async def _finish_outbox_attempt(
    session: AsyncSession,
    *,
    outbox_id: str,
    started_at: datetime,
    status: str,
    http_status: int | None = None,
    telegram_message_id: str | None = None,
    safe_error_message: str | None = None,
    retry_after_seconds: int | None = None,
) -> None:
    row = await session.get(MonitorNotificationOutbox, outbox_id)
    if row is None:
        return
    now = _utc_now()
    row.attempt_count += 1
    row.lease_owner = None
    row.lease_expires_at = None
    if status == "sent":
        row.status = "sent"
        row.sent_at = now
        row.last_error = None
    elif row.attempt_count >= row.max_attempts or status == "permanent_failed":
        row.status = "failed"
        row.last_error = safe_error_message
    else:
        row.status = "pending"
        backoff = retry_after_seconds or min(900, 2 ** min(row.attempt_count, 8))
        row.available_at = now + timedelta(seconds=backoff)
        row.last_error = safe_error_message
    session.add(
        MonitorNotificationAttempt(
            outbox_id=row.id,
            started_at=started_at,
            finished_at=now,
            status=status,
            http_status=http_status,
            telegram_message_id=telegram_message_id,
            safe_error_message=safe_error_message,
        )
    )
    await session.commit()


async def process_next_monitor_notification(
    session: AsyncSession,
    *,
    worker_id: str,
) -> bool:
    """Deliver exactly one claimed Telegram message, with durable retry state."""

    settings = await get_monitor_settings(session)
    if settings.delivery_mode != "telegram":
        await session.commit()
        return False
    started_at = _utc_now()
    outbox = await _claim_next_outbox(session, worker_id=worker_id, now=started_at)
    if outbox is None:
        return False
    destination = await session.get(MonitorNotificationDestination, outbox.destination_id)
    if destination is None or not destination.enabled:
        await _finish_outbox_attempt(
            session,
            outbox_id=outbox.id,
            started_at=started_at,
            status="permanent_failed",
            safe_error_message="Telegram 通知目的地已不存在或被停用。",
        )
        return True
    token = _resolve_env_secret(destination.bot_token_secret_ref)
    chat_id = _resolve_env_secret(destination.chat_id_secret_ref)
    if token is None or chat_id is None:
        await _finish_outbox_attempt(
            session,
            outbox_id=outbox.id,
            started_at=started_at,
            status="permanent_failed",
            safe_error_message="Telegram 密钥引用未在运行时环境中配置。",
        )
        return True
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": str(outbox.payload_json.get("text") or ""),
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        payload = response.json() if response.content else {}
    except httpx.HTTPError:
        await _finish_outbox_attempt(
            session,
            outbox_id=outbox.id,
            started_at=started_at,
            status="retryable_failed",
            safe_error_message="Telegram 网络请求失败。",
        )
        return True
    except ValueError:
        await _finish_outbox_attempt(
            session,
            outbox_id=outbox.id,
            started_at=started_at,
            status="retryable_failed",
            safe_error_message="Telegram 返回了无效响应。",
        )
        return True
    if response.is_success and isinstance(payload, dict) and payload.get("ok") is True:
        result = payload.get("result")
        message_id = str(result.get("message_id")) if isinstance(result, dict) else None
        await _finish_outbox_attempt(
            session,
            outbox_id=outbox.id,
            started_at=started_at,
            status="sent",
            http_status=response.status_code,
            telegram_message_id=message_id,
        )
        return True
    retry_after: int | None = None
    if response.status_code == 429 and isinstance(payload, dict):
        parameters = payload.get("parameters")
        if isinstance(parameters, dict) and isinstance(parameters.get("retry_after"), int):
            retry_after = parameters["retry_after"]
    failure_status = (
        "retryable_failed"
        if response.status_code == 429 or response.status_code >= 500
        else "permanent_failed"
    )
    await _finish_outbox_attempt(
        session,
        outbox_id=outbox.id,
        started_at=started_at,
        status=failure_status,
        http_status=response.status_code,
        safe_error_message="Telegram 拒绝或未能接受该通知。",
        retry_after_seconds=retry_after,
    )
    return True
