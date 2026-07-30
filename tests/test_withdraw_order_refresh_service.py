from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.security import encrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    SourceConfig,
    SystemRetentionSetting,
    WithdrawOrderRefreshState,
    WithdrawOrderSnapshot,
)
from packages.domain.schemas.withdraw_order import WithdrawOrderQueryRequest
from packages.domain.services.remote_withdraw_service import WithdrawFetchResult
from packages.domain.services.retention_cleanup_service import cleanup_expired_data
from packages.domain.services.withdraw_order_refresh_service import (
    queue_withdraw_order_refreshes,
    run_due_withdraw_order_refreshes,
)
from packages.domain.services.withdraw_order_service import (
    query_withdraw_orders,
    withdraw_order_query_window,
)


class FakeWithdrawClient:
    outcomes: dict[str, WithdrawFetchResult | BaseException] = {}
    calls: list[dict[str, object]] = []

    def __init__(self, *, base_url: str, **_: object) -> None:
        self.base_url = base_url

    async def __aenter__(self) -> FakeWithdrawClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def fetch_all_withdraw_orders(self, **kwargs: object) -> WithdrawFetchResult:
        on_page_fetched = kwargs.pop("on_page_fetched", None)
        FakeWithdrawClient.calls.append({"base_url": self.base_url, **kwargs})
        outcome = FakeWithdrawClient.outcomes[self.base_url]
        if isinstance(outcome, BaseException):
            raise outcome
        if on_page_fetched is not None:
            await on_page_fetched()  # type: ignore[misc]
        return outcome


class FakeStorage:
    async def delete(self, _: str) -> None:
        return None


def _settings() -> Settings:
    return Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
        withdraw_order_refresh_interval_hours=24,
    )


def _source(settings: Settings, *, source_id: str, base_url: str) -> SourceConfig:
    source = SourceConfig(
        source_id=source_id,
        display_name=source_id.title(),
        base_url=base_url,
        enabled=True,
        business_timezone="Asia/Kolkata",
        currency="INR",
        credential_version=1,
    )
    source.encrypted_credentials = encrypt_credentials(
        {"username": "reader", "password": "test-password", "totp_secret": "JBSWY3DPEHPK3PXP"},
        source_id=source_id,
        credential_version=1,
        settings=settings,
    )
    return source


@pytest.mark.parametrize(
    ("query_range", "expected_start", "expected_end"),
    [
        (
            "today",
            datetime(2026, 7, 29, 18, 30, tzinfo=UTC),
            datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        ),
        (
            "last_1_hour",
            datetime(2026, 7, 30, 9, 0, tzinfo=UTC),
            datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        ),
        (
            "last_2_hours",
            datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
            datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        ),
        (
            "last_3_hours",
            datetime(2026, 7, 30, 7, 0, tzinfo=UTC),
            datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        ),
        (
            "last_6_hours",
            datetime(2026, 7, 30, 4, 0, tzinfo=UTC),
            datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        ),
        (
            "last_12_hours",
            datetime(2026, 7, 29, 22, 0, tzinfo=UTC),
            datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        ),
        (
            "last_24_hours",
            datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
            datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        ),
        (
            "last_48_hours",
            datetime(2026, 7, 28, 10, 0, tzinfo=UTC),
            datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        ),
    ],
)
def test_refresh_query_windows_are_limited_to_the_allowed_source_time_presets(
    query_range: str,
    expected_start: datetime,
    expected_end: datetime,
) -> None:
    start, end = withdraw_order_query_window(
        query_range=query_range,
        timezone_name="Asia/Kolkata",
        now=datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
    )

    assert (start, end) == (expected_start, expected_end)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 3, 8, 17, 0, tzinfo=UTC),
        datetime(2026, 11, 1, 17, 0, tzinfo=UTC),
    ],
)
def test_rolling_refresh_windows_are_exact_hours_across_dst(now: datetime) -> None:
    start, end = withdraw_order_query_window(
        query_range="last_24_hours",
        timezone_name="America/New_York",
        now=now,
    )

    assert end == now
    assert end - start == timedelta(hours=24)


@pytest.mark.asyncio
async def test_worker_refreshes_approved_fields_then_page_reads_the_local_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    FakeWithdrawClient.calls = []
    FakeWithdrawClient.outcomes = {
        "https://rajwin.example.test": WithdrawFetchResult(
            orders=[
                {
                    "id": "safe-1",
                    "uid": "100",
                    "amount": "500.00",
                    "real_amount": "490.00",
                    "create_time": "2026-07-30 10:00:00",
                    "update_time": "2026-07-30 10:01:00",
                    "submit_time": "2026-07-30 10:02:00",
                    "audit_admin": "operator",
                    "status": "3",
                    "info": {"account": "must-not-persist"},
                    "ip": "192.0.2.1",
                }
            ],
            fetched_pages=1,
            remote_total=1,
            complete=True,
        )
    }
    monkeypatch.setattr(
        "packages.domain.services.withdraw_order_refresh_service.RajAdminWithdrawClient",
        FakeWithdrawClient,
    )

    refresh_time = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    async with factory() as session:
        session.add_all(
            [
                _source(settings, source_id="rajwin", base_url="https://rajwin.example.test"),
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                    withdraw_order_refresh_interval_hours=24,
                    withdraw_order_query_range="today",
                ),
            ]
        )
        await session.commit()

        outcomes = await run_due_withdraw_order_refreshes(
            session,
            now=refresh_time,
            settings=settings,
        )
        snapshot = await session.scalar(select(WithdrawOrderSnapshot))
        state = await session.get(
            WithdrawOrderRefreshState,
            "rajwin",
            populate_existing=True,
        )
        local_result = await query_withdraw_orders(
            session,
            request=WithdrawOrderQueryRequest(source_id="rajwin"),
            now=refresh_time,
            settings=settings,
        )

    assert [result.status for result in outcomes] == ["succeeded"]
    assert FakeWithdrawClient.calls == [
        {
            "base_url": "https://rajwin.example.test",
            "create_start": "2026-07-29T18:30:00.000Z",
            "create_end": "2026-07-30T10:00:00.000Z",
        }
    ]
    assert snapshot is not None
    assert snapshot.remote_order_id == "safe-1"
    assert snapshot.uid == "100"
    assert snapshot.amount == "500.00"
    assert snapshot.status == "3"
    assert not hasattr(snapshot, "info")
    assert not hasattr(snapshot, "ip")
    assert state is not None
    assert state.status == "succeeded"
    assert state.last_remote_total == 1
    assert local_result.items == [
        {
            "id": "safe-1",
            "uid": "100",
            "amount": "500.00",
            "real_amount": "490.00",
            "create_time": "2026-07-30 10:00:00",
            "update_time": "2026-07-30 10:01:00",
            "submit_time": "2026-07-30 10:02:00",
            "audit_admin": "operator",
            "status": "3",
        }
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_manual_queue_overrides_interval_but_not_an_active_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    FakeWithdrawClient.calls = []
    FakeWithdrawClient.outcomes = {
        "https://rajwin.example.test": WithdrawFetchResult(
            orders=[], fetched_pages=1, remote_total=0, complete=True
        )
    }
    monkeypatch.setattr(
        "packages.domain.services.withdraw_order_refresh_service.RajAdminWithdrawClient",
        FakeWithdrawClient,
    )

    started_at = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    async with factory() as session:
        session.add_all(
            [
                _source(settings, source_id="rajwin", base_url="https://rajwin.example.test"),
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                    withdraw_order_refresh_interval_hours=24,
                    withdraw_order_query_range="today",
                ),
            ]
        )
        await session.commit()
        assert len(
            await run_due_withdraw_order_refreshes(
                session,
                now=started_at,
                settings=settings,
            )
        ) == 1

        queued = await queue_withdraw_order_refreshes(
            session,
            source_id="rajwin",
            actor_user_id=None,
            now=started_at + timedelta(minutes=1),
        )
        assert queued.source_ids == ["rajwin"]
        assert len(
            await run_due_withdraw_order_refreshes(
                session,
                now=started_at + timedelta(minutes=1),
                settings=settings,
            )
        ) == 1

        state = await session.get(WithdrawOrderRefreshState, "rajwin")
        assert state is not None
        state.status = "running"
        state.last_started_at = started_at + timedelta(minutes=2)
        state.lease_expires_at = started_at + timedelta(hours=1)
        state.manual_request_at = started_at + timedelta(minutes=3)
        await session.commit()
        assert await run_due_withdraw_order_refreshes(
            session,
            now=started_at + timedelta(minutes=4),
            settings=settings,
        ) == []

    assert len(FakeWithdrawClient.calls) == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_refresh_releases_lease_and_requeues_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    FakeWithdrawClient.calls = []
    FakeWithdrawClient.outcomes = {
        "https://rajwin.example.test": asyncio.CancelledError(),
    }
    monkeypatch.setattr(
        "packages.domain.services.withdraw_order_refresh_service.RajAdminWithdrawClient",
        FakeWithdrawClient,
    )

    started_at = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    async with factory() as session:
        session.add_all(
            [
                _source(settings, source_id="rajwin", base_url="https://rajwin.example.test"),
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                    withdraw_order_refresh_interval_hours=24,
                    withdraw_order_query_range="today",
                ),
            ]
        )
        await session.commit()

        with pytest.raises(asyncio.CancelledError):
            await run_due_withdraw_order_refreshes(
                session,
                now=started_at,
                settings=settings,
            )
        state = await session.get(WithdrawOrderRefreshState, "rajwin", populate_existing=True)

    assert state is not None
    assert state.status == "queued"
    assert state.lease_expires_at is None
    assert state.manual_request_at is not None
    assert state.last_error == "后台同步在工作进程停止前中断，已重新排队。"
    await engine.dispose()


@pytest.mark.asyncio
async def test_one_refresh_failure_is_persisted_and_does_not_block_another_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    FakeWithdrawClient.calls = []
    FakeWithdrawClient.outcomes = {
        "https://bad.example.test": RuntimeError("Bearer should never be persisted"),
        "https://good.example.test": WithdrawFetchResult(
            orders=[], fetched_pages=1, remote_total=0, complete=True
        ),
    }
    monkeypatch.setattr(
        "packages.domain.services.withdraw_order_refresh_service.RajAdminWithdrawClient",
        FakeWithdrawClient,
    )

    async with factory() as session:
        session.add_all(
            [
                _source(settings, source_id="bad", base_url="https://bad.example.test"),
                _source(settings, source_id="good", base_url="https://good.example.test"),
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                    withdraw_order_refresh_interval_hours=24,
                    withdraw_order_query_range="today",
                ),
            ]
        )
        await session.commit()
        outcomes = await run_due_withdraw_order_refreshes(
            session,
            now=datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
            settings=settings,
        )
        states = {
            state.source_id: state
            for state in await session.scalars(
                select(WithdrawOrderRefreshState).order_by(WithdrawOrderRefreshState.source_id)
            )
        }

    assert [(outcome.source_id, outcome.status) for outcome in outcomes] == [
        ("bad", "failed"),
        ("good", "succeeded"),
    ]
    assert states["bad"].last_error == "远端提现订单读取失败，请稍后重试。"
    assert "Bearer" not in (states["bad"].last_error or "")
    assert states["good"].status == "succeeded"
    await engine.dispose()


@pytest.mark.asyncio
async def test_retention_cleanup_removes_only_expired_withdraw_order_snapshots() -> None:
    settings = _settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
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
                    remote_cache_retention_days=3,
                    withdraw_order_refresh_interval_hours=24,
                    withdraw_order_query_range="today",
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="expired",
                    uid="100",
                    status="0",
                    synced_at=now - timedelta(days=4),
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="retained",
                    uid="101",
                    status="3",
                    synced_at=now - timedelta(days=2),
                ),
            ]
        )
        await session.commit()
        counts = await cleanup_expired_data(session, storage=FakeStorage(), now=now)
        remaining_ids = list(await session.scalars(select(WithdrawOrderSnapshot.remote_order_id)))

    assert counts["deletedWithdrawOrderSnapshots"] == 1
    assert remaining_ids == ["retained"]
    await engine.dispose()
