from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import (
    Base,
    RemoteAccount,
    RemoteAccountCapability,
    SourceConfig,
)
from packages.domain.services.erp_redemption_remote_gate import (
    ErpRemoteExecutionNotAuthorizedError,
    authorize_erp_redemption_remote_execution,
)


@pytest.mark.asyncio
async def test_remote_redemption_gate_requires_capability_and_per_execution_authorization() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as session:
            source = SourceConfig(source_id="rajwin", display_name="RajWin", enabled=True)
            account = RemoteAccount(
                source_id="rajwin",
                login_username="redemption-operator",
                display_name="Redemption Operator",
                enabled=True,
            )
            session.add_all([source, account])
            await session.flush()
            session.add(
                RemoteAccountCapability(
                    account_id=account.id,
                    capability="ERP_REDEMPTION_CREATE",
                    enabled=True,
                )
            )
            await session.commit()

            with pytest.raises(
                ErpRemoteExecutionNotAuthorizedError,
                match="明确执行授权",
            ):
                await authorize_erp_redemption_remote_execution(
                    session,
                    account_id=account.id,
                    operation="CREATE",
                    execution_authorized=False,
                )

            with pytest.raises(
                ErpRemoteExecutionNotAuthorizedError,
                match="ERP_REDEMPTION_PUBLISH",
            ):
                await authorize_erp_redemption_remote_execution(
                    session,
                    account_id=account.id,
                    operation="PUBLISH",
                    execution_authorized=True,
                )

            grant = await authorize_erp_redemption_remote_execution(
                session,
                account_id=account.id,
                operation="CREATE",
                execution_authorized=True,
            )
            assert grant.account_id == account.id
            assert grant.source_id == "rajwin"
            assert grant.capability == "ERP_REDEMPTION_CREATE"
    finally:
        await engine.dispose()
