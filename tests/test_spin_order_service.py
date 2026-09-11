from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.security import encrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    DataDictionaryEntry,
    DataSyncRun,
    DataSyncRunEvent,
    SourceConfig,
    SpinOrderSnapshot,
    SystemRetentionSetting,
    UserChannelCache,
)
from packages.domain.schemas.spin_order import (
    SpinChannelSummaryRequest,
    SpinOrderQueryRequest,
)
from packages.domain.services.data_dictionary_service import ensure_spin_order_statuses
from packages.domain.services.remote_spin_service import (
    RajAdminSpinClient,
    SpinFetchResult,
    normalize_spin_order,
)
from packages.domain.services.spin_order_refresh_service import (
    _automatic_slot_is_ready,
    _automatic_window,
    run_due_spin_order_refreshes,
)
from packages.domain.services.spin_order_service import (
    query_spin_channel_summary,
    query_spin_orders,
    summarize_spin_orders,
)


class FakeSpinClient:
    calls: list[dict[str, object]] = []

    def __init__(self, *, base_url: str, page_size: int = 100, **_: object) -> None:
        self.base_url = base_url
        self.page_size = page_size

    async def __aenter__(self) -> FakeSpinClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def login(self) -> str:
        return "test-token"

    async def fetch_spin_orders(self, **kwargs: object) -> SpinFetchResult:
        FakeSpinClient.calls.append(
            {"base_url": self.base_url, "page_size": self.page_size, **kwargs}
        )
        return SpinFetchResult(
            orders=[
                {
                    "remote_order_id": "remote-1",
                    "uid": "101",
                    "vip_level": "1",
                    "agent_total_count": "5",
                    "amount": "20000",
                    "spin_config_id": "10001",
                    "round_number": "2",
                    "invite_count": "3",
                    "status": "1",
                    "create_time": "2026-07-30 09:30:00",
                    "audit_time": "2026-07-30 09:31:00",
                    "account": "must-not-persist",
                }
            ],
            fetched_pages=5,
            remote_total=1,
            complete=True,
        )

    async def fetch_user_channel(self, *, uid: str) -> str | None:
        assert uid == "101"
        return "source-a"


def _settings() -> Settings:
    return Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )


def _source(settings: Settings) -> SourceConfig:
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
        {
            "username": "reader",
            "password": "test-password",
            "totp_secret": "JBSWY3DPEHPK3PXP",
        },
        source_id=source.source_id,
        credential_version=source.credential_version,
        settings=settings,
    )
    return source


def _retention() -> SystemRetentionSetting:
    return SystemRetentionSetting(
        id=1,
        uploaded_file_retention_days=3,
        result_retention_days=30,
        remote_cache_retention_days=30,
        withdraw_order_export_date_mode="previous_day",
    )


def test_spin_order_normalizer_and_summary_keep_only_approved_reporting_fields() -> None:
    normalized = normalize_spin_order(
        {
            "id": 9,
            "uid": 12,
            "vip_level": 1,
            "agent_total_count": 3,
            "amount": 20000,
            "spin_id": 10001,
            "round": 2,
            "invite_count": 4,
            "status": 101,
            "create_time": "2026-07-30 10:00:00",
            "audit_time": "2026-07-30 10:01:00",
            "mobile": "must-not-persist",
            "account": "must-not-persist",
        },
        requested_status="101",
    )
    assert normalized["remote_order_id"] == "9"
    assert normalized["spin_config_id"] == "10001"
    assert "mobile" not in normalized
    assert "account" not in normalized

    summary = summarize_spin_orders(
        [
            {"uid": "1", "status": "1"},
            {"uid": "1", "status": "0"},
            {"uid": "2", "status": "101"},
            {"uid": "3", "status": "2"},
            {"uid": "4", "status": "3"},
        ]
    )
    assert summary["passed_order_count"] == 2
    assert summary["approval_rate"] == "40.00"
    assert summary["winner_count"] == 4
    assert summary["passed_winner_count"] == 2
    assert summary["person_approval_rate"] == "50.00"


def test_configured_spin_automatic_window_uses_interval_and_query_range() -> None:
    # 10:05 India time: for a four-hour cadence, 04:00–07:59 is complete.
    now = datetime(2026, 7, 30, 4, 35, tzinfo=UTC)
    start, end = _automatic_window(
        timezone_name="Asia/Kolkata",
        now=now,
        interval_hours=4,
        query_range="business_day_to_completed_slot",
    )

    assert start == datetime(2026, 7, 29, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 7, 30, 2, 29, 59, tzinfo=UTC)
    assert _automatic_slot_is_ready(
        timezone_name="Asia/Kolkata", now=now, interval_hours=4
    )


def test_spin_automatic_window_supports_recent_hours_and_previous_day() -> None:
    # 10:05 India time; completed-slot endpoint is 09:59:59.
    now = datetime(2026, 7, 30, 4, 35, tzinfo=UTC)
    recent_start, recent_end = _automatic_window(
        timezone_name="Asia/Kolkata",
        now=now,
        interval_hours=2,
        query_range="last_3_hours",
    )
    previous_day_start, previous_day_end = _automatic_window(
        timezone_name="Asia/Kolkata",
        now=now,
        interval_hours=2,
        query_range="previous_day",
    )

    assert recent_start == datetime(2026, 7, 30, 1, 30, tzinfo=UTC)
    assert recent_end == datetime(2026, 7, 30, 4, 29, 59, tzinfo=UTC)
    assert previous_day_start == datetime(2026, 7, 28, 18, 30, tzinfo=UTC)
    assert previous_day_end == datetime(2026, 7, 29, 18, 29, 59, tzinfo=UTC)


@pytest.mark.asyncio
async def test_source_channel_dictionary_skips_remote_aggregate_option() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/stat/userPayLtvLog/channel"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "channelList": {
                        "-": "全部渠道",
                        "source-a": "渠道 A",
                    }
                },
            },
        )

    async with RajAdminSpinClient(
        base_url="https://rajwin.example.test",
        username="reader",
        password="test-password",
        totp_secret="JBSWY3DPEHPK3PXP",
        transport=httpx.MockTransport(handler),
    ) as client:
        client._token = "test-token"
        assert await client.fetch_user_source_channels() == [
            {"code": "source-a", "label": "渠道 A"}
        ]


@pytest.mark.asyncio
async def test_spin_query_and_channel_summary_only_read_local_cache() -> None:
    settings = _settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)
    async with factory() as session:
        session.add_all(
            [
                _source(settings),
                _retention(),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type="user_source_channel",
                    entry_code="source-a",
                    entry_label="渠道 A",
                    active=True,
                    first_seen_at=now,
                    last_seen_at=now,
                    updated_at=now,
                ),
                SpinOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="pass",
                    uid="1",
                    spin_config_id="10001",
                    status="1",
                    channel_id="source-a",
                    create_time="2026-07-30 12:00:00",
                    create_time_utc=datetime(2026, 7, 30, 6, 30, tzinfo=UTC),
                    synced_at=now,
                ),
                SpinOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="auto",
                    uid="2",
                    spin_config_id="10001",
                    status="101",
                    channel_id="source-a",
                    create_time="2026-07-30 12:20:00",
                    create_time_utc=datetime(2026, 7, 30, 6, 50, tzinfo=UTC),
                    synced_at=now,
                ),
                SpinOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="pending",
                    uid="2",
                    spin_config_id="10001",
                    status="0",
                    channel_id="source-a",
                    create_time="2026-07-30 12:30:00",
                    create_time_utc=datetime(2026, 7, 30, 7, 0, tzinfo=UTC),
                    synced_at=now,
                ),
                SpinOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="rejected",
                    uid="3",
                    spin_config_id="10002",
                    status="2",
                    channel_id="unregistered",
                    create_time="2026-07-30 12:40:00",
                    create_time_utc=datetime(2026, 7, 30, 7, 10, tzinfo=UTC),
                    synced_at=now,
                ),
                SpinOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="suspended",
                    uid="4",
                    spin_config_id="10002",
                    status="3",
                    create_time="2026-07-30 12:50:00",
                    create_time_utc=datetime(2026, 7, 30, 7, 20, tzinfo=UTC),
                    synced_at=now,
                ),
            ]
        )
        await session.commit()
        assert await ensure_spin_order_statuses(session, source_id="rajwin", now=now) == 5
        await session.commit()

        result = await query_spin_orders(
            session,
            request=SpinOrderQueryRequest(
                source_id="rajwin",
                create_time_start="2026-07-30 12:00:00",
                create_time_end="2026-07-30 23:59:59",
                page=1,
                page_size=50,
            ),
            settings=settings,
            now=now,
        )
        channel_summary = await query_spin_channel_summary(
            session,
            request=SpinChannelSummaryRequest(
                source_id="rajwin",
                create_time_start="2026-07-30 12:00:00",
                create_time_end="2026-07-30 23:59:59",
                page=1,
                page_size=50,
            ),
            settings=settings,
            now=now,
        )

    assert result.total == 5
    assert result.summary["passed_order_count"] == 2
    assert result.summary["winner_count"] == 4
    assert result.summary["passed_winner_count"] == 2
    assert result.summary["approval_rate"] == "40.00"
    assert {item["channel_name"] for item in result.items} == {
        "渠道 A",
        "未登记渠道",
        "渠道待解析",
    }
    assert [(item["code"], item["label"]) for item in result.status_dictionary] == [
        ("0", "待审核"),
        ("1", "审核通过"),
        ("101", "自动审核通过"),
        ("2", "已拒绝"),
        ("3", "已挂起"),
    ]
    source_a = next(item for item in channel_summary.items if item["channel_id"] == "source-a")
    assert source_a["application_order_count"] == 3
    assert source_a["winner_count"] == 2
    assert source_a["passed_winner_count"] == 2
    assert channel_summary.time_series[0]["applicant_count"] == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_two_hour_worker_refreshes_all_orders_and_minimal_uid_channel_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(
        "packages.domain.services.spin_order_refresh_service.RajAdminSpinClient",
        FakeSpinClient,
    )
    FakeSpinClient.calls = []
    # 10:05 India time: the 08:00–09:59 completed slot is eligible.
    run_at = datetime(2026, 7, 30, 4, 35, tzinfo=UTC)
    async with factory() as session:
        session.add_all([_source(settings), _retention()])
        await session.commit()
        outcomes = await run_due_spin_order_refreshes(session, now=run_at, settings=settings)
        snapshot = await session.scalar(select(SpinOrderSnapshot))
        channel_cache = await session.scalar(select(UserChannelCache))
        sync_run = await session.scalar(select(DataSyncRun))
        sync_events = list(
            await session.scalars(
                select(DataSyncRunEvent).order_by(
                    DataSyncRunEvent.occurred_at,
                    DataSyncRunEvent.id,
                )
            )
        )

    assert [outcome.status for outcome in outcomes] == ["succeeded"]
    assert FakeSpinClient.calls[0]["create_start"] == "2026-07-29 00:00:00"
    assert FakeSpinClient.calls[0]["create_end"] == "2026-07-30 09:59:59"
    assert snapshot is not None
    assert snapshot.channel_id == "source-a"
    assert not hasattr(snapshot, "account")
    assert channel_cache is not None
    assert (channel_cache.uid, channel_cache.channel_id, channel_cache.resolution_status) == (
        "101",
        "source-a",
        "resolved",
    )
    assert sync_run is not None
    assert (sync_run.business_type, sync_run.trigger_type, sync_run.status) == (
        "spin_orders",
        "automatic",
        "succeeded",
    )
    assert (
        sync_run.remote_total,
        sync_run.cached_total,
        sync_run.fetched_pages,
        sync_run.resolved_uid_count,
        sync_run.unresolved_uid_count,
    ) == (1, 1, 5, 1, 0)
    assert [event.event_type for event in sync_events] == [
        "running",
        "remote_fetch_started",
        "remote_fetch_completed",
        "uid_channel_resolution_started",
        "uid_channel_resolution_completed",
        "completed",
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_worker_uses_configured_spin_page_size_and_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(
        "packages.domain.services.spin_order_refresh_service.RajAdminSpinClient",
        FakeSpinClient,
    )
    FakeSpinClient.calls = []
    run_at = datetime(2026, 7, 30, 4, 35, tzinfo=UTC)
    async with factory() as session:
        retention = _retention()
        retention.spin_order_refresh_interval_hours = 4
        retention.spin_order_refresh_page_size = 50
        retention.spin_order_query_range = "business_day_to_completed_slot"
        session.add_all([_source(settings), retention])
        await session.commit()
        outcomes = await run_due_spin_order_refreshes(session, now=run_at, settings=settings)

    assert [outcome.status for outcome in outcomes] == ["succeeded"]
    assert FakeSpinClient.calls[0]["page_size"] == 50
    assert FakeSpinClient.calls[0]["create_start"] == "2026-07-30 00:00:00"
    assert FakeSpinClient.calls[0]["create_end"] == "2026-07-30 07:59:59"
    await engine.dispose()
