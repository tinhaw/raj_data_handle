from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import AppUser, Base
from packages.domain.schemas.erp_balance import (
    ErpDailyBalanceReopenRequest,
    ErpDailyBalanceWriteRequest,
)
from packages.domain.schemas.erp_operator import (
    ErpDeliveryLineCreateRequest,
    ErpOperatorCreateRequest,
)
from packages.domain.schemas.erp_period_lock import (
    ErpPeriodLockRequest,
    ErpPeriodUnlockRequest,
)
from packages.domain.services.erp_balance_service import (
    ErpBalanceConflictError,
    confirm_erp_daily_balance,
    create_erp_daily_balance,
    reopen_erp_daily_balance,
    update_erp_daily_balance,
)
from packages.domain.services.erp_operator_service import (
    create_erp_operator,
    create_erp_operator_line,
)
from packages.domain.services.erp_period_lock_service import (
    lock_erp_period,
    unlock_erp_period,
    validate_erp_period_lock,
)


@pytest.mark.asyncio
async def test_period_lock_blocks_ledger_updates_until_explicit_unlock() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        actor = AppUser(
            username="period-lock-admin",
            username_normalized="period-lock-admin",
            password_hash="not-used-in-this-test",
            display_name="Period Lock Admin",
            role="admin",
        )
        session.add(actor)
        await session.commit()
        operator = await create_erp_operator(
            session,
            request=ErpOperatorCreateRequest(name="Raj Media"),
            actor_user_id=actor.id,
        )
        line = await create_erp_operator_line(
            session,
            operator_id=operator.id,
            request=ErpDeliveryLineCreateRequest(name="Main Line", asset="USDT"),
            actor_user_id=actor.id,
        )
        created = await create_erp_daily_balance(
            session,
            actor_user_id=actor.id,
            request=ErpDailyBalanceWriteRequest(
                operator_line_id=line.id,
                business_date=date(2026, 8, 1),
                opening_mode="MANUAL",
                opening_balance=Decimal("100"),
            ),
        )
        confirmed = await confirm_erp_daily_balance(
            session,
            balance_id=created.id,
            row_version=created.row_version,
            actor_user_id=actor.id,
        )
        lock_request = ErpPeriodLockRequest(month=date(2026, 8, 15), operator_line_ids=[line.id])
        validation = await validate_erp_period_lock(session, request=lock_request)
        assert validation.can_lock is True
        locked = await lock_erp_period(session, request=lock_request, actor_user_id=actor.id)
        assert locked[0].status == "LOCKED"
        assert locked[0].month_start == date(2026, 8, 1)

        with pytest.raises(ErpBalanceConflictError, match="已锁定"):
            await reopen_erp_daily_balance(
                session,
                balance_id=confirmed.id,
                request=ErpDailyBalanceReopenRequest(
                    row_version=confirmed.row_version,
                    reason="correction",
                ),
                actor_user_id=actor.id,
            )

        unlocked = await unlock_erp_period(
            session,
            request=ErpPeriodUnlockRequest(
                month=date(2026, 8, 1),
                operator_line_ids=[line.id],
                reason="approved correction",
            ),
            actor_user_id=actor.id,
        )
        assert unlocked[0].status == "UNLOCKED"
        reopened = await reopen_erp_daily_balance(
            session,
            balance_id=confirmed.id,
            request=ErpDailyBalanceReopenRequest(
                row_version=confirmed.row_version,
                reason="approved correction",
            ),
            actor_user_id=actor.id,
        )
        assert reopened.status == "DRAFT"
        updated = await update_erp_daily_balance(
            session,
            balance_id=reopened.id,
            request=ErpDailyBalanceWriteRequest(
                operator_line_id=line.id,
                business_date=date(2026, 8, 1),
                opening_mode="MANUAL",
                opening_balance=Decimal("120"),
                row_version=reopened.row_version,
            ),
            actor_user_id=actor.id,
        )
        assert updated.opening_balance == Decimal("120")

    await engine.dispose()
