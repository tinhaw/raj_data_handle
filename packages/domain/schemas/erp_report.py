"""Read-only ERP daily and monthly ledger report contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from packages.common.schemas import ApiSchema

ErpReportType = Literal["DAILY", "MONTHLY"]


class ErpReportRow(ApiSchema):
    period: str
    asset: str
    opening_balance: Decimal
    transfer_amount: Decimal
    fraud_from_transfer: Decimal
    effective_transfer_amount: Decimal
    spend_amount: Decimal
    exchange_loss_amount: Decimal
    service_fee_amount: Decimal
    reflux_amount: Decimal
    refund_amount: Decimal
    other_deduction_amount: Decimal
    fraud_from_balance: Decimal
    closing_balance: Decimal
    record_count: int
    warnings: list[str]


class ErpReportResponse(ApiSchema):
    report_type: ErpReportType
    nominal_u: bool
    rows: list[ErpReportRow]
