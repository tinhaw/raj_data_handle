"""Score-table-backed withdrawal summaries over local order caches.

Unlike the legacy scoring-review summary, this report treats the scoring cache
as an inclusion requirement: a management-side withdrawal is counted only when
there is a matching row in ``withdraw_scoring_snapshots``.  Management orders
without that row are returned as a separate coverage metric rather than being
silently assigned to the low-score bucket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import and_, desc, func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings
from packages.domain.models import WithdrawOrderSnapshot, WithdrawScoringSnapshot
from packages.domain.schemas.withdraw_order import WithdrawScoringSummaryRequest
from packages.domain.services.data_dictionary_service import withdraw_status_dictionary
from packages.domain.services.scoring_review_summary_service import _score_category
from packages.domain.services.withdraw_order_service import (
    WithdrawOrderCacheSchemaPendingError,
    _query_context,
)


@dataclass(frozen=True, slots=True)
class WithdrawScoringSummaryCounts:
    total_count: int
    not_entered_scoring_count: int
    score_lte30_count: int
    score31_to60_count: int
    score_gte61_count: int


@dataclass(frozen=True, slots=True)
class WithdrawScoringSummaryItem(WithdrawScoringSummaryCounts):
    audit_admin: str
    audit_admin_missing: bool
    status_counts: list[dict[str, int | str]]


@dataclass(frozen=True, slots=True)
class WithdrawScoreDistributionItem:
    score: str
    order_count: int


@dataclass(frozen=True, slots=True)
class WithdrawScoringSummaryResult:
    source_id: str
    source_display_name: str
    business_timezone: str
    start_at: datetime
    end_at: datetime
    generated_at: datetime
    local_updated_at: datetime | None
    rows: list[WithdrawScoringSummaryItem]
    totals: WithdrawScoringSummaryCounts
    status_columns: list[str]
    status_dictionary: list[dict[str, object]]
    management_order_count: int
    scoring_record_order_count: int
    missing_scoring_record_count: int
    numeric_score_order_count: int
    unscored_score_record_count: int
    score_distribution: list[WithdrawScoreDistributionItem]


@dataclass(slots=True)
class _MutableCounts:
    total_count: int = 0
    not_entered_scoring_count: int = 0
    score_lte30_count: int = 0
    score31_to60_count: int = 0
    score_gte61_count: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)

    def add(self, *, score: str | None, status: str) -> None:
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
        self.status_counts[status] = self.status_counts.get(status, 0) + 1

    def frozen(self) -> WithdrawScoringSummaryCounts:
        return WithdrawScoringSummaryCounts(
            total_count=self.total_count,
            not_entered_scoring_count=self.not_entered_scoring_count,
            score_lte30_count=self.score_lte30_count,
            score31_to60_count=self.score31_to60_count,
            score_gte61_count=self.score_gte61_count,
        )


def _operator_fields(audit_admin: str | None) -> tuple[str, bool]:
    normalized = (audit_admin or "").strip()
    return (normalized or "未记录操作人", not bool(normalized))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _status_sort_key(code: str) -> tuple[int, int | str, str]:
    try:
        return (0, int(code), code)
    except ValueError:
        return (1, code.casefold(), code)


def _normalized_numeric_score(score: str | None) -> tuple[Decimal, str] | None:
    normalized = (score or "").strip()
    if not normalized:
        return None
    try:
        numeric_score = Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None
    if not numeric_score.is_finite():
        return None
    display = format(numeric_score.normalize(), "f")
    return (numeric_score, "0" if display == "-0" else display)


def _is_missing_summary_schema(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    return any(
        table in message
        for table in (
            "withdraw_order_snapshots",
            "withdraw_scoring_snapshots",
            "data_dictionary_entries",
        )
    ) and ("does not exist" in message or "no such table" in message)


async def query_withdraw_scoring_summary(
    session: AsyncSession,
    *,
    request: WithdrawScoringSummaryRequest,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> WithdrawScoringSummaryResult:
    """Aggregate score-backed withdrawals by the management export operator.

    The selected time window always applies to the management-side withdrawal
    ``create_time_utc``.  A matched scoring row with an empty or nonnumeric
    score is included in the ``<=30`` bucket; a management row with no matched
    scoring row is excluded from all per-operator and score totals.
    """

    (
        source_id,
        source_display_name,
        timezone_name,
        _currency,
        query_at,
        window_start,
        window_end,
        _refresh_state,
    ) = await _query_context(
        session,
        source_id=request.source_id,
        create_time_start=request.create_time_start,
        create_time_end=request.create_time_end,
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
            WithdrawOrderSnapshot.status,
            WithdrawOrderSnapshot.status_label,
            WithdrawOrderSnapshot.synced_at.label("withdraw_synced_at"),
            WithdrawScoringSnapshot.id.label("scoring_snapshot_id"),
            WithdrawScoringSnapshot.score_review,
            WithdrawScoringSnapshot.synced_at.label("scoring_synced_at"),
        )
        .select_from(WithdrawOrderSnapshot)
        .outerjoin(WithdrawScoringSnapshot, join_condition)
        .where(
            WithdrawOrderSnapshot.source_id == source_id,
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
        configured_status_dictionary = await withdraw_status_dictionary(
            session,
            source_id=source_id,
        )
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_summary_schema(exc):
            raise
        await session.rollback()
        raise WithdrawOrderCacheSchemaPendingError(
            "提现订单评分缓存正在初始化，请在数据库迁移完成后重试。"
        ) from exc

    grouped: dict[str, _MutableCounts] = {}
    operator_missing: dict[str, bool] = {}
    totals = _MutableCounts()
    observed_status_labels: dict[str, str] = {}
    synced_at_values: list[datetime | None] = []
    management_order_count = 0
    missing_scoring_record_count = 0
    numeric_score_counts: dict[Decimal, tuple[str, int]] = {}
    unscored_score_record_count = 0

    for record in records:
        management_order_count += 1
        synced_at_values.append(record["withdraw_synced_at"])
        if record["scoring_snapshot_id"] is None:
            missing_scoring_record_count += 1
            continue

        synced_at_values.append(record["scoring_synced_at"])
        operator, audit_admin_missing = _operator_fields(record["audit_admin"])
        status = str(record["status"] or "").strip()
        status_label = str(record["status_label"] or "").strip()
        if status not in observed_status_labels:
            observed_status_labels[status] = status_label or (
                "未填写状态" if not status else f"状态 {status}"
            )
        counts = grouped.setdefault(operator, _MutableCounts())
        operator_missing.setdefault(operator, audit_admin_missing)
        counts.add(score=record["score_review"], status=status)
        totals.add(score=record["score_review"], status=status)
        numeric_score = _normalized_numeric_score(record["score_review"])
        if numeric_score is None:
            unscored_score_record_count += 1
            continue
        score_value, score_display = numeric_score
        previous = numeric_score_counts.get(score_value)
        numeric_score_counts[score_value] = (
            score_display,
            (previous[1] if previous else 0) + 1,
        )

    status_by_code = {
        str(entry["code"]).strip(): dict(entry) for entry in configured_status_dictionary
    }
    for status, label in observed_status_labels.items():
        status_by_code.setdefault(
            status,
            {"code": status, "label": label, "active": False},
        )
    status_columns = [
        str(entry["code"])
        for entry in configured_status_dictionary
        if bool(entry["active"])
    ]
    status_columns.extend(
        status
        for status in sorted(observed_status_labels, key=_status_sort_key)
        if status not in status_columns
    )
    status_dictionary = [
        status_by_code[status]
        for status in sorted(status_by_code, key=_status_sort_key)
    ]

    rows: list[WithdrawScoringSummaryItem] = []
    for operator, counts in grouped.items():
        frozen_counts = counts.frozen()
        rows.append(
            WithdrawScoringSummaryItem(
                audit_admin=operator,
                audit_admin_missing=operator_missing[operator],
                status_counts=[
                    {"status": status, "count": count}
                    for status, count in sorted(
                        counts.status_counts.items(), key=lambda item: _status_sort_key(item[0])
                    )
                ],
                total_count=frozen_counts.total_count,
                not_entered_scoring_count=frozen_counts.not_entered_scoring_count,
                score_lte30_count=frozen_counts.score_lte30_count,
                score31_to60_count=frozen_counts.score31_to60_count,
                score_gte61_count=frozen_counts.score_gte61_count,
            )
        )
    rows.sort(
        key=lambda row: (-row.total_count, row.audit_admin.casefold(), row.audit_admin)
    )

    timezone = ZoneInfo(timezone_name)
    frozen_totals = totals.frozen()
    score_distribution = [
        WithdrawScoreDistributionItem(score=score_display, order_count=order_count)
        for _numeric_score, (score_display, order_count) in sorted(
            numeric_score_counts.items(), key=lambda item: item[0]
        )
    ]
    return WithdrawScoringSummaryResult(
        source_id=source_id,
        source_display_name=source_display_name,
        business_timezone=timezone_name,
        start_at=window_start.astimezone(timezone),
        end_at=window_end.astimezone(timezone),
        generated_at=query_at,
        local_updated_at=max(
            (
                value
                for value in (_as_utc(value) for value in synced_at_values)
                if value is not None
            ),
            default=None,
        ),
        rows=rows,
        totals=frozen_totals,
        status_columns=status_columns,
        status_dictionary=status_dictionary,
        management_order_count=management_order_count,
        scoring_record_order_count=frozen_totals.total_count,
        missing_scoring_record_count=missing_scoring_record_count,
        numeric_score_order_count=sum(item.order_count for item in score_distribution),
        unscored_score_record_count=unscored_score_record_count,
        score_distribution=score_distribution,
    )
