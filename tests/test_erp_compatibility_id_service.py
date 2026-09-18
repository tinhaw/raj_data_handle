from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import Base
from packages.domain.services.erp_compatibility_id_service import (
    ERP_COMPATIBILITY_PROJECTION_ID_BASE,
    ErpCompatibilityIdError,
    bind_erp_compatibility_id,
    get_erp_compatibility_ids,
    register_erp_compatibility_id,
)


@pytest.mark.asyncio
async def test_crosswalk_is_stable_typed_and_read_only_on_lookup() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        first = await register_erp_compatibility_id(
            session,
            entity_type="operator",
            canonical_id="operator-uuid",
        )
        again = await register_erp_compatibility_id(
            session,
            entity_type="operator",
            canonical_id="operator-uuid",
        )
        remote = await register_erp_compatibility_id(
            session,
            entity_type="remote_account",
            canonical_id="remote-uuid",
        )
        await session.commit()

        assert again == first
        assert first > ERP_COMPATIBILITY_PROJECTION_ID_BASE
        assert remote != first
        assert await get_erp_compatibility_ids(
            session,
            entity_type="operator",
            canonical_ids=["operator-uuid"],
        ) == {"operator-uuid": first}
        with pytest.raises(ErpCompatibilityIdError, match="missing-uuid"):
            await get_erp_compatibility_ids(
                session,
                entity_type="operator",
                canonical_ids=["missing-uuid"],
            )

        imported = await bind_erp_compatibility_id(
            session,
            entity_type="operator",
            canonical_id="imported-operator-uuid",
            legacy_id=901,
        )
        assert imported == 901
        assert await bind_erp_compatibility_id(
            session,
            entity_type="remote_account",
            canonical_id="imported-remote-uuid",
            legacy_id=901,
        ) == 901
        with pytest.raises(ErpCompatibilityIdError, match="其他当前记录"):
            await bind_erp_compatibility_id(
                session,
                entity_type="operator",
                canonical_id="conflicting-operator-uuid",
                legacy_id=901,
            )

    await engine.dispose()
