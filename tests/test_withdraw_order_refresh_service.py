from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.common.security import encrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    DataSyncRun,
    DataSyncRunEvent,
    SourceConfig,
    SystemRetentionSetting,
    WithdrawOrderRefreshState,
    WithdrawOrderSnapshot,
)
from packages.domain.services.remote_withdraw_service import WithdrawFetchResult
from packages.domain.services.withdraw_order_refresh_service import (
    queue_withdraw_order_refreshes,
    run_due_withdraw_order_refreshes,
)
from packages.domain.services.withdraw_scoring_import_service import WithdrawScoringImportResult


class FakeWithdrawClient:
    """Read-only remote double matching the Excel export client contract."""

    statuses: list[dict[str, str]] = []
    export_outcomes: dict[str, WithdrawFetchResult | BaseException] = {}
    events: list[tuple[str, object]] = []

    def __init__(self, *, base_url: str, **_: object) -> None:
        self.base_url = base_url

    async def __aenter__(self) -> FakeWithdrawClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def fetch_withdraw_statuses(self) -> list[dict[str, str]]:
        FakeWithdrawClient.events.append(("statuses", self.base_url))
        return FakeWithdrawClient.statuses

    async def export_withdraw_orders(self, **kwargs: object) -> WithdrawFetchResult:
        FakeWithdrawClient.events.append(("export", {"base_url": self.base_url, **kwargs}))
        outcome = FakeWithdrawClient.export_outcomes[self.base_url]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _settings() -> Settings:
    return Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )


def _source(settings: Settings, *, source_id: str = "rajwin") -> SourceConfig:
    source = SourceConfig(
        source_id=source_id,
        display_name=source_id.title(),
        base_url=f"https://{source_id}.example.test",
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
        source_id=source_id,
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


def _order(
    remote_order_id: str,
    *,
    status_label: str = "代付成功",
    create_time: str = "2026-07-30 10:00:00",
    audit_person: str = "Operator A",
) -> dict[str, object]:
    return {
        "remote_order_id": remote_order_id,
        "uid": "10001",
        "order_num": f"withdraw-{remote_order_id}",
        "out_trade_no": f"third-{remote_order_id}",
        "pay_channel_name": "Channel A",
        "pay_channel": "channel-a",
        "amount": "100.00",
        "fee": "3.00",
        "real_amount": "97.00",
        "is_first": "是",
        # This is deliberately changed by the refresh service from the Excel
        # label to the source-specific dictionary code.
        "status": "3",
        "status_label": status_label,
        "create_time": create_time,
        "submit_time": "2026-07-30 10:01:00",
        "update_time": "2026-07-30 10:02:00",
        "audit_person": audit_person,
        # A malformed remote double may carry such data; it must not become a
        # snapshot column or local cache payload.
        "bank_account": "must-not-persist",
        "mobile": "must-not-persist",
    }


async def _database() -> tuple[object, async_sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_daily_excel_refresh_runs_at_000501_and_caches_only_approved_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine, factory = await _database()
    source = _source(settings)
    FakeWithdrawClient.statuses = [
        {"code": "success-custom", "label": "代付成功"},
        {"code": "submitted-custom", "label": "已提交代付"},
    ]
    FakeWithdrawClient.export_outcomes = {
        source.base_url or "": WithdrawFetchResult(
            orders=[_order("one"), _order("two", status_label="已提交代付")],
            fetched_pages=1,
            remote_total=2,
            complete=True,
            export_row_count=3,
            duplicate_count=1,
        )
    }
    FakeWithdrawClient.events = []
    monkeypatch.setattr(
        "packages.domain.services.withdraw_order_refresh_service.RajAdminWithdrawClient",
        FakeWithdrawClient,
    )

    # 00:05:00 in India is still before the agreed automatic export time.
    before_due = datetime(2026, 7, 30, 18, 35, tzinfo=UTC)
    due = datetime(2026, 7, 30, 18, 35, 1, tzinfo=UTC)
    async with factory() as session:
        session.add_all([source, _retention()])
        await session.commit()

        assert (
            await run_due_withdraw_order_refreshes(
                session,
                now=before_due,
                settings=settings,
            )
            == []
        )
        result = await run_due_withdraw_order_refreshes(session, now=due, settings=settings)
        snapshots = list(
            await session.scalars(
                select(WithdrawOrderSnapshot).order_by(WithdrawOrderSnapshot.remote_order_id)
            )
        )
        state = await session.get(WithdrawOrderRefreshState, "rajwin")
        sync_run = await session.scalar(select(DataSyncRun))
        sync_events = list(
            await session.scalars(
                select(DataSyncRunEvent).order_by(
                    DataSyncRunEvent.occurred_at,
                    DataSyncRunEvent.id,
                )
            )
        )

    assert [item.status for item in result] == ["succeeded"]
    assert FakeWithdrawClient.events == [
        ("statuses", "https://rajwin.example.test"),
        (
            "export",
            {
                "base_url": "https://rajwin.example.test",
                "create_start": "2026-07-30 00:00:00",
                "create_end": "2026-07-30 23:59:59",
            },
        ),
    ]
    assert [row.remote_order_id for row in snapshots] == ["one", "two"]
    first = snapshots[0]
    assert first.order_num == "withdraw-one"
    assert first.out_trade_no == "third-one"
    assert first.pay_channel == "channel-a"
    assert first.fee == "3.00"
    assert first.audit_admin == "Operator A"
    assert first.status == "success-custom"
    assert first.status_label == "代付成功"
    assert not hasattr(first, "bank_account")
    assert not hasattr(first, "mobile")
    assert state is not None
    assert state.last_remote_total == 2
    assert state.last_cached_total == 2
    assert state.last_fetched_pages == 1
    assert state.last_complete is True
    assert state.last_export_row_count == 3
    assert state.last_imported_count == 2
    assert state.last_duplicate_count == 1
    assert sync_run is not None
    assert (sync_run.business_type, sync_run.trigger_type, sync_run.status) == (
        "withdraw_orders",
        "automatic",
        "succeeded",
    )
    assert (
        sync_run.remote_total,
        sync_run.export_row_count,
        sync_run.cached_total,
        sync_run.duplicate_count,
    ) == (2, 3, 2, 1)
    assert [event.event_type for event in sync_events] == [
        "running",
        "withdraw_status_dictionary_started",
        "withdraw_status_dictionary_fetched",
        "remote_export_started",
        "remote_export_fetched",
        "completed",
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_withdraw_refresh_skips_scoring_sync_without_a_tested_scoring_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine, factory = await _database()
    source = _source(settings)
    FakeWithdrawClient.statuses = [{"code": "success", "label": "代付成功"}]
    FakeWithdrawClient.export_outcomes = {
        source.base_url or "": WithdrawFetchResult(
            orders=[_order("without-scoring")],
            fetched_pages=1,
            remote_total=1,
            complete=True,
            export_row_count=1,
        )
    }

    async def unexpected_scoring_sync(**_: object) -> WithdrawScoringImportResult:
        raise AssertionError("未配置或未测试评分 API 时不应请求评分审核接口")

    monkeypatch.setattr(
        "packages.domain.services.withdraw_order_refresh_service.RajAdminWithdrawClient",
        FakeWithdrawClient,
    )
    monkeypatch.setattr(
        "packages.domain.services.withdraw_order_refresh_service.sync_scoring_reviewed_cases_from_remote",
        unexpected_scoring_sync,
    )
    async with factory() as session:
        session.add_all([source, _retention()])
        await session.commit()
        result = await run_due_withdraw_order_refreshes(
            session,
            now=datetime(2026, 7, 30, 18, 35, 1, tzinfo=UTC),
            settings=settings,
        )

    assert [item.status for item in result] == ["succeeded"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_withdraw_refresh_automatically_syncs_scores_for_a_tested_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine, factory = await _database()
    source = _source(settings)
    source.scoring_api_base_url = "https://scoring.rajwin.example/api"
    source.encrypted_scoring_api_key = "configured-key"
    source.scoring_api_last_test_status = "passed"
    FakeWithdrawClient.statuses = [{"code": "success", "label": "代付成功"}]
    FakeWithdrawClient.export_outcomes = {
        source.base_url or "": WithdrawFetchResult(
            orders=[_order("with-scoring")],
            fetched_pages=1,
            remote_total=1,
            complete=True,
            export_row_count=1,
        )
    }
    calls: list[dict[str, object]] = []

    async def fake_scoring_sync(
        session: AsyncSession,
        **kwargs: object,
    ) -> WithdrawScoringImportResult:
        assert await session.scalar(
            select(WithdrawOrderSnapshot).where(
                WithdrawOrderSnapshot.source_id == "rajwin",
                WithdrawOrderSnapshot.remote_order_id == "with-scoring",
            )
        )
        calls.append(kwargs)
        return WithdrawScoringImportResult(
            source_id="rajwin",
            source_row_count=1,
            matched_count=1,
            created_count=1,
            updated_count=0,
            unmatched_count=0,
            synced_at=datetime.now(UTC),
        )

    monkeypatch.setattr(
        "packages.domain.services.withdraw_order_refresh_service.RajAdminWithdrawClient",
        FakeWithdrawClient,
    )
    monkeypatch.setattr(
        "packages.domain.services.withdraw_order_refresh_service.sync_scoring_reviewed_cases_from_remote",
        fake_scoring_sync,
    )
    async with factory() as session:
        session.add_all([source, _retention()])
        await session.commit()
        result = await run_due_withdraw_order_refreshes(
            session,
            now=datetime(2026, 7, 30, 18, 35, 1, tzinfo=UTC),
            settings=settings,
        )

    assert [item.status for item in result] == ["succeeded"]
    assert calls == [
        {
            "source_id": "rajwin",
            "create_time_start": "2026-07-30 00:00:00",
            "create_time_end": "2026-07-30 23:59:59",
            "actor_user_id": None,
            "settings": settings,
            "trigger_type": "automatic",
        }
    ]
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query_range", "expected_day"),
    [
        ("day_before_yesterday", "2026-07-28"),
        ("yesterday", "2026-07-29"),
        ("today", "2026-07-30"),
    ],
)
async def test_manual_excel_refresh_uses_calendar_day_presets(
    monkeypatch: pytest.MonkeyPatch,
    query_range: str,
    expected_day: str,
) -> None:
    settings = _settings()
    engine, factory = await _database()
    source = _source(settings)
    FakeWithdrawClient.statuses = [{"code": "success", "label": "代付成功"}]
    FakeWithdrawClient.export_outcomes = {
        source.base_url or "": WithdrawFetchResult(
            orders=[_order("manual", create_time=f"{expected_day} 12:00:00")],
            fetched_pages=1,
            remote_total=1,
            complete=True,
            export_row_count=1,
        )
    }
    FakeWithdrawClient.events = []
    monkeypatch.setattr(
        "packages.domain.services.withdraw_order_refresh_service.RajAdminWithdrawClient",
        FakeWithdrawClient,
    )
    queued_at = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    async with factory() as session:
        session.add_all([source, _retention()])
        await session.commit()
        queued = await queue_withdraw_order_refreshes(
            session,
            source_id="rajwin",
            query_range=query_range,
            actor_user_id=None,
            now=queued_at,
        )
        result = await run_due_withdraw_order_refreshes(session, now=queued_at, settings=settings)

    assert queued.query_range == query_range
    assert result[0].status == "succeeded"
    # A manual day other than yesterday can be followed by the overdue daily
    # export in the same worker pass.  The first export is the queued manual
    # request and must retain the user's selected calendar day.
    assert FakeWithdrawClient.events[1] == (
        "export",
        {
            "base_url": "https://rajwin.example.test",
            "create_start": f"{expected_day} 00:00:00",
            "create_end": f"{expected_day} 23:59:59",
        },
    )
    await engine.dispose()


@pytest.mark.asyncio
async def test_manual_excel_refresh_defaults_to_yesterday(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine, factory = await _database()
    source = _source(settings)
    FakeWithdrawClient.statuses = [{"code": "success", "label": "代付成功"}]
    FakeWithdrawClient.export_outcomes = {
        source.base_url or "": WithdrawFetchResult(
            orders=[_order("yesterday", create_time="2026-07-29 12:00:00")],
            fetched_pages=1,
            remote_total=1,
            complete=True,
            export_row_count=1,
        )
    }
    FakeWithdrawClient.events = []
    monkeypatch.setattr(
        "packages.domain.services.withdraw_order_refresh_service.RajAdminWithdrawClient",
        FakeWithdrawClient,
    )
    queued_at = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    async with factory() as session:
        session.add_all([source, _retention()])
        await session.commit()
        queued = await queue_withdraw_order_refreshes(
            session,
            source_id="rajwin",
            actor_user_id=None,
            now=queued_at,
        )
        await run_due_withdraw_order_refreshes(session, now=queued_at, settings=settings)

    assert queued.query_range == "yesterday"
    assert FakeWithdrawClient.events[-1][1] == {
        "base_url": "https://rajwin.example.test",
        "create_start": "2026-07-29 00:00:00",
        "create_end": "2026-07-29 23:59:59",
    }
    await engine.dispose()


@pytest.mark.asyncio
async def test_unmapped_export_status_fails_without_replacing_existing_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine, factory = await _database()
    source = _source(settings)
    FakeWithdrawClient.statuses = [{"code": "success", "label": "代付成功"}]
    FakeWithdrawClient.export_outcomes = {
        source.base_url or "": WithdrawFetchResult(
            orders=[_order("new-row", status_label="远端新增状态")],
            fetched_pages=1,
            remote_total=1,
            complete=True,
            export_row_count=1,
        )
    }
    FakeWithdrawClient.events = []
    monkeypatch.setattr(
        "packages.domain.services.withdraw_order_refresh_service.RajAdminWithdrawClient",
        FakeWithdrawClient,
    )
    due = datetime(2026, 7, 30, 18, 35, 1, tzinfo=UTC)
    async with factory() as session:
        session.add_all(
            [
                source,
                _retention(),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="old-row",
                    uid="100",
                    create_time="2026-07-30 09:00:00",
                    create_time_utc=datetime(2026, 7, 30, 3, 30, tzinfo=UTC),
                    status="success",
                    status_label="代付成功",
                ),
            ]
        )
        await session.commit()
        result = await run_due_withdraw_order_refreshes(session, now=due, settings=settings)
        snapshots = list(await session.scalars(select(WithdrawOrderSnapshot)))
        state = await session.get(WithdrawOrderRefreshState, "rajwin")
        failed_run = await session.scalar(select(DataSyncRun))

    assert [item.status for item in result] == ["failed"]
    assert [snapshot.remote_order_id for snapshot in snapshots] == ["old-row"]
    assert state is not None
    assert state.status == "failed"
    assert state.last_error == "远端提现订单 Excel 导出或校验失败，请稍后重试。"
    assert failed_run is not None
    assert failed_run.status == "failed"
    assert failed_run.error_code == "remote_withdraw_sync_failed"
    assert failed_run.error_message == state.last_error
    await engine.dispose()
