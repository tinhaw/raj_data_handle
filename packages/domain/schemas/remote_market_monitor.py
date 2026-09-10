"""Public contracts for the durable remote-market monitoring module."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from packages.common.schemas import ApiSchema

MetricName = Literal["pending_audit", "pending_review"]
Comparison = Literal["gt", "gte"]
QueryWindowMode = Literal["business_today", "business_today_and_previous_days"]
DeliveryMode = Literal["record_only", "telegram"]


class RemoteMarketMonitorSettingsResponse(ApiSchema):
    monitor_enabled: bool
    delivery_mode: DeliveryMode
    dashboard_refresh_interval_seconds: int
    default_check_interval_seconds: int
    source_request_timeout_seconds: int
    default_breach_consecutive_checks: int
    default_recovery_consecutive_checks: int
    source_failure_consecutive_checks: int
    default_reminder_interval_minutes: int
    source_reminder_interval_minutes: int
    stale_after_multiplier: int
    notification_max_attempts: int
    check_run_retention_days: int
    notification_attempt_retention_days: int
    config_version: int
    updated_at: datetime


class RemoteMarketMonitorSettingsUpdateRequest(ApiSchema):
    monitor_enabled: bool
    delivery_mode: DeliveryMode
    dashboard_refresh_interval_seconds: int = Field(ge=5, le=300)
    default_check_interval_seconds: int = Field(ge=30, le=3600)
    source_request_timeout_seconds: int = Field(ge=5, le=120)
    default_breach_consecutive_checks: int = Field(ge=1, le=20)
    default_recovery_consecutive_checks: int = Field(ge=1, le=20)
    source_failure_consecutive_checks: int = Field(ge=1, le=20)
    default_reminder_interval_minutes: int = Field(ge=1, le=1440)
    source_reminder_interval_minutes: int = Field(ge=1, le=1440)
    stale_after_multiplier: int = Field(ge=2, le=20)
    notification_max_attempts: int = Field(ge=1, le=10)
    check_run_retention_days: int = Field(ge=1, le=3650)
    notification_attempt_retention_days: int = Field(ge=1, le=3650)


class MonitorNotificationDestinationResponse(ApiSchema):
    id: str
    display_name: str
    channel: str
    enabled: bool
    template_set_id: str
    bot_token_configured: bool
    chat_id_configured: bool
    updated_at: datetime


class MonitorNotificationDestinationCreateRequest(ApiSchema):
    display_name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    bot_token_secret_ref: str = Field(min_length=7, max_length=200)
    chat_id_secret_ref: str = Field(min_length=7, max_length=200)
    template_set_id: str = Field(default="default-zh", min_length=1, max_length=64)

    @field_validator("bot_token_secret_ref", "chat_id_secret_ref")
    @classmethod
    def validate_secret_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("env://") or len(normalized) <= len("env://"):
            raise ValueError("密钥引用必须使用 env://变量名。")
        return normalized


class MonitorNotificationDestinationUpdateRequest(ApiSchema):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    bot_token_secret_ref: str | None = Field(default=None, min_length=7, max_length=200)
    chat_id_secret_ref: str | None = Field(default=None, min_length=7, max_length=200)
    template_set_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("bot_token_secret_ref", "chat_id_secret_ref")
    @classmethod
    def validate_optional_secret_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized.startswith("env://") or len(normalized) <= len("env://"):
            raise ValueError("密钥引用必须使用 env://变量名。")
        return normalized


class MonitorNotificationTemplateSetResponse(ApiSchema):
    id: str
    display_name: str
    templates: dict[str, str]
    is_builtin: bool
    config_version: int
    updated_at: datetime


class MonitorNotificationTemplateSetCreateRequest(ApiSchema):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str = Field(min_length=1, max_length=120)
    templates: dict[str, str]


class MonitorNotificationTemplateSetUpdateRequest(ApiSchema):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    templates: dict[str, str] | None = None


class RemoteMarketMonitorMetricPolicyInput(ApiSchema):
    metric: MetricName
    enabled: bool = True
    comparison: Comparison = "gt"
    threshold: int = Field(ge=0, le=1_000_000_000)
    recovery_threshold: int = Field(ge=0, le=1_000_000_000)
    breach_consecutive_checks: int = Field(ge=1, le=20)
    recovery_consecutive_checks: int = Field(ge=1, le=20)
    reminder_interval_minutes: int | None = Field(default=None, ge=1, le=1440)

    @model_validator(mode="after")
    def validate_recovery_threshold(self) -> RemoteMarketMonitorMetricPolicyInput:
        if self.recovery_threshold > self.threshold:
            raise ValueError("恢复阈值不能大于告警阈值。")
        return self


class RemoteMarketMonitorMetricPolicyResponse(RemoteMarketMonitorMetricPolicyInput):
    pass


class RemoteMarketMonitorTargetUpdateRequest(ApiSchema):
    enabled: bool
    check_interval_seconds: int = Field(ge=30, le=3600)
    query_window_mode: QueryWindowMode
    previous_days: int = Field(default=1, ge=1, le=7)
    source_failure_consecutive_checks: int | None = Field(default=None, ge=1, le=20)
    source_reminder_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    destination_ids: list[str] = Field(default_factory=list, max_length=30)
    policies: list[RemoteMarketMonitorMetricPolicyInput] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_policy_set(self) -> RemoteMarketMonitorTargetUpdateRequest:
        metrics = {policy.metric for policy in self.policies}
        if metrics != {"pending_audit", "pending_review"}:
            raise ValueError("必须同时配置待审核和待审查两个指标。")
        if self.query_window_mode == "business_today" and self.previous_days != 1:
            raise ValueError("仅当天查询不需要调整回查天数。")
        return self


class RemoteMarketMonitorTargetResponse(ApiSchema):
    source_id: str
    source_display_name: str
    business_timezone: str
    source_enabled: bool
    enabled: bool
    check_interval_seconds: int
    query_window_mode: QueryWindowMode
    previous_days: int
    source_failure_consecutive_checks: int | None
    source_reminder_interval_minutes: int | None
    destination_ids: list[str]
    policies: list[RemoteMarketMonitorMetricPolicyResponse]
    next_check_at: datetime | None
    last_check_at: datetime | None
    last_success_at: datetime | None
    last_pending_audit_count: int | None
    last_pending_review_count: int | None
    source_health: str
    consecutive_source_failure_count: int
    last_error_code: str | None
    last_safe_error_message: str | None


class RemoteMarketMonitorOverviewResponse(ApiSchema):
    generated_at: datetime
    settings: RemoteMarketMonitorSettingsResponse
    targets: list[RemoteMarketMonitorTargetResponse]
    open_incident_count: int
    pending_outbox_count: int


class RemoteMarketMonitorCheckRunResponse(ApiSchema):
    id: str
    source_id: str
    run_mode: str
    status: str
    pending_audit_count: int | None
    pending_review_count: int | None
    query_range_start: datetime | None
    query_range_end: datetime | None
    started_at: datetime
    finished_at: datetime
    latency_ms: int | None
    error_code: str | None
    safe_error_message: str | None


class RemoteMarketMonitorIncidentResponse(ApiSchema):
    id: str
    source_id: str
    metric: str
    incident_type: str
    status: str
    opened_at: datetime
    last_observed_at: datetime
    closed_at: datetime | None
    opening_count: int | None
    latest_count: int | None
    peak_count: int | None
    last_error_code: str | None
