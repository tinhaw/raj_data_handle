"""Local scoring-review aggregation over the withdrawal cache.

The scoring workbook is supplemental only.  This module always starts with
``WithdrawOrderSnapshot`` and outer-joins the optional scoring snapshot, so a
score-only workbook case can never appear as a withdrawal order or contribute
to an operator's totals.  A master withdrawal without a scoring-export row is
reported as not having entered scoring, while its master data stays canonical.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import and_, desc, func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings
from packages.domain.models import WithdrawOrderSnapshot, WithdrawScoringSnapshot
from packages.domain.services.withdraw_order_service import (
    WithdrawOrderCacheSchemaPendingError,
    _query_context,
)


@dataclass(frozen=True, slots=True)
class ScoringReviewSummaryCounts:
    total_count: int
    not_entered_scoring_count: int
    score_lte30_count: int
    score31_to60_count: int
    score_gte61_count: int


@dataclass(frozen=True, slots=True)
class ScoringReviewOperatorSummaryItem(ScoringReviewSummaryCounts):
    operator: str


@dataclass(frozen=True, slots=True)
class ScoringReviewOperatorSummaryResult:
    """Source-scoped local summary which a router can serialize directly."""

    source_id: str
    source_display_name: str
    business_timezone: str
    start_at: datetime
    end_at: datetime
    generated_at: datetime
    rows: list[ScoringReviewOperatorSummaryItem]
    totals: ScoringReviewSummaryCounts
    local_updated_at: datetime | None


@dataclass(slots=True)
class _MutableCounts:
    total_count: int = 0
    not_entered_scoring_count: int = 0
    score_lte30_count: int = 0
    score31_to60_count: int = 0
    score_gte61_count: int = 0

    def add_score(self, score: str | None) -> None:
        self.total_count += 1
        category = _score_category(score)
        if category == "not_entered":
            self.not_entered_scoring_count += 1
            self.score_lte30_count += 1
        elif category == "lte30":
            self.score_lte30_count += 1
        elif category == "31_to_60":
            self.score31_to60_count += 1
        else:
            self.score_gte61_count += 1

    def frozen(self) -> ScoringReviewSummaryCounts:
        return ScoringReviewSummaryCounts(
            total_count=self.total_count,
            not_entered_scoring_count=self.not_entered_scoring_count,
            score_lte30_count=self.score_lte30_count,
            score31_to60_count=self.score31_to60_count,
            score_gte61_count=self.score_gte61_count,
        )


def _score_category(score: str | None) -> str:
    """Classify one score workbook value using the approved reporting rule."""

    normalized = (score or "").strip()
    if not normalized:
        return "not_entered"
    try:
        numeric_score = Decimal(normalized)
    except (InvalidOperation, ValueError):
        return "not_entered"
    if not numeric_score.is_finite():
        return "not_entered"
    if numeric_score <= Decimal("30"):
        return "lte30"
    if numeric_score <= Decimal("60"):
        return "31_to_60"
    return "gte61"


def _operator_label(audit_admin: str | None) -> str:
    return (audit_admin or "").strip() or "未记录操作人"


def _latest_datetime(values: Iterable[datetime | None]) -> datetime | None:
    normalized = [
        value if value is None or value.tzinfo else value.replace(tzinfo=UTC)
        for value in values
    ]
    return max((value for value in normalized if value is not None), default=None)


def _is_missing_scoring_summary_schema(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    return (
        "withdraw_scoring_snapshots" in message
        or "withdraw_order_snapshots" in message
    ) and (
        "does not exist" in message or "no such table" in message
    )


async def query_scoring_review_operator_summary(
    session: AsyncSession,
    *,
    source_id: str,
    create_time_start: str,
    create_time_end: str,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> ScoringReviewOperatorSummaryResult:
    """Aggregate local withdrawal rows by their master-export audit operator.

    The selected source and date window are resolved with the same rules as
    withdrawal detail.  The SQL starts with the canonical withdrawal cache;
    no score-only workbook case is counted.  Absent score snapshots and
    textual score values are a distinct observation and, per business rule,
    are also included in the ``<=30`` score bucket.
    """

    (
        resolved_source_id,
        source_display_name,
        timezone_name,
        _currency,
        query_at,
        window_start,
        window_end,
        _refresh_state,
    ) = await _query_context(
        session,
        source_id=source_id,
        create_time_start=create_time_start,
        create_time_end=create_time_end,
        settings=settings,
        now=now,
    )

    join_condition = and_(
        WithdrawScoringSnapshot.source_id == WithdrawOrderSnapshot.source_id,
        WithdrawScoringSnapshot.withdraw_order_id == WithdrawOrderSnapshot.remote_order_id,
    )
    statement = (
        select(
            WithdrawOrderSnapshot.audit_admin,
            WithdrawOrderSnapshot.synced_at.label("withdraw_synced_at"),
            WithdrawScoringSnapshot.score_review,
            WithdrawScoringSnapshot.synced_at.label("scoring_synced_at"),
        )
        .select_from(WithdrawOrderSnapshot)
        .outerjoin(WithdrawScoringSnapshot, join_condition)
        .where(
            WithdrawOrderSnapshot.source_id == resolved_source_id,
            WithdrawOrderSnapshot.create_time_utc.is_not(None),
            WithdrawOrderSnapshot.create_time_utc >= window_start,
            WithdrawOrderSnapshot.create_time_utc <= window_end,
        )
        .order_by(
            func.lower(func.coalesce(WithdrawOrderSnapshot.audit_admin, "")),
            desc(WithdrawOrderSnapshot.remote_order_id),
        )
    )
    try:
        records = (await session.execute(statement)).mappings().all()
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_scoring_summary_schema(exc):
            raise
        await session.rollback()
        raise WithdrawOrderCacheSchemaPendingError(
            "提现订单评分缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc

    grouped: dict[str, _MutableCounts] = {}
    synced_at_values: list[datetime | None] = []
    totals = _MutableCounts()
    for record in records:
        operator = _operator_label(record["audit_admin"])
        counts = grouped.setdefault(operator, _MutableCounts())
        score = record["score_review"]
        counts.add_score(score)
        totals.add_score(score)
        synced_at_values.extend(
            (record["withdraw_synced_at"], record["scoring_synced_at"])
        )

    rows: list[ScoringReviewOperatorSummaryItem] = []
    for operator, counts in grouped.items():
        frozen_counts = counts.frozen()
        rows.append(
            ScoringReviewOperatorSummaryItem(
                operator=operator,
                total_count=frozen_counts.total_count,
                not_entered_scoring_count=frozen_counts.not_entered_scoring_count,
                score_lte30_count=frozen_counts.score_lte30_count,
                score31_to60_count=frozen_counts.score31_to60_count,
                score_gte61_count=frozen_counts.score_gte61_count,
            )
        )
    rows.sort(key=lambda row: (-row.total_count, row.operator.casefold(), row.operator))

    timezone = ZoneInfo(timezone_name)
    return ScoringReviewOperatorSummaryResult(
        source_id=resolved_source_id,
        source_display_name=source_display_name,
        business_timezone=timezone_name,
        start_at=window_start.astimezone(timezone),
        end_at=window_end.astimezone(timezone),
        generated_at=query_at,
        rows=rows,
        totals=totals.frozen(),
        local_updated_at=_latest_datetime(synced_at_values),
    )
