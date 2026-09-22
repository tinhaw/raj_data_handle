from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from packages.domain.services.payment_import_service import PaymentOrderGroup
from packages.domain.services.remote_charge_service import REMOTE_SUCCESS_STATUS


@dataclass(frozen=True, slots=True)
class ReconciliationDecision:
    result_status: str
    remote_order: dict[str, Any] | None


def _remote_decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _safe_remote_payload(order: dict[str, Any] | None) -> dict[str, Any] | None:
    if order is None:
        return None
    keys = (
        "order_num",
        "out_trade_no",
        "amount",
        "status",
        "create_time",
        "pay_time",
        "pay_method",
        "_remote_channel_code",
        "_remote_channel_label",
    )
    return {key: order.get(key) for key in keys}


def _evaluate_found_order(
    payment: PaymentOrderGroup,
    remote: dict[str, Any],
    *,
    after_recheck: bool,
) -> ReconciliationDecision:
    remote_payload = _safe_remote_payload(remote)
    if payment.amount is not None:
        remote_amount = _remote_decimal(remote.get("amount"))
        if remote_amount is None or remote_amount != payment.amount:
            return ReconciliationDecision("amount_mismatch", remote_payload)
    try:
        remote_status = int(remote.get("status"))
    except (TypeError, ValueError):
        remote_status = None
    if payment.payment_status_group == "success" and remote_status != REMOTE_SUCCESS_STATUS:
        return ReconciliationDecision("remote_status_not_success", remote_payload)
    return ReconciliationDecision(
        "matched_after_recheck" if after_recheck else "matched",
        remote_payload,
    )


def compare_with_remote_orders(
    payment: PaymentOrderGroup,
    remote_orders: list[dict[str, Any]],
    *,
    after_recheck: bool = False,
) -> ReconciliationDecision | None:
    if payment.preliminary_result_status:
        return ReconciliationDecision(payment.preliminary_result_status, None)
    if not payment.platform_order_no:
        return ReconciliationDecision("invalid_payment_row", None)

    matches = [
        order
        for order in remote_orders
        if str(order.get("out_trade_no") or "").strip() == payment.platform_order_no
    ]
    if len(matches) == 1:
        return _evaluate_found_order(payment, matches[0], after_recheck=after_recheck)
    if len(matches) > 1:
        return ReconciliationDecision("order_reference_conflict", None)
    return None
