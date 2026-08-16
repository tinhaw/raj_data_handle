from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import AppUser, Base
from packages.domain.schemas.erp_redemption import (
    ErpRedemptionBatchCreateRequest,
    ErpRedemptionCampaignCreateRequest,
    ErpRedemptionCodeImportRequest,
    ErpRedemptionCodeInput,
    ErpRedemptionTierWrite,
)
from packages.domain.services.erp_redemption_service import (
    create_erp_redemption_batch,
    create_erp_redemption_campaign,
    import_erp_redemption_codes,
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
