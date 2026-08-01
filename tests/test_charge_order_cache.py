from __future__ import annotations

from datetime import UTC, datetime, time

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.security import encrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    ChargeOrderSnapshot,
    DataDictionaryEntry,
    DataSyncRun,
    DataSyncRunEvent,
    SourceConfig,
    SystemRetentionSetting,
)
from packages.domain.schemas.charge_order import (
    ChargeChannelSummaryRequest,
    ChargeOrderQueryRequest,
)
from packages.domain.services.charge_order_refresh_service import (
    queue_charge_order_refreshes,
    run_due_charge_order_refreshes,
)
from packages.domain.services.charge_order_service import (
    query_charge_channel_summary,
    query_charge_orders,
    summarize_charge_orders,
)
from packages.domain.services.data_dictionary_service import ensure_charge_statuses
from packages.domain.services.remote_charge_service import ChargeFetchResult, normalize_charge_order


class FakeChargeClient:
    calls: list[dict[str, object]] = []

    def __init__(self, *, base_url: str, page_size: int = 100, **_: object) -> None:
        self.base_url = base_url
        self.page_size = page_size

    async def __aenter__(self) -> FakeChargeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def export_charge_orders(self, **kwargs: object) -> ChargeFetchResult:
        FakeChargeClient.calls.append(
            {"base_url": self.base_url, "page_size": self.page_size, **kwargs}
        )
        return ChargeFetchResult(
            orders=[
                {
                    "id": "safe-1",
                    "uid": "100",
                    "order_num": "charge-1",
                    "pay_method": "948",
                    "pay_channel_name": "948",
                    "amount": "500",
                    "status": "1",
                    "create_time": "2026-07-29 15:30:00",
                    "account": "not-present-after-normalization",
                }
            ],
            fetched_pages=1,
            remote_total=1,
            complete=True,
        )


def test_charge_order_normalizer_keeps_only_approved_fields() -> None:
    normalized = normalize_charge_order(
        {
            "id": 12,
            "uid": 34,
            "order_num": "charge-12",
            "out_trade_no": "third-12",
            "pay_method": "948",
            "pay_channel_name": "948",
            "amount": "100.50",
            "balance": "100.50",
            "extra": "0",
            "status": 1,
            "create_time": "2026-07-30 10:00:00",
            "pay_time": "2026-07-30 10:01:00",
            "account": "must-not-be-stored",
            "ip": "must-not-be-stored",
            "attach": "must-not-be-stored",
        }
    )

    assert normalized["id"] == "12"
    assert normalized["amount"] == "100.50"
    assert normalized["pay_channel_name"] == "948"
    assert "account" not in normalized
    assert "ip" not in normalized
    assert "attach" not in normalized


def test_charge_order_summary_uses_initial_status_and_third_party_rules() -> None:
    summary = summarize_charge_orders(
        [
            {"status": "1", "amount": "100", "out_trade_no": "third-1"},
            {"status": "0", "amount": "20", "out_trade_no": ""},
            {"status": "1", "amount": "50", "out_trade_no": "0"},
            {"status": "-1", "amount": "30", "out_trade_no": "third-expired"},
            {"status": "2", "amount": "40", "out_trade_no": "third-refunded"},
        ]
    )

    assert summary == {
        "order_count": 5,
        "successful_order_count": 2,
        "successful_amount": "150.00",
        "unpaid_order_count": 1,
        "no_third_party_order_count": 2,
    }


@pytest.mark.asyncio
async def test_charge_order_query_and_channel_summary_only_read_local_cache() -> None:
    settings = Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)
    async with factory() as session:
        session.add_all(
            [
                SourceConfig(
                    source_id="rajwin",
                    display_name="RajWin",
                    enabled=True,
                    business_timezone="Asia/Kolkata",
                    currency="INR",
                ),
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                    withdraw_order_refresh_interval_hours=1,
                    withdraw_order_refresh_page_size=100,
                    withdraw_order_query_range="today",
                    charge_order_refresh_interval_hours=1,
                    charge_order_refresh_page_size=100,
                    charge_order_query_range="last_2_hours",
                ),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type="payment_channel",
                    entry_code="948",
                    entry_label="渠道 A",
                    active=True,
                    first_seen_at=now,
                    last_seen_at=now,
                    updated_at=now,
                ),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type="payment_channel_name",
                    entry_code="948",
                    entry_label="渠道名称 A",
                    active=True,
                    first_seen_at=now,
                    last_seen_at=now,
                    updated_at=now,
                ),
                ChargeOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="success",
                    uid="1001",
                    pay_method="948",
                    pay_channel_name="948",
                    amount="100",
                    status="1",
                    out_trade_no="third-success",
                    create_time="2026-07-30 12:00:00",
                    create_time_utc=datetime(2026, 7, 30, 6, 30, tzinfo=UTC),
                    synced_at=now,
                ),
                ChargeOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="unpaid",
                    uid="1002",
                    pay_method="948",
                    amount="20",
                    status="0",
                    create_time="2026-07-30 12:30:00",
                    create_time_utc=datetime(2026, 7, 30, 7, 0, tzinfo=UTC),
                    out_trade_no="",
                    synced_at=now,
                ),
                ChargeOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="same-denomination-success",
                    uid="1006",
                    pay_method="948",
                    pay_channel_name="948",
                    amount="100.00",
                    status="1",
                    out_trade_no="third-same-denomination",
                    create_time="2026-07-30 12:35:00",
                    create_time_utc=datetime(2026, 7, 30, 7, 5, tzinfo=UTC),
                    synced_at=now,
                ),
                ChargeOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="other-denomination-success",
                    uid="1007",
                    pay_method="948",
                    pay_channel_name="948",
                    amount="50",
                    status="1",
                    out_trade_no="third-other-denomination",
                    create_time="2026-07-30 12:38:00",
                    create_time_utc=datetime(2026, 7, 30, 7, 8, tzinfo=UTC),
                    synced_at=now,
                ),
                ChargeOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="expired",
                    uid="1004",
                    pay_method="948",
                    pay_channel_name="948",
                    amount="30",
                    status="-1",
                    out_trade_no="third-expired",
                    create_time="2026-07-30 12:40:00",
                    create_time_utc=datetime(2026, 7, 30, 7, 10, tzinfo=UTC),
                    synced_at=now,
                ),
                ChargeOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="refunded",
                    uid="1005",
                    pay_method="948",
                    pay_channel_name="948",
                    amount="40",
                    status="2",
                    out_trade_no="third-refunded",
                    create_time="2026-07-30 12:50:00",
                    create_time_utc=datetime(2026, 7, 30, 7, 20, tzinfo=UTC),
                    synced_at=now,
                ),
                ChargeOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="outside-window",
                    uid="1003",
                    pay_method="948",
                    amount="999",
                    status="1",
                    create_time="2026-07-30 08:00:00",
                    create_time_utc=datetime(2026, 7, 30, 2, 30, tzinfo=UTC),
                    synced_at=now,
                ),
            ]
        )
        await session.commit()
        assert await ensure_charge_statuses(session, source_id="rajwin", now=now) == 4
        await session.commit()

        result = await query_charge_orders(
            session,
            request=ChargeOrderQueryRequest(
                source_id="rajwin",
                create_time_start="2026-07-30 12:00:00",
                create_time_end="2026-07-30 23:59:59",
                page=1,
                page_size=50,
            ),
            settings=settings,
            now=now,
        )
        summary = await query_charge_channel_summary(
            session,
            request=ChargeChannelSummaryRequest(
                source_id="rajwin",
                create_time_start="2026-07-30 12:00:00",
                create_time_end="2026-07-30 23:59:59",
                page=1,
                page_size=50,
            ),
            settings=settings,
            now=now,
        )

    assert result.total == 6
    assert result.summary["successful_amount"] == "250.00"
    assert result.summary["successful_order_count"] == 3
    assert result.summary["unpaid_order_count"] == 1
    assert result.status_dictionary == [
        {"code": "-1", "label": "已失效"},
        {"code": "0", "label": "待支付"},
        {"code": "1", "label": "已支付"},
        {"code": "2", "label": "已退款"},
    ]
    assert result.channel_dictionary == [{"code": "948", "label": "渠道 A"}]
    assert result.channel_name_dictionary == [{"code": "948", "label": "渠道名称 A"}]
    success_item = next(item for item in result.items if item["id"] == "success")
    assert success_item["pay_channel_name"] == "948"
    assert summary.items == [
        {
            "pay_method": "948",
            "pay_channel_name": "渠道名称 A",
            "order_count": 6,
            "successful_order_count": 3,
            "successful_amount": "250.00",
            "unpaid_order_count": 1,
            "no_third_party_order_count": 1,
            "successful_order_share": "100.00",
            "successful_amount_share": "100.00",
            "success_rate": "50.00",
        }
    ]
    assert summary.denomination_distribution == [
        {"amount": "50", "successful_order_count": 1, "successful_amount": "50.00"},
        {"amount": "100", "successful_order_count": 2, "successful_amount": "200.00"},
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_worker_refreshes_recharge_cache_and_deduplicates_by_source_and_order_id(
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
    monkeypatch.setattr(
        "packages.domain.services.charge_order_refresh_service.RajAdminChargeClient",
        FakeChargeClient,
    )
    FakeChargeClient.calls = []
    now = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    async with factory() as session:
        source = SourceConfig(
            source_id="rajwin",
            display_name="RajWin",
            base_url="https://rajwin.example.test",
            enabled=True,
            business_timezone="Asia/Kolkata",
            currency="INR",
            credential_version=1,
        )
        source.encrypted_credentials = encrypt_credentials(
            {"username": "reader", "password": "test-password", "totp_secret": "JBSWY3DPEHPK3PXP"},
            source_id=source.source_id,
            credential_version=source.credential_version,
            settings=settings,
        )
        session.add_all(
            [
                source,
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                    withdraw_order_refresh_interval_hours=1,
                    withdraw_order_refresh_page_size=100,
                    withdraw_order_query_range="today",
                    charge_order_export_date_mode="previous_day",
                ),
            ]
        )
        await session.commit()

        outcomes = await run_due_charge_order_refreshes(session, now=now, settings=settings)
        snapshot = await session.scalar(select(ChargeOrderSnapshot))
        sync_run = await session.scalar(select(DataSyncRun))
        sync_events = list(
            await session.scalars(
                select(DataSyncRunEvent).order_by(
                    DataSyncRunEvent.occurred_at,
                    DataSyncRunEvent.id,
                )
            )
        )

    assert [item.status for item in outcomes] == ["succeeded"]
    assert FakeChargeClient.calls == [
        {
            "base_url": "https://rajwin.example.test",
            "page_size": 100,
            "create_start": "2026-07-29 00:00:00",
            "create_end": "2026-07-29 23:59:59",
        }
    ]
    assert snapshot is not None
    assert snapshot.remote_order_id == "safe-1"
    assert snapshot.pay_method == "948"
    assert snapshot.create_time_utc is not None
    assert snapshot.create_time_utc.replace(tzinfo=UTC) == datetime(2026, 7, 29, 10, 0, tzinfo=UTC)
    assert sync_run is not None
    assert (sync_run.business_type, sync_run.trigger_type, sync_run.status) == (
        "charge_orders",
        "automatic",
        "succeeded",
    )
    assert (sync_run.remote_total, sync_run.cached_total, sync_run.imported_count) == (1, 1, 1)
    assert [event.event_type for event in sync_events] == [
        "running",
        "remote_export_started",
        "remote_export_fetched",
        "completed",
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_worker_refreshes_charge_cache_at_the_configured_export_time(
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
    monkeypatch.setattr(
        "packages.domain.services.charge_order_refresh_service.RajAdminChargeClient",
        FakeChargeClient,
    )
    FakeChargeClient.calls = []
    source = SourceConfig(
        source_id="rajwin",
        display_name="RajWin",
        base_url="https://rajwin.example.test",
        enabled=True,
        business_timezone="Asia/Kolkata",
        currency="INR",
        credential_version=1,
    )
    source.encrypted_credentials = encrypt_credentials(
        {"username": "reader", "password": "test-password", "totp_secret": "JBSWY3DPEHPK3PXP"},
        source_id=source.source_id,
        credential_version=source.credential_version,
        settings=settings,
    )
    retention = SystemRetentionSetting(
        id=1,
        uploaded_file_retention_days=3,
        result_retention_days=30,
        remote_cache_retention_days=30,
        charge_order_export_date_mode="previous_day",
        charge_order_export_time=time(2, 3, 4),
    )
    # Asia/Kolkata 02:03:03 / 02:03:04 on 2026-07-31.
    before_due = datetime(2026, 7, 30, 20, 33, 3, tzinfo=UTC)
    due = datetime(2026, 7, 30, 20, 33, 4, tzinfo=UTC)

    async with factory() as session:
        session.add_all([source, retention])
        await session.commit()

        assert (
            await run_due_charge_order_refreshes(
                session,
                now=before_due,
                settings=settings,
            )
            == []
        )
        outcomes = await run_due_charge_order_refreshes(session, now=due, settings=settings)

    assert [item.status for item in outcomes] == ["succeeded"]
    assert FakeChargeClient.calls == [
        {
            "base_url": "https://rajwin.example.test",
            "page_size": 100,
            "create_start": "2026-07-30 00:00:00",
            "create_end": "2026-07-30 23:59:59",
        }
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_manual_charge_export_uses_yesterday_by_default_and_is_not_limited_by_midnight(
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
    monkeypatch.setattr(
        "packages.domain.services.charge_order_refresh_service.RajAdminChargeClient",
        FakeChargeClient,
    )
    FakeChargeClient.calls = []
    now = datetime(2026, 7, 29, 18, 20, tzinfo=UTC)  # India: 2026-07-29 23:50
    async with factory() as session:
        source = SourceConfig(
            source_id="rajwin",
            display_name="RajWin",
            base_url="https://rajwin.example.test",
            enabled=True,
            business_timezone="Asia/Kolkata",
            currency="INR",
            credential_version=1,
        )
        source.encrypted_credentials = encrypt_credentials(
            {"username": "reader", "password": "test-password", "totp_secret": "JBSWY3DPEHPK3PXP"},
            source_id=source.source_id,
            credential_version=source.credential_version,
            settings=settings,
        )
        session.add(source)
        await session.commit()

        queued = await queue_charge_order_refreshes(
            session,
            source_id="rajwin",
            actor_user_id=None,
            now=now,
        )
        outcomes = await run_due_charge_order_refreshes(session, now=now, settings=settings)

    assert queued.query_range == "yesterday"
    assert [item.status for item in outcomes] == ["succeeded"]
    assert FakeChargeClient.calls == [
        {
            "base_url": "https://rajwin.example.test",
            "page_size": 100,
            "create_start": "2026-07-28 00:00:00",
            "create_end": "2026-07-28 23:59:59",
        }
    ]
    await engine.dispose()
