from __future__ import annotations

from datetime import date, datetime, timedelta
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
    is_default: bool | None = None
    credentials: RemoteAccountCredentialsWrite


class RemoteAccountPatchRequest(ApiSchema):
    login_username: str | None = Field(default=None, min_length=1, max_length=200)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    is_default: bool | None = None
    credentials: RemoteAccountCredentialsWrite | None = None

    @model_validator(mode="after")
    def require_change(self) -> RemoteAccountPatchRequest:
        if (
            self.login_username is None
            and self.display_name is None
            and self.enabled is None
            and self.is_default is None
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
    is_default: bool
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
    is_default: bool
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


class ErpCompatibilityRemoteCreateOptions(ApiSchema):
    """Non-secret configuration forwarded by the Java compatibility facade."""

    publish_environment: Literal["test", "prod"] = "test"
    flow_times: int = Field(ge=0, le=1000)
    activity_recharge: Decimal | None = Field(default=None, ge=0, max_digits=24, decimal_places=8)
    activity_recharge_count: int | None = Field(default=None, ge=0, le=100_000)
    activity_id: int | None = Field(default=None, ge=1)
    key_number: int = Field(default=1, ge=1, le=1000)
    single_user_limit: int = Field(ge=1, le=100)
    single_key_limit: int = Field(ge=1, le=100_000)
    require_bind_bank_card: bool
    require_bind_phone: bool
    check_uuid: bool
    uuid_reward_limit: int = Field(ge=1, le=100)
    check_login_ip: bool
    login_ip_reward_limit: int = Field(ge=1, le=100)
    check_register_ip: bool
    register_ip_reward_limit: int = Field(ge=1, le=100)


class ErpCompatibilityRemoteCreateRequest(ApiSchema):
    """Explicit remote-create request from the preserved ERP UI.

    The numeric account ID is a compatibility projection only.  The API
    resolves the canonical account and decrypts credentials locally; this
    request never carries a password, TOTP secret or remote access token.
    """

    account_id: int = Field(ge=1)
    issue_id: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=500)
    claim_date: date
    valid_from: date | None = None
    valid_to: date | None = None
    label_ids: list[int] = Field(default_factory=list, max_length=100)
    bonus_amount: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    bonus_max_amount: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    options: ErpCompatibilityRemoteCreateOptions
    execution_confirmed: bool = False

    @field_validator("label_ids")
    @classmethod
    def unique_positive_label_ids(cls, value: list[int]) -> list[int]:
        if any(item < 1 for item in value):
            raise ValueError("标签 ID 必须是正整数。")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_remote_confirmation(self) -> ErpCompatibilityRemoteCreateRequest:
        if self.bonus_max_amount < self.bonus_amount:
            raise ValueError("兑换金额上限不能小于下限。")
        valid_from = self.valid_from or self.claim_date
        valid_to = self.valid_to or self.claim_date
        if (
            valid_from < self.claim_date
            or valid_to < valid_from
            or valid_to > self.claim_date + timedelta(days=365)
        ):
            raise ValueError(
                "兑换码生效日期不能早于开始兑换日，结束日不能早于开始日，且最多延后 365 天。"
            )
        if not self.execution_confirmed:
            raise ValueError("必须明确确认本次远端兑换码创建。")
        return self


class ErpCompatibilityRemoteCreateResponse(ApiSchema):
    remote_configuration_id: str
    remote_group_key: str | None = None
    remote_request_id: str | None = None


class ErpCompatibilityRemoteDownloadRequest(ApiSchema):
    account_id: int = Field(ge=1)
    issue_id: int = Field(ge=1)
    remote_configuration_id: str = Field(min_length=1, max_length=255)
    remote_group_key: str | None = Field(default=None, max_length=255)
    key_number: int = Field(default=1, ge=1, le=1000)
    execution_confirmed: bool = False


class ErpCompatibilityRemoteDownloadResponse(ApiSchema):
    redemption_codes: list[str]
    remote_group_key: str | None = None


class ErpCompatibilityRemotePublishRequest(ApiSchema):
    """Confirmed publish request from the preserved ERP workflow."""

    account_id: int = Field(ge=1)
    batch_id: int = Field(ge=1)
    publish_environment: Literal["test", "prod"] = "test"
    mode: Literal["IMMEDIATE", "SCHEDULED"]
    scheduled_time: datetime | None = None
    fallback_to_scheduled: bool = True
    execution_confirmed: bool = False

    @model_validator(mode="after")
    def validate_remote_confirmation(self) -> ErpCompatibilityRemotePublishRequest:
        if self.mode == "SCHEDULED" and self.scheduled_time is None:
            raise ValueError("定时发布必须提供发布时间。")
        if not self.execution_confirmed:
            raise ValueError("必须明确确认本次远端兑换码发布。")
        return self


class ErpCompatibilityRemotePublishResponse(ApiSchema):
    remote_publish_task_id: str
    remote_request_id: str | None = None


class RemoteTag(ApiSchema):
    id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)


class RemoteTagSnapshotWrite(ApiSchema):
    tags: list[RemoteTag] = Field(max_length=2_000)
    source: Literal["MANUAL", "MIGRATED", "REMOTE"] = "MANUAL"

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, value: list[RemoteTag]) -> list[RemoteTag]:
        if len({tag.id for tag in value}) != len(value):
            raise ValueError("标签 ID 不能重复。")
        return value


class RemoteTagSyncRequest(ApiSchema):
    """Explicit operator confirmation for a live remote tag refresh."""

    execution_confirmed: bool = False


class RemoteTagSnapshotResponse(ApiSchema):
    exists: bool
    tags: list[RemoteTag]
    source: str | None
    stale: bool
    synced_at: datetime | None
    updated_at: datetime | None
    row_version: int | None


class RewardTierPresetTier(ApiSchema):
    user_type: Literal["ALL_USERS", "LABEL_USERS"] = "LABEL_USERS"
    label_ids: list[int] = Field(default_factory=list, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    min_deposit_amount: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    bonus_amount: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    bonus_max_amount: Decimal = Field(ge=0, max_digits=24, decimal_places=8)

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_user_type(cls, value: object) -> object:
        if isinstance(value, dict) and not value.get("user_type") and not value.get("userType"):
            normalized = dict(value)
            has_labels = normalized.get("label_ids") or normalized.get("labelIds")
            normalized["user_type"] = "LABEL_USERS" if has_labels else "ALL_USERS"
            return normalized
        return value

    @field_validator("label_ids")
    @classmethod
    def unique_label_ids(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("同一档位的标签 ID 不能重复。")
        return value

    @model_validator(mode="after")
    def validate_user_type(self) -> RewardTierPresetTier:
        if self.user_type == "ALL_USERS" and self.label_ids:
            raise ValueError("全部用户档位不能配置标签 ID。")
        if self.user_type == "LABEL_USERS" and not self.label_ids:
            raise ValueError("标签用户档位必须选择至少一个标签 ID。")
        return self


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
