from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import (
    Base,
    SecurityAuditLog,
    SourceConfig,
    WithdrawOrderSnapshot,
    WithdrawScoringSnapshot,
)
from packages.domain.services.scoring_reviewed_cases_import_service import (
    SCORING_REVIEWED_CASES_EXPORT_COLUMNS,
)
from packages.domain.services.withdraw_scoring_import_service import (
    WithdrawScoringImportError,
    import_scoring_reviewed_cases_export,
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


def _source(source_id: str) -> SourceConfig:
    return SourceConfig(
        source_id=source_id,
        display_name=source_id.title(),
        enabled=True,
        business_timezone="Asia/Kolkata",
    )


def _master(source_id: str, case_id: str) -> WithdrawOrderSnapshot:
    return WithdrawOrderSnapshot(
        source_id=source_id,
        remote_order_id=case_id,
        uid="master-uid",
        amount="100.00",
        pay_channel="master-channel",
        status="3",
        status_label="代付成功",
    )


def _workbook_bytes(rows: list[dict[str, object]]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(SCORING_REVIEWED_CASES_EXPORT_COLUMNS)
    for row in rows:
        worksheet.append([row.get(header) for header in SCORING_REVIEWED_CASES_EXPORT_COLUMNS])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _case(case_id: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "案件号": case_id,
        "UID": "score-uid-must-not-copy",
        "提现金额": "9999.99",
        "渠道": "score-channel-must-not-copy",
        "全局硬性条件": "已通过",
        "场景审核": "未命中",
        "评分审核": -35,
        "决断阶段": "评分审核",
        "最终审核建议": "出款",
        "操作结果": "出款成功",
        "摘要": "评分审核摘要",
        "当前状态": "已提交代付 (1)",
        "审核完成时间": "2026-07-31 18:37:27",
        "审核耗时": "10秒",
        "队列中耗时": "9秒",
        "进入队列时间": "2026-07-31 18:37:17",
        "退出队列时间": "2026-07-31 18:37:27",
        "提现时间": "2026-07-31 18:37:11",
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_import_matches_only_existing_master_in_same_source_and_audits_counts() -> None:
    engine, factory = await _database()
    synced_at = datetime(2026, 8, 1, tzinfo=UTC)
    async with factory() as session:
        session.add_all([_source("rajwin"), _source("rajluck"), _master("rajwin", "case-1")])
        await session.commit()

        result = await import_scoring_reviewed_cases_export(
            session,
            source_id="rajwin",
            content=_workbook_bytes([_case("case-1"), _case("score-only")]),
            actor_user_id=None,
            now=synced_at,
        )

        snapshots = list(
            await session.scalars(
                select(WithdrawScoringSnapshot).order_by(WithdrawScoringSnapshot.withdraw_order_id)
            )
        )
        masters = list(
            await session.scalars(
                select(WithdrawOrderSnapshot).order_by(WithdrawOrderSnapshot.source_id)
            )
        )
        audit = await session.scalar(
            select(SecurityAuditLog).where(SecurityAuditLog.action == "withdraw_scoring.import")
        )

    assert result.source_row_count == 2
    assert result.matched_count == 1
    assert result.created_count == 1
    assert result.updated_count == 0
    assert result.unmatched_count == 1
    assert [(row.source_id, row.withdraw_order_id) for row in snapshots] == [("rajwin", "case-1")]
    assert [(row.source_id, row.remote_order_id) for row in masters] == [("rajwin", "case-1")]
    master = masters[0]
    assert master.uid == "master-uid"
    assert master.amount == "100.00"
    assert master.pay_channel == "master-channel"
    snapshot = snapshots[0]
    assert snapshot.score_review == "-35"
    assert snapshot.review_summary == "评分审核摘要"
    assert snapshot.review_completed_at == datetime(2026, 7, 31, 13, 7, 27)
    assert audit is not None
    assert audit.metadata_json == {
        "sourceRows": 2,
        "matchedRows": 1,
        "createdRows": 1,
        "updatedRows": 0,
        "unmatchedRows": 1,
    }
    await engine.dispose()


@pytest.mark.asyncio
async def test_import_is_source_scoped_and_updates_existing_supplement_in_place() -> None:
    engine, factory = await _database()
    first_sync = datetime(2026, 8, 1, tzinfo=UTC)
    second_sync = first_sync + timedelta(minutes=5)
    async with factory() as session:
        session.add_all([_source("rajwin"), _source("rajluck"), _master("rajwin", "case-1")])
        await session.commit()

        first = await import_scoring_reviewed_cases_export(
            session,
            source_id="rajwin",
            content=_workbook_bytes([_case("case-1")]),
            actor_user_id=None,
            now=first_sync,
        )
        second = await import_scoring_reviewed_cases_export(
            session,
            source_id="rajwin",
            content=_workbook_bytes([_case("case-1", 评分审核=61, 摘要="新的评分摘要")]),
            actor_user_id=None,
            now=second_sync,
        )
        other_source = await import_scoring_reviewed_cases_export(
            session,
            source_id="rajluck",
            content=_workbook_bytes([_case("case-1")]),
            actor_user_id=None,
            now=second_sync,
        )
        snapshots = list(await session.scalars(select(WithdrawScoringSnapshot)))

    assert (first.created_count, first.updated_count) == (1, 0)
    assert (second.created_count, second.updated_count) == (0, 1)
    assert (other_source.matched_count, other_source.unmatched_count) == (0, 1)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.source_id == "rajwin"
    assert snapshot.score_review == "61"
    assert snapshot.review_summary == "新的评分摘要"
    assert snapshot.first_seen_at.replace(tzinfo=UTC) == first_sync
    assert snapshot.synced_at.replace(tzinfo=UTC) == second_sync
    await engine.dispose()


@pytest.mark.asyncio
async def test_import_rolls_back_all_rows_and_audit_when_one_timestamp_is_invalid() -> None:
    engine, factory = await _database()
    async with factory() as session:
        session.add_all(
            [_source("rajwin"), _master("rajwin", "case-1"), _master("rajwin", "case-2")]
        )
        await session.commit()

        with pytest.raises(WithdrawScoringImportError, match="无效时间"):
            await import_scoring_reviewed_cases_export(
                session,
                source_id="rajwin",
                content=_workbook_bytes(
                    [_case("case-1"), _case("case-2", 审核完成时间="not-a-timestamp")]
                ),
                actor_user_id=None,
            )

        assert await session.scalar(select(WithdrawScoringSnapshot)) is None
        assert (
            await session.scalar(
                select(SecurityAuditLog).where(SecurityAuditLog.action == "withdraw_scoring.import")
            )
            is None
        )
        assert len(list(await session.scalars(select(WithdrawOrderSnapshot)))) == 2
    await engine.dispose()
