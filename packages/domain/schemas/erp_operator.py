"""Request contracts for the ERP delivery-company and delivery-line module.

These contracts do not register an API or create database tables. They preserve
the source ERP's validation semantics while schema migration remains gated.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from packages.common.schemas import ApiSchema
from packages.domain.services.erp_operator_rules import (
    normalize_calculation_basis,
    normalize_delivery_line_asset,
    normalize_erp_operator_type,
    required_erp_operator_text,
    validate_calculation_scale,
    validate_rate,
)


class ErpOperatorCreateRequest(ApiSchema):
    name: str = Field(min_length=1, max_length=200)
    operator_type: Literal["COMPANY", "STUDIO", "INDIVIDUAL"] | None = None
    contact_name: str | None = Field(default=None, max_length=200)
    contact_value: str | None = Field(default=None, max_length=200)
    remark: str | None = Field(default=None, max_length=2_000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return required_erp_operator_text(value, field="投放公司名称")

    @field_validator("operator_type", mode="before")
    @classmethod
    def normalize_operator_type(cls, value: str | None) -> str:
        return normalize_erp_operator_type(value)


class ErpOperatorPatchRequest(ApiSchema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    operator_type: Literal["COMPANY", "STUDIO", "INDIVIDUAL"] | None = None
    contact_name: str | None = Field(default=None, max_length=200)
    contact_value: str | None = Field(default=None, max_length=200)
    remark: str | None = Field(default=None, max_length=2_000)
    row_version: int | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return required_erp_operator_text(value, field="投放公司名称") if value else value

    @field_validator("operator_type", mode="before")
    @classmethod
    def normalize_operator_type(cls, value: str | None) -> str | None:
        return normalize_erp_operator_type(value) if value is not None else None


class ErpOperatorResponse(ApiSchema):
    id: str
    code: str
    name: str
    operator_type: Literal["COMPANY", "STUDIO", "INDIVIDUAL"]
    status: Literal["ACTIVE", "INACTIVE"]
    contact_name: str | None
    contact_value: str | None
    remark: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class ErpOperatorDeleteImpactResponse(ApiSchema):
    operator_id: str
    operator_name: str
    delivery_line_count: int
    ledger_count: int
    locked_period_count: int
    has_history: bool
    can_delete_without_purge: bool


class ErpOperatorDeleteRequest(ApiSchema):
    row_version: int | None = Field(default=None, ge=0)
    purge_history: bool = False
    confirmation_name: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=500)


class ErpDeliveryLineCreateRequest(ApiSchema):
    name: str = Field(min_length=1, max_length=120)
    asset: Literal["USDT", "USDC"] = "USDT"
    network: str | None = Field(default=None, max_length=120)
    wallet_address: str | None = Field(default=None, max_length=500)
    start_date: date | None = None
    default_exchange_loss_rate: Decimal | None = Field(
        default=None,
        max_digits=12,
        decimal_places=8,
    )
    default_exchange_loss_basis: str | None = Field(default=None, max_length=40)
    default_service_fee_rate: Decimal | None = Field(
        default=None,
        max_digits=12,
        decimal_places=8,
    )
    default_service_fee_basis: str | None = Field(default=None, max_length=40)
    calculation_scale: int | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return required_erp_operator_text(value, field="投放线名称")

    @field_validator("asset", mode="before")
    @classmethod
    def normalize_asset(cls, value: str | None) -> str:
        return normalize_delivery_line_asset(value)

    @field_validator("default_exchange_loss_rate")
    @classmethod
    def validate_exchange_loss_rate(cls, value: Decimal | None) -> Decimal | None:
        return validate_rate(value, field="默认汇损率")

    @field_validator("default_service_fee_rate")
    @classmethod
    def validate_service_fee_rate(cls, value: Decimal | None) -> Decimal | None:
        return validate_rate(value, field="默认服务费率")

    @field_validator("default_exchange_loss_basis", "default_service_fee_basis")
    @classmethod
    def validate_basis(cls, value: str | None) -> str | None:
        return normalize_calculation_basis(value)

    @field_validator("calculation_scale")
    @classmethod
    def validate_scale(cls, value: int | None) -> int | None:
        return validate_calculation_scale(value)


class ErpDeliveryLinePatchRequest(ApiSchema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    network: str | None = Field(default=None, max_length=120)
    wallet_address: str | None = Field(default=None, max_length=500)
    start_date: date | None = None
    default_exchange_loss_rate: Decimal | None = Field(
        default=None,
        max_digits=12,
        decimal_places=8,
    )
    default_exchange_loss_basis: str | None = Field(default=None, max_length=40)
    default_service_fee_rate: Decimal | None = Field(
        default=None,
        max_digits=12,
        decimal_places=8,
    )
    default_service_fee_basis: str | None = Field(default=None, max_length=40)
    calculation_scale: int | None = None
    row_version: int | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return required_erp_operator_text(value, field="投放线名称") if value else value

    @field_validator("default_exchange_loss_rate")
    @classmethod
    def validate_exchange_loss_rate(cls, value: Decimal | None) -> Decimal | None:
        return validate_rate(value, field="默认汇损率")

    @field_validator("default_service_fee_rate")
    @classmethod
    def validate_service_fee_rate(cls, value: Decimal | None) -> Decimal | None:
        return validate_rate(value, field="默认服务费率")

    @field_validator("default_exchange_loss_basis", "default_service_fee_basis")
    @classmethod
    def validate_basis(cls, value: str | None) -> str | None:
        return normalize_calculation_basis(value)

    @field_validator("calculation_scale")
    @classmethod
    def validate_scale(cls, value: int | None) -> int | None:
        return validate_calculation_scale(value)


class ErpDeliveryLineResponse(ApiSchema):
    id: str
    operator_id: str
    operator_name: str
    display_name: str
    code: str
    name: str
    asset: Literal["USDT", "USDC"]
    network: str | None
    wallet_address: str | None
    start_date: date | None
    default_exchange_loss_rate: Decimal
    default_exchange_loss_basis: str
    default_service_fee_rate: Decimal
    default_service_fee_basis: str
    calculation_scale: int
    status: Literal["ACTIVE", "INACTIVE"]
    row_version: int
    created_at: datetime
    updated_at: datetime
