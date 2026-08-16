"""Local ERP daily-ledger service without remote side effects."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import ErpDailyBalance, ErpOperatorLine
from packages.domain.schemas.erp_balance import (
    ErpBalanceCalculationPreview,
    ErpDailyBalanceListResponse,
    ErpDailyBalanceResponse,
    ErpDailyBalanceWriteRequest,
)
from packages.domain.services.auth_service import write_audit
from packages.domain.services.erp_balance_calculation import (
    ErpBalanceCalculationError,
    ErpBalanceFee,
    calculate_erp_daily_balance,
)
from packages.domain.services.erp_operator_service import (
    ErpOperatorNotFoundError,
    get_erp_operator_line,
)


class ErpBalanceError(ValueError):
    pass


class ErpBalanceNotFoundError(ErpBalanceError):
    pass


class ErpBalanceConflictError(ErpBalanceError):
    pass


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _response(row: ErpDailyBalance) -> ErpDailyBalanceResponse:
    return ErpDailyBalanceResponse.model_validate(row)


def _preview(row: ErpDailyBalance) -> ErpBalanceCalculationPreview:
    return ErpBalanceCalculationPreview(
        suggested_opening_balance=row.suggested_opening_balance,
        opening_balance=row.opening_balance,
        effective_transfer_amount=row.effective_transfer_amount,
        exchange_loss_auto_amount=row.exchange_loss_auto_amount,
        exchange_loss_amount=row.exchange_loss_amount,
        service_fee_auto_amount=row.service_fee_auto_amount,
        service_fee_amount=row.service_fee_amount,
        fraud_from_transfer=row.fraud_loss_amount
        if row.fraud_deduction_source == "TRANSFER"
        else Decimal("0"),
        fraud_from_balance=row.fraud_loss_amount
        if row.fraud_deduction_source == "BALANCE"
        else Decimal("0"),
        closing_balance=row.closing_balance,
    )


async def _previous_balance(
    session: AsyncSession,
    *,
    line_id: str,
    business_date: date,
) -> ErpDailyBalance | None:
    return await session.scalar(
        select(ErpDailyBalance)
        .where(
            ErpDailyBalance.operator_line_id == line_id,
            ErpDailyBalance.business_date < business_date,
        )
        .order_by(ErpDailyBalance.business_date.desc())
        .limit(1)
    )


def _request_value(value: Decimal | None, existing: Decimal | None) -> Decimal:
    return value if value is not None else existing or Decimal("0")


async def _apply_request(
    session: AsyncSession,
    *,
    row: ErpDailyBalance,
    line: ErpOperatorLine,
    request: ErpDailyBalanceWriteRequest,
    creating: bool,
) -> None:
    previous = await _previous_balance(
        session,
        line_id=line.id,
        business_date=request.business_date,
    )
    row.operator_line_id = line.id
    row.business_date = request.business_date
    row.suggested_opening_balance = previous.closing_balance if previous else None

    opening_mode = request.opening_mode or ("AUTO" if previous else "MANUAL")
    if opening_mode == "AUTO":
        if previous is None:
            raise ErpBalanceError("没有历史记录时必须填写人工期初结余。")
        row.opening_balance = previous.closing_balance
        row.opening_override_reason = None
    else:
        opening = (
            request.opening_balance
            if request.opening_balance is not None
            else row.opening_balance
        )
        if opening is None:
            raise ErpBalanceError("人工期初结余不能为空。")
        row.opening_balance = opening
        row.opening_override_reason = _text(request.opening_override_reason)
    row.opening_mode = opening_mode

    row.transfer_amount = _request_value(request.transfer_amount, row.transfer_amount)
    row.fraud_loss_amount = _request_value(request.fraud_loss_amount, row.fraud_loss_amount)
    row.spend_amount = _request_value(request.spend_amount, row.spend_amount)
    row.reflux_amount = _request_value(request.reflux_amount, row.reflux_amount)
    row.refund_amount = _request_value(request.refund_amount, row.refund_amount)
    row.other_deduction_amount = _request_value(
        request.other_deduction_amount,
        row.other_deduction_amount,
    )
    row.other_reason = (
        _text(request.other_reason)
        if request.other_reason is not None
        else row.other_reason
    )
    if row.other_deduction_amount > 0 and not row.other_reason:
        raise ErpBalanceError("其他扣减金额不为 0 时必须填写原因。")
    row.fraud_deduction_source = (
        None
        if row.fraud_loss_amount == 0
        else request.fraud_deduction_source or row.fraud_deduction_source
    )

    row.exchange_loss_rate = (
        request.exchange_loss_rate
        if request.exchange_loss_rate is not None
        else (
            row.exchange_loss_rate
            if not creating
            else line.default_exchange_loss_rate
        )
    )
    row.exchange_loss_basis = request.exchange_loss_basis or (
        row.exchange_loss_basis if not creating else line.default_exchange_loss_basis
    )
    row.exchange_loss_mode = request.exchange_loss_mode or row.exchange_loss_mode or "AUTO"
    if request.exchange_loss_amount is not None:
        row.exchange_loss_amount = request.exchange_loss_amount
    row.exchange_loss_override_reason = (
        _text(request.exchange_loss_override_reason)
        if request.exchange_loss_override_reason is not None
        else row.exchange_loss_override_reason
    )

    row.service_fee_rate = (
        request.service_fee_rate
        if request.service_fee_rate is not None
        else (
            row.service_fee_rate
            if not creating
            else line.default_service_fee_rate
        )
    )
    row.service_fee_basis = request.service_fee_basis or (
        row.service_fee_basis if not creating else line.default_service_fee_basis
    )
    row.service_fee_mode = request.service_fee_mode or row.service_fee_mode or "AUTO"
    if request.service_fee_amount is not None:
        row.service_fee_amount = request.service_fee_amount
    row.service_fee_override_reason = (
        _text(request.service_fee_override_reason)
        if request.service_fee_override_reason is not None
        else row.service_fee_override_reason
    )
    row.calculation_scale = (
        request.calculation_scale
        if request.calculation_scale is not None
        else (row.calculation_scale if not creating else line.calculation_scale)
    )
    row.source_type = request.source_type or row.source_type or "MANUAL"
    if request.remark is not None:
        row.remark = _text(request.remark)

    try:
        calculation = calculate_erp_daily_balance(
            opening_balance=row.opening_balance,
            transfer_amount=row.transfer_amount,
            fraud_loss_amount=row.fraud_loss_amount,
            fraud_deduction_source=row.fraud_deduction_source,
            spend_amount=row.spend_amount,
            exchange_loss=ErpBalanceFee(
                rate=row.exchange_loss_rate,
                basis=row.exchange_loss_basis,
                mode=row.exchange_loss_mode,
                entered_amount=row.exchange_loss_amount,
            ),
            service_fee=ErpBalanceFee(
                rate=row.service_fee_rate,
                basis=row.service_fee_basis,
                mode=row.service_fee_mode,
                entered_amount=row.service_fee_amount,
            ),
            reflux_amount=row.reflux_amount,
            refund_amount=row.refund_amount,
            other_deduction_amount=row.other_deduction_amount,
            calculation_scale=row.calculation_scale,
        )
    except ErpBalanceCalculationError as exc:
        raise ErpBalanceError(str(exc)) from exc
    row.effective_transfer_amount = calculation.effective_transfer_amount
    row.exchange_loss_auto_amount = calculation.exchange_loss_auto_amount
    row.exchange_loss_amount = calculation.exchange_loss_amount
    row.service_fee_auto_amount = calculation.service_fee_auto_amount
    row.service_fee_amount = calculation.service_fee_amount
    row.closing_balance = calculation.closing_balance


async def list_erp_daily_balances(
    session: AsyncSession,
    *,
    operator_line_id: str,
    month: str,
) -> ErpDailyBalanceListResponse:
    try:
        year, number = (int(part) for part in month.split("-", maxsplit=1))
        start = date(year, number, 1)
    except (TypeError, ValueError) as exc:
        raise ErpBalanceError("月份必须为 YYYY-MM。") from exc
    if number == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, number + 1, 1)
    try:
        await get_erp_operator_line(session, line_id=operator_line_id)
    except ErpOperatorNotFoundError as exc:
        raise ErpBalanceNotFoundError(str(exc)) from exc
    rows = await session.scalars(
        select(ErpDailyBalance)
        .where(
            ErpDailyBalance.operator_line_id == operator_line_id,
            ErpDailyBalance.business_date >= start,
            ErpDailyBalance.business_date < end,
        )
        .order_by(ErpDailyBalance.business_date.asc())
    )
    return ErpDailyBalanceListResponse(
        operator_line_id=operator_line_id,
        month=month,
        records=[_response(row) for row in rows],
    )


async def preview_erp_daily_balance(
    session: AsyncSession,
    *,
    request: ErpDailyBalanceWriteRequest,
) -> ErpBalanceCalculationPreview:
    try:
        line = await get_erp_operator_line(session, line_id=request.operator_line_id)
    except ErpOperatorNotFoundError as exc:
        raise ErpBalanceNotFoundError(str(exc)) from exc
    row = ErpDailyBalance()
    await _apply_request(session, row=row, line=line, request=request, creating=True)
    return _preview(row)


async def create_erp_daily_balance(
    session: AsyncSession,
    *,
    request: ErpDailyBalanceWriteRequest,
    actor_user_id: int,
    commit: bool = True,
) -> ErpDailyBalanceResponse:
    try:
        line = await get_erp_operator_line(session, line_id=request.operator_line_id)
    except ErpOperatorNotFoundError as exc:
        raise ErpBalanceNotFoundError(str(exc)) from exc
    if line.status != "ACTIVE":
        raise ErpBalanceConflictError("已停用的投放线不能新建日结。")
    existing = await session.scalar(
        select(ErpDailyBalance.id).where(
            ErpDailyBalance.operator_line_id == line.id,
            ErpDailyBalance.business_date == request.business_date,
        )
    )
    if existing:
        raise ErpBalanceConflictError("该投放线该日期已有日结记录。")
    row = ErpDailyBalance(
        status="DRAFT",
        source_type=request.source_type,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    await _apply_request(session, row=row, line=line, request=request, creating=True)
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ErpBalanceConflictError("该投放线该日期已有日结记录。") from exc
    result = _response(row)
    await write_audit(
        session,
        action="erp_daily_balance.create",
        actor_user_id=actor_user_id,
        target_type="erp_daily_balance",
        target_id=row.id,
        metadata={
            "operator_line_id": row.operator_line_id,
            "business_date": row.business_date.isoformat(),
        },
    )
    if commit:
        await session.commit()
    return result


async def update_erp_daily_balance(
    session: AsyncSession,
    *,
    balance_id: str,
    request: ErpDailyBalanceWriteRequest,
    actor_user_id: int,
    commit: bool = True,
) -> ErpDailyBalanceResponse:
    row = await session.get(ErpDailyBalance, balance_id)
    if row is None:
        raise ErpBalanceNotFoundError("日结记录不存在。")
    if row.status != "DRAFT":
        raise ErpBalanceConflictError("已确认日结必须先重开。")
    if request.row_version is None or request.row_version != row.row_version:
        raise ErpBalanceConflictError("日结记录已被其他人修改，请刷新后重试。")
    if (
        request.operator_line_id != row.operator_line_id
        or request.business_date != row.business_date
    ):
        raise ErpBalanceError("已存在日结记录不能更换投放线或业务日期。")
    try:
        line = await get_erp_operator_line(session, line_id=row.operator_line_id)
    except ErpOperatorNotFoundError as exc:
        raise ErpBalanceNotFoundError(str(exc)) from exc
    await _apply_request(session, row=row, line=line, request=request, creating=False)
    row.row_version += 1
    row.updated_by = actor_user_id
    await session.flush()
    result = _response(row)
    await write_audit(
        session,
        action="erp_daily_balance.update",
        actor_user_id=actor_user_id,
        target_type="erp_daily_balance",
        target_id=row.id,
        metadata={
            "operator_line_id": row.operator_line_id,
            "business_date": row.business_date.isoformat(),
        },
    )
    if commit:
        await session.commit()
    return result


async def confirm_erp_daily_balance(
    session: AsyncSession,
    *,
    balance_id: str,
    row_version: int | None,
    actor_user_id: int,
) -> ErpDailyBalanceResponse:
    row = await session.get(ErpDailyBalance, balance_id)
    if row is None:
        raise ErpBalanceNotFoundError("日结记录不存在。")
    if row_version is None or row_version != row.row_version:
        raise ErpBalanceConflictError("日结记录已被其他人修改，请刷新后重试。")
    if row.status != "DRAFT":
        raise ErpBalanceConflictError("只有草稿可确认。")
    row.status = "CONFIRMED"
    row.confirmed_by = actor_user_id
    row.confirmed_at = datetime.now(UTC)
    row.row_version += 1
    row.updated_by = actor_user_id
    await session.flush()
    result = _response(row)
    await write_audit(
        session,
        action="erp_daily_balance.confirm",
        actor_user_id=actor_user_id,
        target_type="erp_daily_balance",
        target_id=row.id,
    )
    await session.commit()
    return result
