from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import AppUser, Base, ErpAccountingPeriodLock, ErpDailyBalance
from packages.domain.schemas.erp_balance import ErpDailyBalanceWriteRequest
from packages.domain.schemas.erp_operator import (
    ErpDeliveryLineCreateRequest,
    ErpOperatorCreateRequest,
    ErpOperatorDeleteRequest,
    ErpOperatorPatchRequest,
)
from packages.domain.services.erp_balance_service import create_erp_daily_balance
from packages.domain.services.erp_operator_service import (
    ErpOperatorConflictError,
    create_erp_operator,
    create_erp_operator_line,
    delete_erp_operator,
    disable_erp_operator_line,
    get_erp_operator_delete_impact,
    list_erp_operator_lines,
    list_erp_operators,
    update_erp_operator,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _actor_id(session) -> int:
    actor = AppUser(
        username="erp-admin",
        username_normalized="erp-admin",
        password_hash="not-used-in-this-test",
        display_name="ERP Admin",
        role="admin",
    )
    session.add(actor)
    await session.commit()
    return actor.id


@pytest.mark.asyncio
async def test_operator_and_delivery_line_local_lifecycle() -> None:
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            actor_id = await _actor_id(session)
            operator = await create_erp_operator(
                session,
                request=ErpOperatorCreateRequest(name="Raj Media"),
                actor_user_id=actor_id,
            )
            assert operator.status == "ACTIVE"
            assert operator.code.startswith("OP-")

            line = await create_erp_operator_line(
                session,
                operator_id=operator.id,
                request=ErpDeliveryLineCreateRequest(name="Main Line", asset="USDC"),
                actor_user_id=actor_id,
            )
            assert line.operator_name == "Raj Media"
            assert line.asset == "USDC"
            assert line.default_exchange_loss_rate == Decimal("0.02")

            updated = await update_erp_operator(
                session,
                operator_id=operator.id,
                request=ErpOperatorPatchRequest(name="Raj Media India", row_version=1),
                actor_user_id=actor_id,
            )
            assert updated.name == "Raj Media India"
            assert updated.row_version == 2

            disabled = await disable_erp_operator_line(
                session,
                line_id=line.id,
                row_version=1,
                actor_user_id=actor_id,
            )
            assert disabled.status == "INACTIVE"
            assert await list_erp_operator_lines(session, operator_id=operator.id) == []
            assert len(await list_erp_operators(session)) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_operator_and_line_names_are_unique_within_their_scope() -> None:
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            actor_id = await _actor_id(session)
            operator = await create_erp_operator(
                session,
                request=ErpOperatorCreateRequest(name="Raj Media"),
                actor_user_id=actor_id,
            )
            line = ErpDeliveryLineCreateRequest(name="Main Line")
            await create_erp_operator_line(
                session,
                operator_id=operator.id,
                request=line,
                actor_user_id=actor_id,
            )

            try:
                await create_erp_operator(
                    session,
                    request=ErpOperatorCreateRequest(name="raj media"),
                    actor_user_id=actor_id,
                )
            except ErpOperatorConflictError:
                pass
            else:
                raise AssertionError("expected duplicate operator name to be rejected")

            try:
                await create_erp_operator_line(
                    session,
                    operator_id=operator.id,
                    request=ErpDeliveryLineCreateRequest(name="main line"),
                    actor_user_id=actor_id,
                )
            except ErpOperatorConflictError:
                pass
            else:
                raise AssertionError("expected duplicate delivery-line name to be rejected")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_operator_delete_requires_named_history_purge_confirmation() -> None:
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            actor_id = await _actor_id(session)
            operator = await create_erp_operator(
                session,
                request=ErpOperatorCreateRequest(name="Delete Guard Media"),
                actor_user_id=actor_id,
            )
            line = await create_erp_operator_line(
                session,
                operator_id=operator.id,
                request=ErpDeliveryLineCreateRequest(name="Guarded Line"),
                actor_user_id=actor_id,
            )
            balance = await create_erp_daily_balance(
                session,
                actor_user_id=actor_id,
                request=ErpDailyBalanceWriteRequest(
                    operator_line_id=line.id,
                    business_date=date(2026, 8, 18),
                    opening_mode="MANUAL",
                    opening_balance=Decimal("0"),
                ),
            )
            session.add(
                ErpAccountingPeriodLock(
                    operator_line_id=line.id,
                    month_start=date(2026, 8, 1),
                    locked_by=actor_id,
                )
            )
            await session.commit()

            impact = await get_erp_operator_delete_impact(session, operator_id=operator.id)
            assert impact.delivery_line_count == 1
            assert impact.ledger_count == 1
            assert impact.locked_period_count == 1
            assert impact.has_history is True

            with pytest.raises(ErpOperatorConflictError, match="二次确认"):
                await delete_erp_operator(
                    session,
                    operator_id=operator.id,
                    request=ErpOperatorDeleteRequest(row_version=1),
                    actor_user_id=actor_id,
                )
            with pytest.raises(ErpOperatorConflictError, match="完整输入"):
                await delete_erp_operator(
                    session,
                    operator_id=operator.id,
                    request=ErpOperatorDeleteRequest(
                        row_version=1,
                        purge_history=True,
                        confirmation_name="wrong",
                    ),
                    actor_user_id=actor_id,
                )

            await delete_erp_operator(
                session,
                operator_id=operator.id,
                request=ErpOperatorDeleteRequest(
                    row_version=1,
                    purge_history=True,
                    confirmation_name=operator.name,
                ),
                actor_user_id=actor_id,
            )
            assert await session.get(ErpDailyBalance, balance.id) is None
            assert await list_erp_operators(session, include_inactive=True) == []
    finally:
        await engine.dispose()
