from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from packages.common.schemas import ApiSchema
from packages.domain.schemas.system_setting import ChargeOrderQueryRange


class ChargeOrderQueryRequest(ApiSchema):
    source_id: str = Field(min_length=2, max_length=64)
    create_time_start: str | None = Field(default=None, max_length=19)
    create_time_end: str | None = Field(default=None, max_length=19)
    uid: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=40)
    pay_method: str | None = Field(default=None, max_length=120)
    order_num: str | None = Field(default=None, max_length=160)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=10, le=100)

    @field_validator(
        "create_time_start", "create_time_end", "uid", "status", "pay_method", "order_num"
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    @field_validator("create_time_start", "create_time_end")
    @classmethod
    def validate_optional_wall_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError("创建时间必须使用 YYYY-MM-DD HH:mm:ss 格式。") from exc
        return value

    @model_validator(mode="after")
    def validate_time_range(self) -> ChargeOrderQueryRequest:
        if (self.create_time_start is None) != (self.create_time_end is None):
            raise ValueError("创建时间范围必须同时提供开始和结束时间。")
        if (
            self.create_time_start
            and self.create_time_end
            and self.create_time_start > self.create_time_end
        ):
            raise ValueError("创建时间范围的开始时间不能晚于结束时间。")
        return self


class ChargeChannelSummaryRequest(ChargeOrderQueryRequest):
    page_size: int = Field(default=50, ge=10, le=100)


class ChargeOrderResponse(ApiSchema):
    id: str
    uid: str
    order_num: str | None
    out_trade_no: str | None
    pay_method: str | None
    pay_channel_name: str | None
    amount: str | None
    balance: str | None
    extra: str | None
    status: str
    create_time: str | None
    pay_time: str | None
    update_time: str | None
    first_pay: str | None
    notified: str | None
    charge_type: str | None
    fill_order_num: str | None
    fill_order_admin: str | None


class ChargeStatusDictionaryEntry(ApiSchema):
    code: str
    label: str


class ChargeOrderSummary(ApiSchema):
    order_count: int
    successful_order_count: int
    successful_amount: str
    unpaid_order_count: int
    no_third_party_order_count: int


class ChargeOrderQueryResponse(ApiSchema):
    items: list[ChargeOrderResponse]
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
    status_dictionary: list[ChargeStatusDictionaryEntry]
    channel_dictionary: list[dict[str, str]]
    channel_name_dictionary: list[dict[str, str]]
    summary: ChargeOrderSummary


class ChargeChannelSummaryItem(ApiSchema):
    pay_method: str
    pay_channel_name: str
    order_count: int
    successful_order_count: int
    successful_amount: str
    unpaid_order_count: int
    no_third_party_order_count: int
    successful_order_share: str
    successful_amount_share: str
    success_rate: str


class ChargeChannelSummaryResponse(ApiSchema):
    items: list[ChargeChannelSummaryItem]
    total: int
    page: int
    page_size: int
    source_id: str
    source_display_name: str
    business_timezone: str
    effective_create_time_end: str
    fetched_at: datetime
    local_updated_at: datetime | None


class ChargeOrderRefreshRequest(ApiSchema):
    source_id: str | None = Field(default=None, min_length=2, max_length=64)
    query_range: ChargeOrderQueryRange | None = None

    @field_validator("source_id")
    @classmethod
    def normalize_source_id(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None


class ChargeOrderRefreshResponse(ApiSchema):
    status: str
    source_ids: list[str]
    requested_at: datetime
    query_range: ChargeOrderQueryRange | None
    message: str
