"""Export the displayed claim matrix using the supplied market-block template."""

from collections import OrderedDict
from copy import copy
from datetime import date
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

TEMPLATE = Path(__file__).resolve().parents[1] / "templates/redemption_claim_statistics.xlsx"
SHEETS = {
    "PREVIOUS_DAY_DEPOSIT": "每日存款兑换码",
    "SEVEN_DAY_DEPOSIT": "近7天兑换码",
    "AGENT": "代理兑换码",
}
MARKETS = {"rajwin": "win", "rajluck": "luck", "rajspin": "spin", "rajrace": "ace"}


def copy_style(cell, sample):
    for attribute in ("font", "fill", "border", "alignment", "protection"):
        setattr(cell, attribute, copy(getattr(sample, attribute)))
    cell.number_format = sample.number_format


def aggregate(cells):
    known = [c["count"] for c in cells if c["count"] is not None]
    return {
        "count": sum(known) if known else None,
        "complete": all(c["complete"] for c in cells),
        "state": cells[0].get("state") if len({c.get("state") for c in cells}) == 1 else "pending",
    }


def display(cell):
    count = cell["count"]
    if count is not None:
        return count if cell["complete"] else f"{count}（部分）"
    return {"future": "未到日期", "notApplicable": "无适用配置"}.get(cell.get("state"), "待同步")


def matrix_workbook(data: dict) -> bytes:
    template = load_workbook(TEMPLATE)
    book = Workbook()
    book.remove(book.active)
    kinds: dict[str, list] = OrderedDict()
    for column in data["columns"]:
        kinds.setdefault(column.get("redemptionType", "PREVIOUS_DAY_DEPOSIT"), []).append(column)
    for kind, columns in kinds.items():
        name = SHEETS.get(kind, "兑换码领取统计")
        reference = template[name] if name in template.sheetnames else template.worksheets[0]
        sheet = book.create_sheet(name)
        markets: dict[str, list] = OrderedDict()
        for column in columns:
            markets.setdefault(column["sourceId"], []).append(column)
        cursor = 1
        blocks = [
            (MARKETS.get(source, cols[0]["sourceName"]), cols) for source, cols in markets.items()
        ]
        if len(markets) > 1:
            blocks.append(("全部盘口", columns))
        for index, (market, cols) in enumerate(blocks):
            overall = len(markets) > 1 and index == len(blocks) - 1
            header = (
                ["日期", "当日合计"]
                if overall
                else ["日期", *[c["tierName"] for c in cols], "当日合计"]
            )
            style_start = (index % 4) * 7 + 1

            def write(
                row,
                offset,
                value,
                sheet=sheet,
                cursor=cursor,
                reference=reference,
                style_start=style_start,
            ):
                cell = sheet.cell(row, cursor + offset)
                sample = reference.cell(min(row, 3), style_start + min(offset, 5))
                copy_style(cell, sample)
                cell.value = value
                if isinstance(value, str):
                    cell.data_type = "s"  # Never interpret remote names as Excel formulas.
                return cell

            for offset in range(len(header)):
                write(1, offset, market if offset == 0 else None)
                cell = write(2, offset, header[offset])
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                sheet.column_dimensions[get_column_letter(cursor + offset)].width = (
                    reference.column_dimensions[get_column_letter(style_start)].width
                    if offset == 0
                    else 20
                )
                if offset > 0 and not overall and offset <= len(cols):
                    column = cols[offset - 1]
                    cell.comment = Comment(
                        f"奖励 {column['currency']} {column['rewardMin']}–{column['rewardMax']}"
                        f"\n标签：{'、'.join(map(str, column['labels']))}"
                        f"\n时区：{column['timezone']}",
                        "RAJ CONSOLE",
                    )
            sheet.merge_cells(
                start_row=1, start_column=cursor, end_row=1, end_column=cursor + len(header) - 1
            )
            for number, row in enumerate(data["rows"], 3):
                day = row["date"]
                write(number, 0, day if isinstance(day, date) else date.fromisoformat(day))
                sheet.cell(number, cursor).number_format = "yyyy-mm-dd"
                cells = [row["cells"][c["key"]] for c in cols]
                values = [aggregate(cells)] if overall else [*cells, aggregate(cells)]
                for offset, value in enumerate(values, 1):
                    cell = write(number, offset, display(value))
                    notes = []
                    if value.get("configurationIds"):
                        notes.append("远端配置 ID：" + "、".join(value["configurationIds"]))
                    if value.get("error"):
                        notes.append(value["error"])
                    if value.get("asOf"):
                        notes.append("数据截至：" + str(value["asOf"]))
                    if notes:
                        cell.comment = Comment("\n".join(notes), "RAJ CONSOLE")
            bottom = len(data["rows"]) + 3
            write(bottom, 0, "区间合计")
            totals = [data["totals"][c["key"]] for c in cols]
            values = [aggregate(totals)] if overall else [*totals, aggregate(totals)]
            for offset, value in enumerate(values, 1):
                write(bottom, offset, display(value))
            cursor += len(header) + 1
            sheet.column_dimensions[get_column_letter(cursor - 1)].width = 4
        sheet.row_dimensions[1].height = reference.row_dimensions[1].height
        sheet.row_dimensions[2].height = 42
        sheet.freeze_panes = "B3"
        note_row = len(data["rows"]) + 5
        note = sheet.cell(note_row, 1)
        copy_style(note, reference.cell(3, 1))
        note.value = (
            f"任务 {data['taskNumber']} · {data['dateFrom']} 至 {data['dateTo']} · 单位：次。"
            "部分／待同步不代表完整数量；远端 ID 和数据状态见单元格批注。"
        )
        note.data_type = "s"
        sheet.merge_cells(
            start_row=note_row, start_column=1, end_row=note_row, end_column=cursor - 2
        )
        sheet.cell(note_row, 1).alignment = Alignment(wrap_text=True, vertical="center")
        sheet.row_dimensions[note_row].height = 32
    output = BytesIO()
    book.save(output)
    return output.getvalue()
