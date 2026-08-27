from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from packages.common.schemas import ApiSchema

RemoteAccountCredentialMode = Literal["MANAGED", "LEGACY_SOURCE"]


class RemoteAccountCredentialsWrite(ApiSchema):
    password: str | None = Field(default=None, max_length=500)
    totp_secret: str | None = Field(default=None, max_length=500)


class RemoteAccountCreateRequest(ApiSchema):
    source_id: str = Field(min_length=2, max_length=64)
    login_username: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    credentials: RemoteAccountCredentialsWrite


class RemoteAccountPatchRequest(ApiSchema):
    login_username: str | None = Field(default=None, min_length=1, max_length=200)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    credentials: RemoteAccountCredentialsWrite | None = None

    @model_validator(mode="after")
    def require_change(self) -> RemoteAccountPatchRequest:
        if (
            self.login_username is None
            and self.display_name is None
            and self.enabled is None
            and self.credentials is None
        ):
            raise ValueError("至少需要提供一个待更新字段。")
        return self


class RemoteAccountCapabilityUpdateRequest(ApiSchema):
    capabilities: dict[str, bool] = Field(default_factory=dict, max_length=20)

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(cls, value: dict[str, bool]) -> dict[str, bool]:
        return {key.strip().upper(): bool(enabled) for key, enabled in value.items()}


class RemoteAccountResponse(ApiSchema):
    id: str
    source_id: str
    source_display_name: str
    source_base_url: str | None
    source_enabled: bool
    login_username: str | None
    display_name: str
    enabled: bool
    credential_mode: RemoteAccountCredentialMode
    credential_configured: bool
    credential_updated_at: datetime | None
    last_tested_at: datetime | None
    last_test_status: str | None
    capabilities: dict[str, bool]
    created_at: datetime
    updated_at: datetime


class ErpCompatibilityRemoteMarket(ApiSchema):
    id: int
    canonical_id: str
    code: str
    name: str
    base_url: str | None
    enabled: bool
    row_version: int
    created_at: datetime
    updated_at: datetime


class ErpCompatibilityRemoteConnection(ApiSchema):
    id: int
    canonical_id: str
    username: str | None
    market_id: int
    canonical_market_id: str
    market_code: str
    market_name: str
    market_enabled: bool
    base_url: str | None
    has_password: bool
    has_totp_secret: bool
    has_active_session: bool = False
    session_expires_at: datetime | None = None
    last_logged_in_at: datetime | None = None
    enabled: bool
    last_checked_at: datetime | None
    last_error: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime
    capabilities: dict[str, bool]
    tag_ids: list[int] = Field(default_factory=list)


class ErpCompatibilityRemoteRegistry(ApiSchema):
    """Secret-free SourceConfig + RemoteAccount view for the old ERP contract."""

    markets: list[ErpCompatibilityRemoteMarket]
    connections: list[ErpCompatibilityRemoteConnection]


class RemoteTag(ApiSchema):
    id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)


class RemoteTagSnapshotWrite(ApiSchema):
    tags: list[RemoteTag] = Field(max_length=2_000)
    source: Literal["MANUAL", "MIGRATED"] = "MANUAL"

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, value: list[RemoteTag]) -> list[RemoteTag]:
        if len({tag.id for tag in value}) != len(value):
            raise ValueError("标签 ID 不能重复。")
        return value


class RemoteTagSnapshotResponse(ApiSchema):
    exists: bool
    tags: list[RemoteTag]
    source: str | None
    stale: bool
    synced_at: datetime | None
    updated_at: datetime | None
    row_version: int | None


class RewardTierPresetTier(ApiSchema):
    label_ids: list[int] = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    min_deposit_amount: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    bonus_amount: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    bonus_max_amount: Decimal = Field(ge=0, max_digits=24, decimal_places=8)

    @field_validator("label_ids")
    @classmethod
    def unique_label_ids(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("同一档位的标签 ID 不能重复。")
        return value


class RewardTierPresetWrite(ApiSchema):
    tiers: list[RewardTierPresetTier] = Field(min_length=1, max_length=50)
    tag_snapshot: list[RemoteTag] = Field(min_length=1, max_length=2_000)


class RewardTierPresetResponse(ApiSchema):
    exists: bool
    stale: bool
    tiers: list[RewardTierPresetTier]
    tag_snapshot: list[RemoteTag]
    saved_at: datetime | None
    row_version: int | None
