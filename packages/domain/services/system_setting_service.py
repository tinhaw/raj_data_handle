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


def _is_missing_withdraw_query_range_column(
    error: OperationalError | ProgrammingError,
) -> bool:
    message = str(error).lower()
    return "withdraw_order_query_range" in message and (
        "does not exist" in message or "no such column" in message
    )


async def _load_retention_settings(
    session: AsyncSession,
    *,
    defaults: Settings | None = None,
) -> tuple[SystemRetentionSetting, bool]:
    """Load settings and identify a rollout awaiting migration 0006.

    Application code is released separately from database migrations.  The ORM
    model therefore cannot be selected directly against a database that has
    migration 0005 but not 0006: SQLAlchemy includes the newly added column in
    its SELECT.  GET endpoints can safely use the default preset during that
    brief window; writes must wait for the migration.
    """

    current_defaults = defaults or get_settings()
    try:
        row = await session.get(SystemRetentionSetting, RETENTION_SETTINGS_ID)
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_withdraw_query_range_column(exc):
            raise
        await session.rollback()
        result = await session.execute(
            text(
                "SELECT id, uploaded_file_retention_days, result_retention_days, "
                "remote_cache_retention_days, withdraw_order_refresh_interval_hours, "
                "config_version, updated_by, updated_at "
                "FROM system_retention_settings WHERE id = :id"
            ),
            {"id": RETENTION_SETTINGS_ID},
        )
        legacy = result.mappings().one_or_none()
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
                withdraw_order_refresh_interval_hours=int(
                    legacy["withdraw_order_refresh_interval_hours"]
                ),
                withdraw_order_query_range=current_defaults.withdraw_order_query_range,
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
        withdraw_order_refresh_interval_hours=(
            current_defaults.withdraw_order_refresh_interval_hours
        ),
        withdraw_order_query_range=current_defaults.withdraw_order_query_range,
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
            "提现订单查询范围配置正在初始化，请在数据库迁移完成后重新保存。"
        )
    previous = {
        "uploadedFileRetentionDays": row.uploaded_file_retention_days,
        "resultRetentionDays": row.result_retention_days,
        "remoteCacheRetentionDays": row.remote_cache_retention_days,
        "withdrawOrderRefreshIntervalHours": row.withdraw_order_refresh_interval_hours,
        "withdrawOrderQueryRange": row.withdraw_order_query_range,
        "sessionTtlDays": session_settings.session_ttl_days,
    }
    row.uploaded_file_retention_days = payload.uploaded_file_retention_days
    row.result_retention_days = payload.result_retention_days
    row.remote_cache_retention_days = payload.remote_cache_retention_days
    if payload.withdraw_order_refresh_interval_hours is not None:
        row.withdraw_order_refresh_interval_hours = payload.withdraw_order_refresh_interval_hours
    if payload.withdraw_order_query_range is not None:
        row.withdraw_order_query_range = payload.withdraw_order_query_range
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
                    "withdrawOrderRefreshIntervalHours": (
                        row.withdraw_order_refresh_interval_hours
                    ),
                    "withdrawOrderQueryRange": row.withdraw_order_query_range,
                    "sessionTtlDays": session_settings.session_ttl_days,
                },
                "configVersion": row.config_version,
            },
        )
    )
    await session.commit()
    return row, session_settings
