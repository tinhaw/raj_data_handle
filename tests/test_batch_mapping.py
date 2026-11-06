import pytest

from packages.domain.services.batch_service import (
    BatchValidationError,
    _validate_payment_column_mapping,
)


def _detection() -> dict[str, object]:
    return {
        "detectedHeaders": ["商户订单号", "平台订单号", "订单时间"],
        "template": {
            "columnMapping": {
                "merchant_order_no": "商户订单号",
                "platform_order_no": "平台订单号",
            }
        },
    }


def test_payment_mapping_only_requires_the_out_trade_no_column() -> None:
    _validate_payment_column_mapping(
        {"paymentColumnMapping": {"platform_order_no": "平台订单号"}},
        _detection(),
    )


def test_payment_mapping_rejects_a_platform_column_outside_parsed_headers() -> None:
    with pytest.raises(BatchValidationError, match="三方订单号映射"):
        _validate_payment_column_mapping(
            {"paymentColumnMapping": {"platform_order_no": "不存在的列"}},
            _detection(),
        )
