"""Read-only aggregations over local ERP daily-ledger rows."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import ErpDailyBalance, ErpOperatorLine
from packages.domain.schemas.erp_report import ErpReportResponse, ErpReportRow

ZERO = Decimal("0")


class ErpReportError(ValueError):
    pass


@dataclass
class _Totals:
    opening_balance: Decimal = ZERO
    transfer_amount: Decimal = ZERO
    fraud_from_transfer: Decimal = ZERO
    effective_transfer_amount: Decimal = ZERO
    spend_amount: Decimal = ZERO
    exchange_loss_amount: Decimal = ZERO
    service_fee_amount: Decimal = ZERO
    reflux_amount: Decimal = ZERO
    refund_amount: Decimal = ZERO
    other_deduction_amount: Decimal = ZERO
    fraud_from_balance: Decimal = ZERO
    closing_balance: Decimal = ZERO
    record_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def add_flow(self, row: ErpDailyBalance) -> None:
        self.transfer_amount += row.transfer_amount
        self.effective_transfer_amount += row.effective_transfer_amount
        self.spend_amount += row.spend_amount
        self.exchange_loss_amount += row.exchange_loss_amount
        self.service_fee_amount += row.service_fee_amount
        self.reflux_amount += row.reflux_amount
        self.refund_amount += row.refund_amount
        self.other_deduction_amount += row.other_deduction_amount
        if row.fraud_deduction_source == "TRANSFER":
            self.fraud_from_transfer += row.fraud_loss_amount
        if row.fraud_deduction_source == "BALANCE":
            self.fraud_from_balance += row.fraud_loss_amount
        self.record_count += 1

    def as_row(self, *, period: str, asset: str) -> ErpReportRow:
        return ErpReportRow(period=period, asset=asset, **self.__dict__)


def _periods_by_day(start: date, end: date) -> list[date]:
    periods: list[date] = []
    current = start
    while current <= end:
        periods.append(current)
        current += timedelta(days=1)
    return periods


def _month_start(value: str) -> date:
    try:
        year, month = (int(part) for part in value.split("-", maxsplit=1))
        return date(year, month, 1)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ErpReportError("月份必须为 YYYY-MM。") from exc


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _periods_by_month(start: date, end: date) -> list[date]:
    periods: list[date] = []
    current = start
    while current <= end:
        periods.append(current)
        current = _next_month(current)
    return periods


def _last_before(records: list[ErpDailyBalance], on_or_before: date) -> ErpDailyBalance | None:
    result: ErpDailyBalance | None = None
    for record in records:
        if record.business_date <= on_or_before:
            result = record
        else:
            break
    return result


def _on_date(records: list[ErpDailyBalance], value: date) -> ErpDailyBalance | None:
    for record in records:
        if record.business_date == value:
            return record
        if record.business_date > value:
            return None
    return None


def _rows_in_period(
    records: list[ErpDailyBalance],
    *,
    start: date,
    end: date,
) -> list[ErpDailyBalance]:
    return [row for row in records if start <= row.business_date <= end]


def _assets(lines: list[ErpOperatorLine], *, asset: str | None, nominal_u: bool) -> list[str]:
    if nominal_u:
        return ["NOMINAL_U"]
    if asset is not None:
        return [asset]
    return sorted({line.asset for line in lines})


def _line_matches_asset(line: ErpOperatorLine, asset: str | None, nominal_u: bool) -> bool:
    return nominal_u or asset is None or line.asset == asset


def _daily_row(
    *,
    period: date,
    asset: str,
    lines: list[ErpOperatorLine],
    history_by_line: dict[str, list[ErpDailyBalance]],
) -> ErpReportRow:
    totals = _Totals()
    for line in lines:
        records = history_by_line[line.id]
        on_day = _on_date(records, period)
        prior = _last_before(records, period - timedelta(days=1))
        opening = on_day.opening_balance if on_day else prior.closing_balance if prior else ZERO
        closing = on_day.closing_balance if on_day else opening
        totals.opening_balance += opening
        totals.closing_balance += closing
        if on_day:
            totals.add_flow(on_day)
    return totals.as_row(period=period.isoformat(), asset=asset)


def _monthly_row(
    *,
    period_start: date,
    asset: str,
    lines: list[ErpOperatorLine],
    history_by_line: dict[str, list[ErpDailyBalance]],
) -> ErpReportRow:
    period_end = _next_month(period_start) - timedelta(days=1)
    totals = _Totals()
    for line in lines:
        records = history_by_line[line.id]
        prior = _last_before(records, period_start - timedelta(days=1))
        current = _rows_in_period(records, start=period_start, end=period_end)
        ending = _last_before(records, period_end)
        opening = (
            prior.closing_balance
            if prior
            else current[0].opening_balance
            if current
            else ZERO
        )
        closing = ending.closing_balance if ending else opening
        totals.opening_balance += opening
        totals.closing_balance += closing
        for row in current:
            totals.add_flow(row)
    expected_closing = (
        totals.opening_balance
        + totals.effective_transfer_amount
        - totals.spend_amount
        - totals.exchange_loss_amount
        - totals.service_fee_amount
        - totals.reflux_amount
        - totals.refund_amount
        - totals.other_deduction_amount
        - totals.fraud_from_balance
    )
    if expected_closing != totals.closing_balance:
        totals.warnings.append("期末与期初加发生额不一致；可能存在人工期初锚点或范围外调整。")
    return totals.as_row(period=period_start.strftime("%Y-%m"), asset=asset)


async def _report_data(
    session: AsyncSession,
    *,
    end: date,
    operator_ids: list[str] | None,
    operator_line_ids: list[str] | None,
    asset: str | None,
    include_draft: bool,
) -> tuple[list[ErpOperatorLine], dict[str, list[ErpDailyBalance]]]:
    line_query = select(ErpOperatorLine)
    if operator_ids:
        line_query = line_query.where(ErpOperatorLine.operator_id.in_(operator_ids))
    if operator_line_ids:
        line_query = line_query.where(ErpOperatorLine.id.in_(operator_line_ids))
    if asset:
        line_query = line_query.where(ErpOperatorLine.asset == asset)
    lines = list((await session.scalars(line_query.order_by(ErpOperatorLine.name.asc()))).all())
    if not lines:
        return [], {}
    balance_query = select(ErpDailyBalance).where(
        ErpDailyBalance.operator_line_id.in_([line.id for line in lines]),
        ErpDailyBalance.business_date <= end,
    )
    if not include_draft:
        balance_query = balance_query.where(ErpDailyBalance.status == "CONFIRMED")
    rows = list(
        (
            await session.scalars(
                balance_query.order_by(
                    ErpDailyBalance.operator_line_id.asc(),
                    ErpDailyBalance.business_date.asc(),
                )
            )
        ).all()
    )
    history: dict[str, list[ErpDailyBalance]] = defaultdict(list)
    for row in rows:
        history[row.operator_line_id].append(row)
    return lines, history


async def build_erp_daily_report(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    operator_ids: list[str] | None = None,
    operator_line_ids: list[str] | None = None,
    asset: str | None = None,
    include_draft: bool = True,
    nominal_u: bool = False,
) -> ErpReportResponse:
    if date_to < date_from:
        raise ErpReportError("请选择有效的日期范围。")
    normalized_asset = asset.strip().upper() if asset and asset.strip() else None
    if normalized_asset not in {None, "USDT", "USDC"}:
        raise ErpReportError("币种必须为 USDT 或 USDC。")
    lines, history = await _report_data(
        session,
        end=date_to,
        operator_ids=operator_ids,
        operator_line_ids=operator_line_ids,
        asset=normalized_asset,
        include_draft=include_draft,
    )
    rows: list[ErpReportRow] = []
    for period in _periods_by_day(date_from, date_to):
        for item_asset in _assets(lines, asset=normalized_asset, nominal_u=nominal_u):
            selected = [
                line
                for line in lines
                if _line_matches_asset(line, normalized_asset, nominal_u)
                and (nominal_u or line.asset == item_asset)
            ]
            rows.append(
                _daily_row(
                    period=period,
                    asset=item_asset,
                    lines=selected,
                    history_by_line=history,
                )
            )
    return ErpReportResponse(report_type="DAILY", nominal_u=nominal_u, rows=rows)


async def build_erp_monthly_report(
    session: AsyncSession,
    *,
    month_from: str,
    month_to: str,
    operator_ids: list[str] | None = None,
    operator_line_ids: list[str] | None = None,
    asset: str | None = None,
    include_draft: bool = True,
    nominal_u: bool = False,
) -> ErpReportResponse:
    start = _month_start(month_from)
    end = _month_start(month_to)
    if end < start:
        raise ErpReportError("请选择有效的月份范围。")
    normalized_asset = asset.strip().upper() if asset and asset.strip() else None
    if normalized_asset not in {None, "USDT", "USDC"}:
        raise ErpReportError("币种必须为 USDT 或 USDC。")
    lines, history = await _report_data(
        session,
        end=_next_month(end) - timedelta(days=1),
        operator_ids=operator_ids,
        operator_line_ids=operator_line_ids,
        asset=normalized_asset,
        include_draft=include_draft,
    )
    rows: list[ErpReportRow] = []
    for period in _periods_by_month(start, end):
        for item_asset in _assets(lines, asset=normalized_asset, nominal_u=nominal_u):
            selected = [
                line
                for line in lines
                if _line_matches_asset(line, normalized_asset, nominal_u)
                and (nominal_u or line.asset == item_asset)
            ]
            rows.append(
                _monthly_row(
                    period_start=period,
                    asset=item_asset,
                    lines=selected,
                    history_by_line=history,
                )
            )
    return ErpReportResponse(report_type="MONTHLY", nominal_u=nominal_u, rows=rows)
