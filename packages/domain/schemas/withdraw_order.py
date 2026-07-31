from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from packages.common.schemas import ApiSchema
from packages.domain.schemas.system_setting import WithdrawOrderRefreshRange


class WithdrawOrderLocalQueryRequest(ApiSchema):
    """Common local-cache filters shared by withdrawal read endpoints."""

    source_id: str = Field(min_length=2, max_length=64)
    create_time_start: str | None = Field(default=None, max_length=19)
    create_time_end: str | None = Field(default=None, max_length=19)
    audit_admin: str | None = Field(default=None, max_length=120)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=10, le=100)

    @field_validator("create_time_start", "create_time_end", mode="before")
    @classmethod
    def normalize_optional_create_time(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None

    @field_validator("create_time_start", "create_time_end")
    @classmethod
    def validate_optional_create_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError("创建时间必须使用 YYYY-MM-DD HH:mm:ss 格式。") from exc
        return value

    @field_validator("audit_admin")
    @classmethod
    def normalize_optional_filter(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_create_time_range(self) -> WithdrawOrderLocalQueryRequest:
        if (self.create_time_start is None) != (self.create_time_end is None):
            raise ValueError("创建时间范围必须同时提供开始和结束时间。")
        if self.create_time_start is None or self.create_time_end is None:
            return self
        start = datetime.strptime(self.create_time_start, "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(self.create_time_end, "%Y-%m-%d %H:%M:%S")
        if start > end:
            raise ValueError("创建时间范围的开始时间不能晚于结束时间。")
        return self


class WithdrawOrderQueryRequest(WithdrawOrderLocalQueryRequest):
    uid: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=40)
    order_num: str | None = Field(default=None, max_length=160)
    out_trade_no: str | None = Field(default=None, max_length=160)
    pay_channel: str | None = Field(default=None, max_length=120)

    @field_validator("uid", "status", "order_num", "out_trade_no", "pay_channel")
    @classmethod
    def normalize_query_optional_filter(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None


class WithdrawChannelSummaryRequest(WithdrawOrderLocalQueryRequest):
    """Aggregate approved local snapshots by business day and payment channel."""

    pay_channel: str | None = Field(default=None, max_length=120)
    page_size: int = Field(default=50, ge=10, le=100)

    @field_validator("pay_channel")
    @classmethod
    def normalize_channel_filter(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None


class WithdrawOperatorSummaryRequest(WithdrawOrderLocalQueryRequest):
    """Aggregate local withdrawal snapshots by their displayed operator name."""

    statuses: list[str] | None = Field(default=None, max_length=20)
    page_size: int = Field(default=20, ge=1, le=100)

    @field_validator("statuses", mode="before")
    @classmethod
    def normalize_empty_statuses(cls, value: object) -> object:
        if isinstance(value, (list, tuple)) and not value:
            return None
        return value

    @field_validator("statuses")
    @classmethod
    def normalize_selected_statuses(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for raw_status in value:
            status = raw_status.strip()
            if not status:
                raise ValueError("状态筛选不能包含空状态值。")
            if len(status) > 40:
                raise ValueError("状态值长度不能超过 40 个字符。")
            if status not in normalized:
                normalized.append(status)
        if not normalized:
            raise ValueError("状态筛选不能为空。")
        return normalized


class ScoringReviewOperatorSummaryRequest(ApiSchema):
    """Source-scoped local-cache range for scoring-review aggregation."""

    source_id: str = Field(min_length=2, max_length=64)
    create_time_start: str = Field(min_length=19, max_length=19)
    create_time_end: str = Field(min_length=19, max_length=19)

    @field_validator("source_id")
    @classmethod
    def normalize_source_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("盘口不能为空。")
        return normalized

    @field_validator("create_time_start", "create_time_end")
    @classmethod
    def validate_create_time(cls, value: str) -> str:
        normalized = value.strip()
        try:
            datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError("创建时间必须使用 YYYY-MM-DD HH:mm:ss 格式。") from exc
        return normalized

    @model_validator(mode="after")
    def validate_create_time_range(self) -> ScoringReviewOperatorSummaryRequest:
        start = datetime.strptime(self.create_time_start, "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(self.create_time_end, "%Y-%m-%d %H:%M:%S")
        if start > end:
            raise ValueError("创建时间范围的开始时间不能晚于结束时间。")
        return self


class WithdrawOrderResponse(ApiSchema):
    id: str
    uid: str
    order_num: str | None
    out_trade_no: str | None
    pay_channel_name: str | None
    pay_channel: str | None
    amount: str | None
    real_amount: str | None
    fee: str | None
    create_time: str | None
    update_time: str | None
    submit_time: str | None
    audit_admin: str | None
    status: str
    status_label: str | None
    is_first: str | None
    channel: str | None
    # Scoring-review values are strictly supplemental.  The withdrawal export
    # remains the source of truth for every existing withdrawal-order field.
    # A missing scoring row is represented by ``None`` rather than creating a
    # scoring-only order in the detail response.
    scoring_record_imported: bool = False
    scoring_global_gate: str | None = None
    scoring_scene_review: str | None = None
    scoring_score: str | None = None
    scoring_decision_stage: str | None = None
    scoring_final_suggestion: str | None = None
    scoring_operation_result: str | None = None
    scoring_summary: str | None = None
    scoring_current_status: str | None = None
    scoring_reviewed_at: str | None = None
    scoring_review_elapsed: str | None = None
    scoring_queue_elapsed: str | None = None
    scoring_queue_entered_at: str | None = None
    scoring_queue_exited_at: str | None = None


class WithdrawStatusSummary(ApiSchema):
    status: str
    count: int
    amount: str
    real_amount: str


class WithdrawTimeSummary(ApiSchema):
    bucket: str
    count: int
    amount: str
    real_amount: str


class WithdrawOrderSummary(ApiSchema):
    order_count: int
    amount: str
    real_amount: str
    average_amount: str
    status_distribution: list[WithdrawStatusSummary]
    time_series: list[WithdrawTimeSummary]


class WithdrawStatusDictionaryEntry(ApiSchema):
    code: str
    label: str
    active: bool


class WithdrawChannelDictionaryEntry(ApiSchema):
    code: str
    label: str


class WithdrawOrderQueryResponse(ApiSchema):
    items: list[WithdrawOrderResponse]
    total: int
    remote_total: int
    page: int
    page_size: int
    fetched_pages: int
    complete: bool
    source_id: str
    source_display_name: str
    business_timezone: str
    currency: str
    effective_create_time_end: str
    fetched_at: datetime
    local_updated_at: datetime | None
    last_refreshed_at: datetime | None
    refresh_status: str
    status_dictionary: list[WithdrawStatusDictionaryEntry]
    channel_dictionary: list[WithdrawChannelDictionaryEntry]
    summary: WithdrawOrderSummary


class WithdrawChannelSummaryItem(ApiSchema):
    date: str
    pay_channel: str
    pay_channel_name: str
    order_count: int
    successful_order_count: int
    successful_amount: str
    successful_fee: str
    failed_order_count: int
    submitted_order_count: int
    rejected_order_count: int
    successful_order_share: str
    successful_amount_share: str
    stuck_rate: str
    success_rate: str


class WithdrawChannelSummaryResponse(ApiSchema):
    items: list[WithdrawChannelSummaryItem]
    total: int
    page: int
    page_size: int
    source_id: str
    source_display_name: str
    business_timezone: str
    currency: str
    effective_create_time_end: str
    fetched_at: datetime
    local_updated_at: datetime | None
    channel_dictionary: list[WithdrawChannelDictionaryEntry]


class WithdrawOperatorStatusCount(ApiSchema):
    status: str
    count: int


class WithdrawOperatorSummaryItem(ApiSchema):
    audit_admin: str
    audit_admin_missing: bool
    status_counts: list[WithdrawOperatorStatusCount]
    selected_total: int


class WithdrawOperatorSummaryResponse(ApiSchema):
    items: list[WithdrawOperatorSummaryItem]
    total: int
    page: int
    page_size: int
    source_id: str
    source_display_name: str
    business_timezone: str
    effective_create_time_end: str
    fetched_at: datetime
    local_updated_at: datetime | None
    status_columns: list[str]
    status_dictionary: list[WithdrawStatusDictionaryEntry]
    selected_order_total: int


class ScoringReviewSummaryCounts(ApiSchema):
    total_count: int = Field(ge=0)
    not_entered_scoring_count: int = Field(ge=0)
    score_lte30_count: int = Field(ge=0)
    score31_to60_count: int = Field(ge=0)
    score_gte61_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_score_distribution(self) -> ScoringReviewSummaryCounts:
        if self.not_entered_scoring_count > self.score_lte30_count:
            raise ValueError("未进入评分数量不能大于 30 分及以下数量。")
        if self.total_count != (
            self.score_lte30_count + self.score31_to60_count + self.score_gte61_count
        ):
            raise ValueError("评分区间数量之和必须等于总单数。")
        return self


class ScoringReviewOperatorSummaryItem(ScoringReviewSummaryCounts):
    operator: str = Field(min_length=1, max_length=120)

    @field_validator("operator")
    @classmethod
    def normalize_operator(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("操作人不能为空。")
        return normalized


class ScoringReviewOperatorSummaryResponse(ApiSchema):
    source_id: str = Field(min_length=1, max_length=64)
    source_display_name: str = Field(min_length=1, max_length=120)
    business_timezone: str = Field(min_length=1, max_length=120)
    start_at: datetime
    end_at: datetime
    generated_at: datetime
    local_updated_at: datetime | None
    rows: list[ScoringReviewOperatorSummaryItem]
    totals: ScoringReviewSummaryCounts

    @model_validator(mode="after")
    def validate_totals_match_rows(self) -> ScoringReviewOperatorSummaryResponse:
        fields = (
            "total_count",
            "not_entered_scoring_count",
            "score_lte30_count",
            "score31_to60_count",
            "score_gte61_count",
        )
        for field_name in fields:
            expected = sum(getattr(row, field_name) for row in self.rows)
            if getattr(self.totals, field_name) != expected:
                raise ValueError("评分审核汇总合计与操作人明细不一致。")
        return self


class WithdrawScoringImportResponse(ApiSchema):
    """Safe counters for a score-workbook supplement import.

    The uploaded workbook itself is parsed in memory and deliberately not
    retained as an application file object.
    """

    source_id: str
    source_row_count: int = Field(ge=0)
    matched_count: int = Field(ge=0)
    created_count: int = Field(ge=0)
    updated_count: int = Field(ge=0)
    unmatched_count: int = Field(ge=0)
    synced_at: datetime


class WithdrawOrderRefreshRequest(ApiSchema):
    """Queue one source, or all eligible sources when source_id is omitted."""

    source_id: str | None = Field(default=None, min_length=2, max_length=64)
    query_range: WithdrawOrderRefreshRange | None = None

    @field_validator("source_id")
    @classmethod
    def normalize_source_id(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None


class WithdrawOrderRefreshResponse(ApiSchema):
    status: str
    source_ids: list[str]
    requested_at: datetime
    query_range: WithdrawOrderRefreshRange | None
    message: str
