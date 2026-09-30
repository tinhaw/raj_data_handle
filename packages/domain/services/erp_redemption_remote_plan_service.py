"""Local state machine for ERP redemption remote-operation orchestration.

Public plan functions only mutate local orchestration records. Reservation and
completion functions are integration seams for a future explicitly authorised
runner; this module itself never reads credentials or performs network I/O.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import (
    ErpRedemptionCodeBatch,
    ErpRedemptionCodeIssue,
    ErpRedemptionRemoteExecution,
    ErpRedemptionRemotePlan,
    ErpRedemptionTask,
    RemoteAccount,
    SourceConfig,
)
from packages.domain.schemas.erp_redemption_remote import (
    ErpRedemptionRemoteExecutionResponse,
    ErpRedemptionRemoteOperation,
    ErpRedemptionRemotePlanRecoverRequest,
    ErpRedemptionRemotePlanResponse,
    ErpRedemptionRemotePlanWrite,
    ErpRedemptionRemotePublishPlanRequest,
    ErpRedemptionRemoteScheduleCancelRequest,
    ErpRedemptionTaskRemotePlanWrite,
)
from packages.domain.services.auth_service import write_audit
from packages.domain.services.erp_redemption_remote_adapter import (
    RemoteCancelPublishResult,
    RemoteCreateResult,
    RemoteDownloadResult,
    RemotePublishResult,
)
from packages.domain.services.erp_redemption_remote_gate import (
    ErpRemoteExecutionGrant,
    authorize_erp_redemption_remote_execution,
)
from packages.domain.services.remote_account_service import get_reward_tier_preset


class ErpRedemptionRemotePlanError(ValueError):
    pass


class ErpRedemptionRemotePlanNotFoundError(ErpRedemptionRemotePlanError):
    pass


class ErpRedemptionRemotePlanConflictError(ErpRedemptionRemotePlanError):
    pass


ERP_BUSINESS_TIMEZONE = "Asia/Shanghai"


@dataclass(frozen=True, slots=True)
class ErpRemoteExecutionReservation:
    reservation_id: str
    execution: ErpRedemptionRemoteExecutionResponse
    grant: ErpRemoteExecutionGrant


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _business_zone() -> ZoneInfo:
    try:
        return ZoneInfo(ERP_BUSINESS_TIMEZONE)
    except ZoneInfoNotFoundError as exc:
        raise ErpRedemptionRemotePlanError("ERP 业务时区配置无效。") from exc


async def _batch(session: AsyncSession, batch_id: str) -> ErpRedemptionCodeBatch:
    batch = await session.get(ErpRedemptionCodeBatch, batch_id)
    if batch is None:
        raise ErpRedemptionRemotePlanNotFoundError("兑换码批次不存在。")
    if not batch.remote_account_id or not batch.source_id:
        raise ErpRedemptionRemotePlanConflictError(
            "兼容旧单批次没有统一远端账号，不能配置远端编排。"
        )
    return batch


async def _issues(session: AsyncSession, batch_id: str) -> list[ErpRedemptionCodeIssue]:
    return list(
        await session.scalars(
            select(ErpRedemptionCodeIssue)
            .where(ErpRedemptionCodeIssue.batch_id == batch_id)
            .order_by(
                ErpRedemptionCodeIssue.claim_date.asc(),
                ErpRedemptionCodeIssue.min_deposit_amount.asc(),
            )
        )
    )


async def _plan(
    session: AsyncSession,
    batch_id: str,
    *,
    for_update: bool = False,
) -> ErpRedemptionRemotePlan:
    statement = select(ErpRedemptionRemotePlan).where(
        ErpRedemptionRemotePlan.batch_id == batch_id
    )
    if for_update:
        statement = statement.with_for_update()
    plan = await session.scalar(statement)
    if plan is None:
        raise ErpRedemptionRemotePlanNotFoundError("该批次尚未配置远端编排计划。")
    return plan


async def _account_source(
    session: AsyncSession,
    remote_account_id: str,
    *,
    require_enabled: bool = True,
) -> tuple[RemoteAccount, SourceConfig]:
    row = (
        await session.execute(
            select(RemoteAccount, SourceConfig)
            .join(SourceConfig, SourceConfig.source_id == RemoteAccount.source_id)
            .where(RemoteAccount.id == remote_account_id)
        )
    ).one_or_none()
    if row is None:
        raise ErpRedemptionRemotePlanConflictError("统一远端账号或所属盘口不存在。")
    account, source = row
    if require_enabled and (not account.enabled or not source.enabled):
        raise ErpRedemptionRemotePlanConflictError("统一远端账号或所属盘口已停用。")
    return account, source


def _check_version(plan: ErpRedemptionRemotePlan, row_version: int) -> None:
    if plan.row_version != row_version:
        raise ErpRedemptionRemotePlanConflictError("远端编排计划已被更新，请刷新后重试。")


def _execution_response(
    execution: ErpRedemptionRemoteExecution,
) -> ErpRedemptionRemoteExecutionResponse:
    return ErpRedemptionRemoteExecutionResponse(
        id=execution.id,
        plan_id=execution.plan_id,
        issue_id=execution.issue_id,
        operation=execution.operation,
        trigger_type=execution.trigger_type,
        status=execution.status,
        attempt_number=execution.attempt_number,
        scheduled_for=execution.scheduled_for,
        remote_request_id=execution.remote_request_id,
        error_code=execution.error_code,
        error_message=execution.error_message,
        result_metadata=execution.result_metadata_json,
        requested_by=execution.requested_by,
        requested_at=execution.requested_at,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
    )


async def _plan_response(
    session: AsyncSession,
    plan: ErpRedemptionRemotePlan,
) -> ErpRedemptionRemotePlanResponse:
    account, source = await _account_source(
        session,
        plan.remote_account_id,
        require_enabled=False,
    )
    issues = await _issues(session, plan.batch_id)
    scheduled = _aware_utc(plan.scheduled_publish_at)
    local_scheduled = (
        scheduled.astimezone(_business_zone()).replace(tzinfo=None)
        if scheduled is not None
        else None
    )
    return ErpRedemptionRemotePlanResponse(
        id=plan.id,
        batch_id=plan.batch_id,
        remote_account_id=plan.remote_account_id,
        remote_account_name=account.display_name,
        source_id=source.source_id,
        source_display_name=source.display_name,
        business_timezone=ERP_BUSINESS_TIMEZONE,
        redemption_type=plan.redemption_type,
        workflow_status=plan.workflow_status,
        publish_environment=plan.publish_environment,
        flow_times=plan.flow_times,
        creation_interval_seconds=plan.creation_interval_seconds,
        activity_recharge=plan.activity_recharge,
        activity_recharge_count=plan.activity_recharge_count,
        activity_id=plan.activity_id,
        key_number=plan.key_number,
        single_user_limit=plan.single_user_limit,
        single_key_limit=plan.single_key_limit,
        require_bind_bank_card=plan.require_bind_bank_card,
        require_bind_phone=plan.require_bind_phone,
        check_uuid=plan.check_uuid,
        uuid_reward_limit=plan.uuid_reward_limit,
        check_login_ip=plan.check_login_ip,
        login_ip_reward_limit=plan.login_ip_reward_limit,
        check_register_ip=plan.check_register_ip,
        register_ip_reward_limit=plan.register_ip_reward_limit,
        publish_mode=plan.publish_mode,
        scheduled_publish_at=scheduled,
        scheduled_publish_local_at=local_scheduled,
        fallback_to_scheduled=plan.fallback_to_scheduled,
        publish_note=plan.publish_note,
        remote_publish_task_id=plan.remote_publish_task_id,
        schedule_cancelled_at=plan.schedule_cancelled_at,
        reserved_operation=plan.reserved_operation,
        error_code=plan.error_code,
        error_message=plan.error_message,
        issue_count=len(issues),
        created_count=sum(
            issue.remote_workflow_status
            in {"CREATED", "PUBLISHED", "RESERVED", "DOWNLOADING", "DOWNLOADED"}
            and issue.remote_configuration_id is not None
            for issue in issues
        ),
        downloaded_count=sum(
            issue.remote_workflow_status == "DOWNLOADED" for issue in issues
        ),
        failed_count=sum(issue.remote_workflow_status == "FAILED" for issue in issues),
        schedule_due=bool(scheduled and scheduled <= datetime.now(UTC)),
        row_version=plan.row_version,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


async def get_erp_redemption_remote_plan(
    session: AsyncSession,
    *,
    batch_id: str,
) -> ErpRedemptionRemotePlanResponse | None:
    await _batch(session, batch_id)
    plan = await session.scalar(
        select(ErpRedemptionRemotePlan).where(
            ErpRedemptionRemotePlan.batch_id == batch_id
        )
    )
    return await _plan_response(session, plan) if plan is not None else None


async def configure_erp_redemption_remote_plan(
    session: AsyncSession,
    *,
    batch_id: str,
    request: ErpRedemptionRemotePlanWrite,
    actor_user_id: int,
    commit: bool = True,
) -> ErpRedemptionRemotePlanResponse:
    batch = await _batch(session, batch_id)
    account, source = await _account_source(session, batch.remote_account_id or "")
    if account.source_id != batch.source_id:
        raise ErpRedemptionRemotePlanConflictError("批次盘口与统一远端账号归属不一致。")
    issues = await _issues(session, batch.id)
    tier_ids = {issue.campaign_tier_id for issue in issues}
    if set(request.tier_label_ids) != tier_ids:
        raise ErpRedemptionRemotePlanError("必须为当前批次的每个充值档位配置标签 ID。")

    plan = await session.scalar(
        select(ErpRedemptionRemotePlan)
        .where(ErpRedemptionRemotePlan.batch_id == batch.id)
        .with_for_update()
    )
    created = plan is None
    if plan is None:
        plan = ErpRedemptionRemotePlan(
            batch_id=batch.id,
            remote_account_id=account.id,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        session.add(plan)
    else:
        if request.row_version is None:
            raise ErpRedemptionRemotePlanConflictError("更新计划时必须提供行版本。")
        _check_version(plan, request.row_version)
        if plan.workflow_status not in {
            "AWAITING_CREATE_AUTHORIZATION",
            "CREATE_FAILED",
        }:
            raise ErpRedemptionRemotePlanConflictError("远端创建已开始，不能再修改参数快照。")
        plan.row_version += 1
        plan.updated_by = actor_user_id

    plan.redemption_type = request.redemption_type
    plan.publish_environment = request.publish_environment
    plan.flow_times = request.flow_times
    plan.creation_interval_seconds = request.creation_interval_seconds
    plan.activity_recharge = request.activity_recharge
    plan.activity_recharge_count = request.activity_recharge_count
    plan.activity_id = request.activity_id
    plan.key_number = request.key_number
    plan.single_user_limit = request.single_user_limit
    plan.single_key_limit = request.single_key_limit
    plan.require_bind_bank_card = request.require_bind_bank_card
    plan.require_bind_phone = request.require_bind_phone
    plan.check_uuid = request.check_uuid
    plan.uuid_reward_limit = request.uuid_reward_limit
    plan.check_login_ip = request.check_login_ip
    plan.login_ip_reward_limit = request.login_ip_reward_limit
    plan.check_register_ip = request.check_register_ip
    plan.register_ip_reward_limit = request.register_ip_reward_limit
    plan.workflow_status = "AWAITING_CREATE_AUTHORIZATION"
    plan.error_code = None
    plan.error_message = None

    for issue in issues:
        issue.remote_label_ids_json = request.tier_label_ids[issue.campaign_tier_id]
        tier_label = issue.tier_name or str(issue.min_deposit_amount)
        issue.remote_description = (
            f"{source.display_name} {issue.claim_date.isoformat()} {tier_label}"
        )[:500]
        if issue.remote_workflow_status == "FAILED":
            issue.remote_workflow_status = "NOT_STARTED"
            issue.remote_error_code = None
            issue.remote_error_message = None
        issue.row_version += 1

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ErpRedemptionRemotePlanConflictError(
            "该批次的远端编排计划已由其他请求创建。"
        ) from exc
    await write_audit(
        session,
        action="erp_redemption_remote_plan.configure",
        actor_user_id=actor_user_id,
        target_type="erp_redemption_remote_plan",
        target_id=plan.id,
        metadata={
            "batch_id": batch.id,
            "source_id": source.source_id,
            "created": created,
            "issue_count": len(issues),
            "redemption_type": plan.redemption_type,
            "publish_environment": plan.publish_environment,
        },
    )
    if commit:
        await session.commit()
    else:
        await session.flush()
    return await _plan_response(session, plan)


async def configure_erp_redemption_task_remote_plans(
    session: AsyncSession,
    *,
    task_id: str,
    request: ErpRedemptionTaskRemotePlanWrite,
    actor_user_id: int,
) -> list[ErpRedemptionRemotePlanResponse]:
    """Configure every task subtask atomically from unified-account presets."""

    task = await session.get(ErpRedemptionTask, task_id)
    if task is None:
        raise ErpRedemptionRemotePlanNotFoundError("兑换码任务组不存在。")
    batches = list(
        await session.scalars(
            select(ErpRedemptionCodeBatch)
            .where(ErpRedemptionCodeBatch.task_id == task.id)
            .order_by(ErpRedemptionCodeBatch.execution_order.asc())
        )
    )
    if not batches:
        raise ErpRedemptionRemotePlanConflictError("任务组没有可配置的盘口子任务。")

    batch_labels: dict[str, dict[str, list[int]]] = {}
    for batch in batches:
        if not batch.remote_account_id:
            raise ErpRedemptionRemotePlanConflictError("任务组包含未绑定统一远端账号的子任务。")
        issues = await _issues(session, batch.id)
        if request.redemption_type == "PREVIOUS_DAY_DEPOSIT":
            batch_labels[batch.id] = {issue.campaign_tier_id: [] for issue in issues}
            continue
        preset = await get_reward_tier_preset(session, account_id=batch.remote_account_id)
        if not preset.exists:
            raise ErpRedemptionRemotePlanConflictError(
                f"账号 {batch.remote_account_id} 尚未配置充值档位预设。"
            )
        if preset.stale:
            raise ErpRedemptionRemotePlanConflictError(
                f"账号 {batch.remote_account_id} 的档位预设已过期，请先核对标签快照。"
            )
        labels: dict[str, list[int]] = {}
        for issue in issues:
            matched = next(
                (
                    tier
                    for tier in preset.tiers
                    if (
                        issue.tier_name
                        and tier.display_name == issue.tier_name
                    )
                    or tier.min_deposit_amount == issue.min_deposit_amount
                ),
                None,
            )
            if matched is None:
                raise ErpRedemptionRemotePlanConflictError(
                    f"账号 {batch.remote_account_id} 的预设缺少档位“"
                    f"{issue.tier_name or issue.min_deposit_amount}”。"
                )
            labels[issue.campaign_tier_id] = matched.label_ids
        batch_labels[batch.id] = labels

    options = request.model_dump()
    results: list[ErpRedemptionRemotePlanResponse] = []
    for batch in batches:
        existing = await session.scalar(
            select(ErpRedemptionRemotePlan).where(
                ErpRedemptionRemotePlan.batch_id == batch.id
            )
        )
        results.append(
            await configure_erp_redemption_remote_plan(
                session,
                batch_id=batch.id,
                request=ErpRedemptionRemotePlanWrite(
                    **options,
                    tier_label_ids=batch_labels[batch.id],
                    row_version=existing.row_version if existing is not None else None,
                ),
                actor_user_id=actor_user_id,
                commit=False,
            )
        )
    await write_audit(
        session,
        action="erp_redemption_task.remote_plans_configure",
        actor_user_id=actor_user_id,
        target_type="erp_redemption_task",
        target_id=task.id,
        metadata={
            "subtask_count": len(results),
            "redemption_type": request.redemption_type,
            "publish_environment": request.publish_environment,
        },
    )
    await session.commit()
    return results


async def plan_erp_redemption_remote_publish(
    session: AsyncSession,
    *,
    batch_id: str,
    request: ErpRedemptionRemotePublishPlanRequest,
    actor_user_id: int,
) -> ErpRedemptionRemotePlanResponse:
    plan = await _plan(session, batch_id, for_update=True)
    _check_version(plan, request.row_version)
    await _account_source(session, plan.remote_account_id)
    if plan.workflow_status not in {
        "AWAITING_CREATE_AUTHORIZATION",
        "CREATE_FAILED",
        "READY_TO_PUBLISH",
        "PUBLISH_FAILED",
        "AWAITING_PUBLISH_AUTHORIZATION",
    }:
        raise ErpRedemptionRemotePlanConflictError("当前远端编排状态不能修改发布计划。")

    scheduled_utc: datetime | None = None
    if request.scheduled_local_at is not None:
        scheduled_utc = request.scheduled_local_at.replace(
            tzinfo=_business_zone()
        ).astimezone(UTC)
        if scheduled_utc <= datetime.now(UTC):
            raise ErpRedemptionRemotePlanError("定时发布时间必须晚于当前时间。")
    plan.publish_mode = request.mode
    plan.scheduled_publish_at = scheduled_utc
    plan.fallback_to_scheduled = request.fallback_to_scheduled
    plan.publish_note = request.note.strip() if request.note else None
    plan.schedule_cancelled_at = None
    plan.error_code = None
    plan.error_message = None
    plan.updated_by = actor_user_id
    plan.row_version += 1
    if plan.workflow_status in {
        "READY_TO_PUBLISH",
        "PUBLISH_FAILED",
        "AWAITING_PUBLISH_AUTHORIZATION",
    }:
        plan.workflow_status = "AWAITING_PUBLISH_AUTHORIZATION"

    await write_audit(
        session,
        action="erp_redemption_remote_plan.publish_planned",
        actor_user_id=actor_user_id,
        target_type="erp_redemption_remote_plan",
        target_id=plan.id,
        metadata={
            "mode": request.mode,
            "scheduled_publish_at": scheduled_utc.isoformat() if scheduled_utc else None,
            "business_timezone": ERP_BUSINESS_TIMEZONE,
            "fallback_to_scheduled": request.fallback_to_scheduled,
        },
    )
    await session.commit()
    return await _plan_response(session, plan)


async def cancel_local_erp_redemption_publish_schedule(
    session: AsyncSession,
    *,
    batch_id: str,
    request: ErpRedemptionRemoteScheduleCancelRequest,
    actor_user_id: int,
) -> ErpRedemptionRemotePlanResponse:
    plan = await _plan(session, batch_id, for_update=True)
    _check_version(plan, request.row_version)
    if plan.publish_mode != "SCHEDULED" or plan.scheduled_publish_at is None:
        raise ErpRedemptionRemotePlanConflictError("当前没有可取消的本地定时发布计划。")
    if plan.remote_publish_task_id or plan.workflow_status == "PUBLISH_SCHEDULED":
        raise ErpRedemptionRemotePlanConflictError(
            "远端定时任务已存在，必须另行授权远端取消操作。"
        )
    plan.publish_mode = None
    plan.scheduled_publish_at = None
    plan.schedule_cancelled_at = datetime.now(UTC)
    plan.publish_note = request.reason
    plan.updated_by = actor_user_id
    plan.row_version += 1
    if plan.workflow_status == "AWAITING_PUBLISH_AUTHORIZATION":
        plan.workflow_status = "READY_TO_PUBLISH"
    await write_audit(
        session,
        action="erp_redemption_remote_plan.local_schedule_cancelled",
        actor_user_id=actor_user_id,
        target_type="erp_redemption_remote_plan",
        target_id=plan.id,
        metadata={"reason": request.reason},
    )
    await session.commit()
    return await _plan_response(session, plan)


async def recover_erp_redemption_remote_plan(
    session: AsyncSession,
    *,
    batch_id: str,
    request: ErpRedemptionRemotePlanRecoverRequest,
    actor_user_id: int,
) -> ErpRedemptionRemotePlanResponse:
    plan = await _plan(session, batch_id, for_update=True)
    _check_version(plan, request.row_version)
    if plan.workflow_status not in {"CANCELLED", "CANCEL_FAILED"}:
        raise ErpRedemptionRemotePlanConflictError("只有已取消或取消失败的计划可以恢复。")
    if plan.reservation_id:
        raise ErpRedemptionRemotePlanConflictError("计划仍有远端操作保留，不能恢复。")
    issues = await _issues(session, batch_id)
    all_created = bool(issues) and all(
        issue.remote_configuration_id is not None for issue in issues
    )
    plan.workflow_status = "READY_TO_PUBLISH" if all_created else "AWAITING_CREATE_AUTHORIZATION"
    plan.publish_mode = None
    plan.scheduled_publish_at = None
    plan.remote_publish_task_id = None
    plan.schedule_cancelled_at = None
    plan.error_code = None
    plan.error_message = None
    plan.updated_by = actor_user_id
    plan.row_version += 1
    await write_audit(
        session,
        action="erp_redemption_remote_plan.recovered",
        actor_user_id=actor_user_id,
        target_type="erp_redemption_remote_plan",
        target_id=plan.id,
        metadata={"next_status": plan.workflow_status},
    )
    await session.commit()
    return await _plan_response(session, plan)


async def list_due_erp_redemption_publish_plans(
    session: AsyncSession,
) -> list[ErpRedemptionRemotePlanResponse]:
    now = datetime.now(UTC)
    plans = list(
        await session.scalars(
            select(ErpRedemptionRemotePlan)
            .where(
                ErpRedemptionRemotePlan.publish_mode == "SCHEDULED",
                ErpRedemptionRemotePlan.scheduled_publish_at <= now,
                ErpRedemptionRemotePlan.workflow_status
                == "AWAITING_PUBLISH_AUTHORIZATION",
                ErpRedemptionRemotePlan.reservation_id.is_(None),
            )
            .order_by(ErpRedemptionRemotePlan.scheduled_publish_at.asc())
        )
    )
    return [await _plan_response(session, plan) for plan in plans]


async def list_erp_redemption_remote_executions(
    session: AsyncSession,
    *,
    batch_id: str,
) -> list[ErpRedemptionRemoteExecutionResponse]:
    plan = await _plan(session, batch_id)
    executions = list(
        await session.scalars(
            select(ErpRedemptionRemoteExecution)
            .where(ErpRedemptionRemoteExecution.plan_id == plan.id)
            .order_by(ErpRedemptionRemoteExecution.requested_at.desc())
        )
    )
    return [_execution_response(execution) for execution in executions]


async def reserve_erp_redemption_remote_execution(
    session: AsyncSession,
    *,
    batch_id: str,
    operation: ErpRedemptionRemoteOperation,
    issue_id: str | None,
    trigger_type: str,
    execution_authorized: bool,
    actor_user_id: int,
) -> ErpRemoteExecutionReservation:
    """Reserve a single adapter action after the two-layer gate passes.

    This function is deliberately not exposed by an API route in this phase.
    """

    plan = await _plan(session, batch_id, for_update=True)
    if trigger_type not in {"MANUAL", "SCHEDULED"}:
        raise ErpRedemptionRemotePlanError("不支持的远端操作触发类型。")
    if plan.reservation_id:
        raise ErpRedemptionRemotePlanConflictError("该批次已有远端操作正在保留或执行。")
    grant = await authorize_erp_redemption_remote_execution(
        session,
        account_id=plan.remote_account_id,
        operation=operation,
        execution_authorized=execution_authorized,
    )
    issues = await _issues(session, batch_id)
    issue = next((item for item in issues if item.id == issue_id), None)

    if operation in {"CREATE", "DOWNLOAD"} and issue is None:
        raise ErpRedemptionRemotePlanError("单条远端创建或下载必须指定本批次任务。")
    if operation == "CREATE":
        if plan.workflow_status not in {
            "AWAITING_CREATE_AUTHORIZATION",
            "CREATE_FAILED",
        } or issue.remote_workflow_status not in {"NOT_STARTED", "FAILED"}:
            raise ErpRedemptionRemotePlanConflictError("当前状态不能保留远端创建操作。")
    elif operation == "PUBLISH":
        if plan.workflow_status not in {
            "READY_TO_PUBLISH",
            "AWAITING_PUBLISH_AUTHORIZATION",
            "PUBLISH_FAILED",
        } or not issues or any(item.remote_workflow_status != "CREATED" for item in issues):
            raise ErpRedemptionRemotePlanConflictError("全部远端配置创建成功后才能发布。")
        if plan.publish_mode is None:
            raise ErpRedemptionRemotePlanConflictError("请先保存立即或定时发布计划。")
    elif operation == "DOWNLOAD":
        scheduled_due = bool(
            plan.publish_mode == "SCHEDULED"
            and (scheduled := _aware_utc(plan.scheduled_publish_at)) is not None
            and scheduled <= datetime.now(UTC)
        )
        if plan.workflow_status not in {"PUBLISHED", "DOWNLOAD_FAILED"} and not (
            plan.workflow_status == "PUBLISH_SCHEDULED" and scheduled_due
        ):
            raise ErpRedemptionRemotePlanConflictError("远端发布成功后才能下载兑换码。")
        if not issue.remote_configuration_id or issue.remote_workflow_status not in {
            "PUBLISHED",
            "FAILED",
        } | ({"CREATED"} if scheduled_due else set()):
            raise ErpRedemptionRemotePlanConflictError("该任务当前不能下载远端兑换码。")
    elif operation == "CANCEL":
        if plan.workflow_status != "PUBLISH_SCHEDULED" or not plan.remote_publish_task_id:
            raise ErpRedemptionRemotePlanConflictError("当前没有可远端取消的定时发布任务。")

    attempt_number = (
        await session.scalar(
            select(func.max(ErpRedemptionRemoteExecution.attempt_number)).where(
                ErpRedemptionRemoteExecution.plan_id == plan.id,
                ErpRedemptionRemoteExecution.operation == operation,
            )
        )
        or 0
    ) + 1
    reservation_id = str(uuid.uuid4())
    execution = ErpRedemptionRemoteExecution(
        plan_id=plan.id,
        issue_id=issue.id if issue else None,
        operation=operation,
        trigger_type=trigger_type,
        status="RESERVED",
        attempt_number=attempt_number,
        reservation_id=reservation_id,
        scheduled_for=plan.scheduled_publish_at if operation == "PUBLISH" else None,
        requested_by=actor_user_id,
    )
    session.add(execution)
    plan.reservation_id = reservation_id
    plan.reserved_operation = operation
    plan.updated_by = actor_user_id
    plan.row_version += 1
    plan.workflow_status = {
        "CREATE": "CREATING",
        "PUBLISH": "PUBLISHING",
        "DOWNLOAD": "DOWNLOADING",
        "CANCEL": "CANCEL_PENDING",
    }[operation]
    if issue is not None:
        issue.remote_workflow_status = "RESERVED"
        issue.remote_error_code = None
        issue.remote_error_message = None
        issue.row_version += 1
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ErpRedemptionRemotePlanConflictError(
            "远端操作已被其他请求保留，请刷新后重试。"
        ) from exc
    await write_audit(
        session,
        action="erp_redemption_remote_execution.reserved",
        actor_user_id=actor_user_id,
        target_type="erp_redemption_remote_execution",
        target_id=execution.id,
        metadata={
            "batch_id": batch_id,
            "issue_id": issue.id if issue else None,
            "operation": operation,
            "trigger_type": trigger_type,
            "attempt_number": attempt_number,
        },
    )
    await session.commit()
    return ErpRemoteExecutionReservation(
        reservation_id=reservation_id,
        execution=_execution_response(execution),
        grant=grant,
    )


async def mark_erp_redemption_remote_execution_running(
    session: AsyncSession,
    *,
    reservation_id: str,
) -> ErpRedemptionRemoteExecutionResponse:
    execution = await session.scalar(
        select(ErpRedemptionRemoteExecution)
        .where(ErpRedemptionRemoteExecution.reservation_id == reservation_id)
        .with_for_update()
    )
    if execution is None or execution.status != "RESERVED":
        raise ErpRedemptionRemotePlanConflictError("远端执行保留不存在或已被处理。")
    execution.status = "RUNNING"
    execution.started_at = datetime.now(UTC)
    if execution.issue_id:
        issue = await session.get(ErpRedemptionCodeIssue, execution.issue_id)
        if issue is not None:
            issue.remote_workflow_status = (
                "CREATING" if execution.operation == "CREATE" else "DOWNLOADING"
            )
    await session.commit()
    return _execution_response(execution)


async def complete_erp_redemption_remote_execution(
    session: AsyncSession,
    *,
    reservation_id: str,
    result: (
        RemoteCreateResult
        | RemotePublishResult
        | RemoteDownloadResult
        | RemoteCancelPublishResult
    ),
) -> ErpRedemptionRemotePlanResponse:
    execution = await session.scalar(
        select(ErpRedemptionRemoteExecution)
        .where(ErpRedemptionRemoteExecution.reservation_id == reservation_id)
        .with_for_update()
    )
    if execution is None or execution.status not in {"RESERVED", "RUNNING"}:
        raise ErpRedemptionRemotePlanConflictError("远端执行保留不存在或已完成。")
    plan = await session.scalar(
        select(ErpRedemptionRemotePlan)
        .where(ErpRedemptionRemotePlan.id == execution.plan_id)
        .with_for_update()
    )
    if plan is None or plan.reservation_id != reservation_id:
        raise ErpRedemptionRemotePlanConflictError("远端执行保留与计划状态不一致。")
    issues = await _issues(session, plan.batch_id)
    issue = next((item for item in issues if item.id == execution.issue_id), None)
    now = datetime.now(UTC)
    metadata: dict[str, object] = {}

    if execution.operation == "CREATE" and isinstance(result, RemoteCreateResult):
        if issue is None:
            raise ErpRedemptionRemotePlanConflictError("远端创建执行缺少任务记录。")
        remote_configuration_id = result.remote_configuration_id.strip()
        if not remote_configuration_id:
            raise ErpRedemptionRemotePlanError("远端创建结果缺少配置标识。")
        issue.remote_configuration_id = remote_configuration_id
        issue.remote_group_key = result.remote_group_key
        issue.remote_workflow_status = "CREATED"
        issue.remote_created_at = now
        issue.remote_error_code = None
        issue.remote_error_message = None
        issue.row_version += 1
        all_created = all(item.remote_workflow_status == "CREATED" for item in issues)
        plan.workflow_status = (
            "AWAITING_PUBLISH_AUTHORIZATION"
            if all_created and plan.publish_mode
            else "READY_TO_PUBLISH"
            if all_created
            else "AWAITING_CREATE_AUTHORIZATION"
        )
        execution.remote_request_id = result.remote_request_id
        metadata = {"remote_configuration_recorded": True}
    elif execution.operation == "PUBLISH" and isinstance(result, RemotePublishResult):
        remote_publish_task_id = result.remote_publish_task_id.strip()
        if not remote_publish_task_id:
            raise ErpRedemptionRemotePlanError("远端发布结果缺少任务标识。")
        plan.remote_publish_task_id = remote_publish_task_id
        plan.scheduled_publish_at = result.scheduled_publish_at or plan.scheduled_publish_at
        execution.remote_request_id = result.remote_request_id
        scheduled = plan.publish_mode == "SCHEDULED" and plan.scheduled_publish_at is not None
        plan.workflow_status = "PUBLISH_SCHEDULED" if scheduled else "PUBLISHED"
        if not scheduled:
            for item in issues:
                if item.remote_workflow_status == "CREATED":
                    item.remote_workflow_status = "PUBLISHED"
                    item.row_version += 1
        metadata = {"scheduled": scheduled}
    elif execution.operation == "DOWNLOAD" and isinstance(result, RemoteDownloadResult):
        if issue is None:
            raise ErpRedemptionRemotePlanConflictError("远端下载执行缺少任务记录。")
        redemption_code = result.redemption_code.strip()
        if not redemption_code:
            raise ErpRedemptionRemotePlanError("远端下载结果没有兑换码。")
        issue.redemption_code = redemption_code
        issue.remote_group_key = result.remote_group_key or issue.remote_group_key
        issue.remote_workflow_status = "DOWNLOADED"
        issue.workflow_status = "CODE_IMPORTED"
        issue.state = "GENERATED"
        issue.imported_at = now
        issue.remote_downloaded_at = now
        issue.remote_error_code = None
        issue.remote_error_message = None
        issue.row_version += 1
        execution.remote_request_id = result.remote_request_id
        plan.workflow_status = (
            "COMPLETED"
            if all(item.remote_workflow_status == "DOWNLOADED" for item in issues)
            else "PUBLISHED"
        )
        metadata = {"redemption_code_recorded": True}
    elif execution.operation == "CANCEL" and isinstance(result, RemoteCancelPublishResult):
        plan.workflow_status = "CANCELLED"
        plan.schedule_cancelled_at = now
        execution.remote_request_id = result.remote_request_id
        metadata = {"remote_schedule_cancelled": True}
    else:
        raise ErpRedemptionRemotePlanError("远端执行结果类型与保留操作不匹配。")

    execution.status = "SUCCEEDED"
    execution.finished_at = now
    execution.result_metadata_json = metadata
    plan.reservation_id = None
    plan.reserved_operation = None
    plan.error_code = None
    plan.error_message = None
    plan.row_version += 1
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ErpRedemptionRemotePlanConflictError(
            "远端标识或兑换码已被其他任务登记。"
        ) from exc
    await write_audit(
        session,
        action="erp_redemption_remote_execution.succeeded",
        actor_user_id=execution.requested_by,
        target_type="erp_redemption_remote_execution",
        target_id=execution.id,
        metadata={
            "batch_id": plan.batch_id,
            "issue_id": execution.issue_id,
            "operation": execution.operation,
            **metadata,
        },
    )
    await session.commit()
    return await _plan_response(session, plan)


async def fail_erp_redemption_remote_execution(
    session: AsyncSession,
    *,
    reservation_id: str,
    error_code: str,
    error_message: str,
) -> ErpRedemptionRemotePlanResponse:
    execution = await session.scalar(
        select(ErpRedemptionRemoteExecution)
        .where(ErpRedemptionRemoteExecution.reservation_id == reservation_id)
        .with_for_update()
    )
    if execution is None or execution.status not in {"RESERVED", "RUNNING"}:
        raise ErpRedemptionRemotePlanConflictError("远端执行保留不存在或已完成。")
    plan = await session.scalar(
        select(ErpRedemptionRemotePlan)
        .where(ErpRedemptionRemotePlan.id == execution.plan_id)
        .with_for_update()
    )
    if plan is None or plan.reservation_id != reservation_id:
        raise ErpRedemptionRemotePlanConflictError("远端执行保留与计划状态不一致。")
    safe_code = error_code.strip()[:80] or "REMOTE_OPERATION_FAILED"
    safe_message = error_message.strip()[:500] or "远端操作失败。"
    execution.status = "FAILED"
    execution.error_code = safe_code
    execution.error_message = safe_message
    execution.finished_at = datetime.now(UTC)
    plan.workflow_status = {
        "CREATE": "CREATE_FAILED",
        "PUBLISH": "PUBLISH_FAILED",
        "DOWNLOAD": "DOWNLOAD_FAILED",
        "CANCEL": "CANCEL_FAILED",
    }[execution.operation]
    plan.error_code = safe_code
    plan.error_message = safe_message
    plan.reservation_id = None
    plan.reserved_operation = None
    plan.row_version += 1
    if execution.issue_id:
        issue = await session.get(ErpRedemptionCodeIssue, execution.issue_id)
        if issue is not None:
            issue.remote_workflow_status = "FAILED"
            issue.remote_error_code = safe_code
            issue.remote_error_message = safe_message
            issue.row_version += 1
    await write_audit(
        session,
        action="erp_redemption_remote_execution.failed",
        actor_user_id=execution.requested_by,
        target_type="erp_redemption_remote_execution",
        target_id=execution.id,
        result="failure",
        metadata={
            "batch_id": plan.batch_id,
            "issue_id": execution.issue_id,
            "operation": execution.operation,
            "error_code": safe_code,
        },
    )
    await session.commit()
    return await _plan_response(session, plan)
