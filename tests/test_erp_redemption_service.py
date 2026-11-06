from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.routers.erp_redemption import _export_task_bytes
from packages.domain.models import AppUser, Base, RemoteAccount, SourceConfig
from packages.domain.schemas.erp_redemption import (
    ErpRedemptionBatchCreateRequest,
    ErpRedemptionCampaignCreateRequest,
    ErpRedemptionCodeImportRequest,
    ErpRedemptionCodeInput,
    ErpRedemptionTaskCreateRequest,
    ErpRedemptionTierWrite,
)
from packages.domain.services.erp_redemption_service import (
    create_erp_redemption_batch,
    create_erp_redemption_campaign,
    create_erp_redemption_task,
    get_erp_redemption_batch,
    import_erp_redemption_codes,
    list_erp_redemption_campaigns,
    publish_erp_redemption_batch_locally,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _actor_id(session) -> int:
    actor = AppUser(
        username="erp-redemption-admin",
        username_normalized="erp-redemption-admin",
        password_hash="not-used-in-this-test",
        display_name="ERP Redemption Admin",
        role="admin",
    )
    session.add(actor)
    await session.commit()
    return actor.id


@pytest.mark.asyncio
@pytest.mark.parametrize("threshold", [Decimal("0"), Decimal("100")])
async def test_same_threshold_tiers_remain_distinct_after_batch_readback(threshold) -> None:
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            actor_id = await _actor_id(session)
            campaign = await create_erp_redemption_campaign(
                session,
                actor_user_id=actor_id,
                request=ErpRedemptionCampaignCreateRequest(
                    code="shared-threshold",
                    name="Independent reward tiers",
                    tiers=[
                        ErpRedemptionTierWrite(
                            display_name=name,
                            min_deposit_amount=threshold,
                            bonus_amount=Decimal("5"),
                            bonus_max_amount=maximum,
                            sort_order=index,
                        )
                        for index, (name, maximum) in enumerate(
                            [("All users", Decimal("7")), ("Game count zero", Decimal("17"))],
                            start=1,
                        )
                    ],
                ),
            )
            assert len({tier.id for tier in campaign.tiers}) == 2
            stored = (await list_erp_redemption_campaigns(session))[0]
            assert [(tier.display_name, tier.sort_order) for tier in stored.tiers] == [
                ("All users", 1),
                ("Game count zero", 2),
            ]
            detail = await create_erp_redemption_batch(
                session,
                actor_user_id=actor_id,
                request=ErpRedemptionBatchCreateRequest(
                    campaign_id=campaign.id,
                    claim_date_from=date(2026, 11, 1),
                    claim_date_to=date(2026, 11, 2),
                ),
            )
        async with factory() as session:
            reloaded = await get_erp_redemption_batch(session, batch_id=detail.batch.id)
            assert reloaded.batch.expected_code_count == 4
            assert len(reloaded.issues) == 4
            by_tier = {tier.id: tier for tier in campaign.tiers}
            for issue in reloaded.issues:
                tier = by_tier[issue.campaign_tier_id]
                assert issue.min_deposit_amount == threshold
                assert issue.tier_name == tier.display_name
                assert issue.bonus_amount == tier.bonus_amount
                assert issue.bonus_max_amount == tier.bonus_max_amount
            assert {issue.campaign_tier_id for issue in reloaded.issues} == set(by_tier)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_local_redemption_campaign_batch_code_import_and_publish() -> None:
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            actor_id = await _actor_id(session)
            campaign = await create_erp_redemption_campaign(
                session,
                actor_user_id=actor_id,
                request=ErpRedemptionCampaignCreateRequest(
                    code="aug-2026",
                    name="August Reward",
                    lookback_days=7,
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
                            bonus_max_amount=Decimal("60"),
                        ),
                    ],
                ),
            )
            assert campaign.code == "AUG-2026"
            batch_detail = await create_erp_redemption_batch(
                session,
                actor_user_id=actor_id,
                request=ErpRedemptionBatchCreateRequest(
                    campaign_id=campaign.id,
                    claim_date_from=date(2026, 8, 1),
                    claim_date_to=date(2026, 8, 2),
                ),
            )
            assert batch_detail.batch.expected_code_count == 4
            assert batch_detail.issues[0].deposit_window_start == date(2026, 7, 25)

            imported = await import_erp_redemption_codes(
                session,
                batch_id=batch_detail.batch.id,
                actor_user_id=actor_id,
                request=ErpRedemptionCodeImportRequest(
                    rows=[
                        ErpRedemptionCodeInput(
                            issue_id=issue.id,
                            redemption_code=f"LOCAL-{index}",
                            row_version=issue.row_version,
                        )
                        for index, issue in enumerate(batch_detail.issues, start=1)
                    ]
                ),
            )
            assert imported.batch.status == "READY_LOCAL"
            assert imported.batch.imported_code_count == 4

            published = await publish_erp_redemption_batch_locally(
                session,
                batch_id=imported.batch.id,
                row_version=imported.batch.row_version,
                actor_user_id=actor_id,
            )
            assert published.batch.status == "PUBLISHED_LOCAL"
            assert {issue.workflow_status for issue in published.issues} == {"PUBLISHED_LOCAL"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_redemption_task_creates_ordered_local_market_subtasks() -> None:
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            actor_id = await _actor_id(session)
            session.add_all(
                [
                    SourceConfig(source_id="rajwin", display_name="RajWin", enabled=True),
                    SourceConfig(source_id="rajluck", display_name="RajLuck", enabled=True),
                ]
            )
            await session.flush()
            accounts = [
                RemoteAccount(
                    source_id="rajwin", login_username="win", display_name="Win Account"
                ),
                RemoteAccount(
                    source_id="rajluck", login_username="luck", display_name="Luck Account"
                ),
            ]
            session.add_all(accounts)
            await session.commit()
            campaign = await create_erp_redemption_campaign(
                session,
                actor_user_id=actor_id,
                request=ErpRedemptionCampaignCreateRequest(
                    code="task-2026",
                    name="Task Reward",
                    tiers=[
                        ErpRedemptionTierWrite(
                            min_deposit_amount=Decimal("100"),
                            bonus_amount=Decimal("10"),
                        )
                    ],
                ),
            )
            task = await create_erp_redemption_task(
                session,
                actor_user_id=actor_id,
                request=ErpRedemptionTaskCreateRequest(
                    campaign_id=campaign.id,
                    task_name="双盘口任务",
                    claim_date_from=date(2026, 8, 1),
                    claim_date_to=date(2026, 8, 2),
                    remote_account_ids=[accounts[1].id, accounts[0].id],
                ),
            )
            assert task.expected_code_count == 4
            assert [(item.execution_order, item.source_id) for item in task.subtasks] == [
                (1, "rajluck"),
                (2, "rajwin"),
            ]
            details = [
                await get_erp_redemption_batch(session, batch_id=item.batch_id)
                for item in task.subtasks
            ]
            workbook = load_workbook(BytesIO(_export_task_bytes(task, details)))
            assert workbook.sheetnames == ["任务概览", "01-RajLuck", "02-RajWin"]
            assert workbook["任务概览"]["B1"].value == "双盘口任务"
            assert workbook["01-RajLuck"].max_row == 3
    finally:
        await engine.dispose()
