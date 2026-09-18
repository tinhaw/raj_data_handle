"""Database-free validation rules migrated from the ERP operator module."""

from __future__ import annotations

from decimal import Decimal

OPERATOR_TYPES = frozenset({"COMPANY", "STUDIO", "INDIVIDUAL"})
DELIVERY_LINE_ASSETS = frozenset({"USDT", "USDC"})
CALCULATION_BASES = frozenset({"TRANSFER", "EFFECTIVE_TRANSFER", "SPEND", "MANUAL"})


class ErpOperatorValidationError(ValueError):
    """Raised when ERP operator or delivery-line input is invalid."""


def required_erp_operator_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ErpOperatorValidationError(f"{field}不能为空。")
    return normalized


def normalize_erp_operator_type(value: str | None) -> str:
    if value is None or not value.strip():
        return "COMPANY"
    normalized = value.strip().upper()
    if normalized not in OPERATOR_TYPES:
        raise ErpOperatorValidationError("投放公司类型不合法。")
    return normalized


def normalize_delivery_line_asset(value: str | None) -> str:
    if value is None or not value.strip():
        return "USDT"
    normalized = value.strip().upper()
    if normalized not in DELIVERY_LINE_ASSETS:
        raise ErpOperatorValidationError("投放线币种仅支持 USDT 或 USDC。")
    return normalized


def normalize_calculation_basis(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized not in CALCULATION_BASES:
        raise ErpOperatorValidationError("不支持的计算基数。")
    return normalized


def validate_rate(value: Decimal | None, *, field: str) -> Decimal | None:
    if value is None:
        return None
    if value < 0 or value > 1:
        raise ErpOperatorValidationError(f"{field}必须在 0 到 1 之间；2% 请填写 0.02。")
    return value


def validate_calculation_scale(value: int | None) -> int | None:
    if value is None:
        return None
    if value < 0 or value > 8:
        raise ErpOperatorValidationError("计算精度必须在 0 到 8 之间。")
    return value
