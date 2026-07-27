from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

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
