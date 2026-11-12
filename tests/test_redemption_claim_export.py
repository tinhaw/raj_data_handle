from copy import copy
from datetime import date
from io import BytesIO

import pytest
from openpyxl import load_workbook

from packages.domain.services.redemption_claim_export import TEMPLATE, matrix_workbook


def sample():
    return {
        "taskNumber": "202611010001",
        "dateFrom": "2026-11-01",
        "dateTo": "2026-11-02",
        "columns": [
            {
                "key": source,
                "sourceId": source,
                "sourceName": name,
                "tierName": "充值100",
                "currency": "INR",
                "rewardMin": "5",
                "rewardMax": "11",
                "labels": [901],
                "timezone": "Asia/Kolkata",
                "redemptionType": "AGENT",
            }
            for source, name in [("rajwin", "RajWin"), ("rajluck", "RajLuck")]
        ],
        "rows": [
            {
                "date": date(2026, 11, 1),
                "cells": {
                    "rajwin": {"count": 0, "complete": True, "configurationIds": ["42"]},
                    "rajluck": {"count": 3, "complete": False, "error": "更新失败"},
                },
            },
            {
                "date": "2026-11-02",
                "cells": {
                    "rajwin": {"count": None, "complete": False, "state": "pending"},
                    "rajluck": {"count": 4, "complete": True},
                },
            },
        ],
        "totals": {
            "rajwin": {"count": 0, "complete": False},
            "rajluck": {"count": 7, "complete": False},
        },
    }


def test_each_market_has_its_own_sheet_and_quantity_cells_are_numeric_or_blank():
    workbook = load_workbook(BytesIO(matrix_workbook(sample())))
    assert workbook.sheetnames == ["RajWin", "RajLuck"]
    win, luck = workbook.worksheets
    assert win["A1"].value == "RajWin · Asia/Kolkata"
    assert win["A3"].value.date() == date(2026, 11, 1)
    assert win["A4"].value.date() == date(2026, 11, 2)
    assert win["B3"].value == 0 and win["B3"].data_type == "n"
    assert win["B4"].value is None and win["C4"].value is None
    assert win["B5"].value == win["C5"].value == 0
    assert "待同步" in win["B4"].comment.text
    assert "42" in win["B3"].comment.text
    assert luck["B3"].value == luck["C3"].value == 3
    assert luck["B5"].value == luck["C5"].value == 7
    assert "部分数据" in luck["B3"].comment.text
    assert "更新失败" in luck["B3"].comment.text
    assert "部分数据" in luck["C5"].comment.text
    for sheet in workbook:
        assert sheet.max_row == 5 and sheet.max_column == 3
        assert sheet["A5"].value == "区间合计"
        for row in sheet.iter_rows(min_row=3, min_col=2):
            assert all(
                c.value is None or (type(c.value) is int and c.data_type == "n") for c in row
            )


def test_all_page_columns_survive_in_order_including_duplicate_names_and_mixed_types():
    data = sample()
    first, second = data["columns"]
    columns = []
    # Interleave markets and exceed the template's five tier columns.
    for index in range(8):
        columns.append({
            **first, "key": f"win-{index}", "labels": [900 + index],
            "redemptionType": ["AGENT", "PREVIOUS_DAY_DEPOSIT", "SEVEN_DAY_DEPOSIT"][index % 3],
        })
        if index < 2:
            columns.append({**second, "key": f"luck-{index}", "tierName": f"档位{index}"})
    data["columns"] = columns
    for number, row in enumerate(data["rows"], 1):
        row["cells"] = {
            c["key"]: {"count": number * (index + 1), "complete": True}
            for index, c in enumerate(columns)
        }
    data["totals"] = {
        c["key"]: {"count": 3 * (index + 1), "complete": True}
        for index, c in enumerate(columns)
    }
    workbook = load_workbook(BytesIO(matrix_workbook(data)))
    assert workbook.sheetnames == ["RajWin", "RajLuck"]
    win, luck = workbook.worksheets
    assert win.max_column == 10 and luck.max_column == 4
    assert [win.cell(2, n).value for n in range(2, 10)] == [
        f"充值100\n奖励 INR 5–11\n标签 {900 + i}" for i in range(8)
    ]
    assert [luck.cell(2, n).value.splitlines()[0] for n in (2, 3)] == ["档位0", "档位1"]
    for sheet, source in [(win, "rajwin"), (luck, "rajluck")]:
        displayed = [c for c in columns if c["sourceId"] == source]
        for number, row in enumerate(data["rows"], 3):
            expected = [row["cells"][c["key"]]["count"] for c in displayed]
            assert [c.value for c in sheet[number]][1:] == [*expected, sum(expected)]
        expected = [data["totals"][c["key"]]["count"] for c in displayed]
        assert [c.value for c in sheet[5]][1:] == [*expected, sum(expected)]


def test_style_reference_does_not_supply_example_columns_or_data_and_is_not_modified():
    original = TEMPLATE.read_bytes()
    data = sample()
    data["columns"] = data["columns"][:1]
    sheet = load_workbook(BytesIO(matrix_workbook(data))).active
    template = load_workbook(TEMPLATE).worksheets[0]
    assert sheet.title == "RajWin" and sheet.max_column == 3
    assert sheet["A1"].fill.fgColor.rgb == "FF00B0F0"
    assert sheet["A2"].fill.fgColor.rgb == "FFFFFF00"
    for coordinate in ("A1", "A2", "B2", "A3", "B3"):
        for attribute in ("font", "fill", "border"):
            assert copy(getattr(sheet[coordinate], attribute)) == copy(
                getattr(template[coordinate], attribute)
            )
    assert set(map(str, sheet.merged_cells.ranges)) == {"A1:C1"}
    assert sheet.freeze_panes == "B3"
    assert sheet["B2"].alignment.wrap_text
    assert "deposit200" not in [c.value for row in sheet for c in row]
    assert 514 not in [c.value for row in sheet for c in row]
    assert TEMPLATE.read_bytes() == original


@pytest.mark.parametrize("state", ["pending", "future", "notApplicable"])
def test_unknown_quantities_remain_blank_instead_of_zero_or_status_text(state):
    data = sample()
    for row in data["rows"]:
        row["cells"]["rajwin"] = {"count": None, "complete": state != "pending", "state": state}
    data["totals"]["rajwin"] = {"count": None, "complete": False, "state": state}
    sheet = load_workbook(BytesIO(matrix_workbook(data))).active
    assert all(c.value is None for row in sheet.iter_rows(min_row=3, min_col=2) for c in row)
    assert all(c.comment for row in sheet.iter_rows(min_row=3, min_col=2) for c in row)


def test_remote_names_are_plain_text_and_sheet_names_are_valid_and_unique():
    data = sample()
    data["columns"][0]["tierName"] = '=HYPERLINK("https://example.test")'
    for c in data["columns"]:
        c["sourceName"] = "'" + "市场/[]:*?\\" + "长" * 40 + "'"
    workbook = load_workbook(BytesIO(matrix_workbook(data)))
    assert len(set(workbook.sheetnames)) == 2
    for name in workbook.sheetnames:
        assert len(name) <= 31 and not any(char in name for char in "/[]:*?\\")
    assert workbook.active["B2"].value.startswith(data["columns"][0]["tierName"])
    assert workbook.active["B2"].data_type == "s"
