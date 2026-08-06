from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from packages.common.schemas import ApiSchema


class DataDictionaryEntryResponse(ApiSchema):
    id: int
    source_id: str
    source_display_name: str
    dictionary_type: str
    entry_code: str
    entry_label: str
    active: bool
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime


class WithdrawStatusCreateRequest(ApiSchema):
    source_id: str = Field(min_length=2, max_length=64)
    entry_code: str = Field(min_length=1, max_length=80)
    entry_label: str = Field(min_length=1, max_length=255)
    active: bool = True

    @field_validator("source_id", "entry_code", "entry_label")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字典值不能为空。")
        return normalized


class WithdrawStatusPatchRequest(ApiSchema):
    entry_label: str | None = Field(default=None, min_length=1, max_length=255)
    active: bool | None = None

    @field_validator("entry_label")
    @classmethod
    def normalize_optional_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("展示文案不能为空。")
        return normalized


class ChargeStatusCreateRequest(WithdrawStatusCreateRequest):
    """Manually maintained recharge-order status mapping."""


class ChargeStatusPatchRequest(WithdrawStatusPatchRequest):
    """Editable fields for a recharge-order status mapping."""


class WithdrawStatusSyncRequest(ApiSchema):
    source_id: str = Field(min_length=2, max_length=64)

    @field_validator("source_id")
    @classmethod
    def normalize_source_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("盘口不能为空。")
        return normalized


class WithdrawStatusSyncResponse(ApiSchema):
    source_id: str
    source_display_name: str
    fetched_at: datetime
    remote_total: int
    created_entries: int
    refreshed_entries: int
    entries: list[DataDictionaryEntryResponse]


class UserSourceChannelSyncResponse(ApiSchema):
    """Result of replacing one source's channel_id dictionary from remote data."""

    source_id: str
    source_display_name: str
    fetched_at: datetime
    remote_total: int
    replaced_entries: int
    entries: list[DataDictionaryEntryResponse]
