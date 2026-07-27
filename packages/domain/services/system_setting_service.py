from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings, get_settings
from packages.domain.models import SecurityAuditLog, SystemRetentionSetting
from packages.domain.schemas.system_setting import RetentionSettingsUpdateRequest

RETENTION_SETTINGS_ID = 1


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
    )
    session.add(row)
    await session.commit()
    return row


async def update_retention_settings(
    session: AsyncSession,
    *,
    payload: RetentionSettingsUpdateRequest,
    actor_user_id: int,
) -> SystemRetentionSetting:
    row = await get_retention_settings(session)
    previous = {
        "uploadedFileRetentionDays": row.uploaded_file_retention_days,
        "resultRetentionDays": row.result_retention_days,
        "remoteCacheRetentionDays": row.remote_cache_retention_days,
    }
    row.uploaded_file_retention_days = payload.uploaded_file_retention_days
    row.result_retention_days = payload.result_retention_days
    row.remote_cache_retention_days = payload.remote_cache_retention_days
    row.config_version += 1
    row.updated_by = actor_user_id
    row.updated_at = datetime.now(UTC)
    session.add(
        SecurityAuditLog(
            actor_user_id=actor_user_id,
            action="system.retention.update",
            target_type="system_retention_settings",
            target_id=str(RETENTION_SETTINGS_ID),
            metadata_json={
                "previous": previous,
                "current": {
                    "uploadedFileRetentionDays": row.uploaded_file_retention_days,
                    "resultRetentionDays": row.result_retention_days,
                    "remoteCacheRetentionDays": row.remote_cache_retention_days,
                },
                "configVersion": row.config_version,
            },
        )
    )
    await session.commit()
    return row
