from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from packages.common.schemas import ApiSchema


class CaptchaResponse(ApiSchema):
    captcha_id: str
    image: str
    expires_at: datetime


class LoginRequest(ApiSchema):
    username: str
    password: str
    captcha_id: str
    captcha_code: str

    @field_validator("username", "password", "captcha_id", "captcha_code")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("不能为空")
        return value


class AuthUserResponse(ApiSchema):
    id: int
    username: str
    display_name: str
    role: str
    expires_at: datetime | None = None


class LogoutResponse(ApiSchema):
    success: bool = True


class UserResponse(ApiSchema):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserCreateRequest(ApiSchema):
    username: str = Field(min_length=1, max_length=80)
    password: str
    display_name: str = Field(min_length=1, max_length=120)
    role: str = "user"


class UserUpdateRequest(ApiSchema):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


UserLogEventType = Literal["login", "access"]


class UserAccessLogRequest(ApiSchema):
    """A browser route visited by the currently authenticated user."""

    path: str = Field(min_length=1, max_length=500, pattern=r"^/")


class UserLogQueryRequest(ApiSchema):
    user_id: int | None = Field(default=None, ge=1)
    event_types: list[UserLogEventType] | None = Field(default=None, max_length=2)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=10, le=100)

    @field_validator("event_types")
    @classmethod
    def normalize_event_types(
        cls, value: list[UserLogEventType] | None
    ) -> list[UserLogEventType] | None:
        if not value:
            return None
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_time_range(self) -> UserLogQueryRequest:
        if self.started_at and self.ended_at and self.started_at > self.ended_at:
            raise ValueError("访问时间范围的开始时间不能晚于结束时间。")
        return self


class UserLogResponse(ApiSchema):
    id: str
    user_id: int
    username: str | None
    display_name: str | None
    event_type: UserLogEventType
    path: str | None
    occurred_at: datetime


class UserLogQueryResponse(ApiSchema):
    items: list[UserLogResponse]
    total: int
    page: int
    page_size: int
