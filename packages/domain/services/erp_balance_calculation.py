"""Server-authoritative ERP daily-balance calculation.

Migrated from the ERP ``BALANCE_V1_GROSS_TRANSFER`` rule.  It is pure code so
the arithmetic can be verified before the daily-balance tables are initialized.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CALCULATION_BASES = frozenset({"TRANSFER", "EFFECTIVE_TRANSFER", "SPEND", "MANUAL"})
FEE_MODES = frozenset({"AUTO", "MANUAL"})
FRAUD_SOURCES = frozenset({"TRANSFER", "BALANCE"})
AMOUNT_QUANTUM = Decimal("0.00000001")


class ErpBalanceCalculationError(ValueError):
    """Raised when a daily-balance input violates the calculation rules."""


@dataclass(frozen=True, slots=True)
class ErpBalanceFee:
    rate: Decimal | None
    basis: str | None
    mode: str | None
    entered_amount: Decimal | None


@dataclass(frozen=True, slots=True)
class ErpBalanceCalculationResult:
    effective_transfer_amount: Decimal
    exchange_loss_auto_amount: Decimal
    exchange_loss_amount: Decimal
    service_fee_auto_amount: Decimal
    service_fee_amount: Decimal
    fraud_from_transfer: Decimal
    fraud_from_balance: Decimal
    closing_balance: Decimal


def _zero(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("0")


def _amount(value: Decimal | None) -> Decimal:
    return _zero(value).quantize(AMOUNT_QUANTUM, rounding=ROUND_HALF_UP)


def _non_negative(value: Decimal | None, *, label: str) -> Decimal:
    normalized = _zero(value)
    if normalized < 0:
        raise ErpBalanceCalculationError(f"{label}不能小于 0。")
    return normalized


def _normalized_basis(value: str | None) -> str:
    normalized = (value or "TRANSFER").strip().upper()
    if normalized not in CALCULATION_BASES:
        raise ErpBalanceCalculationError("不支持的计算基数。")
    return normalized


def _normalized_mode(value: str | None) -> str:
    normalized = (value or "AUTO").strip().upper()
    if normalized not in FEE_MODES:
        raise ErpBalanceCalculationError("计算模式必须为 AUTO 或 MANUAL。")
    return normalized


def _calculate_fee_auto(
    fee: ErpBalanceFee,
    *,
    transfer_amount: Decimal,
    effective_transfer_amount: Decimal,
    spend_amount: Decimal,
    calculation_scale: int,
    label: str,
) -> tuple[Decimal, str, str]:
    rate = _non_negative(fee.rate, label=f"{label}费率")
    if rate > 1:
        raise ErpBalanceCalculationError(f"{label}费率不得大于 1；2% 请填写 0.02。")
    basis = _normalized_basis(fee.basis)
    mode = _normalized_mode(fee.mode)
    if basis == "MANUAL":
        return Decimal("0"), basis, mode
    base = {
        "TRANSFER": transfer_amount,
        "EFFECTIVE_TRANSFER": effective_transfer_amount,
        "SPEND": spend_amount,
    }[basis]
    return (base * rate).quantize(
        Decimal(1).scaleb(-calculation_scale),
        rounding=ROUND_HALF_UP,
    ), basis, mode


def _actual_fee(
    fee: ErpBalanceFee,
    *,
    auto_amount: Decimal,
    basis: str,
    mode: str,
    label: str,
) -> Decimal:
    if mode == "MANUAL" or basis == "MANUAL":
        if fee.entered_amount is None:
            raise ErpBalanceCalculationError(f"{label}手工录入时必须填写金额。")
        return _non_negative(fee.entered_amount, label=f"{label}金额")
    return auto_amount


def calculate_erp_daily_balance(
    *,
    opening_balance: Decimal | None,
    transfer_amount: Decimal | None,
    fraud_loss_amount: Decimal | None,
    fraud_deduction_source: str | None,
    spend_amount: Decimal | None,
    exchange_loss: ErpBalanceFee,
    service_fee: ErpBalanceFee,
    reflux_amount: Decimal | None,
    refund_amount: Decimal | None,
    other_deduction_amount: Decimal | None,
    calculation_scale: int,
) -> ErpBalanceCalculationResult:
    """Calculate daily-balance derived values without reading or writing data."""

    if calculation_scale < 0 or calculation_scale > 8:
        raise ErpBalanceCalculationError("计算精度必须在 0 到 8 之间。")
    opening = _zero(opening_balance)
    transfer = _non_negative(transfer_amount, label="转 U")
    fraud = _non_negative(fraud_loss_amount, label="欺诈损失")
    spend = _non_negative(spend_amount, label="消耗")
    reflux = _non_negative(reflux_amount, label="回流")
    refund = _non_negative(refund_amount, label="退款")
    other = _non_negative(other_deduction_amount, label="其他扣减")

    source = fraud_deduction_source.strip().upper() if fraud_deduction_source else None
    if fraud > 0 and source is None:
        raise ErpBalanceCalculationError("欺诈损失不为 0 时必须选择承担方式。")
    if source is not None and source not in FRAUD_SOURCES:
        raise ErpBalanceCalculationError("欺诈承担方式必须为 TRANSFER 或 BALANCE。")
    if source == "TRANSFER" and fraud > transfer:
        raise ErpBalanceCalculationError("从转账扣除的欺诈损失不能大于转 U。")

    fraud_from_transfer = fraud if source == "TRANSFER" else Decimal("0")
    fraud_from_balance = fraud if source == "BALANCE" else Decimal("0")
    effective_transfer = transfer - fraud_from_transfer

    exchange_auto, exchange_basis, exchange_mode = _calculate_fee_auto(
        exchange_loss,
        transfer_amount=transfer,
        effective_transfer_amount=effective_transfer,
        spend_amount=spend,
        calculation_scale=calculation_scale,
        label="汇损",
    )
    exchange_amount = _actual_fee(
        exchange_loss,
        auto_amount=exchange_auto,
        basis=exchange_basis,
        mode=exchange_mode,
        label="汇损",
    )
    service_auto, service_basis, service_mode = _calculate_fee_auto(
        service_fee,
        transfer_amount=transfer,
        effective_transfer_amount=effective_transfer,
        spend_amount=spend,
        calculation_scale=calculation_scale,
        label="服务费",
    )
    service_amount = _actual_fee(
        service_fee,
        auto_amount=service_auto,
        basis=service_basis,
        mode=service_mode,
        label="服务费",
    )
    closing = (
        opening
        + effective_transfer
        - spend
        - exchange_amount
        - service_amount
        - reflux
        - refund
        - other
        - fraud_from_balance
    )
    return ErpBalanceCalculationResult(
        effective_transfer_amount=_amount(effective_transfer),
        exchange_loss_auto_amount=_amount(exchange_auto),
        exchange_loss_amount=_amount(exchange_amount),
        service_fee_auto_amount=_amount(service_auto),
        service_fee_amount=_amount(service_amount),
        fraud_from_transfer=_amount(fraud_from_transfer),
        fraud_from_balance=_amount(fraud_from_balance),
        closing_balance=_amount(closing),
    )
