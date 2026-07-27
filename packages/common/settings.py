from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    session_ttl_minutes: int = Field(default=480, ge=15, le=10_080)
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

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
