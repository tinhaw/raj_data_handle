from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from packages.common.schemas import ApiSchema


class SpinOrderBaseQueryRequest(ApiSchema):
    source_id: str = Field(min_length=2, max_length=64)
    create_time_start: str | None = Field(default=None, max_length=19)
    create_time_end: str | None = Field(default=None, max_length=19)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=10, le=100)

    @field_validator("create_time_start", "create_time_end", mode="before")
    @classmethod
    def normalize_time(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("create_time_start", "create_time_end")
    @classmethod
    def validate_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError("申请时间必须使用 YYYY-MM-DD HH:mm:ss 格式。") from exc
        return value

    @model_validator(mode="after")
    def validate_range(self) -> SpinOrderBaseQueryRequest:
        if (self.create_time_start is None) != (self.create_time_end is None):
            raise ValueError("申请时间范围必须同时提供开始和结束时间。")
        if self.create_time_start and self.create_time_end:
            if self.create_time_start > self.create_time_end:
                raise ValueError("申请时间范围的开始时间不能晚于结束时间。")
        return self


class SpinOrderQueryRequest(SpinOrderBaseQueryRequest):
    uid: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=40)
    spin_config_id: str | None = Field(default=None, max_length=40)
    channel_id: str | None = Field(default=None, max_length=120)

    @field_validator("uid", "status", "spin_config_id", "channel_id")
    @classmethod
    def normalize_filter(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class SpinChannelSummaryRequest(SpinOrderBaseQueryRequest):
    spin_config_id: str | None = Field(default=None, max_length=40)
    channel_id: str | None = Field(default=None, max_length=120)

    @field_validator("spin_config_id", "channel_id")
    @classmethod
    def normalize_filter(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class SpinOrderResponse(ApiSchema):
    id: str
    uid: str
    vip_level: str | None
    agent_total_count: str | None
    amount: str | None
    spin_config_id: str
    spin_config_label: str
    round_number: str | None
    invite_count: str | None
    status: str
    status_label: str
    create_time: str | None
    audit_time: str | None
    channel_id: str | None
    channel_name: str


class SpinStatusDictionaryEntry(ApiSchema):
    code: str
    label: str
    active: bool


class SpinChannelDictionaryEntry(ApiSchema):
    code: str
    label: str


class SpinOrderStatusDistribution(ApiSchema):
    status: str
    count: int


class SpinOrderSummary(ApiSchema):
    order_count: int
    passed_order_count: int
    pending_order_count: int
    rejected_order_count: int
    suspended_order_count: int
    approval_rate: str
    winner_count: int
    passed_winner_count: int
    person_approval_rate: str
    status_distribution: list[SpinOrderStatusDistribution]


class SpinOrderQueryResponse(ApiSchema):
    items: list[SpinOrderResponse]
    total: int
    page: int
    page_size: int
    source_id: str
    source_display_name: str
    business_timezone: str
    fetched_at: datetime
    local_updated_at: datetime | None
    last_refreshed_at: datetime | None
    refresh_status: str
    remote_total: int
    fetched_pages: int
    complete: bool
    resolved_uid_count: int
    unresolved_uid_count: int
    status_dictionary: list[SpinStatusDictionaryEntry]
    channel_dictionary: list[SpinChannelDictionaryEntry]
    summary: SpinOrderSummary


class SpinChannelSummaryItem(ApiSchema):
    date: str
    spin_config_id: str
    spin_config_label: str
    channel_id: str | None
    channel_name: str
    application_order_count: int
    passed_order_count: int
    pending_order_count: int
    rejected_order_count: int
    suspended_order_count: int
    approval_rate: str
    winner_count: int
    passed_winner_count: int
    person_approval_rate: str


class SpinTwoHourSeriesItem(ApiSchema):
    date: str
    bucket: str
    spin_config_id: str
    spin_config_label: str
    channel_id: str | None
    channel_name: str
    applicant_count: int


class SpinChannelSummaryResponse(ApiSchema):
    items: list[SpinChannelSummaryItem]
    total: int
    page: int
    page_size: int
    source_id: str
    source_display_name: str
    business_timezone: str
    fetched_at: datetime
    local_updated_at: datetime | None
    channel_dictionary: list[SpinChannelDictionaryEntry]
    time_series: list[SpinTwoHourSeriesItem]


class SpinOrderRefreshRequest(ApiSchema):
    source_id: str | None = Field(default=None, min_length=2, max_length=64)
    query_range: str | None = Field(
        default=None,
        pattern="^(day_before_yesterday|yesterday|today)$",
    )

    @field_validator("source_id")
    @classmethod
    def normalize_source(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class SpinOrderRefreshResponse(ApiSchema):
    status: str
    source_ids: list[str]
    requested_at: datetime
    query_range: str | None
    message: str
