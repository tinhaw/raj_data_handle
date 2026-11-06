from __future__ import annotations

from datetime import datetime
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.security import encrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    DataSyncRun,
    DataSyncRunEvent,
    SecurityAuditLog,
    SourceConfig,
    SystemRetentionSetting,
    WithdrawOrderSnapshot,
    WithdrawScoringSnapshot,
)
from packages.domain.services.scoring_review_sync_service import (
    ScoringReviewSyncError,
    sync_scoring_reviewed_cases_from_remote,
)
from packages.domain.services.scoring_reviewed_cases_import_service import (
    SCORING_REVIEWED_CASES_EXPORT_COLUMNS,
)
from packages.domain.services.source_service import _scoring_api_credential_scope


class FakeScoringReviewClient:
    events: list[tuple[str, str | None]] = []
    export_content = b""
    timeout_seconds: list[float] = []

    def __init__(self, *, base_url: str, api_key: str, timeout_seconds: float = 180.0) -> None:
        assert base_url == "https://score.rajwin.example/api"
        assert api_key == "srk_v1_test.secret"
        FakeScoringReviewClient.timeout_seconds.append(timeout_seconds)

    async def __aenter__(self) -> FakeScoringReviewClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def export_reviewed_cases(
        self,
        *,
        create_time_start: datetime | None = None,
        create_time_end: datetime | None = None,
    ) -> bytes:
        FakeScoringReviewClient.events.append(
            ("export", create_time_start.isoformat() if create_time_start else None)
        )
        return FakeScoringReviewClient.export_content


def _scoring_export_content() -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(SCORING_REVIEWED_CASES_EXPORT_COLUMNS)
    worksheet.append(
        [
            "case-1",
            "10001",
            "100.00",
            "UPI",
            "已通过",
            "人工复核",
            "35",
            "评分审核",
            "manual_review",
            "已处理",
            "允许保存的摘要",
            "processed",
            "2026-07-31 10:01:12",
            "00:01:12",
            "00:00:08",
            "2026-07-31 10:00:00",
            "2026-07-31 10:00:08",
            "2026-07-31 09:58:00",
        ]
    )
    worksheet.append(
        [
            "unmatched-case",
            "10002",
            "200.00",
            "UPI",
            None,
            None,
            "61",
            None,
            "approve",
            None,
            None,
            "processed",
            None,
            None,
            None,
            None,
            None,
            "2026-07-31 09:59:00",
        ]
    )
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def _settings() -> Settings:
    return Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )


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


def _source(settings: Settings) -> SourceConfig:
    source = SourceConfig(
        source_id="rajwin",
        display_name="RajWin",
        enabled=True,
        business_timezone="Asia/Kolkata",
        scoring_api_base_url="https://score.rajwin.example/api",
        scoring_api_key_version=1,
        scoring_api_last_test_status="passed",
    )
    source.encrypted_scoring_api_key = encrypt_credentials(
        {"api_key": "srk_v1_test.secret"},
        source_id=_scoring_api_credential_scope(source.source_id),
        credential_version=source.scoring_api_key_version,
        settings=settings,
    )
    return source


@pytest.mark.asyncio
async def test_remote_scoring_sync_is_source_scoped_and_only_enriches_existing_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine, factory = await _database()
    monkeypatch.setattr(
        "packages.domain.services.scoring_review_sync_service.ScoringReviewRemoteClient",
        FakeScoringReviewClient,
    )
    FakeScoringReviewClient.events = []
    FakeScoringReviewClient.timeout_seconds = []
    FakeScoringReviewClient.export_content = _scoring_export_content()
    async with factory() as session:
        session.add_all(
            [
                _source(settings),
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                    remote_order_sync_timeout_seconds=240,
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="case-1",
                    uid="10001",
                    status="3",
                ),
            ]
        )
        await session.commit()
        result = await sync_scoring_reviewed_cases_from_remote(
            session,
            source_id="rajwin",
            create_time_start="2026-07-31 00:00:00",
            create_time_end="2026-07-31 23:59:59",
            actor_user_id=None,
            settings=settings,
        )
        snapshots = list(await session.scalars(select(WithdrawScoringSnapshot)))
        audit = await session.scalar(
            select(SecurityAuditLog).where(
                SecurityAuditLog.action == "withdraw_scoring.remote_sync"
            )
        )
        run = await session.scalar(select(DataSyncRun))
        run_events = list(
            await session.scalars(
                select(DataSyncRunEvent).order_by(
                    DataSyncRunEvent.occurred_at,
                    DataSyncRunEvent.id,
                )
            )
        )

    assert (result.source_row_count, result.matched_count, result.unmatched_count) == (2, 1, 1)
    assert [(row.source_id, row.withdraw_order_id) for row in snapshots] == [("rajwin", "case-1")]
    assert snapshots[0].score_review == "35"
    assert snapshots[0].review_summary == "允许保存的摘要"
    assert FakeScoringReviewClient.events == [("export", "2026-07-31T00:00:00+05:30")]
    assert FakeScoringReviewClient.timeout_seconds == [240]
    assert audit is not None
    assert audit.metadata_json == {
        "sourceRows": 2,
        "matchedRows": 1,
        "createdRows": 1,
        "updatedRows": 0,
        "unmatchedRows": 1,
        "createTimeStart": "2026-07-31 00:00:00",
        "createTimeEnd": "2026-07-31 23:59:59",
        "transport": "excel_export",
        "exportBytes": len(FakeScoringReviewClient.export_content),
    }
    assert run is not None
    assert run.business_type == "withdraw_scoring_import"
    assert run.operation_kind == "remote_sync"
    assert run.trigger_type == "manual"
    assert run.status == "succeeded"
    assert run.remote_total == 2
    assert run.export_row_count == 2
    assert run.fetched_pages is None
    assert run.input_size_bytes == len(FakeScoringReviewClient.export_content)
    assert (run.imported_count, run.matched_count, run.unmatched_count) == (2, 1, 1)
    assert [event.event_type for event in run_events] == [
        "running",
        "scoring_remote_export_started",
        "scoring_remote_export_fetched",
        "scoring_remote_export_parsed",
        "import_started",
        "completed",
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_remote_scoring_sync_rejects_invalid_export_without_writing_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine, factory = await _database()
    monkeypatch.setattr(
        "packages.domain.services.scoring_review_sync_service.ScoringReviewRemoteClient",
        FakeScoringReviewClient,
    )
    FakeScoringReviewClient.events = []
    FakeScoringReviewClient.export_content = b"not-an-xlsx"
    async with factory() as session:
        session.add_all(
            [
                _source(settings),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="case-1",
                    uid="10001",
                    status="3",
                ),
            ]
        )
        await session.commit()

        with pytest.raises(ScoringReviewSyncError, match="评分审核导出文件"):
            await sync_scoring_reviewed_cases_from_remote(
                session,
                source_id="rajwin",
                create_time_start="2026-07-31 00:00:00",
                create_time_end="2026-07-31 23:59:59",
                actor_user_id=None,
                settings=settings,
            )

        snapshots = list(await session.scalars(select(WithdrawScoringSnapshot)))
        run = await session.scalar(select(DataSyncRun))
        run_events = list(
            await session.scalars(
                select(DataSyncRunEvent).order_by(
                    DataSyncRunEvent.occurred_at,
                    DataSyncRunEvent.id,
                )
            )
        )

    assert snapshots == []
    assert run is not None
    assert run.status == "failed"
    assert run.error_code == "remote_scoring_review_sync_failed"
    assert run.input_size_bytes == len(FakeScoringReviewClient.export_content)
    assert [event.event_type for event in run_events] == [
        "running",
        "scoring_remote_export_started",
        "scoring_remote_export_fetched",
        "failed",
    ]
    await engine.dispose()
