from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import AppUser, Base
from packages.domain.schemas.erp_balance import ErpDailyBalanceWriteRequest
from packages.domain.schemas.erp_operator import (
    ErpDeliveryLineCreateRequest,
    ErpOperatorCreateRequest,
)
from packages.domain.services.erp_balance_service import create_erp_daily_balance
from packages.domain.services.erp_operator_service import (
    create_erp_operator,
    create_erp_operator_line,
)
from packages.domain.services.erp_report_service import (
    build_erp_daily_report,
    build_erp_monthly_report,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _actor_id(session) -> int:
    actor = AppUser(
        username="erp-report-admin",
        username_normalized="erp-report-admin",
        password_hash="not-used-in-this-test",
        display_name="ERP Report Admin",
        role="admin",
    )
    session.add(actor)
    await session.commit()
    return actor.id


@pytest.mark.asyncio
async def test_daily_and_monthly_reports_keep_balances_as_points_in_time() -> None:
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
                request=ErpDeliveryLineCreateRequest(name="USDT Line", asset="USDT"),
                actor_user_id=actor_id,
            )
            await create_erp_daily_balance(
                session,
                actor_user_id=actor_id,
                request=ErpDailyBalanceWriteRequest(
                    operator_line_id=line.id,
                    business_date=date(2026, 8, 1),
                    opening_mode="MANUAL",
                    opening_balance=Decimal("100"),
                    transfer_amount=Decimal("10"),
                    spend_amount=Decimal("3"),
                    exchange_loss_rate=Decimal("0"),
                    service_fee_rate=Decimal("0"),
                ),
            )
            await create_erp_daily_balance(
                session,
                actor_user_id=actor_id,
                request=ErpDailyBalanceWriteRequest(
                    operator_line_id=line.id,
                    business_date=date(2026, 8, 2),
                    opening_mode="AUTO",
                    transfer_amount=Decimal("10"),
                    spend_amount=Decimal("2"),
                    exchange_loss_rate=Decimal("0"),
                    service_fee_rate=Decimal("0"),
                ),
            )

            daily = await build_erp_daily_report(
                session,
                date_from=date(2026, 8, 1),
                date_to=date(2026, 8, 3),
                include_draft=True,
            )
            balance_points = [
                (row.period, row.opening_balance, row.closing_balance)
                for row in daily.rows
            ]
            assert balance_points == [
                ("2026-08-01", Decimal("100.00000000"), Decimal("107.00000000")),
                ("2026-08-02", Decimal("107.00000000"), Decimal("115.00000000")),
                ("2026-08-03", Decimal("115.00000000"), Decimal("115.00000000")),
            ]
            assert daily.rows[2].record_count == 0

            monthly = await build_erp_monthly_report(
                session,
                month_from="2026-08",
                month_to="2026-08",
                include_draft=True,
            )
            assert len(monthly.rows) == 1
            assert monthly.rows[0].opening_balance == Decimal("100.00000000")
            assert monthly.rows[0].transfer_amount == Decimal("20.00000000")
            assert monthly.rows[0].closing_balance == Decimal("115.00000000")
            assert monthly.rows[0].warnings == []
    finally:
        await engine.dispose()
