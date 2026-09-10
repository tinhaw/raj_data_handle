"""Configuration and read-only status APIs for remote-market monitoring."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context, require_admin
from packages.common.database import get_db_session
from packages.domain.models import (
    RemoteMarketMonitorCheckRun,
    RemoteMarketMonitorIncident,
    SecurityAuditLog,
    SourceConfig,
)
from packages.domain.schemas.remote_market_monitor import (
    MonitorNotificationDestinationCreateRequest,
    MonitorNotificationDestinationResponse,
    MonitorNotificationDestinationUpdateRequest,
    MonitorNotificationTemplateSetCreateRequest,
    MonitorNotificationTemplateSetResponse,
    MonitorNotificationTemplateSetUpdateRequest,
    RemoteMarketMonitorCheckRunResponse,
    RemoteMarketMonitorIncidentResponse,
    RemoteMarketMonitorOverviewResponse,
    RemoteMarketMonitorSettingsResponse,
    RemoteMarketMonitorSettingsUpdateRequest,
    RemoteMarketMonitorTargetResponse,
    RemoteMarketMonitorTargetUpdateRequest,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.remote_market_monitor_service import (
    RemoteMarketMonitorError,
    _destination_response_values,
    create_notification_destination,
    create_template_set,
    get_monitor_overview,
    get_monitor_settings,
    get_target_snapshot,
    list_notification_destinations,
    list_template_sets,
    run_manual_monitor_query,
    update_monitor_settings,
    update_notification_destination,
    update_target_settings,
    update_template_set,
)

router = APIRouter(prefix="/remote-market-monitor", tags=["remote-market-monitor"])
system_router = APIRouter(prefix="/system-settings", tags=["remote-market-monitor-settings"])


def _settings_response(row) -> RemoteMarketMonitorSettingsResponse:
    return RemoteMarketMonitorSettingsResponse(
        monitorEnabled=row.monitor_enabled,
        deliveryMode=row.delivery_mode,
        dashboardRefreshIntervalSeconds=row.dashboard_refresh_interval_seconds,
        defaultCheckIntervalSeconds=row.default_check_interval_seconds,
        sourceRequestTimeoutSeconds=row.source_request_timeout_seconds,
        defaultBreachConsecutiveChecks=row.default_breach_consecutive_checks,
        defaultRecoveryConsecutiveChecks=row.default_recovery_consecutive_checks,
        sourceFailureConsecutiveChecks=row.source_failure_consecutive_checks,
        defaultReminderIntervalMinutes=row.default_reminder_interval_minutes,
        sourceReminderIntervalMinutes=row.source_reminder_interval_minutes,
        staleAfterMultiplier=row.stale_after_multiplier,
        notificationMaxAttempts=row.notification_max_attempts,
        checkRunRetentionDays=row.check_run_retention_days,
        notificationAttemptRetentionDays=row.notification_attempt_retention_days,
        configVersion=row.config_version,
        updatedAt=row.updated_at,
    )


def _template_response(row) -> MonitorNotificationTemplateSetResponse:
    return MonitorNotificationTemplateSetResponse(
        id=row.id,
        displayName=row.display_name,
        templates=row.templates_json,
        isBuiltin=row.is_builtin,
        configVersion=row.config_version,
        updatedAt=row.updated_at,
    )


async def _target_response(
    session: AsyncSession, source_id: str
) -> RemoteMarketMonitorTargetResponse:
    source = await session.get(SourceConfig, source_id)
    if source is None or not source.base_url:
        raise RemoteMarketMonitorError("盘口不存在或尚未配置后台地址。")
    return RemoteMarketMonitorTargetResponse.model_validate(
        await get_target_snapshot(session, source=source, persist_defaults=True)
    )


@router.get("/overview", response_model=RemoteMarketMonitorOverviewResponse)
async def overview(
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> RemoteMarketMonitorOverviewResponse:
    result = await get_monitor_overview(session)
    return RemoteMarketMonitorOverviewResponse(
        generatedAt=result["generated_at"],
        settings=_settings_response(result["settings"]),
        targets=result["targets"],
        openIncidentCount=result["open_incident_count"],
        pendingOutboxCount=result["pending_outbox_count"],
    )


@router.get("/targets/{source_id}", response_model=RemoteMarketMonitorTargetResponse)
async def get_target(
    source_id: str,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> RemoteMarketMonitorTargetResponse:
    try:
        return await _target_response(session, source_id)
    except RemoteMarketMonitorError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/targets/{source_id}", response_model=RemoteMarketMonitorTargetResponse)
async def patch_target(
    source_id: str,
    payload: RemoteMarketMonitorTargetUpdateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> RemoteMarketMonitorTargetResponse:
    try:
        await update_target_settings(
            session,
            source_id=source_id,
            payload=payload,
            actor_user_id=auth.user.id,
        )
        return await _target_response(session, source_id)
    except RemoteMarketMonitorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/targets/{source_id}/test-query", response_model=RemoteMarketMonitorCheckRunResponse)
async def test_query(
    source_id: str,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> RemoteMarketMonitorCheckRunResponse:
    try:
        await run_manual_monitor_query(session, source_id=source_id)
    except RemoteMarketMonitorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # The manual query itself is durable; record the operator separately.
    # It intentionally does not advance alert or notification state.
    session.add(
        SecurityAuditLog(
            actor_user_id=auth.user.id,
            action="remote_market_monitor.target.test_query",
            target_type="source_config",
            target_id=source_id,
            metadata_json={},
        )
    )
    await session.commit()
    row = await session.scalar(
        select(RemoteMarketMonitorCheckRun)
        .where(
            RemoteMarketMonitorCheckRun.source_id == source_id,
            RemoteMarketMonitorCheckRun.run_mode == "manual",
        )
        .order_by(RemoteMarketMonitorCheckRun.finished_at.desc())
        .limit(1)
    )
    if row is None:
        raise HTTPException(status_code=500, detail="手动检查记录未保存。")
    return RemoteMarketMonitorCheckRunResponse.model_validate(row)


@router.get("/check-runs", response_model=list[RemoteMarketMonitorCheckRunResponse])
async def check_runs(
    source_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[RemoteMarketMonitorCheckRunResponse]:
    statement = select(RemoteMarketMonitorCheckRun).order_by(
        RemoteMarketMonitorCheckRun.finished_at.desc()
    )
    if source_id:
        statement = statement.where(RemoteMarketMonitorCheckRun.source_id == source_id)
    rows = list(await session.scalars(statement.limit(limit)))
    return [RemoteMarketMonitorCheckRunResponse.model_validate(row) for row in rows]


@router.get("/incidents", response_model=list[RemoteMarketMonitorIncidentResponse])
async def incidents(
    source_id: str | None = None,
    open_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[RemoteMarketMonitorIncidentResponse]:
    statement = select(RemoteMarketMonitorIncident).order_by(
        RemoteMarketMonitorIncident.last_observed_at.desc()
    )
    if source_id:
        statement = statement.where(RemoteMarketMonitorIncident.source_id == source_id)
    if open_only:
        statement = statement.where(RemoteMarketMonitorIncident.status == "open")
    rows = list(await session.scalars(statement.limit(limit)))
    return [RemoteMarketMonitorIncidentResponse.model_validate(row) for row in rows]


@system_router.get("/remote-market-monitor", response_model=RemoteMarketMonitorSettingsResponse)
async def monitor_settings(
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> RemoteMarketMonitorSettingsResponse:
    row = await get_monitor_settings(session)
    await session.commit()
    return _settings_response(row)


@system_router.patch("/remote-market-monitor", response_model=RemoteMarketMonitorSettingsResponse)
async def patch_monitor_settings(
    payload: RemoteMarketMonitorSettingsUpdateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> RemoteMarketMonitorSettingsResponse:
    row = await update_monitor_settings(session, payload=payload, actor_user_id=auth.user.id)
    return _settings_response(row)


@system_router.get(
    "/monitor-notification-destinations",
    response_model=list[MonitorNotificationDestinationResponse],
)
async def notification_destinations(
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[MonitorNotificationDestinationResponse]:
    return [
        MonitorNotificationDestinationResponse.model_validate(_destination_response_values(row))
        for row in await list_notification_destinations(session)
    ]


@system_router.post(
    "/monitor-notification-destinations",
    response_model=MonitorNotificationDestinationResponse,
)
async def post_notification_destination(
    payload: MonitorNotificationDestinationCreateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> MonitorNotificationDestinationResponse:
    try:
        row = await create_notification_destination(
            session, payload=payload, actor_user_id=auth.user.id
        )
    except RemoteMarketMonitorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MonitorNotificationDestinationResponse.model_validate(_destination_response_values(row))


@system_router.patch(
    "/monitor-notification-destinations/{destination_id}",
    response_model=MonitorNotificationDestinationResponse,
)
async def patch_notification_destination(
    destination_id: str,
    payload: MonitorNotificationDestinationUpdateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> MonitorNotificationDestinationResponse:
    try:
        row = await update_notification_destination(
            session,
            destination_id=destination_id,
            payload=payload,
            actor_user_id=auth.user.id,
        )
    except RemoteMarketMonitorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MonitorNotificationDestinationResponse.model_validate(_destination_response_values(row))


@system_router.get(
    "/monitor-notification-template-sets",
    response_model=list[MonitorNotificationTemplateSetResponse],
)
async def template_sets(
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[MonitorNotificationTemplateSetResponse]:
    return [_template_response(row) for row in await list_template_sets(session)]


@system_router.post(
    "/monitor-notification-template-sets",
    response_model=MonitorNotificationTemplateSetResponse,
)
async def post_template_set(
    payload: MonitorNotificationTemplateSetCreateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> MonitorNotificationTemplateSetResponse:
    try:
        row = await create_template_set(session, payload=payload, actor_user_id=auth.user.id)
    except RemoteMarketMonitorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _template_response(row)


@system_router.patch(
    "/monitor-notification-template-sets/{template_set_id}",
    response_model=MonitorNotificationTemplateSetResponse,
)
async def patch_template_set(
    template_set_id: str,
    payload: MonitorNotificationTemplateSetUpdateRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> MonitorNotificationTemplateSetResponse:
    try:
        row = await update_template_set(
            session,
            template_set_id=template_set_id,
            payload=payload,
            actor_user_id=auth.user.id,
        )
    except RemoteMarketMonitorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _template_response(row)
