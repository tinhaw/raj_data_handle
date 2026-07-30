from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from packages.common.schemas import ApiSchema


class WithdrawOrderQueryRequest(ApiSchema):
    source_id: str = Field(min_length=2, max_length=64)
    uid: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=40)
    audit_admin: str | None = Field(default=None, max_length=120)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=10, le=100)

    @field_validator("uid", "status", "audit_admin")
    @classmethod
    def normalize_optional_filter(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None


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
