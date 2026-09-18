from decimal import Decimal

import pytest
from pydantic import ValidationError

from packages.domain.schemas.erp_operator import (
    ErpDeliveryLineCreateRequest,
    ErpOperatorCreateRequest,
)


def test_operator_contract_normalizes_name_and_type() -> None:
    request = ErpOperatorCreateRequest(name="  Raj Media  ", operator_type="studio")

    assert request.name == "Raj Media"
    assert request.operator_type == "STUDIO"


def test_delivery_line_contract_has_legacy_compatible_defaults() -> None:
    request = ErpDeliveryLineCreateRequest(name="  Main line  ")

    assert request.name == "Main line"
    assert request.asset == "USDT"


@pytest.mark.parametrize("asset", ["BTC", "usdc-erc20"])
def test_delivery_line_contract_rejects_unknown_asset(asset: str) -> None:
    with pytest.raises(ValidationError, match="投放线币种"):
        ErpDeliveryLineCreateRequest(name="Main line", asset=asset)


@pytest.mark.parametrize("rate", [Decimal("-0.01"), Decimal("1.01")])
def test_delivery_line_contract_rejects_out_of_range_rate(rate: Decimal) -> None:
    with pytest.raises(ValidationError, match="默认汇损率"):
        ErpDeliveryLineCreateRequest(name="Main line", default_exchange_loss_rate=rate)


def test_operator_contract_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        ErpOperatorCreateRequest(name="   ")
