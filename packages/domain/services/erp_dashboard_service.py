"""Read-only local ERP workbench aggregation without remote side effects."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import (
    ErpAccountingPeriodLock,
    ErpDailyBalance,
    ErpImportJob,
    ErpImportJobRow,
    ErpOperator,
    ErpOperatorLine,
)
from packages.domain.schemas.erp_dashboard import (
    ErpDashboardHealthItem,
    ErpDashboardMetric,
    ErpDashboardRecentBalance,
    ErpDashboardResponse,
    ErpDashboardTrendPoint,
)
from packages.domain.services.erp_report_service import build_erp_daily_report

ZERO = Decimal("0")


async def _count(session: AsyncSession, statement) -> int:
    return int(await session.scalar(statement) or 0)


async def build_erp_dashboard(
    session: AsyncSession,
    *,
    business_date: date,
    operator_ids: list[str] | None = None,
) -> ErpDashboardResponse:
    operator_filter = (
        ErpOperator.id.in_(operator_ids) if operator_ids is not None else None
    )
    line_filter = (
        ErpOperatorLine.operator_id.in_(operator_ids) if operator_ids is not None else None
    )
    balance_line_ids = (
        select(ErpOperatorLine.id).where(ErpOperatorLine.operator_id.in_(operator_ids))
        if operator_ids is not None
        else None
    )
    active_operator_count = await _count(
        session,
        select(func.count()).select_from(ErpOperator).where(
            ErpOperator.status == "ACTIVE",
            *([operator_filter] if operator_filter is not None else []),
        ),
    )
    active_line_count = await _count(
        session,
        select(func.count()).select_from(ErpOperatorLine).where(
            ErpOperatorLine.status == "ACTIVE",
            *([line_filter] if line_filter is not None else []),
        ),
    )
    report = await build_erp_daily_report(
        session,
        date_from=business_date,
        date_to=business_date,
        include_draft=True,
        nominal_u=True,
        operator_ids=operator_ids,
    )
    totals = report.rows[0] if report.rows else None
    metric = ErpDashboardMetric(
        opening_balance=totals.opening_balance if totals else ZERO,
        transfer_amount=totals.transfer_amount if totals else ZERO,
        spend_amount=totals.spend_amount if totals else ZERO,
        closing_balance=totals.closing_balance if totals else ZERO,
        active_operator_count=active_operator_count,
        active_line_count=active_line_count,
    )

    trend_report = await build_erp_daily_report(
        session,
        date_from=business_date - timedelta(days=6),
        date_to=business_date,
        include_draft=True,
        nominal_u=True,
        operator_ids=operator_ids,
    )
    trend = [
        ErpDashboardTrendPoint(
            business_date=date.fromisoformat(row.period),
            closing_balance=row.closing_balance,
        )
        for row in trend_report.rows
    ]

    draft_count = await _count(
        session,
        select(func.count())
        .select_from(ErpDailyBalance)
        .where(
            ErpDailyBalance.status == "DRAFT",
            ErpDailyBalance.business_date <= business_date,
            *(
                [ErpDailyBalance.operator_line_id.in_(balance_line_ids)]
                if balance_line_ids is not None
                else []
            ),
        ),
    )
    negative_count = await _count(
        session,
        select(func.count())
        .select_from(ErpDailyBalance)
        .where(
            ErpDailyBalance.business_date == business_date,
            ErpDailyBalance.closing_balance < 0,
            *(
                [ErpDailyBalance.operator_line_id.in_(balance_line_ids)]
                if balance_line_ids is not None
                else []
            ),
        ),
    )
    month_start = business_date.replace(day=1)
    locked_line_count = await _count(
        session,
        select(func.count())
        .select_from(ErpAccountingPeriodLock)
        .where(
            ErpAccountingPeriodLock.month_start == month_start,
            ErpAccountingPeriodLock.status == "LOCKED",
            *(
                [ErpAccountingPeriodLock.operator_line_id.in_(balance_line_ids)]
                if balance_line_ids is not None
                else []
            ),
        ),
    )
    import_error_statement = select(func.count(func.distinct(ErpImportJob.id))).where(
        ErpImportJob.status == "PREVIEW_READY", ErpImportJob.error_rows > 0
    )
    if balance_line_ids is not None:
        import_error_statement = import_error_statement.join(
            ErpImportJobRow, ErpImportJobRow.import_job_id == ErpImportJob.id
        ).where(ErpImportJobRow.operator_line_id.in_(balance_line_ids))
    import_error_count = await _count(session, import_error_statement)
    health_items = [
        ErpDashboardHealthItem(
            code="DRAFT_BALANCES",
            severity="WARNING" if draft_count else "INFO",
            title=f"{draft_count} 条草稿日结等待确认" if draft_count else "没有待确认的历史日结",
            description="确认前可继续编辑；锁定期间前需处理全部日结。",
            target_path="/erp/balances",
            count=draft_count,
        ),
        ErpDashboardHealthItem(
            code="NEGATIVE_CLOSING",
            severity="DANGER" if negative_count else "INFO",
            title=(
                f"{negative_count} 条当日期末结余为负"
                if negative_count
                else "当日没有负结余投放线"
            ),
            description="负结余需核对转 U、消耗及其他扣减的录入。",
            target_path="/erp/balances",
            count=negative_count,
        ),
        ErpDashboardHealthItem(
            code="MONTH_LOCKS",
            severity="INFO",
            title=f"本月已有 {locked_line_count} 条投放线锁定",
            description="锁定后该月日结、导入和重开均会被阻止。",
            target_path="/erp/balances",
            count=locked_line_count,
        ),
        ErpDashboardHealthItem(
            code="IMPORT_ERRORS",
            severity="WARNING" if import_error_count else "INFO",
            title=(
                f"{import_error_count} 个导入预览仍有错误"
                if import_error_count
                else "没有待处理的错误导入预览"
            ),
            description="请修正源文件后重新生成预览；错误预览不能提交。",
            target_path="/erp/imports",
            count=import_error_count,
        ),
    ]

    recent_statement = (
        select(ErpDailyBalance, ErpOperatorLine, ErpOperator)
        .join(ErpOperatorLine, ErpOperatorLine.id == ErpDailyBalance.operator_line_id)
        .join(ErpOperator, ErpOperator.id == ErpOperatorLine.operator_id)
    )
    if operator_filter is not None:
        recent_statement = recent_statement.where(operator_filter)
    rows = (
        await session.execute(
            recent_statement.order_by(
                ErpDailyBalance.business_date.desc(), ErpDailyBalance.updated_at.desc()
            )
            .limit(12)
        )
    ).all()
    recent_balances = [
        ErpDashboardRecentBalance(
            id=balance.id,
            business_date=balance.business_date,
            operator_name=operator.name,
            operator_line_name=line.name,
            asset=line.asset,
            opening_balance=balance.opening_balance,
            transfer_amount=balance.transfer_amount,
            spend_amount=balance.spend_amount,
            closing_balance=balance.closing_balance,
            status=balance.status,
        )
        for balance, line, operator in rows
    ]
    return ErpDashboardResponse(
        business_date=business_date,
        metric=metric,
        trend=trend,
        health_items=health_items,
        recent_balances=recent_balances,
    )
