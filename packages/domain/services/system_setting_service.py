from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings, get_settings
from packages.domain.models import SecurityAuditLog, SystemRetentionSetting, SystemSessionSetting
from packages.domain.schemas.system_setting import RetentionSettingsUpdateRequest
from packages.domain.services.session_setting_service import get_session_settings

RETENTION_SETTINGS_ID = 1


class SystemSettingsSchemaPendingError(RuntimeError):
    pass


def _is_missing_refresh_policy_column(
    error: OperationalError | ProgrammingError,
) -> bool:
    message = str(error).lower()
    return (
        "withdraw_order_query_range" in message
        or "withdraw_order_refresh_page_size" in message
        or "charge_order_query_range" in message
        or "charge_order_refresh_page_size" in message
        or "charge_order_refresh_interval_hours" in message
        or "charge_order_export_date_mode" in message
        or "charge_order_export_specific_date" in message
        or "charge_order_export_time" in message
        or "withdraw_order_export_date_mode" in message
        or "withdraw_order_export_specific_date" in message
        or "withdraw_order_export_time" in message
        or "spin_order_refresh_interval_hours" in message
        or "spin_order_refresh_page_size" in message
        or "spin_order_query_range" in message
        or "sync_log_retention_days" in message
    ) and ("does not exist" in message or "no such column" in message)


async def _load_legacy_retention_row(
    session: AsyncSession,
) -> tuple[object | None, bool, bool, bool, bool, bool, bool, bool, bool]:
    """Read a settings row while refresh-policy migrations are pending.

    The ORM cannot select a model with a column that has not been migrated yet.
    Try the newest compatible projection first, then progressively fall back so
    a staged deployment can still serve a read-only settings response while
    migrations are pending.
    """

    base_columns = (
        "id, uploaded_file_retention_days, result_retention_days, "
        "remote_cache_retention_days, withdraw_order_refresh_interval_hours, "
    )
    projections = (
        (
            "sync_log_retention_days, withdraw_order_query_range, "
            "withdraw_order_refresh_page_size, charge_order_refresh_interval_hours, "
            "charge_order_refresh_page_size, charge_order_query_range, "
            "charge_order_export_date_mode, charge_order_export_specific_date, "
            "charge_order_export_time, withdraw_order_export_date_mode, "
            "withdraw_order_export_specific_date, withdraw_order_export_time, "
            "spin_order_refresh_interval_hours, spin_order_refresh_page_size, "
            "spin_order_query_range, ",
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
        ),
        (
            "sync_log_retention_days, withdraw_order_query_range, "
            "withdraw_order_refresh_page_size, charge_order_refresh_interval_hours, "
            "charge_order_refresh_page_size, charge_order_query_range, "
            "charge_order_export_date_mode, charge_order_export_specific_date, "
            "withdraw_order_export_date_mode, withdraw_order_export_specific_date, "
            "spin_order_refresh_interval_hours, spin_order_refresh_page_size, "
            "spin_order_query_range, ",
            True,
            True,
            True,
            True,
            True,
            False,
            True,
            True,
        ),
        (
            "withdraw_order_query_range, withdraw_order_refresh_page_size, "
            "charge_order_refresh_interval_hours, charge_order_refresh_page_size, "
            "charge_order_query_range, charge_order_export_date_mode, "
            "charge_order_export_specific_date, withdraw_order_export_date_mode, "
            "withdraw_order_export_specific_date, spin_order_refresh_interval_hours, "
            "spin_order_refresh_page_size, spin_order_query_range, ",
            True,
            True,
            True,
            True,
            True,
            False,
            True,
            False,
        ),
        (
            "withdraw_order_query_range, withdraw_order_refresh_page_size, "
            "charge_order_refresh_interval_hours, charge_order_refresh_page_size, "
            "charge_order_query_range, charge_order_export_date_mode, "
            "charge_order_export_specific_date, withdraw_order_export_date_mode, "
            "withdraw_order_export_specific_date, ",
            True,
            True,
            True,
            True,
            True,
            False,
            False,
            False,
        ),
        (
            "withdraw_order_query_range, withdraw_order_refresh_page_size, "
            "charge_order_refresh_interval_hours, charge_order_refresh_page_size, "
            "charge_order_query_range, ",
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            False,
        ),
        (
            "withdraw_order_query_range, withdraw_order_refresh_page_size, ",
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
        ),
        (
            "withdraw_order_query_range, ",
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        ),
        ("", False, False, False, False, False, False, False, False),
    )
    for (
        extra_columns,
        has_query_range,
        has_page_size,
        has_charge_policy,
        has_charge_export_policy,
        has_withdraw_export_policy,
        has_export_time_policy,
        has_spin_policy,
        has_sync_log_policy,
    ) in projections:
        try:
            result = await session.execute(
                text(
                    "SELECT "
                    f"{base_columns}{extra_columns}"
                    "config_version, updated_by, updated_at "
                    "FROM system_retention_settings WHERE id = :id"
                ),
                {"id": RETENTION_SETTINGS_ID},
            )
        except (OperationalError, ProgrammingError) as exc:
            if not _is_missing_refresh_policy_column(exc):
                raise
            await session.rollback()
            continue
        return (
            result.mappings().one_or_none(),
            has_query_range,
            has_page_size,
            has_charge_policy,
            has_charge_export_policy,
            has_withdraw_export_policy,
            has_export_time_policy,
            has_spin_policy,
            has_sync_log_policy,
        )
    return None, False, False, False, False, False, False, False, False


async def _load_retention_settings(
    session: AsyncSession,
    *,
    defaults: Settings | None = None,
) -> tuple[SystemRetentionSetting, bool]:
    """Load settings and identify a rollout awaiting refresh-policy migrations.

    Application code is released separately from database migrations.  The ORM
    model therefore cannot be selected directly against a database missing a
    newly added refresh-policy column: SQLAlchemy includes it in its SELECT.
    GET endpoints can safely use defaults during that brief window; writes
    must wait for the relevant migration.
    """

    current_defaults = defaults or get_settings()
    try:
        row = await session.get(SystemRetentionSetting, RETENTION_SETTINGS_ID)
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_refresh_policy_column(exc):
            raise
        await session.rollback()
        (
            legacy,
            has_query_range,
            has_page_size,
            has_charge_policy,
            has_charge_export_policy,
            has_withdraw_export_policy,
            has_export_time_policy,
            has_spin_policy,
            has_sync_log_policy,
        ) = await _load_legacy_retention_row(session)
        if legacy is None:
            raise SystemSettingsSchemaPendingError(
                "提现订单刷新配置正在初始化，请在数据库迁移完成后重试。"
            ) from exc
        return (
            SystemRetentionSetting(
                id=int(legacy["id"]),
                uploaded_file_retention_days=int(legacy["uploaded_file_retention_days"]),
                result_retention_days=int(legacy["result_retention_days"]),
                remote_cache_retention_days=int(legacy["remote_cache_retention_days"]),
                sync_log_retention_days=(
                    int(legacy["sync_log_retention_days"]) if has_sync_log_policy else 30
                ),
                withdraw_order_refresh_interval_hours=int(
                    legacy["withdraw_order_refresh_interval_hours"]
                ),
                withdraw_order_refresh_page_size=(
                    int(legacy["withdraw_order_refresh_page_size"]) if has_page_size else 100
                ),
                withdraw_order_query_range=(
                    str(legacy["withdraw_order_query_range"]) if has_query_range else "today"
                ),
                withdraw_order_export_date_mode=(
                    str(legacy["withdraw_order_export_date_mode"])
                    if has_withdraw_export_policy
                    else current_defaults.withdraw_order_export_date_mode
                ),
                withdraw_order_export_specific_date=(
                    legacy["withdraw_order_export_specific_date"]
                    if has_withdraw_export_policy
                    else current_defaults.withdraw_order_export_specific_date
                ),
                withdraw_order_export_time=(
                    legacy["withdraw_order_export_time"]
                    if has_export_time_policy
                    else current_defaults.withdraw_order_export_time
                ),
                charge_order_refresh_interval_hours=(
                    int(legacy["charge_order_refresh_interval_hours"])
                    if has_charge_policy
                    else current_defaults.charge_order_refresh_interval_hours
                ),
                charge_order_refresh_page_size=(
                    int(legacy["charge_order_refresh_page_size"])
                    if has_charge_policy
                    else current_defaults.charge_order_refresh_page_size
                ),
                charge_order_query_range=(
                    str(legacy["charge_order_query_range"])
                    if has_charge_policy
                    else current_defaults.charge_order_query_range
                ),
                charge_order_export_date_mode=(
                    str(legacy["charge_order_export_date_mode"])
                    if has_charge_export_policy
                    else "previous_day"
                ),
                charge_order_export_specific_date=(
                    legacy["charge_order_export_specific_date"]
                    if has_charge_export_policy
                    else None
                ),
                charge_order_export_time=(
                    legacy["charge_order_export_time"]
                    if has_export_time_policy
                    else current_defaults.charge_order_export_time
                ),
                spin_order_refresh_interval_hours=(
                    int(legacy["spin_order_refresh_interval_hours"])
                    if has_spin_policy
                    else current_defaults.spin_order_refresh_interval_hours
                ),
                spin_order_refresh_page_size=(
                    int(legacy["spin_order_refresh_page_size"])
                    if has_spin_policy
                    else current_defaults.spin_order_refresh_page_size
                ),
                spin_order_query_range=(
                    str(legacy["spin_order_query_range"])
                    if has_spin_policy
                    else current_defaults.spin_order_query_range
                ),
                config_version=int(legacy["config_version"]),
                updated_by=legacy["updated_by"],
                updated_at=legacy["updated_at"],
            ),
            True,
        )

    if row is not None:
        return row, False

    row = SystemRetentionSetting(
        id=RETENTION_SETTINGS_ID,
        uploaded_file_retention_days=current_defaults.uploaded_file_retention_days,
        result_retention_days=current_defaults.result_retention_days,
        remote_cache_retention_days=current_defaults.remote_cache_retention_days,
        sync_log_retention_days=30,
        # Legacy pagination-policy columns remain in the schema for a safe
        # rollout but are no longer used by withdrawal export refreshes.
        withdraw_order_refresh_interval_hours=1,
        withdraw_order_refresh_page_size=100,
        withdraw_order_query_range="today",
        withdraw_order_export_date_mode=current_defaults.withdraw_order_export_date_mode,
        withdraw_order_export_specific_date=current_defaults.withdraw_order_export_specific_date,
        withdraw_order_export_time=current_defaults.withdraw_order_export_time,
        charge_order_refresh_interval_hours=(current_defaults.charge_order_refresh_interval_hours),
        charge_order_refresh_page_size=current_defaults.charge_order_refresh_page_size,
        charge_order_query_range=current_defaults.charge_order_query_range,
        charge_order_export_date_mode="previous_day",
        charge_order_export_specific_date=None,
        charge_order_export_time=current_defaults.charge_order_export_time,
        spin_order_refresh_interval_hours=current_defaults.spin_order_refresh_interval_hours,
        spin_order_refresh_page_size=current_defaults.spin_order_refresh_page_size,
        spin_order_query_range=current_defaults.spin_order_query_range,
    )
    session.add(row)
    await session.commit()
    return row, False


async def get_retention_settings(
    session: AsyncSession,
    *,
    defaults: Settings | None = None,
) -> SystemRetentionSetting:
    row, _ = await _load_retention_settings(session, defaults=defaults)
    return row


async def update_retention_settings(
    session: AsyncSession,
    *,
    payload: RetentionSettingsUpdateRequest,
    actor_user_id: int,
) -> tuple[SystemRetentionSetting, SystemSessionSetting]:
    session_settings = await get_session_settings(session)
    if session_settings is None:
        raise SystemSettingsSchemaPendingError(
            "登录有效期配置正在初始化，请在数据库迁移完成后重新保存。"
        )
    row, schema_pending = await _load_retention_settings(session)
    if schema_pending:
        raise SystemSettingsSchemaPendingError(
            "订单后台同步配置正在初始化，请在数据库迁移完成后重新保存。"
        )
    previous = {
        "uploadedFileRetentionDays": row.uploaded_file_retention_days,
        "resultRetentionDays": row.result_retention_days,
        "remoteCacheRetentionDays": row.remote_cache_retention_days,
        "syncLogRetentionDays": row.sync_log_retention_days,
        "withdrawOrderRefreshIntervalHours": row.withdraw_order_refresh_interval_hours,
        "withdrawOrderRefreshPageSize": row.withdraw_order_refresh_page_size,
        "withdrawOrderQueryRange": row.withdraw_order_query_range,
        "withdrawOrderExportDateMode": row.withdraw_order_export_date_mode,
        "withdrawOrderExportSpecificDate": (
            row.withdraw_order_export_specific_date.isoformat()
            if row.withdraw_order_export_specific_date is not None
            else None
        ),
        "withdrawOrderExportTime": row.withdraw_order_export_time.isoformat(),
        "chargeOrderRefreshIntervalHours": row.charge_order_refresh_interval_hours,
        "chargeOrderRefreshPageSize": row.charge_order_refresh_page_size,
        "chargeOrderQueryRange": row.charge_order_query_range,
        "chargeOrderExportDateMode": row.charge_order_export_date_mode,
        "chargeOrderExportSpecificDate": (
            row.charge_order_export_specific_date.isoformat()
            if row.charge_order_export_specific_date is not None
            else None
        ),
        "chargeOrderExportTime": row.charge_order_export_time.isoformat(),
        "spinOrderRefreshIntervalHours": row.spin_order_refresh_interval_hours,
        "spinOrderRefreshPageSize": row.spin_order_refresh_page_size,
        "spinOrderQueryRange": row.spin_order_query_range,
        "sessionTtlDays": session_settings.session_ttl_days,
    }
    row.uploaded_file_retention_days = payload.uploaded_file_retention_days
    row.result_retention_days = payload.result_retention_days
    row.remote_cache_retention_days = payload.remote_cache_retention_days
    if payload.sync_log_retention_days is not None:
        row.sync_log_retention_days = payload.sync_log_retention_days
    if payload.withdraw_order_refresh_interval_hours is not None:
        row.withdraw_order_refresh_interval_hours = payload.withdraw_order_refresh_interval_hours
    if payload.withdraw_order_refresh_page_size is not None:
        row.withdraw_order_refresh_page_size = payload.withdraw_order_refresh_page_size
    if payload.withdraw_order_query_range is not None:
        row.withdraw_order_query_range = payload.withdraw_order_query_range
    if payload.withdraw_order_export_date_mode is not None:
        row.withdraw_order_export_date_mode = payload.withdraw_order_export_date_mode
        row.withdraw_order_export_specific_date = (
            payload.withdraw_order_export_specific_date
            if payload.withdraw_order_export_date_mode == "specific_date"
            else None
        )
    if payload.withdraw_order_export_time is not None:
        row.withdraw_order_export_time = payload.withdraw_order_export_time
    if payload.charge_order_refresh_interval_hours is not None:
        row.charge_order_refresh_interval_hours = payload.charge_order_refresh_interval_hours
    if payload.charge_order_refresh_page_size is not None:
        row.charge_order_refresh_page_size = payload.charge_order_refresh_page_size
    if payload.charge_order_query_range is not None:
        row.charge_order_query_range = payload.charge_order_query_range
    if payload.charge_order_export_date_mode is not None:
        row.charge_order_export_date_mode = payload.charge_order_export_date_mode
        row.charge_order_export_specific_date = (
            payload.charge_order_export_specific_date
            if payload.charge_order_export_date_mode == "specific_date"
            else None
        )
    if payload.charge_order_export_time is not None:
        row.charge_order_export_time = payload.charge_order_export_time
    if payload.spin_order_refresh_interval_hours is not None:
        row.spin_order_refresh_interval_hours = payload.spin_order_refresh_interval_hours
    if payload.spin_order_refresh_page_size is not None:
        row.spin_order_refresh_page_size = payload.spin_order_refresh_page_size
    if payload.spin_order_query_range is not None:
        row.spin_order_query_range = payload.spin_order_query_range
    row.config_version += 1
    row.updated_by = actor_user_id
    row.updated_at = datetime.now(UTC)
    session_settings.session_ttl_days = payload.session_ttl_days
    session_settings.config_version += 1
    session_settings.updated_by = actor_user_id
    session_settings.updated_at = datetime.now(UTC)
    session.add(
        SecurityAuditLog(
            actor_user_id=actor_user_id,
            action="system.settings.update",
            target_type="system_retention_settings",
            target_id=str(RETENTION_SETTINGS_ID),
            metadata_json={
                "previous": previous,
                "current": {
                    "uploadedFileRetentionDays": row.uploaded_file_retention_days,
                    "resultRetentionDays": row.result_retention_days,
                    "remoteCacheRetentionDays": row.remote_cache_retention_days,
                    "syncLogRetentionDays": row.sync_log_retention_days,
                    "withdrawOrderRefreshIntervalHours": (
                        row.withdraw_order_refresh_interval_hours
                    ),
                    "withdrawOrderRefreshPageSize": row.withdraw_order_refresh_page_size,
                    "withdrawOrderQueryRange": row.withdraw_order_query_range,
                    "withdrawOrderExportDateMode": row.withdraw_order_export_date_mode,
                    "withdrawOrderExportSpecificDate": (
                        row.withdraw_order_export_specific_date.isoformat()
                        if row.withdraw_order_export_specific_date is not None
                        else None
                    ),
                    "withdrawOrderExportTime": row.withdraw_order_export_time.isoformat(),
                    "chargeOrderRefreshIntervalHours": row.charge_order_refresh_interval_hours,
                    "chargeOrderRefreshPageSize": row.charge_order_refresh_page_size,
                    "chargeOrderQueryRange": row.charge_order_query_range,
                    "chargeOrderExportDateMode": row.charge_order_export_date_mode,
                    "chargeOrderExportSpecificDate": (
                        row.charge_order_export_specific_date.isoformat()
                        if row.charge_order_export_specific_date is not None
                        else None
                    ),
                    "chargeOrderExportTime": row.charge_order_export_time.isoformat(),
                    "spinOrderRefreshIntervalHours": row.spin_order_refresh_interval_hours,
                    "spinOrderRefreshPageSize": row.spin_order_refresh_page_size,
                    "spinOrderQueryRange": row.spin_order_query_range,
                    "sessionTtlDays": session_settings.session_ttl_days,
                },
                "configVersion": row.config_version,
            },
        )
    )
    await session.commit()
    return row, session_settings
