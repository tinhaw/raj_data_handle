from __future__ import annotations

from datetime import datetime

from pydantic import Field, HttpUrl, field_validator

from packages.common.schemas import ApiSchema


class SourceCredentialsWrite(ApiSchema):
    username: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=500)
    totp_secret: str | None = Field(default=None, max_length=500)


class ScoringApiWrite(ApiSchema):
    """Write-only source-scoped configuration for the scoring-review API."""

    base_url: HttpUrl | None = None
    api_key: str | None = Field(default=None, max_length=1_000)


class SourceUpsertRequest(ApiSchema):
    display_name: str = Field(min_length=1, max_length=120)
    base_url: HttpUrl | None = None
    enabled: bool = False
    business_timezone: str = "Asia/Kolkata"
    currency: str = "INR"
    credentials: SourceCredentialsWrite | None = None
    scoring_api: ScoringApiWrite | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("币种必须是 ISO 4217 三字母代码")
        return normalized


class SourceCreateRequest(SourceUpsertRequest):
    source_id: str = Field(min_length=2, max_length=64)


class SourcePatchRequest(ApiSchema):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: HttpUrl | None = None
    enabled: bool | None = None
    business_timezone: str | None = None
    currency: str | None = None
    credentials: SourceCredentialsWrite | None = None
    scoring_api: ScoringApiWrite | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("币种必须是 ISO 4217 三字母代码")
        return normalized


class SourceOrderRequest(ApiSchema):
    source_ids: list[str] = Field(min_length=1, max_length=200)


class SourceResponse(ApiSchema):
    source_id: str
    display_name: str
    display_order: int
    base_url: str | None
    enabled: bool
    business_timezone: str
    currency: str
    config_version: int
    credential_configured: bool
    login_username: str | None
    credential_updated_at: datetime | None
    scoring_api_base_url: str | None
    scoring_api_key_configured: bool
    scoring_api_key_updated_at: datetime | None
    scoring_api_last_tested_at: datetime | None
    scoring_api_last_test_status: str | None
    last_tested_at: datetime | None
    last_test_status: str | None
    created_at: datetime
    updated_at: datetime


class SourceConnectionTestResponse(ApiSchema):
    source_id: str
    status: str
    request_id: str
    message: str
