"""Contracts for local ERP month-close locks."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from packages.common.schemas import ApiSchema

ErpPeriodLockStatus = Literal["LOCKED", "UNLOCKED"]


class ErpPeriodLockRequest(ApiSchema):
    month: date
    operator_ids: list[str] = Field(default_factory=list, max_length=2_000)
    operator_line_ids: list[str] = Field(default_factory=list, max_length=5_000)

    @field_validator("operator_ids", "operator_line_ids")
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("不能包含重复的投放公司或投放线。")
        return value

    @model_validator(mode="after")
    def require_target(self) -> ErpPeriodLockRequest:
        if not self.operator_ids and not self.operator_line_ids:
            raise ValueError("至少选择一个投放公司或投放线。")
        return self


class ErpPeriodUnlockRequest(ErpPeriodLockRequest):
    reason: str = Field(min_length=1, max_length=500)


class ErpPeriodLockIssue(ApiSchema):
    operator_line_id: str
    business_date: date | None
    code: str
    message: str


class ErpPeriodLockValidationResponse(ApiSchema):
    month: date
    can_lock: bool
    issues: list[ErpPeriodLockIssue]


class ErpPeriodLockResponse(ApiSchema):
    id: str
    operator_line_id: str
    month_start: date
    status: ErpPeriodLockStatus
    locked_by: int | None
    locked_at: datetime | None
    unlock_reason: str | None
    unlocked_by: int | None
    unlocked_at: datetime | None
    row_version: int
    created_at: datetime
    updated_at: datetime
