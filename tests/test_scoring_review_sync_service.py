from __future__ import annotations

from datetime import datetime

import pytest
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
    WithdrawOrderSnapshot,
    WithdrawScoringSnapshot,
)
from packages.domain.services.remote_scoring_review_service import ScoringReviewRemotePage
from packages.domain.services.scoring_review_sync_service import (
    sync_scoring_reviewed_cases_from_remote,
)
from packages.domain.services.scoring_reviewed_cases_import_service import ScoringReviewedCase
from packages.domain.services.source_service import _scoring_api_credential_scope


class FakeScoringReviewClient:
    events: list[tuple[int, int, str | None]] = []

    def __init__(self, *, base_url: str, api_key: str) -> None:
        assert base_url == "https://score.rajwin.example/api"
        assert api_key == "srk_v1_test.secret"

    async def __aenter__(self) -> FakeScoringReviewClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def fetch_reviewed_cases(
        self,
        *,
        page: int,
        page_size: int,
        create_time_start: datetime | None = None,
        create_time_end: datetime | None = None,
    ) -> ScoringReviewRemotePage:
        FakeScoringReviewClient.events.append(
            (page, page_size, create_time_start.isoformat() if create_time_start else None)
        )
        all_cases = [
            ScoringReviewedCase(
                withdraw_order_id="case-1",
                global_hard_condition=None,
                scenario_review="人工复核",
                score_review="35",
                decision_stage="评分审核",
                final_review_suggestion="manual_review",
                operation_result="已处理",
                review_summary="允许保存的摘要",
                current_status="processed",
                review_completed_at="2026-07-31 10:01:12",
                review_duration="00:01:12",
                queue_duration="00:00:08",
                entered_queue_at="2026-07-31 10:00:00",
                exited_queue_at="2026-07-31 10:00:08",
            ),
            ScoringReviewedCase(
                withdraw_order_id="unmatched-case",
                global_hard_condition=None,
                scenario_review=None,
                score_review="61",
                decision_stage=None,
                final_review_suggestion="approve",
                operation_result=None,
                review_summary=None,
                current_status="processed",
                review_completed_at=None,
                review_duration=None,
                queue_duration=None,
                entered_queue_at=None,
                exited_queue_at=None,
            ),
        ]
        return ScoringReviewRemotePage(
            cases=all_cases if page == 1 else [],
            total=2,
            page=page,
            page_size=page_size,
        )


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
    assert FakeScoringReviewClient.events == [(1, 500, "2026-07-31T00:00:00+05:30")]
    assert audit is not None
    assert audit.metadata_json == {
        "sourceRows": 2,
        "matchedRows": 1,
        "createdRows": 1,
        "updatedRows": 0,
        "unmatchedRows": 1,
        "createTimeStart": "2026-07-31 00:00:00",
        "createTimeEnd": "2026-07-31 23:59:59",
        "remotePages": 1,
    }
    assert run is not None
    assert run.business_type == "withdraw_scoring_import"
    assert run.operation_kind == "remote_sync"
    assert run.trigger_type == "manual"
    assert run.status == "succeeded"
    assert run.remote_total == 2
    assert run.fetched_pages == 1
    assert (run.imported_count, run.matched_count, run.unmatched_count) == (2, 1, 1)
    assert [event.event_type for event in run_events] == [
        "running",
        "scoring_remote_fetch_started",
        "scoring_remote_fetch_fetched",
        "completed",
    ]
    await engine.dispose()
