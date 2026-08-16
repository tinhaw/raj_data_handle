"""Contracts for ERP local daily ledger records."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from packages.common.schemas import ApiSchema
from packages.domain.services.erp_operator_rules import (
    normalize_calculation_basis,
    validate_calculation_scale,
    validate_rate,
)

CalculationBasis = Literal["TRANSFER", "EFFECTIVE_TRANSFER", "SPEND", "MANUAL"]
CalculationMode = Literal["AUTO", "MANUAL"]
FraudDeductionSource = Literal["TRANSFER", "BALANCE"]
DailyBalanceStatus = Literal["DRAFT", "CONFIRMED"]
DailyBalanceSourceType = Literal["MANUAL", "PASTE", "IMPORT"]


class ErpDailyBalanceWriteRequest(ApiSchema):
    operator_line_id: str = Field(min_length=1, max_length=36)
    business_date: date
    opening_balance: Decimal | None = Field(default=None, max_digits=24, decimal_places=8)
    opening_mode: Literal["AUTO", "MANUAL"] | None = None
    opening_override_reason: str | None = Field(default=None, max_length=500)
    transfer_amount: Decimal | None = Field(default=None, max_digits=24, decimal_places=8)
    fraud_loss_amount: Decimal | None = Field(default=None, max_digits=24, decimal_places=8)
    fraud_deduction_source: FraudDeductionSource | None = None
    spend_amount: Decimal | None = Field(default=None, max_digits=24, decimal_places=8)
    exchange_loss_rate: Decimal | None = Field(default=None, max_digits=12, decimal_places=8)
    exchange_loss_basis: CalculationBasis | None = None
    exchange_loss_mode: CalculationMode | None = None
    exchange_loss_amount: Decimal | None = Field(default=None, max_digits=24, decimal_places=8)
    exchange_loss_override_reason: str | None = Field(default=None, max_length=500)
    service_fee_rate: Decimal | None = Field(default=None, max_digits=12, decimal_places=8)
    service_fee_basis: CalculationBasis | None = None
    service_fee_mode: CalculationMode | None = None
    service_fee_amount: Decimal | None = Field(default=None, max_digits=24, decimal_places=8)
    service_fee_override_reason: str | None = Field(default=None, max_length=500)
    reflux_amount: Decimal | None = Field(default=None, max_digits=24, decimal_places=8)
    refund_amount: Decimal | None = Field(default=None, max_digits=24, decimal_places=8)
    other_deduction_amount: Decimal | None = Field(default=None, max_digits=24, decimal_places=8)
    other_reason: str | None = Field(default=None, max_length=500)
    calculation_scale: int | None = None
    source_type: DailyBalanceSourceType = "MANUAL"
    remark: str | None = Field(default=None, max_length=5_000)
    row_version: int | None = Field(default=None, ge=0)

    @field_validator("exchange_loss_rate")
    @classmethod
    def validate_exchange_rate(cls, value: Decimal | None) -> Decimal | None:
        return validate_rate(value, field="汇损费率")

    @field_validator("service_fee_rate")
    @classmethod
    def validate_service_rate(cls, value: Decimal | None) -> Decimal | None:
        return validate_rate(value, field="服务费率")

    @field_validator("exchange_loss_basis", "service_fee_basis", mode="before")
    @classmethod
    def normalize_basis(cls, value: str | None) -> str | None:
        return normalize_calculation_basis(value)

    @field_validator("calculation_scale")
    @classmethod
    def validate_scale(cls, value: int | None) -> int | None:
        return validate_calculation_scale(value)

    @model_validator(mode="after")
    def validate_other_reason(self) -> ErpDailyBalanceWriteRequest:
        if self.other_deduction_amount and self.other_deduction_amount > 0:
            if not self.other_reason or not self.other_reason.strip():
                raise ValueError("其他扣减金额不为 0 时必须填写原因。")
        return self


class ErpBalanceCalculationPreview(ApiSchema):
    suggested_opening_balance: Decimal | None
    opening_balance: Decimal
    effective_transfer_amount: Decimal
    exchange_loss_auto_amount: Decimal
    exchange_loss_amount: Decimal
    service_fee_auto_amount: Decimal
    service_fee_amount: Decimal
    fraud_from_transfer: Decimal
    fraud_from_balance: Decimal
    closing_balance: Decimal


class ErpDailyBalanceResponse(ErpBalanceCalculationPreview):
    id: str
    operator_line_id: str
    business_date: date
    opening_mode: Literal["AUTO", "MANUAL"]
    opening_override_reason: str | None
    transfer_amount: Decimal
    fraud_loss_amount: Decimal
    fraud_deduction_source: FraudDeductionSource | None
    spend_amount: Decimal
    exchange_loss_rate: Decimal
    exchange_loss_basis: CalculationBasis
    exchange_loss_mode: CalculationMode
    exchange_loss_override_reason: str | None
    service_fee_rate: Decimal
    service_fee_basis: CalculationBasis
    service_fee_mode: CalculationMode
    service_fee_override_reason: str | None
    reflux_amount: Decimal
    refund_amount: Decimal
    other_deduction_amount: Decimal
    other_reason: str | None
    calculation_scale: int
    status: DailyBalanceStatus
    source_type: DailyBalanceSourceType
    remark: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None


class ErpDailyBalanceListResponse(ApiSchema):
    operator_line_id: str
    month: str
    records: list[ErpDailyBalanceResponse]
