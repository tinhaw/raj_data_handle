from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.request_context import reset_request_id, set_request_id
from packages.domain.models import AppUser, Base, ErpOperator, ErpOperatorLine
from packages.domain.services.auth_service import write_audit
from packages.domain.services.erp_audit_service import list_erp_audit_logs


@pytest.mark.asyncio
async def test_erp_audit_returns_only_erp_actions() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            actor = AppUser(
                username="erp-audit-admin",
                username_normalized="erp-audit-admin",
                password_hash="not-used-in-this-test",
                display_name="ERP Audit Admin",
                role="admin",
            )
            session.add(actor)
            await session.flush()
            token = set_request_id("audit-test-request")
            try:
                await write_audit(
                    session,
                    action="erp_daily_balance.confirm",
                    actor_user_id=actor.id,
                    target_type="erp_daily_balance",
                    target_id="balance-1",
                    metadata={"business_date": "2026-08-18"},
                )
            finally:
                reset_request_id(token)
            await write_audit(session, action="user.access", actor_user_id=actor.id)
            await session.commit()
            result = await list_erp_audit_logs(
                session,
                date_from=date.today(),
                date_to=date.today(),
                action=None,
                page=1,
                page_size=50,
            )
            assert result.total == 1
            assert result.items[0].action == "erp_daily_balance.confirm"
            assert result.items[0].actor_display_name == "ERP Audit Admin"
            assert result.items[0].request_id == "audit-test-request"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_erp_audit_respects_operator_scope() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            first = ErpOperator(code="OP-AUDIT-1", name="Scoped Company")
            second = ErpOperator(code="OP-AUDIT-2", name="Hidden Company")
            session.add_all([first, second])
            await session.flush()
            first_line = ErpOperatorLine(
                operator_id=first.id, code="LINE-AUDIT-1", name="Scoped Line"
            )
            second_line = ErpOperatorLine(
                operator_id=second.id, code="LINE-AUDIT-2", name="Hidden Line"
            )
            session.add_all([first_line, second_line])
            await session.flush()
            for line in (first_line, second_line):
                await write_audit(
                    session,
                    action="erp_operator_line.update",
                    target_type="erp_operator_line",
                    target_id=line.id,
                )
            await session.commit()

            result = await list_erp_audit_logs(
                session,
                date_from=date.today(),
                date_to=date.today(),
                action=None,
                operator_ids=[first.id],
                page=1,
                page_size=50,
            )
            assert result.total == 1
            assert result.items[0].target_id == first_line.id
    finally:
        await engine.dispose()
