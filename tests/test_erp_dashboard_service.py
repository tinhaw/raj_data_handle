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
from packages.domain.services.erp_dashboard_service import build_erp_dashboard
from packages.domain.services.erp_operator_service import (
    create_erp_operator,
    create_erp_operator_line,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_dashboard_summarizes_local_ledger_and_quality_items() -> None:
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            actor = AppUser(
                username="erp-dashboard-admin",
                username_normalized="erp-dashboard-admin",
                password_hash="not-used-in-this-test",
                display_name="ERP Dashboard Admin",
                role="admin",
            )
            session.add(actor)
            await session.commit()
            operator = await create_erp_operator(
                session,
                request=ErpOperatorCreateRequest(name="Dashboard Media"),
                actor_user_id=actor.id,
            )
            line = await create_erp_operator_line(
                session,
                operator_id=operator.id,
                request=ErpDeliveryLineCreateRequest(name="Dashboard Line", asset="USDT"),
                actor_user_id=actor.id,
            )
            await create_erp_daily_balance(
                session,
                actor_user_id=actor.id,
                request=ErpDailyBalanceWriteRequest(
                    operator_line_id=line.id,
                    business_date=date(2026, 8, 18),
                    opening_mode="MANUAL",
                    opening_balance=Decimal("100"),
                    transfer_amount=Decimal("20"),
                    exchange_loss_rate=Decimal("0"),
                    service_fee_rate=Decimal("0"),
                ),
            )
            dashboard = await build_erp_dashboard(session, business_date=date(2026, 8, 18))
            assert dashboard.metric.active_operator_count == 1
            assert dashboard.metric.active_line_count == 1
            assert dashboard.metric.opening_balance == Decimal("100.00000000")
            assert dashboard.metric.transfer_amount == Decimal("20.00000000")
            assert dashboard.metric.closing_balance == Decimal("120.00000000")
            assert len(dashboard.trend) == 7
            assert dashboard.recent_balances[0].operator_name == "Dashboard Media"
            assert dashboard.health_items[0].code == "DRAFT_BALANCES"
            assert dashboard.health_items[0].count == 1
    finally:
        await engine.dispose()
