from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings, get_settings
from packages.domain.models import SecurityAuditLog, SystemRetentionSetting, SystemSessionSetting
from packages.domain.schemas.system_setting import RetentionSettingsUpdateRequest
from packages.domain.services.session_setting_service import get_session_settings

RETENTION_SETTINGS_ID = 1


class SystemSettingsSchemaPendingError(RuntimeError):
    pass


async def get_retention_settings(
    session: AsyncSession,
    *,
    defaults: Settings | None = None,
) -> SystemRetentionSetting:
    row = await session.get(SystemRetentionSetting, RETENTION_SETTINGS_ID)
    if row is not None:
        return row

    current_defaults = defaults or get_settings()
    row = SystemRetentionSetting(
        id=RETENTION_SETTINGS_ID,
        uploaded_file_retention_days=current_defaults.uploaded_file_retention_days,
        result_retention_days=current_defaults.result_retention_days,
        remote_cache_retention_days=current_defaults.remote_cache_retention_days,
        withdraw_order_refresh_interval_hours=(
            current_defaults.withdraw_order_refresh_interval_hours
        ),
    )
    session.add(row)
    await session.commit()
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
    row = await get_retention_settings(session)
    previous = {
        "uploadedFileRetentionDays": row.uploaded_file_retention_days,
        "resultRetentionDays": row.result_retention_days,
        "remoteCacheRetentionDays": row.remote_cache_retention_days,
        "withdrawOrderRefreshIntervalHours": row.withdraw_order_refresh_interval_hours,
        "sessionTtlDays": session_settings.session_ttl_days,
    }
    row.uploaded_file_retention_days = payload.uploaded_file_retention_days
    row.result_retention_days = payload.result_retention_days
    row.remote_cache_retention_days = payload.remote_cache_retention_days
    if payload.withdraw_order_refresh_interval_hours is not None:
        row.withdraw_order_refresh_interval_hours = payload.withdraw_order_refresh_interval_hours
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
                    "sessionTtlDays": session_settings.session_ttl_days,
                },
                "configVersion": row.config_version,
            },
        )
    )
    await session.commit()
    return row, session_settings
