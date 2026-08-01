from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context, require_admin
from packages.common.database import get_db_session
from packages.common.settings import get_settings
from packages.domain.models import SystemRetentionSetting
from packages.domain.schemas.system_setting import (
    RetentionSettingsResponse,
    RetentionSettingsUpdateRequest,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.session_setting_service import get_session_settings
from packages.domain.services.system_setting_service import (
    SystemSettingsSchemaPendingError,
    get_retention_settings,
    update_retention_settings,
)

router = APIRouter(prefix="/system-settings", tags=["system-settings"])


def _response(
    retention: SystemRetentionSetting,
    *,
    session_ttl_days: int,
) -> RetentionSettingsResponse:
    return RetentionSettingsResponse(
        uploadedFileRetentionDays=retention.uploaded_file_retention_days,
        resultRetentionDays=retention.result_retention_days,
        remoteCacheRetentionDays=retention.remote_cache_retention_days,
        syncLogRetentionDays=retention.sync_log_retention_days or 30,
        withdrawOrderRefreshIntervalHours=retention.withdraw_order_refresh_interval_hours or 1,
        withdrawOrderRefreshPageSize=retention.withdraw_order_refresh_page_size or 100,
        withdrawOrderQueryRange=retention.withdraw_order_query_range or "today",
        withdrawOrderExportDateMode=retention.withdraw_order_export_date_mode or "previous_day",
        withdrawOrderExportSpecificDate=retention.withdraw_order_export_specific_date,
        chargeOrderRefreshIntervalHours=retention.charge_order_refresh_interval_hours or 1,
        chargeOrderRefreshPageSize=retention.charge_order_refresh_page_size or 100,
        chargeOrderQueryRange=retention.charge_order_query_range or "today",
        chargeOrderExportDateMode=retention.charge_order_export_date_mode or "previous_day",
        chargeOrderExportSpecificDate=retention.charge_order_export_specific_date,
        spinOrderRefreshIntervalHours=retention.spin_order_refresh_interval_hours or 2,
        spinOrderRefreshPageSize=retention.spin_order_refresh_page_size or 100,
        spinOrderQueryRange=(
            retention.spin_order_query_range or "previous_business_day_to_completed_slot"
        ),
        sessionTtlDays=session_ttl_days,
        configVersion=retention.config_version,
        updatedBy=retention.updated_by,
        updatedAt=retention.updated_at,
    )


@router.get("/retention", response_model=RetentionSettingsResponse)
async def retention_settings(
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> RetentionSettingsResponse:
    session_settings = await get_session_settings(session)
    try:
        retention = await get_retention_settings(session)
    except SystemSettingsSchemaPendingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _response(
        retention,
        session_ttl_days=(
            session_settings.session_ttl_days
            if session_settings is not None
            else get_settings().session_ttl_days
        ),
    )


@router.patch("/retention", response_model=RetentionSettingsResponse)
async def patch_retention_settings(
    payload: RetentionSettingsUpdateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> RetentionSettingsResponse:
    try:
        retention, session_settings = await update_retention_settings(
            session,
            payload=payload,
            actor_user_id=auth.user.id,
        )
    except SystemSettingsSchemaPendingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _response(retention, session_ttl_days=session_settings.session_ttl_days)
