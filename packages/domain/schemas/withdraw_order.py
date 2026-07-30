from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from packages.common.schemas import ApiSchema


class WithdrawOrderQueryRequest(ApiSchema):
    source_id: str = Field(min_length=2, max_length=64)
    create_time_start: str | None = Field(default=None, max_length=19)
    create_time_end: str | None = Field(default=None, max_length=19)
    uid: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=40)
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

    @field_validator("uid", "status", "audit_admin")
    @classmethod
    def normalize_optional_filter(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_create_time_range(self) -> WithdrawOrderQueryRequest:
        if (self.create_time_start is None) != (self.create_time_end is None):
            raise ValueError("创建时间范围必须同时提供开始和结束时间。")
        if self.create_time_start is None or self.create_time_end is None:
            return self
        start = datetime.strptime(self.create_time_start, "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(self.create_time_end, "%Y-%m-%d %H:%M:%S")
        if start > end:
            raise ValueError("创建时间范围的开始时间不能晚于结束时间。")
        return self


class WithdrawOrderResponse(ApiSchema):
    id: str
    uid: str
    amount: str | None
    real_amount: str | None
    create_time: str | None
    update_time: str | None
    submit_time: str | None
    audit_admin: str | None
    status: str


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
    summary: WithdrawOrderSummary


class WithdrawOrderRefreshRequest(ApiSchema):
    """Queue one source, or all eligible sources when source_id is omitted."""

    source_id: str | None = Field(default=None, min_length=2, max_length=64)

    @field_validator("source_id")
    @classmethod
    def normalize_source_id(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None


class WithdrawOrderRefreshResponse(ApiSchema):
    status: str
    source_ids: list[str]
    requested_at: datetime
    message: str
