from __future__ import annotations

from typing import Any

from packages.common.schemas import ApiSchema


class PaymentPlatformResponse(ApiSchema):
    id: int
    platform_key: str
    display_name: str
    active: bool


class PaymentTemplateResponse(ApiSchema):
    id: int
    platform_id: int
    platform_key: str
    platform_display_name: str
    business_type: str
    version: int
    sheet_name_pattern: str | None
    header_signature: list[str]
    column_mapping: dict[str, Any]
    success_status_values: list[str]
    match_rules: list[dict[str, Any]]
    active: bool


class PaymentChannelBindingResponse(ApiSchema):
    id: int
    platform_id: int
    platform_key: str
    source_id: str
    business_type: str
    remote_channel_code: str
    remote_channel_label: str
    merchant_discriminator: str | None
    active: bool


class TemplateDetectionResponse(ApiSchema):
    status: str
    file_name: str
    source_sheet: str | None
    header_row: int | None
    detected_headers: list[str]
    header_coverage: float
    template: PaymentTemplateResponse | None
    message: str
