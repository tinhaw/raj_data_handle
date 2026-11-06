"""Schemas for the local-only operational data synchronization log."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from packages.common.schemas import ApiSchema

SyncLogBusinessType = Literal[
    "charge_orders",
    "withdraw_orders",
    "withdraw_scoring_import",
    "spin_orders",
]
SyncLogTriggerType = Literal["automatic", "manual", "upload"]
SyncLogStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "partial",
    "failed",
    "superseded",
    "cancelled",
]


class SyncLogQueryRequest(ApiSchema):
    source_id: str | None = Field(default=None, min_length=2, max_length=64)
    business_types: list[SyncLogBusinessType] | None = Field(default=None, max_length=4)
    trigger_types: list[SyncLogTriggerType] | None = Field(default=None, max_length=3)
    statuses: list[SyncLogStatus] | None = Field(default=None, max_length=7)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    keyword: str | None = Field(default=None, max_length=120)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=10, le=100)

    @field_validator("source_id", "keyword")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    @field_validator("business_types", "trigger_types", "statuses")
    @classmethod
    def normalize_selection(cls, value: list[str] | None) -> list[str] | None:
        if not value:
            return None
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_time_range(self) -> SyncLogQueryRequest:
        if self.started_at and self.ended_at and self.started_at > self.ended_at:
            raise ValueError("执行时间范围的开始时间不能晚于结束时间。")
        return self


class SyncLogRunResponse(ApiSchema):
    id: str
    source_id: str | None
    source_display_name: str
    business_timezone: str | None
    source_config_version: int | None
    business_type: str
    operation_kind: str
    trigger_type: str
    status: str
    requested_by_user_id: int | None
    requested_by_display_name: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    window_start_utc: datetime | None
    window_end_utc: datetime | None
    query_range: str | None
    page_size: int | None
    remote_total: int | None
    export_row_count: int | None
    cached_total: int | None
    fetched_pages: int | None
    imported_count: int | None
    created_count: int | None
    updated_count: int | None
    duplicate_count: int | None
    matched_count: int | None
    unmatched_count: int | None
    resolved_uid_count: int | None
    unresolved_uid_count: int | None
    complete: bool | None
    input_filename: str | None
    input_size_bytes: int | None
    error_code: str | None
    error_message: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SyncLogRunEventResponse(ApiSchema):
    id: int
    event_type: str
    status: str | None
    message: str | None
    metadata: dict[str, Any]
    occurred_at: datetime


class SyncLogSummaryResponse(ApiSchema):
    total: int
    queued_count: int
    running_count: int
    succeeded_count: int
    partial_count: int
    failed_count: int
    superseded_count: int
    cancelled_count: int
    in_progress_count: int
    last_24_hours_succeeded_count: int
    last_24_hours_problem_count: int
    latest_succeeded_at: datetime | None


class SyncLogTrendPoint(ApiSchema):
    bucket_start: datetime
    queued_count: int
    running_count: int
    succeeded_count: int
    partial_count: int
    failed_count: int


class SyncLogQueryResponse(ApiSchema):
    items: list[SyncLogRunResponse]
    total: int
    page: int
    page_size: int
    summary: SyncLogSummaryResponse
    trend: list[SyncLogTrendPoint]
    generated_at: datetime


class SyncLogDetailResponse(ApiSchema):
    run: SyncLogRunResponse
    events: list[SyncLogRunEventResponse]
