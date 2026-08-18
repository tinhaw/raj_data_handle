"""Contracts for local-only ERP redemption campaign management."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from packages.common.schemas import ApiSchema


class ErpRedemptionTierWrite(ApiSchema):
    display_name: str | None = Field(default=None, max_length=120)
    min_deposit_amount: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    bonus_amount: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    bonus_max_amount: Decimal | None = Field(default=None, ge=0, max_digits=24, decimal_places=8)
    sort_order: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_bonus_range(self) -> ErpRedemptionTierWrite:
        maximum = self.bonus_max_amount if self.bonus_max_amount is not None else self.bonus_amount
        if maximum < self.bonus_amount:
            raise ValueError("最大奖金金额不能小于赠金金额。")
        return self


class ErpRedemptionCampaignCreateRequest(ApiSchema):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    lookback_days: int = Field(default=7, ge=1, le=60)
    description: str | None = Field(default=None, max_length=10_000)
    tiers: list[ErpRedemptionTierWrite] = Field(min_length=1, max_length=20)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("活动编码不能为空。")
        return normalized

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("活动名称不能为空。")
        return normalized


class ErpRedemptionTierResponse(ApiSchema):
    id: str
    display_name: str | None
    min_deposit_amount: Decimal
    bonus_amount: Decimal
    bonus_max_amount: Decimal
    sort_order: int
    row_version: int


class ErpRedemptionCampaignResponse(ApiSchema):
    id: str
    code: str
    name: str
    status: Literal["DRAFT", "ACTIVE", "ARCHIVED"]
    lookback_days: int
    description: str | None
    tiers: list[ErpRedemptionTierResponse]
    planned_code_count: int
    imported_code_count: int
    row_version: int
    created_at: datetime
    updated_at: datetime


class ErpRedemptionBatchCreateRequest(ApiSchema):
    campaign_id: str = Field(min_length=1, max_length=36)
    claim_date_from: date
    claim_date_to: date

    @model_validator(mode="after")
    def validate_date_range(self) -> ErpRedemptionBatchCreateRequest:
        if self.claim_date_to < self.claim_date_from:
            raise ValueError("领取日期结束不能早于开始日期。")
        if (self.claim_date_to - self.claim_date_from).days > 365:
            raise ValueError("单个兑换码批次最长为 366 天。")
        return self


class ErpRedemptionTaskCreateRequest(ErpRedemptionBatchCreateRequest):
    task_name: str | None = Field(default=None, max_length=200)
    remote_account_ids: list[str] = Field(min_length=1, max_length=50)

    @field_validator("remote_account_ids")
    @classmethod
    def unique_remote_accounts(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("同一任务组不能重复选择远端账号。")
        return value


class ErpRedemptionBatchResponse(ApiSchema):
    id: str
    campaign_id: str
    task_id: str | None
    source_id: str | None
    remote_account_id: str | None
    execution_order: int
    claim_date_from: date
    claim_date_to: date
    lookback_days: int
    expected_code_count: int
    imported_code_count: int
    status: Literal["PLANNED", "READY_LOCAL", "PUBLISHED_LOCAL"]
    published_at: datetime | None
    row_version: int
    created_at: datetime


class ErpRedemptionTaskSubtask(ApiSchema):
    batch_id: str
    execution_order: int
    source_id: str
    source_display_name: str
    remote_account_id: str
    remote_account_name: str
    expected_code_count: int
    imported_code_count: int
    status: Literal["PLANNED", "READY_LOCAL", "PUBLISHED_LOCAL"]


class ErpRedemptionTaskResponse(ApiSchema):
    id: str
    campaign_id: str
    task_name: str
    claim_date_from: date
    claim_date_to: date
    lookback_days: int
    export_group_key: str
    status: Literal["PLANNED", "READY_LOCAL", "PUBLISHED_LOCAL"]
    expected_code_count: int
    imported_code_count: int
    row_version: int
    created_at: datetime
    subtasks: list[ErpRedemptionTaskSubtask]


class ErpRedemptionIssueResponse(ApiSchema):
    id: str
    campaign_id: str
    campaign_tier_id: str
    batch_id: str
    claim_date: date
    deposit_window_start: date
    deposit_window_end: date
    tier_name: str | None
    min_deposit_amount: Decimal
    bonus_amount: Decimal
    bonus_max_amount: Decimal
    redemption_code: str | None
    local_reference: str | None
    workflow_status: Literal["PENDING_LOCAL_CODE", "CODE_IMPORTED", "PUBLISHED_LOCAL"]
    state: Literal["PENDING", "GENERATED"]
    imported_at: datetime | None
    remote_workflow_status: Literal[
        "NOT_STARTED",
        "RESERVED",
        "CREATING",
        "CREATED",
        "PUBLISHED",
        "DOWNLOADING",
        "DOWNLOADED",
        "FAILED",
    ]
    remote_configuration_id: str | None
    remote_group_key: str | None
    remote_label_ids: list[int]
    remote_description: str | None
    remote_error_code: str | None
    remote_error_message: str | None
    remote_created_at: datetime | None
    remote_downloaded_at: datetime | None
    row_version: int


class ErpRedemptionBatchDetailResponse(ApiSchema):
    batch: ErpRedemptionBatchResponse
    issues: list[ErpRedemptionIssueResponse]


class ErpRedemptionCodeInput(ApiSchema):
    issue_id: str = Field(min_length=1, max_length=36)
    redemption_code: str = Field(min_length=1, max_length=255)
    local_reference: str | None = Field(default=None, max_length=255)
    row_version: int | None = Field(default=None, ge=0)

    @field_validator("redemption_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("兑换码不能为空。")
        return normalized


class ErpRedemptionCodeImportRequest(ApiSchema):
    rows: list[ErpRedemptionCodeInput] = Field(min_length=1, max_length=10_000)


class ErpRedemptionLocalPublishRequest(ApiSchema):
    row_version: int | None = Field(default=None, ge=0)
