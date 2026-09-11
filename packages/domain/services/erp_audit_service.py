"""Read local ERP business audits from the project's append-only audit log."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import (
    AppUser,
    ErpDailyBalance,
    ErpImportJobRow,
    ErpOperatorLine,
    SecurityAuditLog,
)
from packages.domain.schemas.erp_audit import ErpAuditLogEntry, ErpAuditLogList

BUSINESS_TIME_ZONE = ZoneInfo("Asia/Shanghai")


async def list_erp_audit_logs(
    session: AsyncSession,
    *,
    date_from: date | None,
    date_to: date | None,
    action: str | None,
    operator_ids: list[str] | None = None,
    operator_id: str | None = None,
    page: int,
    page_size: int,
) -> ErpAuditLogList:
    start = datetime.combine(
        date_from or (datetime.now(BUSINESS_TIME_ZONE).date() - timedelta(days=6)),
        time.min,
        tzinfo=BUSINESS_TIME_ZONE,
    ).astimezone(UTC)
    end = datetime.combine(
        date_to or datetime.now(BUSINESS_TIME_ZONE).date(),
        time.max,
        tzinfo=BUSINESS_TIME_ZONE,
    ).astimezone(UTC)
    if end < start:
        raise ValueError("结束日期不能早于开始日期。")
    filters = [
        SecurityAuditLog.action.startswith("erp_"),
        SecurityAuditLog.created_at >= start,
        SecurityAuditLog.created_at <= end,
    ]
    if action and action.strip():
        filters.append(SecurityAuditLog.action == action.strip())
    if operator_id is not None:
        if operator_ids is not None and operator_id not in operator_ids:
            return ErpAuditLogList(items=[], total=0, page=page, page_size=page_size)
        effective_operator_ids = [operator_id]
    else:
        effective_operator_ids = operator_ids
    if effective_operator_ids is not None:
        if not effective_operator_ids:
            return ErpAuditLogList(items=[], total=0, page=page, page_size=page_size)
        line_ids = select(ErpOperatorLine.id).where(
            ErpOperatorLine.operator_id.in_(effective_operator_ids)
        )
        balance_ids = select(ErpDailyBalance.id).where(
            ErpDailyBalance.operator_line_id.in_(line_ids)
        )
        import_job_ids = select(ErpImportJobRow.import_job_id).where(
            ErpImportJobRow.operator_line_id.in_(line_ids)
        )
        filters.append(
            or_(
                (SecurityAuditLog.target_type == "erp_operator")
                & SecurityAuditLog.target_id.in_(effective_operator_ids),
                (SecurityAuditLog.target_type == "erp_operator_line")
                & SecurityAuditLog.target_id.in_(line_ids),
                (SecurityAuditLog.target_type == "erp_daily_balance")
                & SecurityAuditLog.target_id.in_(balance_ids),
                (SecurityAuditLog.target_type == "erp_import_job")
                & SecurityAuditLog.target_id.in_(import_job_ids),
                SecurityAuditLog.metadata_json["operator_id"]
                .as_string()
                .in_(effective_operator_ids),
                SecurityAuditLog.metadata_json["operator_line_id"].as_string().in_(line_ids),
            )
        )
    total = int(
        await session.scalar(
            select(func.count()).select_from(SecurityAuditLog).where(*filters)
        )
        or 0
    )
    rows = (
        await session.execute(
            select(SecurityAuditLog, AppUser.display_name)
            .outerjoin(AppUser, AppUser.id == SecurityAuditLog.actor_user_id)
            .where(*filters)
            .order_by(SecurityAuditLog.created_at.desc(), SecurityAuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ErpAuditLogList(
        items=[
            ErpAuditLogEntry(
                id=row.id,
                action=row.action,
                actor_user_id=row.actor_user_id,
                actor_display_name=display_name,
                target_type=row.target_type,
                target_id=row.target_id,
                request_id=row.request_id,
                result=row.result,
                metadata=row.metadata_json if isinstance(row.metadata_json, dict) else {},
                created_at=row.created_at,
            )
            for row, display_name in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
