from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    SourceConfig,
    SystemRetentionSetting,
    WithdrawOrderSnapshot,
    WithdrawScoringSnapshot,
)
from packages.domain.services.scoring_review_summary_service import (
    _score_category,
    query_scoring_review_operator_summary,
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
    source_id: str = "rajwin",
    audit_admin: str | None,
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
        status="3",
        audit_admin=audit_admin,
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
async def test_scoring_operator_summary_uses_master_left_join_and_source_scoped_scores() -> None:
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
                # Alice: 2 textual/missing, 2 more <=30, 2 in 31..60, 1 >=61.
                _withdraw_snapshot("missing-score", audit_admin="Alice"),
                _withdraw_snapshot("text-score", audit_admin="Alice"),
                _withdraw_snapshot("negative-score", audit_admin="Alice"),
                _withdraw_snapshot("score-30", audit_admin="Alice"),
                _withdraw_snapshot("score-31", audit_admin="Alice"),
                _withdraw_snapshot("score-60", audit_admin="Alice"),
                _withdraw_snapshot("score-61", audit_admin="Alice"),
                # Bob has no score row at all, so this master row is reported
                # as not having entered scoring.  Blank operator is numeric.
                _withdraw_snapshot("bob-no-score", audit_admin="Bob"),
                _withdraw_snapshot("blank-operator", audit_admin="  "),
                # Same case ID in another source must not leak into RajWin.
                _withdraw_snapshot(
                    "score-31",
                    source_id="rajluck",
                    audit_admin="RajLuck Operator",
                ),
                # A master row outside the requested date is also excluded.
                _withdraw_snapshot(
                    "outside-window",
                    audit_admin="Alice",
                    created_at=datetime(2026, 7, 31, 6, 0, tzinfo=UTC),
                ),
                _scoring_snapshot("missing-score", None),
                _scoring_snapshot("text-score", "未进入评分"),
                _scoring_snapshot("negative-score", "-35"),
                _scoring_snapshot("score-30", "30"),
                _scoring_snapshot("score-31", "31"),
                _scoring_snapshot("score-60", "60"),
                _scoring_snapshot("score-61", "61"),
                _scoring_snapshot("blank-operator", "100"),
                _scoring_snapshot("score-31", "999", source_id="rajluck"),
                _scoring_snapshot("outside-window", "100"),
                # This synthetic orphan can exist in SQLite test mode only;
                # the production composite FK rejects it.  The summary must
                # still start from master rows and never count it.
                _scoring_snapshot("score-only", "999"),
            ]
        )
        await session.commit()
        result = await query_scoring_review_operator_summary(
            session,
            source_id="rajwin",
            create_time_start="2026-07-30 00:00:00",
            create_time_end="2026-07-30 23:59:59",
            settings=_settings(),
            now=datetime(2026, 7, 31, 6, 0, tzinfo=UTC),
        )

    assert result.source_id == "rajwin"
    assert result.source_display_name == "RajWin"
    assert result.business_timezone == "Asia/Kolkata"
    assert result.start_at.isoformat() == "2026-07-30T00:00:00+05:30"
    assert result.end_at.isoformat() == "2026-07-30T23:59:59+05:30"
    assert result.totals.total_count == 9
    assert result.totals.not_entered_scoring_count == 3
    assert result.totals.score_lte30_count == 5
    assert result.totals.score31_to60_count == 2
    assert result.totals.score_gte61_count == 2
    assert [(row.operator, row.total_count) for row in result.rows] == [
        ("Alice", 7),
        ("Bob", 1),
        ("未记录操作人", 1),
    ]
    alice = result.rows[0]
    assert (
        alice.not_entered_scoring_count,
        alice.score_lte30_count,
        alice.score31_to60_count,
        alice.score_gte61_count,
    ) == (2, 4, 2, 1)
    assert all(row.operator != "RajLuck Operator" for row in result.rows)
    await engine.dispose()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "not_entered"),
        ("", "not_entered"),
        ("未进入评分", "not_entered"),
        ("NaN", "not_entered"),
        ("-1", "lte30"),
        ("30", "lte30"),
        ("30.5", "31_to_60"),
        ("60", "31_to_60"),
        ("60.1", "gte61"),
    ],
)
def test_score_categories_follow_business_buckets(value: str | None, expected: str) -> None:
    assert _score_category(value) == expected
