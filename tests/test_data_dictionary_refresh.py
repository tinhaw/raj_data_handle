from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.security import encrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import (
    AppUser,
    Base,
    DataDictionaryRefreshConfig,
    SecurityAuditLog,
    SourceConfig,
)
from packages.domain.services import data_dictionary_refresh_service as refresh_service
from packages.domain.services.data_dictionary_refresh_service import (
    get_data_dictionary_refresh_config,
    run_due_data_dictionary_refreshes,
    update_data_dictionary_refresh_config,
)
from packages.domain.services.data_dictionary_service import (
    list_payment_channel_names,
    list_payment_channels,
    sync_remote_payment_dictionary,
)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


@pytest.mark.asyncio
async def test_remote_payment_dictionary_refreshes_each_read_only_interface(
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

    class FakeChargeClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def fetch_payment_channels(self) -> list[dict[str, str]]:
            return [{"code": "448", "label": "MasterPay"}]

        async def fetch_channels(self) -> list[dict[str, str]]:
            return [{"code": "948", "label": "aelopay"}]

    monkeypatch.setattr(
        "packages.domain.services.data_dictionary_service.RajAdminChargeClient",
        FakeChargeClient,
    )

    async with factory() as session:
        source = SourceConfig(
            source_id="rajwin",
            display_name="RajWin",
            base_url="https://admin.example.test",
            enabled=True,
            business_timezone="Asia/Kolkata",
            currency="INR",
            credential_version=1,
        )
        source.encrypted_credentials = encrypt_credentials(
            {
                "username": "reader",
                "password": "test-password",
                "totp_secret": "JBSWY3DPEHPK3PXP",
            },
            source_id=source.source_id,
            credential_version=source.credential_version,
            settings=settings,
        )
        session.add(source)
        await session.commit()

        payment_result = await sync_remote_payment_dictionary(
            session,
            source_id="rajwin",
            dictionary_type="payment_channel",
            actor_user_id=None,
            trigger_type="automatic",
            settings=settings,
        )
        name_result = await sync_remote_payment_dictionary(
            session,
            source_id="rajwin",
            dictionary_type="payment_channel_name",
            actor_user_id=None,
            trigger_type="automatic",
            settings=settings,
        )

        assert payment_result.remote_total == 1
        assert name_result.remote_total == 1
        assert [item.entry_code for item in await list_payment_channels(session)] == ["448"]
        assert [item.entry_code for item in await list_payment_channel_names(session)] == ["948"]
        audits = list(
            await session.scalars(
                select(SecurityAuditLog)
                .where(SecurityAuditLog.action.like("data_dictionary.payment_channel%.sync"))
                .order_by(SecurityAuditLog.action)
            )
        )
        assert len(audits) == 2
        assert all(item.actor_user_id is None for item in audits)
        assert all(item.metadata_json["trigger_type"] == "automatic" for item in audits)

    await engine.dispose()


@pytest.mark.asyncio
async def test_auto_refresh_config_defaults_off_and_save_does_not_run_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    configured_at = datetime(2026, 8, 29, 7, 30, tzinfo=UTC)

    async def unexpected_remote_sync(*_: object, **__: object) -> None:
        raise AssertionError("saving automatic refresh settings must not call remote APIs")

    monkeypatch.setattr(
        refresh_service,
        "sync_remote_user_source_channels",
        unexpected_remote_sync,
    )

    async with factory() as session:
        session.add_all(
            [
                SourceConfig(
                    source_id="rajwin",
                    display_name="RajWin",
                    base_url="https://admin.example.test",
                    enabled=True,
                    business_timezone="Asia/Kolkata",
                    currency="INR",
                    encrypted_credentials="test-credential-envelope",
                    credential_version=1,
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

        default_config = await get_data_dictionary_refresh_config(
            session,
            source_id="rajwin",
            dictionary_type="user_source_channel",
        )
        assert default_config.enabled is False
        assert default_config.interval_minutes == 360
        assert default_config.next_refresh_at is None

        saved = await update_data_dictionary_refresh_config(
            session,
            source_id="rajwin",
            dictionary_type="user_source_channel",
            enabled=True,
            interval_minutes=180,
            actor_user_id=admin.id,
            now=configured_at,
        )
        assert saved.enabled is True
        assert saved.interval_minutes == 180
        assert saved.next_refresh_at == configured_at + timedelta(minutes=180)
        audit = await session.scalar(
            select(SecurityAuditLog).where(
                SecurityAuditLog.action == "data_dictionary.auto_refresh_config.update"
            )
        )
        assert audit is not None
        assert audit.metadata_json["dictionary_type"] == "user_source_channel"

    await engine.dispose()


@pytest.mark.asyncio
async def test_due_auto_refresh_runs_only_claimed_dictionary_and_reschedules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    due_at = datetime(2026, 8, 29, 8, 0, tzinfo=UTC)
    calls: list[tuple[str, str]] = []

    async def fake_channel_sync(
        session: object,
        *,
        source_id: str,
        actor_user_id: int | None,
        trigger_type: str,
    ) -> None:
        assert session is not None
        assert actor_user_id is None
        calls.append((source_id, trigger_type))

    monkeypatch.setattr(
        refresh_service,
        "sync_remote_user_source_channels",
        fake_channel_sync,
    )

    async with factory() as session:
        session.add_all(
            [
                SourceConfig(
                    source_id="rajwin",
                    display_name="RajWin",
                    business_timezone="Asia/Kolkata",
                    currency="INR",
                ),
                DataDictionaryRefreshConfig(
                    source_id="rajwin",
                    dictionary_type="user_source_channel",
                    enabled=True,
                    interval_minutes=60,
                    status="idle",
                    next_refresh_at=due_at,
                ),
                DataDictionaryRefreshConfig(
                    source_id="rajwin",
                    dictionary_type="payment_channel",
                    enabled=True,
                    interval_minutes=60,
                    status="idle",
                    next_refresh_at=due_at + timedelta(minutes=1),
                ),
            ]
        )
        await session.commit()

        outcomes = await run_due_data_dictionary_refreshes(session, now=due_at)
        assert [(item.dictionary_type, item.status) for item in outcomes] == [
            ("user_source_channel", "succeeded")
        ]
        assert calls == [("rajwin", "automatic")]
        config = await session.get(
            DataDictionaryRefreshConfig,
            ("rajwin", "user_source_channel"),
        )
        assert config is not None
        assert config.status == "succeeded"
        assert _as_utc(config.last_succeeded_at) == due_at
        assert _as_utc(config.next_refresh_at) == due_at + timedelta(minutes=60)
        assert config.lease_expires_at is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_auto_refresh_failure_keeps_only_safe_error_and_releases_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    due_at = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)

    async def failing_sync(*_: object, **__: object) -> None:
        raise RuntimeError("Bearer secret-must-not-be-persisted")

    monkeypatch.setattr(
        refresh_service,
        "sync_remote_user_source_channels",
        failing_sync,
    )

    async with factory() as session:
        session.add_all(
            [
                SourceConfig(
                    source_id="rajwin",
                    display_name="RajWin",
                    business_timezone="Asia/Kolkata",
                    currency="INR",
                ),
                DataDictionaryRefreshConfig(
                    source_id="rajwin",
                    dictionary_type="user_source_channel",
                    enabled=True,
                    interval_minutes=30,
                    status="idle",
                    next_refresh_at=due_at,
                ),
            ]
        )
        await session.commit()

        outcomes = await run_due_data_dictionary_refreshes(session, now=due_at)
        assert outcomes[0].status == "failed"
        config = await session.get(
            DataDictionaryRefreshConfig,
            ("rajwin", "user_source_channel"),
        )
        assert config is not None
        assert config.status == "failed"
        assert config.last_error == "自动刷新失败，本地字典保持不变。"
        assert "secret-must-not-be-persisted" not in config.last_error
        assert _as_utc(config.next_refresh_at) == due_at + timedelta(minutes=30)
        assert config.lease_expires_at is None
        failure_audit = await session.scalar(
            select(SecurityAuditLog).where(
                SecurityAuditLog.action == "data_dictionary.auto_refresh.failure"
            )
        )
        assert failure_audit is not None
        assert "secret-must-not-be-persisted" not in str(failure_audit.metadata_json)

    await engine.dispose()
