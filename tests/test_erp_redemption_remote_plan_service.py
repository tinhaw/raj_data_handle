from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import (
    AppUser,
    Base,
    ErpRedemptionCodeBatch,
    RemoteAccount,
    RemoteAccountCapability,
    RemoteAccountRewardTierPreset,
    SourceConfig,
)
from packages.domain.schemas.erp_redemption import (
    ErpRedemptionCampaignCreateRequest,
    ErpRedemptionTaskCreateRequest,
    ErpRedemptionTierWrite,
)
from packages.domain.schemas.erp_redemption_remote import (
    ErpRedemptionRemotePlanRecoverRequest,
    ErpRedemptionRemotePlanWrite,
    ErpRedemptionRemotePublishPlanRequest,
    ErpRedemptionRemoteScheduleCancelRequest,
    ErpRedemptionTaskRemotePlanWrite,
)
from packages.domain.services.erp_redemption_remote_adapter import (
    RemoteCancelPublishResult,
    RemoteCreateResult,
    RemoteDownloadResult,
    RemotePublishResult,
)
from packages.domain.services.erp_redemption_remote_gate import (
    ErpRemoteExecutionNotAuthorizedError,
)
from packages.domain.services.erp_redemption_remote_plan_service import (
    cancel_local_erp_redemption_publish_schedule,
    complete_erp_redemption_remote_execution,
    configure_erp_redemption_remote_plan,
    configure_erp_redemption_task_remote_plans,
    fail_erp_redemption_remote_execution,
    list_erp_redemption_remote_executions,
    mark_erp_redemption_remote_execution_running,
    plan_erp_redemption_remote_publish,
    recover_erp_redemption_remote_plan,
    reserve_erp_redemption_remote_execution,
)
from packages.domain.services.erp_redemption_service import (
    create_erp_redemption_campaign,
    create_erp_redemption_task,
    get_erp_redemption_batch,
)


async def _setup():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


async def _task_fixture(session):
    actor = AppUser(
        username="remote-plan-admin",
        username_normalized="remote-plan-admin",
        password_hash="not-used",
        display_name="Remote Plan Admin",
        role="admin",
    )
    source = SourceConfig(
        source_id="rajwin",
        display_name="RajWin",
        enabled=True,
        business_timezone="Asia/Kolkata",
    )
    account = RemoteAccount(
        source_id="rajwin",
        login_username="remote-operator",
        display_name="Remote Operator",
        enabled=True,
    )
    session.add_all([actor, source, account])
    await session.commit()
    campaign = await create_erp_redemption_campaign(
        session,
        actor_user_id=actor.id,
        request=ErpRedemptionCampaignCreateRequest(
            code="remote-stage",
            name="Remote Stage",
            tiers=[
                ErpRedemptionTierWrite(
                    display_name="100 tier",
                    min_deposit_amount=Decimal("100"),
                    bonus_amount=Decimal("10"),
                ),
                ErpRedemptionTierWrite(
                    display_name="500 tier",
                    min_deposit_amount=Decimal("500"),
                    bonus_amount=Decimal("50"),
                ),
            ],
        ),
    )
    task = await create_erp_redemption_task(
        session,
        actor_user_id=actor.id,
        request=ErpRedemptionTaskCreateRequest(
            campaign_id=campaign.id,
            task_name="Remote Workflow",
            claim_date_from=date(2026, 8, 20),
            claim_date_to=date(2026, 8, 20),
            remote_account_ids=[account.id],
        ),
    )
    return actor, account, campaign, task.subtasks[0].batch_id


@pytest.mark.asyncio
async def test_remote_plan_tracks_create_publish_cancel_without_network_calls() -> None:
    engine, factory = await _setup()
    try:
        async with factory() as session:
            actor, account, campaign, batch_id = await _task_fixture(session)
            labels = {
                campaign.tiers[0].id: [901091],
                campaign.tiers[1].id: [901092, 901093],
            }
            plan = await configure_erp_redemption_remote_plan(
                session,
                batch_id=batch_id,
                actor_user_id=actor.id,
                request=ErpRedemptionRemotePlanWrite(tier_label_ids=labels),
            )
            assert plan.workflow_status == "AWAITING_CREATE_AUTHORIZATION"
            assert plan.issue_count == 2

            scheduled_local = (datetime.now() + timedelta(days=2)).replace(microsecond=0)
            plan = await plan_erp_redemption_remote_publish(
                session,
                batch_id=batch_id,
                actor_user_id=actor.id,
                request=ErpRedemptionRemotePublishPlanRequest(
                    mode="SCHEDULED",
                    scheduled_local_at=scheduled_local,
                    row_version=plan.row_version,
                ),
            )
            assert plan.scheduled_publish_local_at == scheduled_local

            detail = await get_erp_redemption_batch(session, batch_id=batch_id)
            with pytest.raises(ErpRemoteExecutionNotAuthorizedError, match="明确执行授权"):
                await reserve_erp_redemption_remote_execution(
                    session,
                    batch_id=batch_id,
                    operation="CREATE",
                    issue_id=detail.issues[0].id,
                    trigger_type="MANUAL",
                    execution_authorized=False,
                    actor_user_id=actor.id,
                )

            session.add_all(
                [
                    RemoteAccountCapability(
                        account_id=account.id,
                        capability=capability,
                        enabled=True,
                    )
                    for capability in (
                        "ERP_REDEMPTION_CREATE",
                        "ERP_REDEMPTION_PUBLISH",
                        "ERP_REDEMPTION_CANCEL",
                    )
                ]
            )
            await session.commit()

            for index, issue in enumerate(detail.issues, start=1):
                reservation = await reserve_erp_redemption_remote_execution(
                    session,
                    batch_id=batch_id,
                    operation="CREATE",
                    issue_id=issue.id,
                    trigger_type="MANUAL",
                    execution_authorized=True,
                    actor_user_id=actor.id,
                )
                await mark_erp_redemption_remote_execution_running(
                    session,
                    reservation_id=reservation.reservation_id,
                )
                plan = await complete_erp_redemption_remote_execution(
                    session,
                    reservation_id=reservation.reservation_id,
                    result=RemoteCreateResult(
                        remote_configuration_id=f"remote-config-{index}",
                        remote_group_key="remote-group",
                        remote_request_id=f"create-request-{index}",
                    ),
                )

            assert plan.workflow_status == "AWAITING_PUBLISH_AUTHORIZATION"
            assert plan.created_count == 2
            publish_reservation = await reserve_erp_redemption_remote_execution(
                session,
                batch_id=batch_id,
                operation="PUBLISH",
                issue_id=None,
                trigger_type="MANUAL",
                execution_authorized=True,
                actor_user_id=actor.id,
            )
            plan = await complete_erp_redemption_remote_execution(
                session,
                reservation_id=publish_reservation.reservation_id,
                result=RemotePublishResult(
                    remote_publish_task_id="publish-task-1",
                    scheduled_publish_at=plan.scheduled_publish_at,
                    remote_request_id="publish-request-1",
                ),
            )
            assert plan.workflow_status == "PUBLISH_SCHEDULED"

            cancel_reservation = await reserve_erp_redemption_remote_execution(
                session,
                batch_id=batch_id,
                operation="CANCEL",
                issue_id=None,
                trigger_type="MANUAL",
                execution_authorized=True,
                actor_user_id=actor.id,
            )
            plan = await complete_erp_redemption_remote_execution(
                session,
                reservation_id=cancel_reservation.reservation_id,
                result=RemoteCancelPublishResult(remote_request_id="cancel-request-1"),
            )
            assert plan.workflow_status == "CANCELLED"
            plan = await recover_erp_redemption_remote_plan(
                session,
                batch_id=batch_id,
                actor_user_id=actor.id,
                request=ErpRedemptionRemotePlanRecoverRequest(
                    row_version=plan.row_version
                ),
            )
            assert plan.workflow_status == "READY_TO_PUBLISH"
            executions = await list_erp_redemption_remote_executions(
                session,
                batch_id=batch_id,
            )
            assert len(executions) == 4
            assert {execution.status for execution in executions} == {"SUCCEEDED"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_task_remote_plans_are_configured_from_unified_account_preset() -> None:
    engine, factory = await _setup()
    try:
        async with factory() as session:
            actor, account, campaign, batch_id = await _task_fixture(session)
            session.add(
                RemoteAccountRewardTierPreset(
                    account_id=account.id,
                    tiers_json=[
                        {
                            "display_name": tier.display_name,
                            "min_deposit_amount": str(tier.min_deposit_amount),
                            "bonus_amount": str(tier.bonus_amount),
                            "bonus_max_amount": str(tier.bonus_max_amount),
                            "label_ids": [901091 + index],
                        }
                        for index, tier in enumerate(campaign.tiers)
                    ],
                    tag_snapshot_json=[
                        {"id": 901091, "name": "Tier 100"},
                        {"id": 901092, "name": "Tier 500"},
                    ],
                    saved_by=actor.id,
                )
            )
            await session.commit()

            batch = await session.get(ErpRedemptionCodeBatch, batch_id)
            plans = await configure_erp_redemption_task_remote_plans(
                session,
                task_id=batch.task_id,
                request=ErpRedemptionTaskRemotePlanWrite(
                    redemption_type="SEVEN_DAY_DEPOSIT",
                    publish_environment="test",
                ),
                actor_user_id=actor.id,
            )
            assert len(plans) == 1
            assert plans[0].batch_id == batch_id
            detail = await get_erp_redemption_batch(session, batch_id=batch_id)
            assert [issue.remote_label_ids for issue in detail.issues] == [[901091], [901092]]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_remote_plan_failure_retry_and_download_completion_are_recoverable() -> None:
    engine, factory = await _setup()
    try:
        async with factory() as session:
            actor, account, campaign, batch_id = await _task_fixture(session)
            plan = await configure_erp_redemption_remote_plan(
                session,
                batch_id=batch_id,
                actor_user_id=actor.id,
                request=ErpRedemptionRemotePlanWrite(
                    tier_label_ids={
                        tier.id: [902000 + index]
                        for index, tier in enumerate(campaign.tiers)
                    }
                ),
            )
            session.add_all(
                [
                    RemoteAccountCapability(
                        account_id=account.id,
                        capability=capability,
                        enabled=True,
                    )
                    for capability in (
                        "ERP_REDEMPTION_CREATE",
                        "ERP_REDEMPTION_PUBLISH",
                        "ERP_REDEMPTION_DOWNLOAD",
                    )
                ]
            )
            await session.commit()
            detail = await get_erp_redemption_batch(session, batch_id=batch_id)
            for index, issue in enumerate(detail.issues, start=1):
                reservation = await reserve_erp_redemption_remote_execution(
                    session,
                    batch_id=batch_id,
                    operation="CREATE",
                    issue_id=issue.id,
                    trigger_type="MANUAL",
                    execution_authorized=True,
                    actor_user_id=actor.id,
                )
                plan = await complete_erp_redemption_remote_execution(
                    session,
                    reservation_id=reservation.reservation_id,
                    result=RemoteCreateResult(
                        remote_configuration_id=f"download-config-{index}"
                    ),
                )

            plan = await plan_erp_redemption_remote_publish(
                session,
                batch_id=batch_id,
                actor_user_id=actor.id,
                request=ErpRedemptionRemotePublishPlanRequest(
                    mode="IMMEDIATE",
                    row_version=plan.row_version,
                ),
            )
            publish = await reserve_erp_redemption_remote_execution(
                session,
                batch_id=batch_id,
                operation="PUBLISH",
                issue_id=None,
                trigger_type="MANUAL",
                execution_authorized=True,
                actor_user_id=actor.id,
            )
            plan = await complete_erp_redemption_remote_execution(
                session,
                reservation_id=publish.reservation_id,
                result=RemotePublishResult(remote_publish_task_id="immediate-publish"),
            )
            assert plan.workflow_status == "PUBLISHED"

            first_download = await reserve_erp_redemption_remote_execution(
                session,
                batch_id=batch_id,
                operation="DOWNLOAD",
                issue_id=detail.issues[0].id,
                trigger_type="MANUAL",
                execution_authorized=True,
                actor_user_id=actor.id,
            )
            plan = await fail_erp_redemption_remote_execution(
                session,
                reservation_id=first_download.reservation_id,
                error_code="REMOTE_TIMEOUT",
                error_message="test timeout",
            )
            assert plan.workflow_status == "DOWNLOAD_FAILED"

            for index, issue in enumerate(detail.issues, start=1):
                download = await reserve_erp_redemption_remote_execution(
                    session,
                    batch_id=batch_id,
                    operation="DOWNLOAD",
                    issue_id=issue.id,
                    trigger_type="MANUAL",
                    execution_authorized=True,
                    actor_user_id=actor.id,
                )
                plan = await complete_erp_redemption_remote_execution(
                    session,
                    reservation_id=download.reservation_id,
                    result=RemoteDownloadResult(
                        redemption_code=f"DOWNLOADED-{index}"
                    ),
                )
            assert plan.workflow_status == "COMPLETED"
            assert plan.downloaded_count == 2
            refreshed = await get_erp_redemption_batch(session, batch_id=batch_id)
            assert refreshed.batch.imported_code_count == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_local_schedule_can_be_cancelled_before_any_remote_publish_exists() -> None:
    engine, factory = await _setup()
    try:
        async with factory() as session:
            actor, _, campaign, batch_id = await _task_fixture(session)
            plan = await configure_erp_redemption_remote_plan(
                session,
                batch_id=batch_id,
                actor_user_id=actor.id,
                request=ErpRedemptionRemotePlanWrite(
                    tier_label_ids={
                        tier.id: [901000 + index]
                        for index, tier in enumerate(campaign.tiers)
                    }
                ),
            )
            plan = await plan_erp_redemption_remote_publish(
                session,
                batch_id=batch_id,
                actor_user_id=actor.id,
                request=ErpRedemptionRemotePublishPlanRequest(
                    mode="SCHEDULED",
                    scheduled_local_at=(datetime.now() + timedelta(days=1)).replace(
                        microsecond=0
                    ),
                    row_version=plan.row_version,
                ),
            )
            cancelled = await cancel_local_erp_redemption_publish_schedule(
                session,
                batch_id=batch_id,
                actor_user_id=actor.id,
                request=ErpRedemptionRemoteScheduleCancelRequest(
                    row_version=plan.row_version,
                    reason="运营调整计划",
                ),
            )
            assert cancelled.publish_mode is None
            assert cancelled.scheduled_publish_at is None
            assert cancelled.schedule_cancelled_at is not None
            assert await list_erp_redemption_remote_executions(
                session,
                batch_id=batch_id,
            ) == []
    finally:
        await engine.dispose()
