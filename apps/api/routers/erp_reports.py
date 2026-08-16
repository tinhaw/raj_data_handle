"""Read-only local ERP daily and monthly report endpoints."""

from __future__ import annotations

from datetime import date
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context
from packages.common.database import get_db_session
from packages.domain.schemas.erp_report import ErpReportResponse
from packages.domain.services.auth_service import AuthContext, write_audit
from packages.domain.services.erp_report_service import (
    ErpReportError,
    build_erp_daily_report,
    build_erp_monthly_report,
)

router = APIRouter(prefix="/erp/reports", tags=["erp-reports"])


def _workbook_bytes(report: ErpReportResponse) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "ERP 报表"
    sheet.append(
        [
            "期间",
            "币种",
            "期初结余",
            "转 U",
            "欺诈扣转账",
            "有效转 U",
            "消耗",
            "汇损",
            "服务费",
            "回流",
            "退款",
            "其他扣减",
            "欺诈扣结余",
            "期末结余",
            "记录数",
            "提示",
        ]
    )
    for row in report.rows:
        sheet.append(
            [
                row.period,
                row.asset,
                row.opening_balance,
                row.transfer_amount,
                row.fraud_from_transfer,
                row.effective_transfer_amount,
                row.spend_amount,
                row.exchange_loss_amount,
                row.service_fee_amount,
                row.reflux_amount,
                row.refund_amount,
                row.other_deduction_amount,
                row.fraud_from_balance,
                row.closing_balance,
                row.record_count,
                "；".join(row.warnings),
            ]
        )
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = min(
            max(len(str(cell.value or "")) for cell in column) + 2,
            30,
        )
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _report_error(exc: ErpReportError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/daily", response_model=ErpReportResponse)
async def get_daily_report(
    date_from: date,
    date_to: date,
    operator_ids: list[str] | None = Query(default=None),
    operator_line_ids: list[str] | None = Query(default=None),
    asset: str | None = None,
    include_draft: bool = True,
    nominal_u: bool = False,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> ErpReportResponse:
    try:
        return await build_erp_daily_report(
            session,
            date_from=date_from,
            date_to=date_to,
            operator_ids=operator_ids,
            operator_line_ids=operator_line_ids,
            asset=asset,
            include_draft=include_draft,
            nominal_u=nominal_u,
        )
    except ErpReportError as exc:
        raise _report_error(exc) from exc


@router.get("/monthly", response_model=ErpReportResponse)
async def get_monthly_report(
    month_from: str,
    month_to: str,
    operator_ids: list[str] | None = Query(default=None),
    operator_line_ids: list[str] | None = Query(default=None),
    asset: str | None = None,
    include_draft: bool = True,
    nominal_u: bool = False,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> ErpReportResponse:
    try:
        return await build_erp_monthly_report(
            session,
            month_from=month_from,
            month_to=month_to,
            operator_ids=operator_ids,
            operator_line_ids=operator_line_ids,
            asset=asset,
            include_draft=include_draft,
            nominal_u=nominal_u,
        )
    except ErpReportError as exc:
        raise _report_error(exc) from exc


@router.get("/daily/export")
async def export_daily_report(
    date_from: date,
    date_to: date,
    operator_ids: list[str] | None = Query(default=None),
    operator_line_ids: list[str] | None = Query(default=None),
    asset: str | None = None,
    include_draft: bool = True,
    nominal_u: bool = False,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    try:
        report = await build_erp_daily_report(
            session,
            date_from=date_from,
            date_to=date_to,
            operator_ids=operator_ids,
            operator_line_ids=operator_line_ids,
            asset=asset,
            include_draft=include_draft,
            nominal_u=nominal_u,
        )
    except ErpReportError as exc:
        raise _report_error(exc) from exc
    await write_audit(
        session,
        action="erp_report.daily_export",
        actor_user_id=auth.user.id,
        target_type="erp_report",
        target_id="daily",
        metadata={
            "rows": len(report.rows),
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        },
    )
    await session.commit()
    return Response(
        content=_workbook_bytes(report),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="erp-daily-report-{date_from}_to_{date_to}.xlsx"'
            )
        },
    )


@router.get("/monthly/export")
async def export_monthly_report(
    month_from: str,
    month_to: str,
    operator_ids: list[str] | None = Query(default=None),
    operator_line_ids: list[str] | None = Query(default=None),
    asset: str | None = None,
    include_draft: bool = True,
    nominal_u: bool = False,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    try:
        report = await build_erp_monthly_report(
            session,
            month_from=month_from,
            month_to=month_to,
            operator_ids=operator_ids,
            operator_line_ids=operator_line_ids,
            asset=asset,
            include_draft=include_draft,
            nominal_u=nominal_u,
        )
    except ErpReportError as exc:
        raise _report_error(exc) from exc
    await write_audit(
        session,
        action="erp_report.monthly_export",
        actor_user_id=auth.user.id,
        target_type="erp_report",
        target_id="monthly",
        metadata={"rows": len(report.rows), "month_from": month_from, "month_to": month_to},
    )
    await session.commit()
    return Response(
        content=_workbook_bytes(report),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="erp-monthly-report-{month_from}_to_{month_to}.xlsx"'
            )
        },
    )
