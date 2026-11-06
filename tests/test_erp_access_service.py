from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import AppUser, Base, ErpOperator
from packages.domain.schemas.erp_access import ErpUserAccessUpdateRequest
from packages.domain.services.erp_access_service import (
    ERP_PERMISSION_LEDGER_WRITE,
    ERP_PERMISSION_REPORT_VIEW,
    ErpScopePermissionError,
    get_erp_access_snapshot,
    resolve_erp_operator_scope,
    update_erp_access,
    user_has_erp_permission,
)


@pytest.mark.asyncio
async def test_erp_roles_and_operator_scope_are_local_to_a_user() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        user = AppUser(
            username="ledger-user",
            username_normalized="ledger-user",
            password_hash="not-used-in-this-test",
            display_name="Ledger User",
            role="user",
        )
        first_operator = ErpOperator(code="COMPANY-001", name="Company 1")
        second_operator = ErpOperator(code="COMPANY-002", name="Company 2")
        session.add_all([user, first_operator, second_operator])
        await session.commit()

        snapshot = await update_erp_access(
            session,
            user_id=user.id,
            request=ErpUserAccessUpdateRequest(
                role_grants=["ERP_LEDGER_OPERATOR", "ERP_AUDITOR"],
                operator_ids=[first_operator.id],
            ),
            actor_user_id=user.id,
        )

        assert snapshot.all_operators is False
        assert snapshot.operator_ids == [first_operator.id]
        assert ERP_PERMISSION_LEDGER_WRITE in snapshot.effective_permissions
        assert ERP_PERMISSION_REPORT_VIEW in snapshot.effective_permissions
        assert await user_has_erp_permission(
            session,
            user_id=user.id,
            permission=ERP_PERMISSION_LEDGER_WRITE,
            operator_id=first_operator.id,
        )
        assert not await user_has_erp_permission(
            session,
            user_id=user.id,
            permission=ERP_PERMISSION_LEDGER_WRITE,
            operator_id=second_operator.id,
        )
        assert await resolve_erp_operator_scope(session, user_id=user.id) == [first_operator.id]
        with pytest.raises(ErpScopePermissionError):
            await resolve_erp_operator_scope(
                session,
                user_id=user.id,
                requested_operator_ids=[second_operator.id],
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_global_platform_admin_keeps_all_erp_permissions_without_domain_grants() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        admin = AppUser(
            username="admin",
            username_normalized="admin",
            password_hash="not-used-in-this-test",
            display_name="Admin",
            role="admin",
        )
        session.add(admin)
        await session.commit()

        snapshot = await get_erp_access_snapshot(session, user_id=admin.id)
        assert snapshot.all_operators is True
        assert ERP_PERMISSION_LEDGER_WRITE in snapshot.effective_permissions

    await engine.dispose()
