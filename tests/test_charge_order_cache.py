from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.security import encrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    ChargeOrderSnapshot,
    DataDictionaryEntry,
    SourceConfig,
    SystemRetentionSetting,
)
from packages.domain.schemas.charge_order import (
    ChargeChannelSummaryRequest,
    ChargeOrderQueryRequest,
)
from packages.domain.services.charge_order_refresh_service import run_due_charge_order_refreshes
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

    async def fetch_channels(self) -> list[dict[str, str]]:
        return [{"code": "948", "label": "渠道名称选项 A"}]

    async def fetch_payment_channels(self) -> list[dict[str, str]]:
        return [{"code": "948", "label": "渠道 A"}]

    async def fetch_all_charge_orders(self, **kwargs: object) -> ChargeFetchResult:
        on_page_fetched = kwargs.pop("on_page_fetched")
        FakeChargeClient.calls.append(
            {"base_url": self.base_url, "page_size": self.page_size, **kwargs}
        )
        await on_page_fetched()  # type: ignore[misc]
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
                    "create_time": "2026-07-30 15:30:00",
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
            request=ChargeOrderQueryRequest(source_id="rajwin", page=1, page_size=50),
            settings=settings,
            now=now,
        )
        summary = await query_charge_channel_summary(
            session,
            request=ChargeChannelSummaryRequest(source_id="rajwin", page=1, page_size=50),
            settings=settings,
            now=now,
        )

    assert result.total == 4
    assert result.summary["successful_amount"] == "100.00"
    assert result.summary["successful_order_count"] == 1
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
            "order_count": 4,
            "successful_order_count": 1,
            "successful_amount": "100.00",
            "unpaid_order_count": 1,
            "no_third_party_order_count": 1,
            "successful_order_share": "100.00",
            "successful_amount_share": "100.00",
            "success_rate": "25.00",
        }
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
                    charge_order_refresh_interval_hours=24,
                    charge_order_refresh_page_size=50,
                    charge_order_query_range="today",
                ),
            ]
        )
        await session.commit()

        outcomes = await run_due_charge_order_refreshes(session, now=now, settings=settings)
        snapshot = await session.scalar(select(ChargeOrderSnapshot))

    assert [item.status for item in outcomes] == ["succeeded"]
    assert FakeChargeClient.calls == [
        {
            "base_url": "https://rajwin.example.test",
            "page_size": 50,
            "channels": [{"code": "948", "label": "渠道 A"}],
            "create_start": "2026-07-30 00:00:00",
            "create_end": "2026-07-30 15:30:00",
        }
    ]
    assert snapshot is not None
    assert snapshot.remote_order_id == "safe-1"
    assert snapshot.pay_method == "948"
    assert snapshot.create_time_utc is not None
    assert snapshot.create_time_utc.replace(tzinfo=UTC) == datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    await engine.dispose()
