from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.security import encrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import (
    AppUser,
    Base,
    DataDictionaryEntry,
    SecurityAuditLog,
    SourceConfig,
)
from packages.domain.services.data_dictionary_service import (
    DataDictionaryConflictError,
    DataDictionarySyncError,
    DataDictionaryValidationError,
    create_withdraw_status,
    list_payment_channel_names,
    list_withdraw_statuses,
    sync_payment_channel_names,
    sync_remote_withdraw_statuses,
    update_withdraw_status,
    withdraw_status_dictionary,
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


@pytest.mark.asyncio
async def test_withdraw_statuses_are_source_scoped_editable_and_audited() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        session.add_all(
            [
                SourceConfig(
                    source_id="rajwin",
                    display_name="RajWin",
                    business_timezone="Asia/Kolkata",
                    currency="INR",
                ),
                SourceConfig(
                    source_id="rajluck",
                    display_name="RajLuck",
                    business_timezone="Asia/Kolkata",
                    currency="INR",
                ),
                AppUser(
                    username="admin",
                    username_normalized="admin",
                    password_hash="test-hash",
                    display_name="Admin",
                    role="admin",
                ),
            ]
        )
        await session.commit()
        admin = await session.scalar(select(AppUser).where(AppUser.username == "admin"))
        assert admin is not None

        rajwin = await create_withdraw_status(
            session,
            source_id="rajwin",
            entry_code="3",
            entry_label="代付成功",
            active=True,
            actor_user_id=admin.id,
        )
        rajluck = await create_withdraw_status(
            session,
            source_id="rajluck",
            entry_code="3",
            entry_label="已完成",
            active=True,
            actor_user_id=admin.id,
        )
        updated = await update_withdraw_status(
            session,
            entry_id=rajwin.id,
            entry_label="出款完成",
            active=False,
            actor_user_id=admin.id,
        )

        assert rajluck.entry_label == "已完成"
        assert updated.entry_label == "出款完成"
        assert updated.active is False
        rajwin_rows = await list_withdraw_statuses(session, source_id="rajwin")
        assert [row.entry_code for row in rajwin_rows] == ["3"]
        assert await withdraw_status_dictionary(session, source_id="rajwin") == [
            {"code": "3", "label": "出款完成", "active": False}
        ]
        actions = list(
            await session.scalars(
                select(SecurityAuditLog.action).order_by(SecurityAuditLog.created_at)
            )
        )
        assert actions == [
            "data_dictionary.withdraw_status.create",
            "data_dictionary.withdraw_status.create",
            "data_dictionary.withdraw_status.update",
        ]

        with pytest.raises(DataDictionaryConflictError, match="状态值已存在"):
            await create_withdraw_status(
                session,
                source_id="rajwin",
                entry_code="3",
                entry_label="重复",
                active=True,
                actor_user_id=admin.id,
            )
        with pytest.raises(DataDictionaryValidationError, match="至少修改"):
            await update_withdraw_status(
                session,
                entry_id=rajwin.id,
                entry_label=None,
                active=None,
                actor_user_id=admin.id,
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_remote_withdraw_status_sync_adds_only_missing_codes_and_preserves_local_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class FakeWithdrawStatusClient:
        statuses: list[dict[str, str]] = []

        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def fetch_withdraw_statuses(self) -> list[dict[str, str]]:
            return self.statuses

    monkeypatch.setattr(
        "packages.domain.services.data_dictionary_service.RajAdminWithdrawClient",
        FakeWithdrawStatusClient,
    )

    initial_seen_at = datetime(2026, 1, 1, tzinfo=UTC)
    async with factory() as session:
        rajwin = SourceConfig(
            source_id="rajwin",
            display_name="RajWin",
            base_url="https://admin.example.test",
            enabled=True,
            business_timezone="Asia/Kolkata",
            currency="INR",
            credential_version=1,
        )
        rajwin.encrypted_credentials = encrypt_credentials(
            {"username": "reader", "password": "test-password", "totp_secret": "JBSWY3DPEHPK3PXP"},
            source_id=rajwin.source_id,
            credential_version=rajwin.credential_version,
            settings=settings,
        )
        session.add_all(
            [
                rajwin,
                SourceConfig(
                    source_id="rajluck",
                    display_name="RajLuck",
                    business_timezone="Asia/Kolkata",
                    currency="INR",
                ),
                AppUser(
                    username="admin",
                    username_normalized="admin",
                    password_hash="test-hash",
                    display_name="Admin",
                    role="admin",
                ),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type="withdraw_status",
                    entry_code="3",
                    entry_label="人工完成",
                    active=False,
                    first_seen_at=initial_seen_at,
                    last_seen_at=initial_seen_at,
                    updated_at=initial_seen_at,
                ),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type="withdraw_status",
                    entry_code="9",
                    entry_label="人工新增状态",
                    active=True,
                    first_seen_at=initial_seen_at,
                    last_seen_at=initial_seen_at,
                    updated_at=initial_seen_at,
                ),
                DataDictionaryEntry(
                    source_id="rajluck",
                    dictionary_type="withdraw_status",
                    entry_code="0",
                    entry_label="RajLuck 专用文案",
                    active=True,
                ),
            ]
        )
        await session.commit()
        admin = await session.scalar(select(AppUser).where(AppUser.username == "admin"))
        assert admin is not None

        FakeWithdrawStatusClient.statuses = [
            {"code": "0", "label": "待审核"},
            {"code": "3", "label": "远端代付成功"},
            {"code": "6", "label": "提交三方失败"},
        ]
        first = await sync_remote_withdraw_statuses(
            session,
            source_id="rajwin",
            actor_user_id=admin.id,
            settings=settings,
        )

        assert first.remote_total == 3
        assert first.created_entries == 2
        assert first.refreshed_entries == 1
        assert [entry.entry_code for entry in first.entries] == ["0", "3", "6", "9"]
        first_entries = {entry.entry_code: entry for entry in first.entries}
        assert first_entries["3"].entry_label == "人工完成"
        assert first_entries["3"].active is False
        assert first_entries["9"].active is True
        assert first_entries["0"].entry_label == "待审核"

        manual_entry = await session.scalar(
            select(DataDictionaryEntry).where(
                DataDictionaryEntry.source_id == "rajwin",
                DataDictionaryEntry.entry_code == "3",
            )
        )
        assert manual_entry is not None
        assert manual_entry.last_seen_at != initial_seen_at

        FakeWithdrawStatusClient.statuses = [
            {"code": "0", "label": "远端修改文案"},
            {"code": "3", "label": "远端再次修改"},
        ]
        second = await sync_remote_withdraw_statuses(
            session,
            source_id="rajwin",
            actor_user_id=admin.id,
            settings=settings,
        )

        assert second.remote_total == 2
        assert second.created_entries == 0
        assert second.refreshed_entries == 2
        second_entries = {entry.entry_code: entry for entry in second.entries}
        assert second_entries["0"].entry_label == "待审核"
        assert second_entries["3"].entry_label == "人工完成"
        assert second_entries["3"].active is False
        assert second_entries["6"].active is True
        assert second_entries["9"].active is True
        assert await withdraw_status_dictionary(session, source_id="rajluck") == [
            {"code": "0", "label": "RajLuck 专用文案", "active": True}
        ]
        audits = list(
            await session.scalars(
                select(SecurityAuditLog).where(
                    SecurityAuditLog.action == "data_dictionary.withdraw_status.sync"
                )
            )
        )
        assert len(audits) == 2
        assert audits[-1].metadata_json == {
            "remote_total": 2,
            "created_entries": 0,
            "refreshed_entries": 2,
        }

    await engine.dispose()
