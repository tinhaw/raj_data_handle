from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Any

from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import OrderReconciliationResult, ReconciliationBatch

EXPORT_COLUMNS = [
    ("比对结果", "resultStatus"),
    ("支付状态分类", "paymentStatusGroup"),
    ("支付平台状态", "paymentStatusRaw"),
    ("商户订单号", "merchantOrderNo"),
    ("支付平台订单号", "platformOrderNo"),
    ("金额", "amount"),
    ("币种", "currency"),
    ("支付时间", "paymentTime"),
    ("支付平台", "platformKey"),
    ("来源工作表", "sourceSheet"),
    ("来源行号", "sourceRowNumbers"),
    ("重复行数", "duplicateCount"),
    ("远端订单号", "remoteOrderNum"),
    ("远端平台订单号", "remoteOutTradeNo"),
    ("远端状态", "remoteStatus"),
    ("远端渠道", "remoteChannel"),
]


def _safe_export_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def result_record(row: OrderReconciliationResult) -> dict[str, Any]:
    payload = row.payload_json or {}
    remote = payload.get("remoteOrder") if isinstance(payload.get("remoteOrder"), dict) else {}
    source_rows = payload.get("sourceRowNumbers")
    return {
        "resultStatus": row.result_status,
        "paymentStatusGroup": row.payment_status_group,
        "paymentStatusRaw": row.payment_status_raw,
        "merchantOrderNo": row.merchant_order_no,
        "platformOrderNo": row.platform_order_no,
        "amount": payload.get("amount"),
        "currency": payload.get("currency"),
        "paymentTime": payload.get("paymentTime"),
        "platformKey": payload.get("platformKey"),
        "sourceSheet": payload.get("sourceSheet"),
        "sourceRowNumbers": ",".join(str(item) for item in source_rows)
        if isinstance(source_rows, list)
        else "",
        "duplicateCount": payload.get("duplicateCount"),
        "remoteOrderNum": remote.get("order_num"),
        "remoteOutTradeNo": remote.get("out_trade_no"),
        "remoteStatus": remote.get("status"),
        "remoteChannel": remote.get("_remote_channel_label"),
    }


async def list_results(
    session: AsyncSession,
    *,
    batch_id: str,
    result_status: str | None = None,
    payment_status_group: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[OrderReconciliationResult], int]:
    filters = [OrderReconciliationResult.batch_id == batch_id]
    if result_status:
        filters.append(OrderReconciliationResult.result_status == result_status)
    if payment_status_group:
        filters.append(OrderReconciliationResult.payment_status_group == payment_status_group)
    statement = (
        select(OrderReconciliationResult)
        .where(*filters)
        .order_by(OrderReconciliationResult.created_at, OrderReconciliationResult.id)
        .limit(limit)
        .offset(offset)
    )
    count_statement = select(func.count()).select_from(OrderReconciliationResult).where(*filters)
    return (
        list(await session.scalars(statement)),
        int(await session.scalar(count_statement) or 0),
    )


async def all_results(
    session: AsyncSession,
    batch_id: str,
) -> list[OrderReconciliationResult]:
    return list(
        await session.scalars(
            select(OrderReconciliationResult)
            .where(OrderReconciliationResult.batch_id == batch_id)
            .order_by(OrderReconciliationResult.created_at, OrderReconciliationResult.id)
        )
    )


def export_csv(rows: list[OrderReconciliationResult]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[label for label, _ in EXPORT_COLUMNS])
    writer.writeheader()
    for row in rows:
        record = result_record(row)
        writer.writerow(
            {label: _safe_export_value(record.get(key)) for label, key in EXPORT_COLUMNS}
        )
    return ("\ufeff" + output.getvalue()).encode()


def _append_result_sheet(
    workbook: Workbook,
    title: str,
    rows: list[OrderReconciliationResult],
) -> None:
    sheet = workbook.create_sheet(title)
    sheet.append([label for label, _ in EXPORT_COLUMNS])
    for row in rows:
        record = result_record(row)
        sheet.append([_safe_export_value(record.get(key)) for _, key in EXPORT_COLUMNS])
    for column in ("D", "E", "M", "N"):
        for cell in sheet[column]:
            cell.number_format = "@"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions


def export_excel(
    batch: ReconciliationBatch,
    rows: list[OrderReconciliationResult],
) -> bytes:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "汇总"
    summary.append(["项目", "值"])
    summary.append(["批次 ID", batch.id])
    summary.append(["盘口", batch.source_display_name])
    summary.append(["执行版本", batch.run_version])
    summary.append(["状态", batch.status])
    counts = Counter(row.result_status for row in rows)
    for key, count in sorted(counts.items()):
        summary.append([key, count])
    summary.append(
        [
            "confirmed_missing_success",
            sum(
                1
                for row in rows
                if row.result_status == "confirmed_missing"
                and row.payment_status_group == "success"
            ),
        ]
    )
    groups = [
        ("确认遗漏", {"confirmed_missing"}),
        ("远端状态异常", {"remote_status_not_success"}),
        ("待复查", {"recheck_inconclusive", "candidate_missing"}),
        (
            "重复数据冲突",
            {
                "duplicate_payment_conflict",
                "order_reference_conflict",
                "invalid_payment_row",
            },
        ),
        ("全部明细", {row.result_status for row in rows}),
    ]
    for title, statuses in groups:
        _append_result_sheet(
            workbook,
            title,
            [row for row in rows if row.result_status in statuses],
        )
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()
