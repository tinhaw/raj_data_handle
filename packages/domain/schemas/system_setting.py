from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WithdrawOrderQueryRange = Literal[
    "today",
    "last_1_hour",
    "last_2_hours",
    "last_3_hours",
    "last_6_hours",
    "last_12_hours",
    "last_24_hours",
    "last_48_hours",
]
WithdrawPendingMonitorRefreshIntervalSeconds = Literal[5, 10, 15, 20, 25, 30, 60, 120, 300]
WithdrawPendingMonitorQueryRange = Literal[
    "india_today",
    "india_yesterday_today",
]
WITHDRAW_PENDING_MONITOR_REFRESH_INTERVAL_SECONDS = (5, 10, 15, 20, 25, 30, 60, 120, 300)
WITHDRAW_PENDING_MONITOR_QUERY_RANGES = (
    "india_today",
    "india_yesterday_today",
)


def normalize_withdraw_pending_monitor_refresh_interval(
    value: int | None,
) -> WithdrawPendingMonitorRefreshIntervalSeconds:
    if value in WITHDRAW_PENDING_MONITOR_REFRESH_INTERVAL_SECONDS:
        return cast(WithdrawPendingMonitorRefreshIntervalSeconds, value)
    return 60


def normalize_withdraw_pending_monitor_query_range(
    value: str | None,
) -> WithdrawPendingMonitorQueryRange:
    if value in WITHDRAW_PENDING_MONITOR_QUERY_RANGES:
        return cast(WithdrawPendingMonitorQueryRange, value)
    return "india_today"


WithdrawOrderRefreshPageSize = Literal[10, 20, 30, 50, 100]
WithdrawOrderRefreshRange = Literal["day_before_yesterday", "yesterday", "today"]
WithdrawOrderExportDateMode = Literal["previous_day", "specific_date"]
ChargeOrderQueryRange = WithdrawOrderQueryRange
ChargeOrderRefreshPageSize = WithdrawOrderRefreshPageSize
ChargeOrderExportDateMode = Literal["previous_day", "specific_date"]
SpinOrderRefreshIntervalHours = Literal[1, 2, 3, 4, 6, 8, 12, 24]
SpinOrderRefreshPageSize = WithdrawOrderRefreshPageSize
SpinOrderQueryRange = Literal[
    "last_completed_slot",
    "business_day_to_completed_slot",
    "previous_business_day_to_completed_slot",
    "last_2_hours",
    "last_3_hours",
    "last_6_hours",
    "last_12_hours",
    "previous_day",
]


class RetentionSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    uploaded_file_retention_days: int = Field(alias="uploadedFileRetentionDays")
    result_retention_days: int = Field(alias="resultRetentionDays")
    remote_cache_retention_days: int = Field(alias="remoteCacheRetentionDays")
    sync_log_retention_days: int = Field(alias="syncLogRetentionDays")
    withdraw_pending_monitor_refresh_interval_seconds: (
        WithdrawPendingMonitorRefreshIntervalSeconds
    ) = Field(
        alias="withdrawPendingMonitorRefreshIntervalSeconds",
    )
    withdraw_order_refresh_page_size: WithdrawOrderRefreshPageSize = Field(
        alias="withdrawOrderRefreshPageSize",
    )
    withdraw_pending_monitor_query_range: WithdrawPendingMonitorQueryRange = Field(
        alias="withdrawPendingMonitorQueryRange",
    )
    # Compatibility projection for an already-open pre-upgrade web client.
    # New clients use the monitor-specific second/day fields above.
    withdraw_order_refresh_interval_hours: int = Field(
        ge=1,
        le=24,
        alias="withdrawOrderRefreshIntervalHours",
    )
    withdraw_order_query_range: WithdrawOrderQueryRange = Field(
        alias="withdrawOrderQueryRange",
    )
    withdraw_order_export_date_mode: WithdrawOrderExportDateMode = Field(
        alias="withdrawOrderExportDateMode",
    )
    withdraw_order_export_specific_date: date | None = Field(
        alias="withdrawOrderExportSpecificDate",
    )
    withdraw_order_export_time: time = Field(alias="withdrawOrderExportTime")
    automatic_sync_retry_limit: int = Field(ge=0, le=10, alias="automaticSyncRetryLimit")
    automatic_sync_retry_interval_minutes: int = Field(
        ge=1,
        le=1440,
        alias="automaticSyncRetryIntervalMinutes",
    )
    remote_order_sync_timeout_seconds: int = Field(
        ge=30,
        le=600,
        alias="remoteOrderSyncTimeoutSeconds",
    )
    charge_order_refresh_interval_hours: int = Field(
        ge=1,
        le=24,
        alias="chargeOrderRefreshIntervalHours",
    )
    charge_order_refresh_page_size: ChargeOrderRefreshPageSize = Field(
        alias="chargeOrderRefreshPageSize",
    )
    charge_order_query_range: ChargeOrderQueryRange = Field(
        alias="chargeOrderQueryRange",
    )
    charge_order_export_date_mode: ChargeOrderExportDateMode = Field(
        alias="chargeOrderExportDateMode",
    )
    charge_order_export_specific_date: date | None = Field(
        alias="chargeOrderExportSpecificDate",
    )
    charge_order_export_time: time = Field(alias="chargeOrderExportTime")
    spin_order_refresh_interval_hours: SpinOrderRefreshIntervalHours = Field(
        alias="spinOrderRefreshIntervalHours",
    )
    spin_order_refresh_page_size: SpinOrderRefreshPageSize = Field(
        alias="spinOrderRefreshPageSize",
    )
    spin_order_query_range: SpinOrderQueryRange = Field(alias="spinOrderQueryRange")
    session_ttl_days: int = Field(alias="sessionTtlDays")
    config_version: int = Field(alias="configVersion")
    updated_by: int | None = Field(alias="updatedBy")
    updated_at: datetime = Field(alias="updatedAt")


class RetentionSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uploaded_file_retention_days: int = Field(ge=1, le=3650, alias="uploadedFileRetentionDays")
    result_retention_days: int = Field(ge=1, le=3650, alias="resultRetentionDays")
    remote_cache_retention_days: int = Field(ge=1, le=3650, alias="remoteCacheRetentionDays")
    # Optional for a staged rollout: older clients should not reset the
    # independently managed operational-log retention accidentally.
    sync_log_retention_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        alias="syncLogRetentionDays",
    )
    # Optional so older clients can save other settings without resetting the
    # independently managed live-monitor policy.
    withdraw_pending_monitor_refresh_interval_seconds: (
        WithdrawPendingMonitorRefreshIntervalSeconds | None
    ) = Field(
        default=None,
        alias="withdrawPendingMonitorRefreshIntervalSeconds",
    )
    # Optional so older clients can save other settings during a staged
    # rollout; any explicitly supplied value is one of the remote choices.
    withdraw_order_refresh_page_size: WithdrawOrderRefreshPageSize | None = Field(
        default=None,
        alias="withdrawOrderRefreshPageSize",
    )
    withdraw_pending_monitor_query_range: WithdrawPendingMonitorQueryRange | None = Field(
        default=None,
        alias="withdrawPendingMonitorQueryRange",
    )
    withdraw_order_export_date_mode: WithdrawOrderExportDateMode | None = Field(
        default=None,
        alias="withdrawOrderExportDateMode",
    )
    withdraw_order_export_specific_date: date | None = Field(
        default=None,
        alias="withdrawOrderExportSpecificDate",
    )
    withdraw_order_export_time: time | None = Field(
        default=None,
        alias="withdrawOrderExportTime",
    )
    automatic_sync_retry_limit: int | None = Field(
        default=None,
        ge=0,
        le=10,
        alias="automaticSyncRetryLimit",
    )
    automatic_sync_retry_interval_minutes: int | None = Field(
        default=None,
        ge=1,
        le=1440,
        alias="automaticSyncRetryIntervalMinutes",
    )
    remote_order_sync_timeout_seconds: int | None = Field(
        default=None,
        ge=30,
        le=600,
        alias="remoteOrderSyncTimeoutSeconds",
    )
    charge_order_refresh_interval_hours: int | None = Field(
        default=None,
        ge=1,
        le=24,
        alias="chargeOrderRefreshIntervalHours",
    )
    charge_order_refresh_page_size: ChargeOrderRefreshPageSize | None = Field(
        default=None,
        alias="chargeOrderRefreshPageSize",
    )
    charge_order_query_range: ChargeOrderQueryRange | None = Field(
        default=None,
        alias="chargeOrderQueryRange",
    )
    charge_order_export_date_mode: ChargeOrderExportDateMode | None = Field(
        default=None,
        alias="chargeOrderExportDateMode",
    )
    charge_order_export_specific_date: date | None = Field(
        default=None,
        alias="chargeOrderExportSpecificDate",
    )
    charge_order_export_time: time | None = Field(
        default=None,
        alias="chargeOrderExportTime",
    )
    spin_order_refresh_interval_hours: SpinOrderRefreshIntervalHours | None = Field(
        default=None,
        alias="spinOrderRefreshIntervalHours",
    )
    spin_order_refresh_page_size: SpinOrderRefreshPageSize | None = Field(
        default=None,
        alias="spinOrderRefreshPageSize",
    )
    spin_order_query_range: SpinOrderQueryRange | None = Field(
        default=None,
        alias="spinOrderQueryRange",
    )
    session_ttl_days: int = Field(ge=1, le=365, alias="sessionTtlDays")

    @field_validator("charge_order_export_time", "withdraw_order_export_time")
    @classmethod
    def validate_export_time_precision(cls, value: time | None) -> time | None:
        if value is not None and value.tzinfo is not None:
            raise ValueError("自动导出时间不能包含时区或 UTC 偏移。")
        if value is not None and value.microsecond:
            raise ValueError("自动导出时间必须精确到秒。")
        return value

    @model_validator(mode="after")
    def validate_export_dates(self) -> RetentionSettingsUpdateRequest:
        if (
            self.withdraw_order_export_date_mode == "specific_date"
            and self.withdraw_order_export_specific_date is None
        ):
            raise ValueError("提现订单选择指定日期时必须填写导出日期。")
        if (
            self.charge_order_export_date_mode == "specific_date"
            and self.charge_order_export_specific_date is None
        ):
            raise ValueError("充值订单选择指定日期时必须填写导出日期。")
        return self
