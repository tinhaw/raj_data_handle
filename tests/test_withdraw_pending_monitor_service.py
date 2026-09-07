from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.security import encrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import Base, SourceConfig, SystemRetentionSetting
from packages.domain.services.remote_charge_service import RemoteResponseError
from packages.domain.services.withdraw_pending_monitor_service import (
    query_withdraw_pending_monitor,
)


class FakeWithdrawClient:
    outcomes: dict[tuple[str, str], int | BaseException] = {}
    calls: list[dict[str, object]] = []

    def __init__(self, *, base_url: str, **_: object) -> None:
        self.base_url = base_url

    async def __aenter__(self) -> FakeWithdrawClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def fetch_withdraw_status_summary(self, **kwargs: str) -> int:
        FakeWithdrawClient.calls.append({"base_url": self.base_url, **kwargs})
        outcome = FakeWithdrawClient.outcomes[(self.base_url, kwargs["status"])]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _settings() -> Settings:
    return Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )


def _source(settings: Settings, source_id: str) -> SourceConfig:
    source = SourceConfig(
        source_id=source_id,
        display_name=source_id.title(),
        display_order=1 if source_id == "rajwin" else 2,
        base_url=f"https://{source_id}.example.test",
        enabled=True,
        business_timezone="Asia/Shanghai",
        currency="INR",
        credential_version=1,
    )
    source.encrypted_credentials = encrypt_credentials(
        {
            "username": "reader",
            "password": "test-password",
            "totp_secret": "JBSWY3DPEHPK3PXP",
        },
        source_id=source_id,
        credential_version=1,
        settings=settings,
    )
    return source


@pytest.mark.asyncio
async def test_pending_monitor_combines_only_successful_markets_and_projects_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    rajwin = _source(settings, "rajwin")
    rajluck = _source(settings, "rajluck")
    FakeWithdrawClient.outcomes = {
        (rajwin.base_url or "", "0"): 7,
        (rajwin.base_url or "", "4"): 3,
        (rajluck.base_url or "", "0"): RemoteResponseError("safe test failure"),
    }
    FakeWithdrawClient.calls = []
    monkeypatch.setattr(
        "packages.domain.services.withdraw_pending_monitor_service.RajAdminWithdrawClient",
        FakeWithdrawClient,
    )

    async with factory() as session:
        session.add_all(
            [
                rajwin,
                rajluck,
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                    withdraw_order_refresh_interval_hours=2,
                    withdraw_order_query_range="last_3_hours",
                    remote_order_sync_timeout_seconds=90,
                ),
            ]
        )
        await session.commit()

        result = await query_withdraw_pending_monitor(
            session,
            settings=settings,
            now=datetime(2026, 9, 8, 10, 30, 45, tzinfo=UTC),
        )

    assert result.query_range == "last_3_hours"
    assert result.refresh_interval_hours == 2
    assert result.successful_source_count == 1
    assert result.pending_audit_total == 7
    assert result.pending_review_total == 3
    assert [(row.source_id, row.status) for row in result.sources] == [
        ("rajwin", "succeeded"),
        ("rajluck", "failed"),
    ]
    assert result.sources[0].create_time_start == "2026-09-08 15:30:45"
    assert result.sources[0].create_time_end == "2026-09-08 18:30:45"
    assert result.sources[1].pending_audit_count == 0
    assert result.sources[1].pending_review_count == 0
    assert result.sources[1].message == "远端提现汇总查询失败，请稍后刷新或检查盘口连接。"
    assert FakeWithdrawClient.calls == [
        {
            "base_url": "https://rajwin.example.test",
            "create_start": "2026-09-08T07:30:45.000Z",
            "create_end": "2026-09-08T10:30:45.000Z",
            "status": "0",
        },
        {
            "base_url": "https://rajwin.example.test",
            "create_start": "2026-09-08T07:30:45.000Z",
            "create_end": "2026-09-08T10:30:45.000Z",
            "status": "4",
        },
        {
            "base_url": "https://rajluck.example.test",
            "create_start": "2026-09-08T07:30:45.000Z",
            "create_end": "2026-09-08T10:30:45.000Z",
            "status": "0",
        },
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_pending_monitor_marks_market_without_analysis_account_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    source = SourceConfig(
        source_id="rajwin",
        display_name="RajWin",
        base_url="https://rajwin.example.test",
        enabled=True,
        business_timezone="Asia/Shanghai",
        currency="INR",
    )
    FakeWithdrawClient.calls = []
    monkeypatch.setattr(
        "packages.domain.services.withdraw_pending_monitor_service.RajAdminWithdrawClient",
        FakeWithdrawClient,
    )

    async with factory() as session:
        session.add(source)
        await session.commit()
        result = await query_withdraw_pending_monitor(
            session,
            settings=settings,
            now=datetime(2026, 9, 8, 10, 30, tzinfo=UTC),
        )

    assert result.successful_source_count == 0
    assert result.pending_audit_total == 0
    assert result.pending_review_total == 0
    assert result.sources[0].status == "unavailable"
    assert result.sources[0].message == "未配置可用于数据分析读取的默认远端账号。"
    assert FakeWithdrawClient.calls == []
    await engine.dispose()
