"""Local ERP monthly close locks used by ledger and import writes."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import (
    ErpAccountingPeriodLock,
    ErpDailyBalance,
    ErpOperator,
    ErpOperatorLine,
)
from packages.domain.schemas.erp_period_lock import (
    ErpPeriodLockIssue,
    ErpPeriodLockRequest,
    ErpPeriodLockResponse,
    ErpPeriodLockValidationResponse,
    ErpPeriodUnlockRequest,
)
from packages.domain.services.auth_service import write_audit


class ErpPeriodLockError(ValueError):
    pass


class ErpPeriodLockNotFoundError(ErpPeriodLockError):
    pass


class ErpPeriodLockConflictError(ErpPeriodLockError):
    pass


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _response(row: ErpAccountingPeriodLock) -> ErpPeriodLockResponse:
    return ErpPeriodLockResponse.model_validate(row)


async def _line_ids_for_request(
    session: AsyncSession,
    *,
    request: ErpPeriodLockRequest,
) -> list[str]:
    requested = set(request.operator_line_ids)
    if request.operator_ids:
        found_operator_ids = set(
            await session.scalars(
                select(ErpOperator.id).where(ErpOperator.id.in_(request.operator_ids))
            )
        )
        if set(request.operator_ids) - found_operator_ids:
            raise ErpPeriodLockNotFoundError("包含不存在的投放公司。")
        requested.update(
            await session.scalars(
                select(ErpOperatorLine.id).where(ErpOperatorLine.operator_id.in_(request.operator_ids))
            )
        )
    if not requested:
        raise ErpPeriodLockNotFoundError("所选投放公司没有投放线。")
    found_line_ids = set(
        await session.scalars(select(ErpOperatorLine.id).where(ErpOperatorLine.id.in_(requested)))
    )
    if requested - found_line_ids:
        raise ErpPeriodLockNotFoundError("包含不存在的投放线。")
    return sorted(found_line_ids)


async def is_erp_period_locked(
    session: AsyncSession,
    *,
    operator_line_id: str,
    business_date: date,
) -> bool:
    return bool(
        await session.scalar(
            select(ErpAccountingPeriodLock.id).where(
                ErpAccountingPeriodLock.operator_line_id == operator_line_id,
                ErpAccountingPeriodLock.month_start == _month_start(business_date),
                ErpAccountingPeriodLock.status == "LOCKED",
            )
        )
    )


async def ensure_erp_period_unlocked(
    session: AsyncSession,
    *,
    operator_line_id: str,
    business_date: date,
) -> None:
    if await is_erp_period_locked(
        session,
        operator_line_id=operator_line_id,
        business_date=business_date,
    ):
        raise ErpPeriodLockConflictError("该业务月份已锁定，不能修改日结。")


async def validate_erp_period_lock(
    session: AsyncSession,
    *,
    request: ErpPeriodLockRequest,
) -> ErpPeriodLockValidationResponse:
    month = _month_start(request.month)
    next_month = _next_month(month)
    issues: list[ErpPeriodLockIssue] = []
    for line_id in await _line_ids_for_request(session, request=request):
        records = list(
            await session.scalars(
                select(ErpDailyBalance)
                .where(
                    ErpDailyBalance.operator_line_id == line_id,
                    ErpDailyBalance.business_date >= month,
                    ErpDailyBalance.business_date < next_month,
                )
                .order_by(ErpDailyBalance.business_date.asc())
            )
        )
        if not records:
            issues.append(
                ErpPeriodLockIssue(
                    operator_line_id=line_id,
                    business_date=None,
                    code="NO_MONTHLY_RECORD",
                    message="该投放线本月没有日结记录，不能锁定。",
                )
            )
        for record in records:
            if record.status != "CONFIRMED":
                issues.append(
                    ErpPeriodLockIssue(
                        operator_line_id=line_id,
                        business_date=record.business_date,
                        code="DRAFT_BALANCE",
                        message="存在未确认的日结记录。",
                    )
                )
    return ErpPeriodLockValidationResponse(
        month=month,
        can_lock=not issues,
        issues=issues,
    )


async def list_erp_period_locks(
    session: AsyncSession,
    *,
    month: date,
    operator_ids: list[str] | None = None,
) -> list[ErpPeriodLockResponse]:
    statement = select(ErpAccountingPeriodLock).where(
        ErpAccountingPeriodLock.month_start == _month_start(month)
    )
    if operator_ids:
        statement = statement.join(
            ErpOperatorLine,
            ErpOperatorLine.id == ErpAccountingPeriodLock.operator_line_id,
        ).where(ErpOperatorLine.operator_id.in_(operator_ids))
    rows = await session.scalars(statement.order_by(ErpAccountingPeriodLock.operator_line_id.asc()))
    return [_response(row) for row in rows]


async def lock_erp_period(
    session: AsyncSession,
    *,
    request: ErpPeriodLockRequest,
    actor_user_id: int,
) -> list[ErpPeriodLockResponse]:
    validation = await validate_erp_period_lock(session, request=request)
    if not validation.can_lock:
        raise ErpPeriodLockConflictError("存在未确认或缺失的日结，不能锁定期间。")
    now = datetime.now(UTC)
    rows: list[ErpAccountingPeriodLock] = []
    for line_id in await _line_ids_for_request(session, request=request):
        row = await session.scalar(
            select(ErpAccountingPeriodLock).where(
                ErpAccountingPeriodLock.operator_line_id == line_id,
                ErpAccountingPeriodLock.month_start == validation.month,
            )
        )
        if row is None:
            row = ErpAccountingPeriodLock(
                operator_line_id=line_id,
                month_start=validation.month,
                status="LOCKED",
                locked_by=actor_user_id,
                locked_at=now,
            )
            session.add(row)
        elif row.status != "LOCKED":
            row.status = "LOCKED"
            row.locked_by = actor_user_id
            row.locked_at = now
            row.unlock_reason = None
            row.unlocked_by = None
            row.unlocked_at = None
            row.row_version += 1
        rows.append(row)
    await session.flush()
    await write_audit(
        session,
        action="erp_period_lock.lock",
        actor_user_id=actor_user_id,
        target_type="erp_accounting_period",
        target_id=validation.month.isoformat(),
        metadata={"month": validation.month.isoformat(), "operator_line_count": len(rows)},
    )
    await session.commit()
    return [_response(row) for row in rows]


async def unlock_erp_period(
    session: AsyncSession,
    *,
    request: ErpPeriodUnlockRequest,
    actor_user_id: int,
) -> list[ErpPeriodLockResponse]:
    month = _month_start(request.month)
    reason = request.reason.strip()
    if not reason:
        raise ErpPeriodLockError("解锁必须填写原因。")
    rows: list[ErpAccountingPeriodLock] = []
    for line_id in await _line_ids_for_request(session, request=request):
        row = await session.scalar(
            select(ErpAccountingPeriodLock).where(
                ErpAccountingPeriodLock.operator_line_id == line_id,
                ErpAccountingPeriodLock.month_start == month,
            )
        )
        if row is None or row.status != "LOCKED":
            raise ErpPeriodLockConflictError("所选投放线的该月份尚未锁定。")
        row.status = "UNLOCKED"
        row.unlock_reason = reason
        row.unlocked_by = actor_user_id
        row.unlocked_at = datetime.now(UTC)
        row.row_version += 1
        rows.append(row)
    await session.flush()
    await write_audit(
        session,
        action="erp_period_lock.unlock",
        actor_user_id=actor_user_id,
        target_type="erp_accounting_period",
        target_id=month.isoformat(),
        metadata={"month": month.isoformat(), "operator_line_count": len(rows)},
    )
    await session.commit()
    return [_response(row) for row in rows]
