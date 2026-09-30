from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from packages.common.schemas import ApiSchema


class TotpAccountCreateRequest(ApiSchema):
    display_name: str = Field(min_length=1, max_length=120)
    account_name: str = Field(min_length=1, max_length=200)
    totp_secret: str = Field(min_length=1, max_length=2_000)
    enabled: bool = True


class TotpAccountPatchRequest(ApiSchema):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    account_name: str | None = Field(default=None, min_length=1, max_length=200)
    totp_secret: str | None = Field(default=None, min_length=1, max_length=2_000)
    enabled: bool | None = None


class TotpAccountResponse(ApiSchema):
    id: str
    display_name: str
    account_name: str
    display_order: int
    enabled: bool
    secret_updated_at: datetime
    created_at: datetime
    updated_at: datetime


class TotpCodeItemResponse(ApiSchema):
    account_id: str
    display_name: str
    account_name: str
    enabled: bool
    status: Literal["available", "disabled", "invalid"]
    code: str | None = Field(default=None, pattern=r"^\d{6}$")
    message: str | None = None


class TotpCodeListResponse(ApiSchema):
    generated_at: datetime
    expires_at: datetime
    period_seconds: int = Field(ge=1, le=300)
    items: list[TotpCodeItemResponse]
