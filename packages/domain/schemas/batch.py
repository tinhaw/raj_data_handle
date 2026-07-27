from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from packages.common.schemas import ApiSchema


class BatchResponse(ApiSchema):
    id: str
    comparison_series_id: str
    run_version: int
    rerun_of_batch_id: str | None
    source_id: str
    source_display_name: str
    source_config_version: int
    source_business_timezone: str
    source_currency: str
    business_type: str
    status: str
    is_final: bool
    uploaded_file_name: str
    uploaded_file_sha256: str
    parameters_json: dict[str, Any]
    progress_json: dict[str, Any]
    execution_requested_by: int
    created_by: int
    error_category: str | None
    error_message: str | None
    cancellation_requested_at: datetime | None
    cancelled_at: datetime | None
    cancelled_by: int | None
    cancellation_reason: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result_expires_at: datetime
    updated_at: datetime


class BatchListResponse(ApiSchema):
    items: list[BatchResponse]
    total: int


class BatchCreateResponse(ApiSchema):
    batch: BatchResponse
    duplicate_of_existing: bool


class BatchCancelRequest(ApiSchema):
    reason: str | None = Field(default=None, max_length=500)


class OrderResultResponse(ApiSchema):
    id: str
    batch_id: str
    order_group_id: str
    result_status: str
    payment_status_raw: str | None
    payment_status_group: str
    merchant_order_no: str | None
    platform_order_no: str | None
    payload_json: dict[str, Any]
    is_final: bool
    created_at: datetime


class OrderResultListResponse(ApiSchema):
    items: list[OrderResultResponse]
    total: int


class BatchSummaryResponse(ApiSchema):
    batch_id: str
    run_version: int
    is_final: bool
    counts: dict[str, int]
    aggregation_version: str = "v1"


class BatchChartsResponse(ApiSchema):
    batch_id: str
    run_version: int
    is_final: bool
    result_status_distribution: list[dict[str, Any]]
    payment_status_result_matrix: list[dict[str, Any]]
    time_series: list[dict[str, Any]]
    channel_comparison: list[dict[str, Any]]
    aggregation_version: str = "v1"


class OperationalSummaryResponse(ApiSchema):
    execution_status_distribution: list[dict[str, Any]]
    execution_created_time_series: list[dict[str, Any]]
    execution_duration_buckets: list[dict[str, Any]]
    failure_category_distribution: list[dict[str, Any]]
    aggregation_version: str = "v1"
