from decimal import Decimal

import pytest

from packages.domain.services.erp_balance_calculation import (
    ErpBalanceCalculationError,
    ErpBalanceFee,
    calculate_erp_daily_balance,
)


def _fee(rate: str, basis: str = "TRANSFER", mode: str = "AUTO") -> ErpBalanceFee:
    return ErpBalanceFee(
        rate=Decimal(rate),
        basis=basis,
        mode=mode,
        entered_amount=None,
    )


def test_daily_balance_calculation_matches_gross_transfer_rule() -> None:
    result = calculate_erp_daily_balance(
        opening_balance=Decimal("100"),
        transfer_amount=Decimal("1000"),
        fraud_loss_amount=Decimal("50"),
        fraud_deduction_source="TRANSFER",
        spend_amount=Decimal("500"),
        exchange_loss=_fee("0.02"),
        service_fee=_fee("0.02", basis="EFFECTIVE_TRANSFER"),
        reflux_amount=Decimal("0"),
        refund_amount=Decimal("0"),
        other_deduction_amount=Decimal("0"),
        calculation_scale=2,
    )

    assert result.effective_transfer_amount == Decimal("950.00000000")
    assert result.exchange_loss_amount == Decimal("20.00000000")
    assert result.service_fee_amount == Decimal("19.00000000")
    assert result.closing_balance == Decimal("511.00000000")


def test_manual_fee_requires_explicit_amount() -> None:
    with pytest.raises(ErpBalanceCalculationError, match="汇损手工录入"):
        calculate_erp_daily_balance(
            opening_balance=Decimal("0"),
            transfer_amount=Decimal("100"),
            fraud_loss_amount=Decimal("0"),
            fraud_deduction_source=None,
            spend_amount=Decimal("0"),
            exchange_loss=_fee("0", basis="MANUAL"),
            service_fee=_fee("0"),
            reflux_amount=Decimal("0"),
            refund_amount=Decimal("0"),
            other_deduction_amount=Decimal("0"),
            calculation_scale=2,
        )


def test_fraud_deducted_from_transfer_cannot_exceed_transfer() -> None:
    with pytest.raises(ErpBalanceCalculationError, match="不能大于转 U"):
        calculate_erp_daily_balance(
            opening_balance=Decimal("0"),
            transfer_amount=Decimal("10"),
            fraud_loss_amount=Decimal("11"),
            fraud_deduction_source="TRANSFER",
            spend_amount=Decimal("0"),
            exchange_loss=_fee("0"),
            service_fee=_fee("0"),
            reflux_amount=Decimal("0"),
            refund_amount=Decimal("0"),
            other_deduction_amount=Decimal("0"),
            calculation_scale=2,
        )
