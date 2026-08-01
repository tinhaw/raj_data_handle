from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    DataDictionaryEntry,
    SourceConfig,
    SystemRetentionSetting,
    WithdrawOrderSnapshot,
    WithdrawScoringSnapshot,
)
from packages.domain.schemas.withdraw_order import (
    WithdrawScoringSummaryRequest,
    WithdrawScoringSummaryResponse,
)
from packages.domain.services.data_dictionary_service import WITHDRAW_STATUS_DICTIONARY
from packages.domain.services.withdraw_scoring_summary_service import (
    query_withdraw_scoring_summary,
)


def _settings() -> Settings:
    return Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )


async def _database() -> tuple[object, async_sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _withdraw_snapshot(
    remote_order_id: str,
    *,
    audit_admin: str | None,
    status: str,
    status_label: str,
    source_id: str = "rajwin",
    created_at: datetime = datetime(2026, 7, 30, 6, 0, tzinfo=UTC),
) -> WithdrawOrderSnapshot:
    return WithdrawOrderSnapshot(
        source_id=source_id,
        remote_order_id=remote_order_id,
        uid="10001",
        amount="100.00",
        real_amount="97.00",
        create_time=created_at.strftime("%Y-%m-%d %H:%M:%S"),
        create_time_utc=created_at,
        audit_admin=audit_admin,
        status=status,
        status_label=status_label,
    )


def _scoring_snapshot(
    withdraw_order_id: str,
    score_review: str | None,
    *,
    source_id: str = "rajwin",
) -> WithdrawScoringSnapshot:
    return WithdrawScoringSnapshot(
        source_id=source_id,
        withdraw_order_id=withdraw_order_id,
        score_review=score_review,
    )


@pytest.mark.asyncio
async def test_withdraw_scoring_summary_only_counts_matched_scoring_rows() -> None:
    engine, factory = await _database()
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
                SourceConfig(
                    source_id="rajluck",
                    display_name="RajLuck",
                    enabled=True,
                    business_timezone="Asia/Kolkata",
                    currency="INR",
                ),
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                ),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type=WITHDRAW_STATUS_DICTIONARY,
                    entry_code="-1",
                    entry_label="审核拒绝",
                    active=True,
                ),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type=WITHDRAW_STATUS_DICTIONARY,
                    entry_code="0",
                    entry_label="待审核",
                    active=True,
                ),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type=WITHDRAW_STATUS_DICTIONARY,
                    entry_code="3",
                    entry_label="代付成功",
                    active=True,
                ),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type=WITHDRAW_STATUS_DICTIONARY,
                    entry_code="5",
                    entry_label="提交中",
                    active=True,
                ),
                # Alice has one record in each numeric score interval and one
                # matching scoring row with no numeric score.
                _withdraw_snapshot(
                    "alice-no-score", audit_admin="Alice", status="0", status_label="待审核"
                ),
                _withdraw_snapshot(
                    "alice-low", audit_admin="Alice", status="3", status_label="代付成功"
                ),
                _withdraw_snapshot(
                    "alice-mid", audit_admin="Alice", status="-1", status_label="审核拒绝"
                ),
                _withdraw_snapshot(
                    "alice-high", audit_admin="Alice", status="3", status_label="代付成功"
                ),
                # Bob's no-scoring-row management order is reported only as a
                # coverage gap, never as a low-score order.
                _withdraw_snapshot(
                    "bob-text-score", audit_admin="Bob", status="5", status_label="提交中"
                ),
                _withdraw_snapshot(
                    "bob-no-scoring-row", audit_admin="Bob", status="3", status_label="代付成功"
                ),
                _withdraw_snapshot(
                    "blank-operator", audit_admin=" ", status="3", status_label="代付成功"
                ),
                _withdraw_snapshot(
                    "outside-window",
                    audit_admin="Alice",
                    status="3",
                    status_label="代付成功",
                    created_at=datetime(2026, 7, 31, 6, 0, tzinfo=UTC),
                ),
                _withdraw_snapshot(
                    "alice-low",
                    audit_admin="RajLuck Operator",
                    status="3",
                    status_label="代付成功",
                    source_id="rajluck",
                ),
                _scoring_snapshot("alice-no-score", None),
                _scoring_snapshot("alice-low", "30"),
                _scoring_snapshot("alice-mid", "31"),
                _scoring_snapshot("alice-high", "61"),
                _scoring_snapshot("bob-text-score", "未进入评分"),
                _scoring_snapshot("blank-operator", "60"),
                _scoring_snapshot("outside-window", "100"),
                _scoring_snapshot("alice-low", "999", source_id="rajluck"),
            ]
        )
        await session.commit()

        result = await query_withdraw_scoring_summary(
            session,
            request=WithdrawScoringSummaryRequest(
                source_id="rajwin",
                create_time_start="2026-07-30 00:00:00",
                create_time_end="2026-07-30 23:59:59",
            ),
            settings=_settings(),
            now=datetime(2026, 7, 31, 6, 0, tzinfo=UTC),
        )

    assert result.source_id == "rajwin"
    assert result.start_at.isoformat() == "2026-07-30T00:00:00+05:30"
    assert result.end_at.isoformat() == "2026-07-30T23:59:59+05:30"
    assert result.management_order_count == 7
    assert result.scoring_record_order_count == 6
    assert result.missing_scoring_record_count == 1
    assert (
        result.totals.total_count,
        result.totals.not_entered_scoring_count,
        result.totals.score_lte30_count,
        result.totals.score31_to60_count,
        result.totals.score_gte61_count,
    ) == (6, 2, 3, 2, 1)
    assert result.status_columns == ["-1", "0", "3", "5"]
    assert [(row.audit_admin, row.total_count) for row in result.rows] == [
        ("Alice", 4),
        ("Bob", 1),
        ("未记录操作人", 1),
    ]
    alice = result.rows[0]
    assert alice.audit_admin_missing is False
    assert alice.status_counts == [
        {"status": "-1", "count": 1},
        {"status": "0", "count": 1},
        {"status": "3", "count": 2},
    ]
    assert result.rows[1].status_counts == [{"status": "5", "count": 1}]
    assert result.rows[2].audit_admin_missing is True
    assert result.rows[2].status_counts == [{"status": "3", "count": 1}]

    response = WithdrawScoringSummaryResponse(
        source_id=result.source_id,
        source_display_name=result.source_display_name,
        business_timezone=result.business_timezone,
        start_at=result.start_at,
        end_at=result.end_at,
        generated_at=result.generated_at,
        local_updated_at=result.local_updated_at,
        rows=result.rows,
        totals=result.totals,
        status_columns=result.status_columns,
        status_dictionary=result.status_dictionary,
        management_order_count=result.management_order_count,
        scoring_record_order_count=result.scoring_record_order_count,
        missing_scoring_record_count=result.missing_scoring_record_count,
    )
    assert response.model_dump(by_alias=True)["missingScoringRecordCount"] == 1
    await engine.dispose()
