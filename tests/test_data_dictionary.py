import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import Base, DataDictionaryEntry, SourceConfig
from packages.domain.services.data_dictionary_service import (
    DataDictionarySyncError,
    list_payment_channel_names,
    sync_payment_channel_names,
)


@pytest.mark.asyncio
async def test_payment_channel_names_are_versioned_by_source_and_deactivated() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        session.add(
            SourceConfig(
                source_id="rajwin",
                display_name="RajWin",
                business_timezone="Asia/Kolkata",
                currency="INR",
            )
        )
        await session.commit()

        first = await sync_payment_channel_names(
            session,
            source_id="rajwin",
            channels=[
                {"code": "948", "label": "aelopay(HX)"},
                {"code": "659", "label": "elePay(HX)"},
            ],
        )
        await session.commit()
        assert first.active_entries == 2
        assert first.created_entries == 2

        second = await sync_payment_channel_names(
            session,
            source_id="rajwin",
            channels=[
                {"code": "948", "label": "aelopay(HX)-新名称"},
                {"code": "800", "label": "elePay(QR)"},
            ],
        )
        await session.commit()

        rows = await list_payment_channel_names(session)
        rows_by_code = {row.entry_code: row for row in rows}
        active_rows = await list_payment_channel_names(session, active=True)
        assert second.active_entries == 2
        assert second.created_entries == 1
        assert second.updated_entries == 1
        assert second.deactivated_entries == 1
        assert rows_by_code["948"].entry_label == "aelopay(HX)-新名称"
        assert rows_by_code["948"].active is True
        assert rows_by_code["659"].active is False
        assert rows_by_code["800"].active is True
        assert all(row.source_display_name == "RajWin" for row in rows)
        assert {row.entry_code for row in active_rows} == {"948", "800"}
        assert len(list(await session.scalars(select(DataDictionaryEntry)))) == 3

    await engine.dispose()


@pytest.mark.asyncio
async def test_payment_channel_name_sync_rejects_conflicting_duplicate_ids() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        with pytest.raises(DataDictionarySyncError, match="同一 ID"):
            await sync_payment_channel_names(
                session,
                source_id="rajwin",
                channels=[
                    {"code": "948", "label": "aelopay(HX)"},
                    {"code": "948", "label": "aelopay(唤醒)"},
                ],
            )

    await engine.dispose()
