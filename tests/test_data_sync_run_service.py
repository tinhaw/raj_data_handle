from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import (
    Base,
    DataSyncRun,
    DataSyncRunEvent,
    SourceConfig,
    SystemRetentionSetting,
)
from packages.domain.schemas.sync_log import SyncLogQueryRequest
from packages.domain.services.data_sync_run_service import (
    SyncRunMetrics,
    cancel_sync_run,
    complete_sync_run,
    create_sync_run,
    fail_sync_run,
    get_sync_run_detail,
    mark_sync_run_running,
    query_sync_runs,
)
from packages.domain.services.retention_cleanup_service import cleanup_expired_data
from packages.storage.local import LocalFileStorage


async def _database() -> tuple[object, async_sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _source() -> SourceConfig:
    return SourceConfig(
        source_id="rajwin",
        display_name="RajWin",
        enabled=True,
        business_timezone="Asia/Kolkata",
        config_version=4,
    )


@pytest.mark.asyncio
async def test_sync_run_lifecycle_is_queryable_with_events_and_safe_metrics() -> None:
    engine, factory = await _database()
    requested_at = datetime(2026, 8, 1, 1, 0, tzinfo=UTC)
    started_at = requested_at + timedelta(seconds=5)
    finished_at = started_at + timedelta(seconds=42)

    async with factory() as session:
        source = _source()
        session.add(source)
        await session.commit()

        run = await create_sync_run(
            session,
            source=source,
            business_type="withdraw_orders",
            trigger_type="manual",
            requested_at=requested_at,
            query_range="yesterday",
            page_size=100,
        )
        await mark_sync_run_running(
            session,
            run=run,
            started_at=started_at,
            window_start_utc=datetime(2026, 7, 31, tzinfo=UTC),
            window_end_utc=datetime(2026, 7, 31, 23, 59, 59, tzinfo=UTC),
        )
        await complete_sync_run(
            session,
            run=run,
            finished_at=finished_at,
            metrics=SyncRunMetrics(
                remote_total=80,
                export_row_count=84,
                cached_total=80,
                fetched_pages=1,
                imported_count=80,
                duplicate_count=4,
            ),
        )
        await session.commit()

        result = await query_sync_runs(
            session,
            request=SyncLogQueryRequest(
                sourceId="rajwin",
                businessTypes=["withdraw_orders"],
                startedAt=requested_at - timedelta(minutes=1),
                endedAt=finished_at + timedelta(minutes=1),
            ),
            now=finished_at,
        )
        detail = await get_sync_run_detail(session, run_id=run.id)

    assert result.total == 1
    assert result.summary["succeeded_count"] == 1
    assert result.summary["in_progress_count"] == 0
    assert result.items[0]["duration_ms"] == 42_000
    assert result.items[0]["export_row_count"] == 84
    assert result.items[0]["metadata"] == {}
    assert [event["event_type"] for event in detail.events] == [
        "queued",
        "running",
        "completed",
    ]
    assert detail.run["window_start_utc"] == datetime(2026, 7, 31, tzinfo=UTC)
    await engine.dispose()


@pytest.mark.asyncio
async def test_sync_run_filters_terminal_states_and_cleanup_preserves_active_runs(
    tmp_path: Path,
) -> None:
    engine, factory = await _database()
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    old_at = now - timedelta(days=31)

    async with factory() as session:
        source = _source()
        session.add_all(
            [
                source,
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                    sync_log_retention_days=30,
                ),
            ]
        )
        await session.commit()

        expired = await create_sync_run(
            session,
            source=source,
            business_type="charge_orders",
            trigger_type="automatic",
            status="running",
            requested_at=old_at,
        )
        await fail_sync_run(
            session,
            run=expired,
            error_code="remote_export_failed",
            error_message="远端导出未完成，请稍后重试。",
            finished_at=old_at + timedelta(minutes=1),
        )
        active = await create_sync_run(
            session,
            source=source,
            business_type="spin_orders",
            trigger_type="automatic",
            status="running",
            requested_at=old_at,
        )
        cancelled = await create_sync_run(
            session,
            source=source,
            business_type="withdraw_scoring_import",
            trigger_type="upload",
            operation_kind="excel_import",
            status="running",
            requested_at=now,
            input_filename="reviewed.xlsx",
            input_size_bytes=1024,
        )
        await cancel_sync_run(session, run=cancelled, finished_at=now + timedelta(seconds=1))
        await session.commit()

        failed_only = await query_sync_runs(
            session,
            request=SyncLogQueryRequest(statuses=["failed"]),
            now=now,
        )
        assert failed_only.total == 1
        assert failed_only.items[0]["error_code"] == "remote_export_failed"

        cleanup = await cleanup_expired_data(
            session,
            storage=LocalFileStorage(tmp_path / "storage", max_bytes=1024),
            now=now,
        )
        remaining_runs = list(await session.scalars(select(DataSyncRun).order_by(DataSyncRun.id)))
        remaining_events = list(await session.scalars(select(DataSyncRunEvent)))

    assert cleanup["deletedSyncRuns"] == 1
    assert {run.id for run in remaining_runs} == {active.id, cancelled.id}
    assert {event.run_id for event in remaining_events} == {active.id, cancelled.id}
    await engine.dispose()
