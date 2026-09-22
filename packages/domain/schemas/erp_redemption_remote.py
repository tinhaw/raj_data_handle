"""Contracts for local orchestration of future remote redemption operations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from packages.common.schemas import ApiSchema

ErpRedemptionType = Literal["SEVEN_DAY_DEPOSIT", "PREVIOUS_DAY_DEPOSIT"]
ErpRedemptionRemoteOperation = Literal["CREATE", "PUBLISH", "DOWNLOAD", "CANCEL"]
ErpRedemptionRemotePlanStatus = Literal[
    "AWAITING_CREATE_AUTHORIZATION",
    "CREATING",
    "CREATE_FAILED",
    "READY_TO_PUBLISH",
    "AWAITING_PUBLISH_AUTHORIZATION",
    "PUBLISHING",
    "PUBLISH_FAILED",
    "PUBLISH_SCHEDULED",
    "PUBLISHED",
    "DOWNLOADING",
    "DOWNLOAD_FAILED",
    "COMPLETED",
    "CANCEL_PENDING",
    "CANCEL_FAILED",
    "CANCELLED",
]


class ErpRedemptionRemotePlanOptions(ApiSchema):
    redemption_type: ErpRedemptionType = "SEVEN_DAY_DEPOSIT"
    publish_environment: Literal["test", "prod"] = "test"
    flow_times: int = Field(default=5, ge=0, le=1000)
    creation_interval_seconds: int = Field(default=5, ge=1, le=60)
    activity_recharge: Decimal | None = Field(default=None, ge=0, max_digits=24, decimal_places=8)
    activity_recharge_count: int | None = Field(default=None, ge=0, le=100_000)
    activity_id: int | None = Field(default=None, ge=1)
    key_number: int = Field(default=1, ge=1, le=1)
    single_user_limit: int = Field(default=1, ge=1, le=100)
    single_key_limit: int = Field(default=2000, ge=1, le=100_000)
    require_bind_bank_card: bool = False
    require_bind_phone: bool = True
    check_uuid: bool = True
    uuid_reward_limit: int = Field(default=1, ge=1, le=100)
    check_login_ip: bool = True
    login_ip_reward_limit: int = Field(default=1, ge=1, le=100)
    check_register_ip: bool = True
    register_ip_reward_limit: int = Field(default=1, ge=1, le=100)


class ErpRedemptionTaskRemotePlanWrite(ErpRedemptionRemotePlanOptions):
    """Shared options applied to every account subtask using its saved preset."""


class ErpRedemptionRemotePlanWrite(ErpRedemptionRemotePlanOptions):
    tier_label_ids: dict[str, list[int]] = Field(default_factory=dict, max_length=50)
    row_version: int | None = Field(default=None, ge=1)

    @field_validator("tier_label_ids")
    @classmethod
    def validate_label_ids(cls, value: dict[str, list[int]]) -> dict[str, list[int]]:
        normalized: dict[str, list[int]] = {}
        for tier_id, label_ids in value.items():
            key = tier_id.strip()
            if not key:
                raise ValueError("充值档位 ID 不能为空。")
            if len(label_ids) > 100:
                raise ValueError("每个充值档位最多配置 100 个标签 ID。")
            unique = list(dict.fromkeys(label_ids))
            if any(label_id < 1 for label_id in unique):
                raise ValueError("标签 ID 必须为正整数。")
            normalized[key] = unique
        return normalized

    @model_validator(mode="after")
    def require_seven_day_labels(self) -> ErpRedemptionRemotePlanWrite:
        if self.redemption_type == "SEVEN_DAY_DEPOSIT" and any(
            not label_ids for label_ids in self.tier_label_ids.values()
        ):
            raise ValueError("近 7 天充值的每个档位都必须配置标签 ID。")
        return self


class ErpRedemptionRemotePublishPlanRequest(ApiSchema):
    mode: Literal["IMMEDIATE", "SCHEDULED"]
    scheduled_local_at: datetime | None = None
    fallback_to_scheduled: bool = True
    note: str | None = Field(default=None, max_length=2000)
    row_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_schedule(self) -> ErpRedemptionRemotePublishPlanRequest:
        if self.mode == "SCHEDULED" and self.scheduled_local_at is None:
            raise ValueError("定时发布必须填写业务时区发布时间。")
        if self.mode == "IMMEDIATE" and self.scheduled_local_at is not None:
            raise ValueError("立即发布不能填写定时时间。")
        if self.scheduled_local_at is not None and self.scheduled_local_at.tzinfo is not None:
            raise ValueError("定时时间请填写盘口业务时区的本地时间，不要附带时区偏移。")
        return self


class ErpRedemptionRemoteScheduleCancelRequest(ApiSchema):
    row_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("取消原因不能为空。")
        return normalized


class ErpRedemptionRemotePlanRecoverRequest(ApiSchema):
    row_version: int = Field(ge=1)


class ErpRedemptionRemotePlanResponse(ApiSchema):
    id: str
    batch_id: str
    remote_account_id: str
    remote_account_name: str
    source_id: str
    source_display_name: str
    business_timezone: str
    redemption_type: ErpRedemptionType
    workflow_status: ErpRedemptionRemotePlanStatus
    publish_environment: Literal["test", "prod"]
    flow_times: int
    creation_interval_seconds: int
    activity_recharge: Decimal | None
    activity_recharge_count: int | None
    activity_id: int | None
    key_number: int
    single_user_limit: int
    single_key_limit: int
    require_bind_bank_card: bool
    require_bind_phone: bool
    check_uuid: bool
    uuid_reward_limit: int
    check_login_ip: bool
    login_ip_reward_limit: int
    check_register_ip: bool
    register_ip_reward_limit: int
    publish_mode: Literal["IMMEDIATE", "SCHEDULED"] | None
    scheduled_publish_at: datetime | None
    scheduled_publish_local_at: datetime | None
    fallback_to_scheduled: bool
    publish_note: str | None
    remote_publish_task_id: str | None
    schedule_cancelled_at: datetime | None
    reserved_operation: ErpRedemptionRemoteOperation | None
    error_code: str | None
    error_message: str | None
    issue_count: int
    created_count: int
    downloaded_count: int
    failed_count: int
    schedule_due: bool
    row_version: int
    created_at: datetime
    updated_at: datetime


class ErpRedemptionRemoteExecutionResponse(ApiSchema):
    id: str
    plan_id: str
    issue_id: str | None
    operation: ErpRedemptionRemoteOperation
    trigger_type: Literal["MANUAL", "SCHEDULED"]
    status: Literal["RESERVED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
    attempt_number: int
    scheduled_for: datetime | None
    remote_request_id: str | None
    error_code: str | None
    error_message: str | None
    result_metadata: dict[str, object]
    requested_by: int | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
