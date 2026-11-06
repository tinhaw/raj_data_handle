"""Private, session-authenticated facade for the preserved ERP claim UI."""

from datetime import date
from io import BytesIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.routing import APIRoute
from openpyxl import Workbook
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from apps.api.dependencies import require_erp_permission
from packages.common.database import get_db_session
from packages.common.schemas import ApiSchema
from packages.domain.models import RedemptionClaimRecord, RedemptionClaimRun
from packages.domain.services import redemption_claim_service as claims
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.erp_access_service import (
    ERP_PERMISSION_REDEMPTION_EXPORT,
    ERP_PERMISSION_REDEMPTION_STATS_SYNC,
    ERP_PERMISSION_REDEMPTION_VIEW,
)
from packages.domain.services.redemption_claim_export import matrix_workbook


class ClaimRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                return await handler(request)
            except claims.ClaimError as exc:
                return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
            except (ProgrammingError, OperationalError):
                return JSONResponse(
                    status_code=503,
                    content={"detail": "领取统计暂不可用，请确认统计数据库迁移已经完成。"},
                )

        return guarded


router = APIRouter(
    prefix="/erp/remote-accounts/compatibility-redemption/claims",
    tags=["redemption-claims"],
    route_class=ClaimRoute,
)
view = require_erp_permission(ERP_PERMISSION_REDEMPTION_VIEW)
sync_permission = require_erp_permission(ERP_PERMISSION_REDEMPTION_STATS_SYNC)


async def checked(session, task_id, result):
    # A worker may publish between the group metadata and count queries.
    # Re-read the version before serving a mixed-generation response.
    _, current = await claims.projected_groups(session, task_id)
    claims.check_version(current, result["queryVersion"])
    return result


class ScheduleWrite(ApiSchema):
    enabled: bool
    interval_minutes: Literal[30, 60, 120, 180, 360, 720, 1440]
    row_version: int = Field(ge=0)


@router.get("/tasks/{task_id}/claim-statistics")
async def statistics(
    task_id: int,
    date_from: date | None = Query(None, alias="dateFrom"),
    date_to: date | None = Query(None, alias="dateTo"),
    source_id: str | None = Query(None, alias="sourceId"),
    auth: AuthContext = Depends(view),
    session: AsyncSession = Depends(get_db_session),
):
    await claims.authorize(session, auth.user.id)
    result = await claims.summary(session, task_id, date_from, date_to, source_id)
    return await checked(session, task_id, result)


@router.get("/tasks/{task_id}/claim-statistics/codes")
async def codes(
    task_id: int,
    claim_date: date = Query(alias="claimDate"),
    column_key: str = Query(alias="columnKey", max_length=64),
    query_version: str | None = Query(None, alias="queryVersion", max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=100),
    auth: AuthContext = Depends(view),
    session: AsyncSession = Depends(get_db_session),
):
    await claims.authorize(session, auth.user.id)
    result = await claims.code_details(
        session, task_id, claim_date, column_key, query_version, page, page_size
    )
    return await checked(session, task_id, result)


@router.get("/tasks/{task_id}/claim-records")
async def records(
    task_id: int,
    claim_date: date = Query(alias="claimDate"),
    group_id: str = Query(alias="groupId", max_length=100),
    code: str = Query(max_length=255),
    query_version: str | None = Query(None, alias="queryVersion", max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=100),
    auth: AuthContext = Depends(view),
    session: AsyncSession = Depends(get_db_session),
):
    await claims.authorize(session, auth.user.id)
    result = await claims.record_details(
        session, task_id, claim_date, group_id, code, query_version, page, page_size
    )
    return await checked(session, task_id, result)


@router.get("/tasks/{task_id}/claim-statistics/sync-settings")
async def settings(
    task_id: int,
    auth: AuthContext = Depends(view),
    session: AsyncSession = Depends(get_db_session),
):
    await claims.authorize(session, auth.user.id)
    await claims.task_projection(session, task_id)
    return await claims.get_schedule(session, task_id)


@router.put("/tasks/{task_id}/claim-statistics/sync-settings")
async def update_settings(
    task_id: int,
    payload: ScheduleWrite,
    auth: AuthContext = Depends(sync_permission),
    session: AsyncSession = Depends(get_db_session),
):
    return await claims.save_schedule(
        session,
        task_id,
        auth.user.id,
        payload.enabled,
        payload.interval_minutes,
        payload.row_version,
    )


@router.post("/tasks/{task_id}/claim-statistics/sync")
async def sync(
    task_id: int,
    auth: AuthContext = Depends(sync_permission),
    session: AsyncSession = Depends(get_db_session),
):
    return await claims.request_sync(session, task_id, auth.user.id)


@router.get("/claim-statistic-syncs/{sync_id}")
async def progress(
    sync_id: str,
    auth: AuthContext = Depends(view),
    session: AsyncSession = Depends(get_db_session),
):
    await claims.authorize(session, auth.user.id)
    run = await session.get(RedemptionClaimRun, sync_id)
    if not run:
        raise HTTPException(404, "同步任务不存在。")
    await claims.task_projection(session, run.task_id)
    return claims.run_response(run)


def _append(sheet, values):
    sheet.append(values)
    for cell in sheet[sheet.max_row]:
        if isinstance(cell.value, str):
            cell.data_type = "s"  # remote text must never become an Excel formula


@router.get("/tasks/{task_id}/claim-statistics/export")
async def export(
    task_id: int,
    date_from: date = Query(alias="dateFrom"),
    date_to: date = Query(alias="dateTo"),
    source_id: str | None = Query(None, alias="sourceId"),
    query_version: str | None = Query(None, alias="queryVersion", max_length=64),
    layout: Literal["details", "template"] = Query("details"),
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_REDEMPTION_EXPORT)),
    session: AsyncSession = Depends(get_db_session),
):
    await claims.authorize(session, auth.user.id)
    data = await claims.summary(session, task_id, date_from, date_to, source_id)
    if query_version and data["queryVersion"] != query_version:
        raise claims.ClaimError("统计数据已更新，请刷新后重新导出。")
    if layout == "template":
        content = matrix_workbook(data)
        await checked(session, task_id, data)
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="redemption-claims-{task_id}.xlsx"'
            },
        )
    _, groups = await claims.projected_groups(session, task_id)
    selected = [g for g in groups if not source_id or g.source_id == source_id]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "档位每日汇总"
    _append(sheet, ["任务编号", data["taskNumber"], "统计版本", data["queryVersion"]])
    _append(
        sheet,
        [
            "实际领取日",
            *[f"{c['sourceName']} · {c['tierName']}" for c in data["columns"]],
            "合计",
            "完整性",
        ],
    )
    for row in data["rows"]:
        values = [row["cells"][c["key"]] for c in data["columns"]]
        _append(
            sheet,
            [
                str(row["date"]),
                *[v["count"] for v in values],
                row["total"]["count"],
                "完整" if row["total"]["complete"] else "部分数据/待同步",
            ],
        )
    code_sheet = workbook.create_sheet("单码每日统计")
    _append(code_sheet, ["实际领取日", "盘口", "时区", "档位", "配置 ID", "号码", "次数", "完整性"])
    # Bound exports rather than silently truncating a workbook.
    estimated = (date_to - date_from).days + 1
    if estimated * sum(max(len(g.snapshot["codes"]), 1) for g in selected) > 100_000:
        raise claims.ClaimError("导出范围较大，请缩小日期范围或选择单个盘口。", 422)
    for row in data["rows"]:
        for c in data["columns"]:
            detail = await claims.code_details(
                session, task_id, row["date"], c["key"], data["queryVersion"], 1, 100_001
            )
            for item in detail["items"]:
                _append(
                    code_sheet,
                    [
                        str(row["date"]),
                        c["sourceName"],
                        c["timezone"],
                        c["tierName"],
                        item["configurationId"],
                        item["code"],
                        item["count"],
                        "完整" if item["complete"] else "不完整",
                    ],
                )
    record_sheet = workbook.create_sheet("领取明细")
    _append(
        record_sheet, ["盘口", "时区", "组描述", "领取 ID", "兑换码", "UID", "领取时间", "金额"]
    )
    by_id = {g.id: g for g in selected}
    items = list(
        await session.scalars(
            select(RedemptionClaimRecord)
            .where(
                RedemptionClaimRecord.group_id.in_(by_id),
                RedemptionClaimRecord.claim_date.between(date_from, date_to),
            )
            .order_by(RedemptionClaimRecord.received_at)
            .limit(100_001)
        )
    )
    if len(items) > 100_000:
        raise claims.ClaimError("领取明细超过导出上限，请缩小范围。", 422)
    for item in items:
        g = by_id[item.group_id]
        _append(
            record_sheet,
            [
                g.snapshot["sourceName"],
                g.snapshot["timezone"],
                g.snapshot["description"],
                item.remote_id,
                item.code,
                item.uid,
                item.receive_time,
                str(item.amount),
            ],
        )
    # READ COMMITTED queries may see a worker publication between sheets.
    session.expire_all()
    _, final_groups = await claims.projected_groups(session, task_id)
    claims.check_version(final_groups, data["queryVersion"])
    for current in workbook:
        current.freeze_panes = "B3" if current == sheet else "A2"
        current.auto_filter.ref = current.dimensions
    output = BytesIO()
    workbook.save(output)
    return Response(
        output.getvalue(),
        media_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        headers={"Content-Disposition": f'attachment; filename="redemption-claims-{task_id}.xlsx"'},
    )
