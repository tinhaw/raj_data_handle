"""Local CRUD service for ERP delivery companies and delivery lines.

This module has no remote calls. It keeps the ERP write domain local to the
Raj Data Handle database and uses the project's existing security audit log.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import ErpOperator, ErpOperatorLine
from packages.domain.schemas.erp_operator import (
    ErpDeliveryLineCreateRequest,
    ErpDeliveryLinePatchRequest,
    ErpDeliveryLineResponse,
    ErpOperatorCreateRequest,
    ErpOperatorPatchRequest,
    ErpOperatorResponse,
)
from packages.domain.services.auth_service import write_audit


class ErpOperatorError(ValueError):
    pass


class ErpOperatorNotFoundError(ErpOperatorError):
    pass


class ErpOperatorConflictError(ErpOperatorError):
    pass


def _next_code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:18].upper()}"


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _response(operator: ErpOperator) -> ErpOperatorResponse:
    return ErpOperatorResponse.model_validate(operator)


def _line_response(line: ErpOperatorLine, operator: ErpOperator) -> ErpDeliveryLineResponse:
    return ErpDeliveryLineResponse(
        id=line.id,
        operator_id=operator.id,
        operator_name=operator.name,
        display_name=f"{operator.name} · {line.name}",
        code=line.code,
        name=line.name,
        asset=line.asset,
        network=line.network,
        wallet_address=line.wallet_address,
        start_date=line.start_date,
        default_exchange_loss_rate=line.default_exchange_loss_rate,
        default_exchange_loss_basis=line.default_exchange_loss_basis,
        default_service_fee_rate=line.default_service_fee_rate,
        default_service_fee_basis=line.default_service_fee_basis,
        calculation_scale=line.calculation_scale,
        status=line.status,
        row_version=line.row_version,
        created_at=line.created_at,
        updated_at=line.updated_at,
    )


async def list_erp_operators(
    session: AsyncSession,
    *,
    include_inactive: bool = False,
    search: str | None = None,
) -> list[ErpOperatorResponse]:
    statement = select(ErpOperator)
    if not include_inactive:
        statement = statement.where(ErpOperator.status == "ACTIVE")
    if search and search.strip():
        pattern = f"%{search.strip().lower()}%"
        statement = statement.where(
            func.lower(ErpOperator.name).like(pattern) | func.lower(ErpOperator.code).like(pattern)
        )
    rows = await session.scalars(statement.order_by(ErpOperator.name.asc(), ErpOperator.code.asc()))
    return [_response(row) for row in rows]


async def get_erp_operator(session: AsyncSession, *, operator_id: str) -> ErpOperator:
    operator = await session.get(ErpOperator, operator_id)
    if operator is None:
        raise ErpOperatorNotFoundError("投放公司不存在。")
    return operator


async def _ensure_operator_name_available(
    session: AsyncSession,
    *,
    name: str,
    exclude_id: str | None = None,
) -> None:
    statement = select(ErpOperator.id).where(func.lower(ErpOperator.name) == name.lower())
    if exclude_id:
        statement = statement.where(ErpOperator.id != exclude_id)
    if await session.scalar(statement):
        raise ErpOperatorConflictError("投放公司名称已存在。")


async def create_erp_operator(
    session: AsyncSession,
    *,
    request: ErpOperatorCreateRequest,
    actor_user_id: int,
) -> ErpOperatorResponse:
    await _ensure_operator_name_available(session, name=request.name)
    operator = ErpOperator(
        code=_next_code("OP"),
        name=request.name,
        operator_type=request.operator_type or "COMPANY",
        contact_name=_optional_text(request.contact_name),
        contact_value=_optional_text(request.contact_value),
        remark=_optional_text(request.remark),
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(operator)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ErpOperatorConflictError("投放公司名称或编号已存在。") from exc
    result = _response(operator)
    await write_audit(
        session,
        action="erp_operator.create",
        actor_user_id=actor_user_id,
        target_type="erp_operator",
        target_id=operator.id,
        metadata={"name": operator.name, "code": operator.code},
    )
    await session.commit()
    return result


def _assert_version(*, actual: int, requested: int | None, label: str) -> None:
    if requested is not None and requested != actual:
        raise ErpOperatorConflictError(f"{label}已被其他人修改，请刷新后重试。")


async def update_erp_operator(
    session: AsyncSession,
    *,
    operator_id: str,
    request: ErpOperatorPatchRequest,
    actor_user_id: int,
) -> ErpOperatorResponse:
    operator = await get_erp_operator(session, operator_id=operator_id)
    _assert_version(actual=operator.row_version, requested=request.row_version, label="投放公司")
    changed_fields: list[str] = []
    if request.name is not None and request.name != operator.name:
        await _ensure_operator_name_available(session, name=request.name, exclude_id=operator.id)
        operator.name = request.name
        changed_fields.append("name")
    if request.operator_type is not None and request.operator_type != operator.operator_type:
        operator.operator_type = request.operator_type
        changed_fields.append("operator_type")
    for field in ("contact_name", "contact_value", "remark"):
        value = getattr(request, field)
        if value is not None and value != getattr(operator, field):
            setattr(operator, field, _optional_text(value))
            changed_fields.append(field)
    if changed_fields:
        operator.row_version += 1
        operator.updated_by = actor_user_id
    result = _response(operator)
    await write_audit(
        session,
        action="erp_operator.update",
        actor_user_id=actor_user_id,
        target_type="erp_operator",
        target_id=operator.id,
        metadata={"changed_fields": changed_fields},
    )
    await session.commit()
    return result


async def disable_erp_operator(
    session: AsyncSession,
    *,
    operator_id: str,
    row_version: int | None,
    actor_user_id: int,
) -> ErpOperatorResponse:
    operator = await get_erp_operator(session, operator_id=operator_id)
    _assert_version(actual=operator.row_version, requested=row_version, label="投放公司")
    if operator.status != "INACTIVE":
        operator.status = "INACTIVE"
        operator.row_version += 1
        operator.updated_by = actor_user_id
    result = _response(operator)
    await write_audit(
        session,
        action="erp_operator.disable",
        actor_user_id=actor_user_id,
        target_type="erp_operator",
        target_id=operator.id,
    )
    await session.commit()
    return result


async def list_erp_operator_lines(
    session: AsyncSession,
    *,
    operator_id: str,
    include_inactive: bool = False,
) -> list[ErpDeliveryLineResponse]:
    operator = await get_erp_operator(session, operator_id=operator_id)
    statement = select(ErpOperatorLine).where(ErpOperatorLine.operator_id == operator.id)
    if not include_inactive:
        statement = statement.where(ErpOperatorLine.status == "ACTIVE")
    rows = await session.scalars(
        statement.order_by(ErpOperatorLine.name.asc(), ErpOperatorLine.code.asc())
    )
    return [_line_response(row, operator) for row in rows]


async def get_erp_operator_line(session: AsyncSession, *, line_id: str) -> ErpOperatorLine:
    line = await session.get(ErpOperatorLine, line_id)
    if line is None:
        raise ErpOperatorNotFoundError("投放线不存在。")
    return line


async def _ensure_line_name_available(
    session: AsyncSession,
    *,
    operator_id: str,
    name: str,
    exclude_id: str | None = None,
) -> None:
    statement = select(ErpOperatorLine.id).where(
        ErpOperatorLine.operator_id == operator_id,
        func.lower(ErpOperatorLine.name) == name.lower(),
    )
    if exclude_id:
        statement = statement.where(ErpOperatorLine.id != exclude_id)
    if await session.scalar(statement):
        raise ErpOperatorConflictError("同一投放公司下的投放线名称已存在。")


async def create_erp_operator_line(
    session: AsyncSession,
    *,
    operator_id: str,
    request: ErpDeliveryLineCreateRequest,
    actor_user_id: int,
) -> ErpDeliveryLineResponse:
    operator = await get_erp_operator(session, operator_id=operator_id)
    if operator.status != "ACTIVE":
        raise ErpOperatorConflictError("已停用的投放公司不能新增投放线。")
    await _ensure_line_name_available(session, operator_id=operator.id, name=request.name)
    line = ErpOperatorLine(
        operator_id=operator.id,
        code=_next_code("LINE"),
        name=request.name,
        asset=request.asset,
        network=_optional_text(request.network),
        wallet_address=_optional_text(request.wallet_address),
        start_date=request.start_date,
        default_exchange_loss_rate=request.default_exchange_loss_rate or Decimal("0.02"),
        default_exchange_loss_basis=request.default_exchange_loss_basis or "TRANSFER",
        default_service_fee_rate=request.default_service_fee_rate or Decimal("0.02"),
        default_service_fee_basis=request.default_service_fee_basis or "TRANSFER",
        calculation_scale=request.calculation_scale if request.calculation_scale is not None else 2,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(line)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ErpOperatorConflictError("投放线名称或编号已存在。") from exc
    result = _line_response(line, operator)
    await write_audit(
        session,
        action="erp_operator_line.create",
        actor_user_id=actor_user_id,
        target_type="erp_operator_line",
        target_id=line.id,
        metadata={"operator_id": operator.id, "name": line.name, "code": line.code},
    )
    await session.commit()
    return result


async def update_erp_operator_line(
    session: AsyncSession,
    *,
    line_id: str,
    request: ErpDeliveryLinePatchRequest,
    actor_user_id: int,
) -> ErpDeliveryLineResponse:
    line = await get_erp_operator_line(session, line_id=line_id)
    operator = await get_erp_operator(session, operator_id=line.operator_id)
    _assert_version(actual=line.row_version, requested=request.row_version, label="投放线")
    changed_fields: list[str] = []
    if request.name is not None and request.name != line.name:
        await _ensure_line_name_available(
            session,
            operator_id=line.operator_id,
            name=request.name,
            exclude_id=line.id,
        )
        line.name = request.name
        changed_fields.append("name")
    for field in (
        "network",
        "wallet_address",
        "start_date",
        "default_exchange_loss_rate",
        "default_exchange_loss_basis",
        "default_service_fee_rate",
        "default_service_fee_basis",
        "calculation_scale",
    ):
        value = getattr(request, field)
        if value is not None and value != getattr(line, field):
            setattr(line, field, _optional_text(value) if isinstance(value, str) else value)
            changed_fields.append(field)
    if changed_fields:
        line.row_version += 1
        line.updated_by = actor_user_id
    result = _line_response(line, operator)
    await write_audit(
        session,
        action="erp_operator_line.update",
        actor_user_id=actor_user_id,
        target_type="erp_operator_line",
        target_id=line.id,
        metadata={"changed_fields": changed_fields},
    )
    await session.commit()
    return result


async def disable_erp_operator_line(
    session: AsyncSession,
    *,
    line_id: str,
    row_version: int | None,
    actor_user_id: int,
) -> ErpDeliveryLineResponse:
    line = await get_erp_operator_line(session, line_id=line_id)
    operator = await get_erp_operator(session, operator_id=line.operator_id)
    _assert_version(actual=line.row_version, requested=row_version, label="投放线")
    if line.status != "INACTIVE":
        line.status = "INACTIVE"
        line.row_version += 1
        line.updated_by = actor_user_id
    result = _line_response(line, operator)
    await write_audit(
        session,
        action="erp_operator_line.disable",
        actor_user_id=actor_user_id,
        target_type="erp_operator_line",
        target_id=line.id,
    )
    await session.commit()
    return result
