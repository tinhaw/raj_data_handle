from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CHARGE_ORDER_REFRESH_PAGE_SIZES = frozenset({10, 20, 30, 50, 100})
# Deprecated compatibility values for existing environment files and staged
# rollouts.  Withdrawal refreshes no longer read them; their real policy is
# the daily Excel-export date mode below.
WITHDRAW_ORDER_REFRESH_PAGE_SIZES = CHARGE_ORDER_REFRESH_PAGE_SIZES


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RAJ_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = "development"
    api_title: str = "Raj Data Handle API"
    api_version: str = "0.1.0"
    api_prefix: str = "/api/v1"

    database_url: str = (
        "postgresql+asyncpg://raj_data_handle:raj_data_handle@localhost:5432/raj_data_handle"
    )
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "development-only-change-me-please-32chars"
    credential_encryption_key: str | None = None

    # The database-backed system setting takes precedence once its migration has
    # been applied.  This value is the safe fallback during bootstrap and while
    # rolling out the application before the corresponding schema migration.
    session_ttl_days: int = Field(default=30, ge=1, le=365)
    session_cookie_name: str = "raj_session"
    session_cookie_secure: bool = False
    session_cookie_samesite: str = "lax"

    cors_origins: list[str] = ["http://localhost:5173"]
    storage_root: Path = Path("runtime/uploads")
    upload_max_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)

    login_rate_limit_enabled: bool = True
    login_rate_limit_window_seconds: int = 60
    login_rate_limit_max_attempts: int = 8

    default_business_timezone: str = "Asia/Kolkata"
    default_currency: str = "INR"
    uploaded_file_retention_days: int = 3
    result_retention_days: int = 30
    remote_cache_retention_days: int = 30
    withdraw_order_refresh_interval_hours: int = Field(default=1, ge=1, le=24)
    withdraw_order_refresh_page_size: int = Field(default=100)
    withdraw_order_query_range: Literal[
        "today",
        "last_1_hour",
        "last_2_hours",
        "last_3_hours",
        "last_6_hours",
        "last_12_hours",
        "last_24_hours",
        "last_48_hours",
    ] = "today"
    # The persisted system setting takes precedence once its migration has
    # been applied. This fallback is used only when the singleton setting row
    # is first initialized.
    withdraw_order_export_date_mode: Literal["previous_day", "specific_date"] = "previous_day"
    withdraw_order_export_specific_date: date | None = None
    charge_order_refresh_interval_hours: int = Field(default=1, ge=1, le=24)
    charge_order_refresh_page_size: int = Field(default=100)
    charge_order_query_range: Literal[
        "today",
        "last_1_hour",
        "last_2_hours",
        "last_3_hours",
        "last_6_hours",
        "last_12_hours",
        "last_24_hours",
        "last_48_hours",
    ] = "today"

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("RAJ_SECRET_KEY must contain at least 32 characters")
        return value

    @field_validator("session_cookie_samesite")
    @classmethod
    def validate_samesite(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("session_cookie_samesite must be lax, strict, or none")
        return normalized

    @field_validator("charge_order_refresh_page_size")
    @classmethod
    def validate_charge_order_refresh_page_size(cls, value: int) -> int:
        if value not in CHARGE_ORDER_REFRESH_PAGE_SIZES:
            raise ValueError("charge_order_refresh_page_size must be 10, 20, 30, 50, or 100")
        return value

    @field_validator("withdraw_order_refresh_page_size")
    @classmethod
    def validate_withdraw_order_refresh_page_size(cls, value: int) -> int:
        if value not in WITHDRAW_ORDER_REFRESH_PAGE_SIZES:
            raise ValueError("withdraw_order_refresh_page_size must be 10, 20, 30, 50, or 100")
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
