from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import AppUser, Base
from packages.domain.schemas.erp_balance import (
    ErpDailyBalanceBatchRequest,
    ErpDailyBalanceWriteRequest,
)
from packages.domain.schemas.erp_operator import (
    ErpDeliveryLineCreateRequest,
    ErpOperatorCreateRequest,
)
from packages.domain.services.erp_balance_service import (
    ErpBalanceConflictError,
    batch_erp_daily_balances,
    confirm_erp_daily_balance,
    create_erp_daily_balance,
    list_erp_daily_balances,
    preview_erp_daily_balance_impact,
    update_erp_daily_balance,
)
from packages.domain.services.erp_operator_service import (
    create_erp_operator,
    create_erp_operator_line,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _actor_id(session) -> int:
    actor = AppUser(
        username="erp-balance-admin",
        username_normalized="erp-balance-admin",
        password_hash="not-used-in-this-test",
        display_name="ERP Balance Admin",
        role="admin",
    )
    session.add(actor)
    await session.commit()
    return actor.id


@pytest.mark.asyncio
async def test_daily_balance_calculates_and_carries_forward_opening_balance() -> None:
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            actor_id = await _actor_id(session)
            operator = await create_erp_operator(
                session,
                request=ErpOperatorCreateRequest(name="Raj Media"),
                actor_user_id=actor_id,
            )
            line = await create_erp_operator_line(
                session,
                operator_id=operator.id,
                request=ErpDeliveryLineCreateRequest(name="Main Line", asset="USDT"),
                actor_user_id=actor_id,
            )

            first = await create_erp_daily_balance(
                session,
                actor_user_id=actor_id,
                request=ErpDailyBalanceWriteRequest(
                    operator_line_id=line.id,
                    business_date=date(2026, 8, 1),
                    opening_mode="MANUAL",
                    opening_balance=Decimal("100"),
                    transfer_amount=Decimal("200"),
                    fraud_loss_amount=Decimal("15"),
                    fraud_deduction_source="TRANSFER",
                    spend_amount=Decimal("50"),
                    exchange_loss_rate=Decimal("0.10"),
                    exchange_loss_basis="TRANSFER",
                    service_fee_rate=Decimal("0.05"),
                    service_fee_basis="EFFECTIVE_TRANSFER",
                    reflux_amount=Decimal("5"),
                    refund_amount=Decimal("2"),
                    other_deduction_amount=Decimal("3"),
                    other_reason="manual adjustment",
                ),
            )
            assert first.effective_transfer_amount == Decimal("185.00")
            assert first.exchange_loss_amount == Decimal("20.00")
            assert first.service_fee_amount == Decimal("9.25")
            assert first.closing_balance == Decimal("195.75")

            second = await create_erp_daily_balance(
                session,
                actor_user_id=actor_id,
                request=ErpDailyBalanceWriteRequest(
                    operator_line_id=line.id,
                    business_date=date(2026, 8, 2),
                    opening_mode="AUTO",
                ),
            )
            assert second.suggested_opening_balance == Decimal("195.75000000")
            assert second.opening_balance == Decimal("195.75000000")
            assert second.closing_balance == Decimal("195.75")

            updated = await update_erp_daily_balance(
                session,
                balance_id=second.id,
                actor_user_id=actor_id,
                request=ErpDailyBalanceWriteRequest(
                    operator_line_id=line.id,
                    business_date=date(2026, 8, 2),
                    transfer_amount=Decimal("10"),
                    row_version=second.row_version,
                ),
            )
            assert updated.row_version == 2
            assert updated.closing_balance == Decimal("205.35")

            confirmed = await confirm_erp_daily_balance(
                session,
                balance_id=second.id,
                row_version=updated.row_version,
                actor_user_id=actor_id,
            )
            assert confirmed.status == "CONFIRMED"
            assert confirmed.row_version == 3

            month = await list_erp_daily_balances(
                session,
                operator_line_id=line.id,
                month="2026-08",
            )
            assert [record.id for record in month.records] == [first.id, second.id]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_daily_balance_batch_creates_ordered_records_in_one_commit() -> None:
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            actor_id = await _actor_id(session)
            operator = await create_erp_operator(
                session,
                request=ErpOperatorCreateRequest(name="Batch Media"),
                actor_user_id=actor_id,
            )
            line = await create_erp_operator_line(
                session,
                operator_id=operator.id,
                request=ErpDeliveryLineCreateRequest(name="Batch Line", asset="USDT"),
                actor_user_id=actor_id,
            )
            results = await batch_erp_daily_balances(
                session,
                actor_user_id=actor_id,
                request=ErpDailyBalanceBatchRequest(
                    records=[
                        ErpDailyBalanceWriteRequest(
                            operator_line_id=line.id,
                            business_date=date(2026, 8, 2),
                            opening_mode="AUTO",
                            transfer_amount=Decimal("5"),
                        ),
                        ErpDailyBalanceWriteRequest(
                            operator_line_id=line.id,
                            business_date=date(2026, 8, 1),
                            opening_mode="MANUAL",
                            opening_balance=Decimal("100"),
                            transfer_amount=Decimal("10"),
                        ),
                    ]
                ),
            )
            assert [row.business_date for row in results] == [date(2026, 8, 1), date(2026, 8, 2)]
            assert results[1].opening_balance == results[0].closing_balance
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_daily_balance_previews_and_cascades_only_draft_auto_openings() -> None:
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            actor_id = await _actor_id(session)
            operator = await create_erp_operator(
                session,
                request=ErpOperatorCreateRequest(name="Impact Media"),
                actor_user_id=actor_id,
            )
            line = await create_erp_operator_line(
                session,
                operator_id=operator.id,
                request=ErpDeliveryLineCreateRequest(name="Impact Line", asset="USDT"),
                actor_user_id=actor_id,
            )
            first = await create_erp_daily_balance(
                session,
                actor_user_id=actor_id,
                request=ErpDailyBalanceWriteRequest(
                    operator_line_id=line.id,
                    business_date=date(2026, 8, 1),
                    opening_mode="MANUAL",
                    opening_balance=Decimal("100"),
                    transfer_amount=Decimal("10"),
                ),
            )
            second = await create_erp_daily_balance(
                session,
                actor_user_id=actor_id,
                request=ErpDailyBalanceWriteRequest(
                    operator_line_id=line.id,
                    business_date=date(2026, 8, 2),
                    opening_mode="AUTO",
                    transfer_amount=Decimal("5"),
                ),
            )
            third = await create_erp_daily_balance(
                session,
                actor_user_id=actor_id,
                request=ErpDailyBalanceWriteRequest(
                    operator_line_id=line.id,
                    business_date=date(2026, 8, 3),
                    opening_mode="AUTO",
                ),
            )

            request = ErpDailyBalanceWriteRequest(
                operator_line_id=line.id,
                business_date=date(2026, 8, 1),
                transfer_amount=Decimal("20"),
                row_version=first.row_version,
            )
            preview = await preview_erp_daily_balance_impact(session, request=request)
            assert preview.current.closing_balance == Decimal("119.20")
            assert [record.id for record in preview.impacted_records] == [second.id, third.id]
            assert not preview.blocking_reasons

            updated = await update_erp_daily_balance(
                session,
                balance_id=first.id,
                actor_user_id=actor_id,
                request=request,
            )
            assert updated.closing_balance == Decimal("119.20")
            balances = await list_erp_daily_balances(
                session,
                operator_line_id=line.id,
                month="2026-08",
            )
            assert balances.records[1].opening_balance == Decimal("119.20000000")
            assert balances.records[2].opening_balance == Decimal("124.00000000")

            confirmed = await confirm_erp_daily_balance(
                session,
                balance_id=second.id,
                row_version=balances.records[1].row_version,
                actor_user_id=actor_id,
            )
            assert confirmed.status == "CONFIRMED"
            updated_request = ErpDailyBalanceWriteRequest(
                operator_line_id=line.id,
                business_date=date(2026, 8, 1),
                transfer_amount=Decimal("30"),
                row_version=updated.row_version,
            )
            preview = await preview_erp_daily_balance_impact(session, request=updated_request)
            assert preview.blocking_reasons == ["2026-08-02 已确认，修改前序日结前需先重开。"]
            with pytest.raises(ErpBalanceConflictError, match="2026-08-02 已确认"):
                await update_erp_daily_balance(
                    session,
                    balance_id=first.id,
                    actor_user_id=actor_id,
                    request=updated_request,
                )
    finally:
        await engine.dispose()
