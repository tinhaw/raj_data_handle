"""Read-only contracts for the local ERP workbench."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field

from packages.common.schemas import ApiSchema


class ErpDashboardMetric(ApiSchema):
    opening_balance: Decimal
    transfer_amount: Decimal
    spend_amount: Decimal
    closing_balance: Decimal
    active_operator_count: int
    active_line_count: int


class ErpDashboardTrendPoint(ApiSchema):
    business_date: date
    closing_balance: Decimal


class ErpDashboardHealthItem(ApiSchema):
    code: str
    severity: Literal["INFO", "WARNING", "DANGER"]
    title: str
    description: str
    target_path: str
    count: int = Field(ge=0)


class ErpDashboardRecentBalance(ApiSchema):
    id: str
    business_date: date
    operator_name: str
    operator_line_name: str
    asset: str
    opening_balance: Decimal
    transfer_amount: Decimal
    spend_amount: Decimal
    closing_balance: Decimal
    status: Literal["DRAFT", "CONFIRMED"]


class ErpDashboardResponse(ApiSchema):
    business_date: date
    metric: ErpDashboardMetric
    trend: list[ErpDashboardTrendPoint]
    health_items: list[ErpDashboardHealthItem]
    recent_balances: list[ErpDashboardRecentBalance]
