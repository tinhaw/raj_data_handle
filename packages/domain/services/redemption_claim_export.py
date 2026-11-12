"""Export the displayed columns per market; the supplied template provides styles only."""

import re
from copy import copy
from datetime import date
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

TEMPLATE = Path(__file__).resolve().parents[1] / "templates/redemption_claim_statistics.xlsx"


def copy_style(cell, sample):
    for attribute in ("font", "fill", "border", "alignment", "protection"):
        setattr(cell, attribute, copy(getattr(sample, attribute)))
    cell.number_format = sample.number_format


def aggregate(cells):
    known = [c["count"] for c in cells if c["count"] is not None]
    return {
        "count": sum(known) if known else None,
        "complete": all(c["complete"] for c in cells),
    }


def sheet_title(name, existing):
    title = re.sub(r"[\\/*?:\[\]\x00-\x1f]", "_", name).strip("'") or "盘口"
    title = title[:31]
    used = {value.casefold() for value in existing}
    candidate, suffix = title, 1
    while candidate.casefold() in used:
        suffix += 1
        ending = f" ({suffix})"
        candidate = title[: 31 - len(ending)] + ending
    return candidate


def header(column):
    lines = [
        column["tierName"],
        f"奖励 {column['currency']} {column['rewardMin']}–{column['rewardMax']}",
    ]
    if column["labels"]:
        lines.append("标签 " + "、".join(map(str, column["labels"])))
    return "\n".join(lines)


def write_count(cell, value):
    # Keep known zeroes numeric and unknown quantities blank, never invent a zero.
    cell.value = value["count"]
    cell.number_format = "0"
    notes = []
    if value["count"] is None:
        notes.append(
            {"future": "未到日期", "notApplicable": "无适用配置"}.get(
                value.get("state"), "待同步，尚无领取数量"
            )
        )
    elif not value["complete"]:
        notes.append("部分数据，当前数量不代表完整领取数量")
    if value.get("configurationIds"):
        notes.append("远端配置 ID：" + "、".join(map(str, value["configurationIds"])))
    if value.get("error"):
        notes.append(value["error"])
    if value.get("asOf"):
        notes.append("数据截至：" + str(value["asOf"]))
    if notes:
        cell.comment = Comment("\n".join(notes), "RAJ CONSOLE")


def matrix_workbook(data: dict) -> bytes:
    template = load_workbook(TEMPLATE)
    reference = template.worksheets[0]
    book = Workbook()
    book.remove(book.active)
    markets: dict[str, list] = {}
    # Match the page's grouping and insertion order. Names are not identities:
    # same-name tiers with different labels/rewards must remain separate columns.
    for column in data["columns"]:
        markets.setdefault(column["sourceId"], []).append(column)
    for columns in markets.values():
        market = columns[0]["sourceName"]
        sheet = book.create_sheet(sheet_title(market, book.sheetnames))
        headers = ["日期", *[header(column) for column in columns], "当日合计"]

        def write(row, col, value=None, sheet=sheet):
            cell = sheet.cell(row, col)
            copy_style(cell, reference.cell(min(row, 3), 1 if col == 1 else 2))
            cell.value = value
            if isinstance(value, str):
                cell.data_type = "s"  # Never interpret remote names as Excel formulas.
            return cell

        for col, title in enumerate(headers, 1):
            write(1, col, f"{market} · {columns[0]['timezone']}" if col == 1 else None)
            cell = write(2, col, title)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            sheet.column_dimensions[get_column_letter(col)].width = (
                reference.column_dimensions["A"].width if col == 1 else 24
            )
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
        for number, row in enumerate(data["rows"], 3):
            day = row["date"]
            write(number, 1, day if isinstance(day, date) else date.fromisoformat(day))
            sheet.cell(number, 1).number_format = "yyyy-mm-dd"
            values = [row["cells"][column["key"]] for column in columns]
            for col, value in enumerate([*values, aggregate(values)], 2):
                write_count(write(number, col), value)
        bottom = len(data["rows"]) + 3
        write(bottom, 1, "区间合计")
        totals = [data["totals"][column["key"]] for column in columns]
        for col, value in enumerate([*totals, aggregate(totals)], 2):
            write_count(write(bottom, col), value)
        sheet.row_dimensions[1].height = reference.row_dimensions[1].height
        sheet.row_dimensions[2].height = 72
        sheet.freeze_panes = "B3"
        sheet.print_title_rows = "1:2"
        sheet.print_options.horizontalCentered = True
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.print_area = f"A1:{get_column_letter(len(headers))}{bottom}"
    output = BytesIO()
    book.save(output)
    return output.getvalue()
