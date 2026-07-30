from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
WithdrawOrderRefreshPageSize = Literal[10, 20, 30, 50, 100]
WithdrawOrderRefreshRange = Literal["day_before_yesterday", "yesterday", "today"]
WithdrawOrderExportDateMode = Literal["previous_day", "specific_date"]
ChargeOrderQueryRange = WithdrawOrderQueryRange
ChargeOrderRefreshPageSize = WithdrawOrderRefreshPageSize
ChargeOrderExportDateMode = Literal["previous_day", "specific_date"]


class RetentionSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    uploaded_file_retention_days: int = Field(alias="uploadedFileRetentionDays")
    result_retention_days: int = Field(alias="resultRetentionDays")
    remote_cache_retention_days: int = Field(alias="remoteCacheRetentionDays")
    withdraw_order_refresh_interval_hours: int = Field(
        ge=1,
        le=24,
        alias="withdrawOrderRefreshIntervalHours",
    )
    withdraw_order_refresh_page_size: WithdrawOrderRefreshPageSize = Field(
        alias="withdrawOrderRefreshPageSize",
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
    session_ttl_days: int = Field(alias="sessionTtlDays")
    config_version: int = Field(alias="configVersion")
    updated_by: int | None = Field(alias="updatedBy")
    updated_at: datetime = Field(alias="updatedAt")


class RetentionSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uploaded_file_retention_days: int = Field(ge=1, le=3650, alias="uploadedFileRetentionDays")
    result_retention_days: int = Field(ge=1, le=3650, alias="resultRetentionDays")
    remote_cache_retention_days: int = Field(ge=1, le=3650, alias="remoteCacheRetentionDays")
    # Kept optional for a compatible API rollout: legacy clients can still
    # save other system settings without resetting this newly introduced value.
    withdraw_order_refresh_interval_hours: int | None = Field(
        default=None,
        ge=1,
        le=24,
        alias="withdrawOrderRefreshIntervalHours",
    )
    # Optional so older clients can save other settings during a staged
    # rollout; any explicitly supplied value is one of the remote choices.
    withdraw_order_refresh_page_size: WithdrawOrderRefreshPageSize | None = Field(
        default=None,
        alias="withdrawOrderRefreshPageSize",
    )
    # Optional so older clients can save other settings during a staged
    # rollout; any explicitly supplied value is constrained to these presets.
    withdraw_order_query_range: WithdrawOrderQueryRange | None = Field(
        default=None,
        alias="withdrawOrderQueryRange",
    )
    withdraw_order_export_date_mode: WithdrawOrderExportDateMode | None = Field(
        default=None,
        alias="withdrawOrderExportDateMode",
    )
    withdraw_order_export_specific_date: date | None = Field(
        default=None,
        alias="withdrawOrderExportSpecificDate",
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
    session_ttl_days: int = Field(ge=1, le=365, alias="sessionTtlDays")

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
