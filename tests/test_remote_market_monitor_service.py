from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import (
    Base,
    MonitorNotificationDestination,
    MonitorNotificationOutbox,
    RemoteMarketMonitorIncident,
    RemoteMarketMonitorTargetDestination,
    SourceConfig,
)
from packages.domain.services import remote_market_monitor_service as monitor_service
from packages.domain.services.remote_market_monitor_service import (
    MonitorSample,
    ensure_target_settings,
    get_monitor_settings,
    run_automatic_monitor_check,
)


async def _database() -> tuple[object, async_sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _source() -> SourceConfig:
    return SourceConfig(
        source_id="rajwin",
        display_name="RajWin",
        base_url="https://rajwin.example.test",
        enabled=True,
        business_timezone="Asia/Kolkata",
        currency="INR",
    )


def _sample(
    now: datetime,
    *,
    audit: int | None = None,
    review: int | None = None,
    error_code: str | None = None,
) -> MonitorSample:
    return MonitorSample(
        status="ok" if error_code is None else "source_unavailable",
        started_at=now,
        finished_at=now,
        query_range_start=now - timedelta(hours=1),
        query_range_end=now,
        pending_audit_count=audit,
        pending_review_count=review,
        error_code=error_code,
        safe_error_message="远端测试错误。" if error_code else None,
    )


def test_all_templates_require_market_name_placeholder() -> None:
    assert all(
        "{source_display_name}" in template
        for template in monitor_service.DEFAULT_TEMPLATES.values()
    )
    invalid_templates = dict(monitor_service.DEFAULT_TEMPLATES)
    invalid_templates["test_message"] = "通知测试"

    with pytest.raises(monitor_service.RemoteMarketMonitorError, match="盘口名称"):
        monitor_service.validate_template_map(invalid_templates)


@pytest.mark.asyncio
async def test_metric_threshold_is_debounced_and_recovery_is_notified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory = await _database()
    now = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
    samples = iter(
        [
            _sample(now, audit=11, review=0),
            _sample(now + timedelta(minutes=1), audit=12, review=0),
            _sample(now + timedelta(minutes=2), audit=8, review=0),
            _sample(now + timedelta(minutes=3), audit=7, review=0),
        ]
    )

    async def fake_fetch(*_: object, **__: object) -> MonitorSample:
        return next(samples)

    monkeypatch.setattr(monitor_service, "fetch_remote_monitor_sample", fake_fetch)
    async with factory() as session:
        source = _source()
        session.add(source)
        await session.commit()
        settings = await get_monitor_settings(session)
        settings.monitor_enabled = True
        target, policies, state = await ensure_target_settings(session, source=source)
        target.enabled = True
        destination = MonitorNotificationDestination(
            display_name="测试群",
            bot_token_secret_ref="env://TEST_BOT_TOKEN",
            chat_id_secret_ref="env://TEST_CHAT_ID",
        )
        session.add(destination)
        await session.flush()
        session.add(
            RemoteMarketMonitorTargetDestination(
                source_id=source.source_id,
                destination_id=destination.id,
            )
        )
        for policy in policies:
            policy.threshold = 10
            policy.recovery_threshold = 8
            policy.breach_consecutive_checks = 2
            policy.recovery_consecutive_checks = 2
        state.lease_owner = "test-worker"
        await session.commit()

        for _ in range(4):
            state = await session.get(type(state), source.source_id)
            state.lease_owner = "test-worker"
            await session.commit()
            await run_automatic_monitor_check(
                session,
                source_id=source.source_id,
                worker_id="test-worker",
            )

        incidents = list(
            await session.scalars(
                select(RemoteMarketMonitorIncident).where(
                    RemoteMarketMonitorIncident.metric == "pending_audit"
                )
            )
        )
        outbox = list(await session.scalars(select(MonitorNotificationOutbox)))

    assert len(incidents) == 1
    assert incidents[0].status == "closed"
    assert [row.event_type for row in outbox] == [
        "PENDING_THRESHOLD_BREACHED",
        "PENDING_THRESHOLD_RECOVERED",
    ]
    assert {row.status for row in outbox} == {"recorded"}
    await engine.dispose()


@pytest.mark.asyncio
async def test_metric_reminder_interval_starts_from_initial_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory = await _database()
    now = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
    samples = iter(
        [
            _sample(now, audit=11, review=0),
            _sample(now + timedelta(minutes=1), audit=12, review=0),
            _sample(now + timedelta(minutes=10), audit=13, review=0),
            _sample(now + timedelta(minutes=11), audit=14, review=0),
            _sample(now + timedelta(minutes=12), audit=15, review=0),
        ]
    )

    async def fake_fetch(*_: object, **__: object) -> MonitorSample:
        return next(samples)

    monkeypatch.setattr(monitor_service, "fetch_remote_monitor_sample", fake_fetch)
    async with factory() as session:
        source = _source()
        session.add(source)
        await session.commit()
        settings = await get_monitor_settings(session)
        settings.monitor_enabled = True
        settings.default_reminder_interval_minutes = 10
        target, policies, state = await ensure_target_settings(session, source=source)
        target.enabled = True
        destination = MonitorNotificationDestination(
            display_name="测试群",
            bot_token_secret_ref="env://TEST_BOT_TOKEN",
            chat_id_secret_ref="env://TEST_CHAT_ID",
        )
        session.add(destination)
        await session.flush()
        session.add(
            RemoteMarketMonitorTargetDestination(
                source_id=source.source_id,
                destination_id=destination.id,
            )
        )
        for policy in policies:
            policy.threshold = 10
            policy.recovery_threshold = 8
            policy.breach_consecutive_checks = 2
            policy.reminder_interval_minutes = None
        state.lease_owner = "test-worker"
        await session.commit()

        for _ in range(5):
            state = await session.get(type(state), source.source_id)
            state.lease_owner = "test-worker"
            await session.commit()
            await run_automatic_monitor_check(
                session,
                source_id=source.source_id,
                worker_id="test-worker",
            )

        outbox = list(
            await session.scalars(
                select(MonitorNotificationOutbox).order_by(MonitorNotificationOutbox.created_at)
            )
        )

    assert [row.event_type for row in outbox] == [
        "PENDING_THRESHOLD_BREACHED",
        "PENDING_THRESHOLD_REMINDER",
    ]
    assert outbox[1].idempotency_key.endswith(":1")
    assert "当前数量：<b>14</b>" in outbox[1].payload_json["text"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_source_failure_does_not_replace_last_good_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory = await _database()
    now = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
    samples = iter(
        [
            _sample(now, audit=3, review=4),
            _sample(now + timedelta(minutes=1), error_code="READ_TIMEOUT"),
            _sample(now + timedelta(minutes=2), error_code="READ_TIMEOUT"),
        ]
    )

    async def fake_fetch(*_: object, **__: object) -> MonitorSample:
        return next(samples)

    monkeypatch.setattr(monitor_service, "fetch_remote_monitor_sample", fake_fetch)
    async with factory() as session:
        source = _source()
        session.add(source)
        await session.commit()
        settings = await get_monitor_settings(session)
        settings.monitor_enabled = True
        target, _, state = await ensure_target_settings(session, source=source)
        target.enabled = True
        settings.source_failure_consecutive_checks = 2
        state.lease_owner = "test-worker"
        await session.commit()

        for _ in range(3):
            state = await session.get(type(state), source.source_id)
            state.lease_owner = "test-worker"
            await session.commit()
            await run_automatic_monitor_check(
                session,
                source_id=source.source_id,
                worker_id="test-worker",
            )

        state = await session.get(type(state), source.source_id)
        source_incident = await session.scalar(
            select(RemoteMarketMonitorIncident).where(
                RemoteMarketMonitorIncident.metric == "source",
                RemoteMarketMonitorIncident.status == "open",
            )
        )

    assert state.last_pending_audit_count == 3
    assert state.last_pending_review_count == 4
    assert state.source_health == "unavailable"
    assert source_incident is not None
    await engine.dispose()
