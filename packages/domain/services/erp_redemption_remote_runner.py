"""Explicitly authorised execution runner for migrated ERP redemption jobs.

Nothing imports or schedules this runner in the application today.  A future
API/worker entry point must pass ``execution_authorized=True`` for the exact
operation after obtaining user approval; the reservation gate and account
capability are then checked again before credentials are decrypted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings
from packages.domain.models import (
    ErpRedemptionCodeIssue,
    ErpRedemptionRemotePlan,
    RemoteAccount,
    SourceConfig,
)
from packages.domain.services.erp_redemption_remote_adapter import (
    RemoteCancelPublishCommand,
    RemoteCreateCommand,
    RemoteCreationOptions,
    RemoteDownloadCommand,
    RemotePublishCommand,
)
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    RajAdminGiftCodeAdapter,
)
from packages.domain.services.erp_redemption_remote_plan_service import (
    ERP_BUSINESS_TIMEZONE,
    ErpRedemptionRemotePlanError,
    complete_erp_redemption_remote_execution,
    fail_erp_redemption_remote_execution,
    mark_erp_redemption_remote_execution_running,
    reserve_erp_redemption_remote_execution,
)
from packages.domain.services.remote_account_credentials import (
    RemoteAccountCredentialsError,
    credential_envelope_for_account,
    decrypt_remote_account_credentials,
)
from packages.domain.services.remote_account_session_service import account_session


class ErpRedemptionRemoteRunnerError(ValueError):
    pass


def _credentials(
    account: RemoteAccount, source: SourceConfig, settings: Settings
) -> tuple[str, str, str]:
    envelope = credential_envelope_for_account(account=account, source=source)
    if envelope is None:
        raise ErpRedemptionRemoteRunnerError("统一远端账号凭据配置不完整。")
    try:
        values = decrypt_remote_account_credentials(envelope, settings=settings)
    except RemoteAccountCredentialsError as exc:
        raise ErpRedemptionRemoteRunnerError("统一远端账号凭据不可用。") from exc
    return values["username"], values["password"], values["totp_secret"]


def _options(plan: ErpRedemptionRemotePlan) -> RemoteCreationOptions:
    return RemoteCreationOptions(
        publish_environment=plan.publish_environment,
        flow_times=plan.flow_times,
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
    )


async def execute_erp_redemption_remote_operation(
    session: AsyncSession,
    *,
    batch_id: str,
    operation: str,
    issue_id: str | None,
    trigger_type: str,
    execution_authorized: bool,
    actor_user_id: int,
    settings: Settings,
    transport=None,
):
    """Execute one reserved operation; never called by an HTTP route implicitly."""

    reservation = await reserve_erp_redemption_remote_execution(
        session,
        batch_id=batch_id,
        operation=operation,
        issue_id=issue_id,
        trigger_type=trigger_type,
        execution_authorized=execution_authorized,
        actor_user_id=actor_user_id,
    )
    await mark_erp_redemption_remote_execution_running(
        session, reservation_id=reservation.reservation_id
    )
    execution = reservation.execution
    try:
        plan = await session.get(ErpRedemptionRemotePlan, execution.plan_id)
        if plan is None:
            raise ErpRedemptionRemoteRunnerError("远端编排计划不存在。")
        account = await session.get(RemoteAccount, plan.remote_account_id)
        source = await session.get(SourceConfig, reservation.grant.source_id)
        if account is None or source is None or not source.base_url:
            raise ErpRedemptionRemoteRunnerError("统一远端账号或盘口配置不可用。")
        username, password, totp_secret = _credentials(account, source, settings)
        envelope = credential_envelope_for_account(account=account, source=source)
        async with RajAdminGiftCodeAdapter(
            remote_session=account_session(
                session, envelope=envelope, base_url=source.base_url, settings=settings
            ),
            account_id=account.id,
            source_id=source.source_id,
            base_url=source.base_url,
            username=username,
            password=password,
            totp_secret=totp_secret,
            business_timezone=ERP_BUSINESS_TIMEZONE,
            transport=transport,
        ) as adapter:
            if operation == "CREATE":
                issue = await session.get(ErpRedemptionCodeIssue, issue_id or "")
                if issue is None:
                    raise ErpRedemptionRemoteRunnerError("远端创建任务不存在。")
                result = await adapter.create_configuration(
                    grant=reservation.grant,
                    command=RemoteCreateCommand(
                        issue_id=issue.id,
                        description=issue.remote_description or issue.tier_name or issue.id,
                        claim_date=issue.claim_date,
                        deposit_window_start=issue.deposit_window_start,
                        deposit_window_end=issue.deposit_window_end,
                        label_ids=tuple(issue.remote_label_ids_json),
                        bonus_amount=issue.bonus_amount,
                        bonus_max_amount=issue.bonus_max_amount,
                        options=_options(plan),
                    ),
                )
            elif operation == "PUBLISH":
                command = RemotePublishCommand(
                    publish_environment=plan.publish_environment,
                    mode=plan.publish_mode or "IMMEDIATE",
                    scheduled_publish_at=plan.scheduled_publish_at,
                    fallback_to_scheduled=plan.fallback_to_scheduled,
                )
                try:
                    result = await adapter.publish(grant=reservation.grant, command=command)
                except ErpRedemptionRemoteHttpError:
                    if command.mode != "IMMEDIATE" or not command.fallback_to_scheduled:
                        raise
                    last_error: ErpRedemptionRemoteHttpError | None = None
                    for minutes in (15, 30, 60):
                        try:
                            fallback = RemotePublishCommand(
                                publish_environment=plan.publish_environment,
                                mode="SCHEDULED",
                                scheduled_publish_at=datetime.now(UTC) + timedelta(minutes=minutes),
                                fallback_to_scheduled=False,
                            )
                            result = await adapter.publish(
                                grant=reservation.grant, command=fallback
                            )
                            plan.publish_mode = "SCHEDULED"
                            plan.publish_note = (
                                f"立即发布失败，已自动回退至 {minutes} 分钟后定时发布。"
                            )
                            break
                        except ErpRedemptionRemoteHttpError as exc:
                            last_error = exc
                    else:
                        raise last_error or ErpRedemptionRemoteHttpError(
                            "立即发布及自动定时发布均失败。"
                        )
            elif operation == "DOWNLOAD":
                issue = await session.get(ErpRedemptionCodeIssue, issue_id or "")
                if issue is None or not issue.remote_configuration_id:
                    raise ErpRedemptionRemoteRunnerError("远端下载任务配置不完整。")
                result = await adapter.download(
                    grant=reservation.grant,
                    command=RemoteDownloadCommand(
                        issue_id=issue.id,
                        remote_configuration_id=issue.remote_configuration_id,
                        remote_group_key=issue.remote_group_key,
                    ),
                )
            elif operation == "CANCEL":
                if not plan.remote_publish_task_id:
                    raise ErpRedemptionRemoteRunnerError("远端定时发布任务标识不存在。")
                result = await adapter.cancel_publish(
                    grant=reservation.grant,
                    command=RemoteCancelPublishCommand(
                        remote_publish_task_id=plan.remote_publish_task_id
                    ),
                )
            else:
                raise ErpRedemptionRemoteRunnerError("不支持的远端兑换码操作。")
        return await complete_erp_redemption_remote_execution(
            session, reservation_id=reservation.reservation_id, result=result
        )
    except (ErpRedemptionRemoteHttpError, ErpRedemptionRemoteRunnerError) as exc:
        await fail_erp_redemption_remote_execution(
            session,
            reservation_id=reservation.reservation_id,
            error_code="REMOTE_OPERATION_FAILED",
            error_message=str(exc),
        )
        raise ErpRedemptionRemoteRunnerError(str(exc)) from exc
    except ErpRedemptionRemotePlanError:
        raise
    except Exception as exc:
        await fail_erp_redemption_remote_execution(
            session,
            reservation_id=reservation.reservation_id,
            error_code="REMOTE_OPERATION_FAILED",
            error_message="远端操作发生未预期错误。",
        )
        raise ErpRedemptionRemoteRunnerError("远端操作发生未预期错误。") from exc
