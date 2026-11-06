from copy import copy
from datetime import date
from io import BytesIO

import pytest
from openpyxl import load_workbook

from packages.domain.services.redemption_claim_export import TEMPLATE, matrix_workbook


def sample(kind="PREVIOUS_DAY_DEPOSIT"):
    columns = [
        {
            "key": source,
            "sourceId": source,
            "sourceName": source,
            "tierName": "充值100",
            "currency": "INR",
            "rewardMin": "5",
            "rewardMax": "11",
            "labels": [901],
            "timezone": "Asia/Kolkata",
            "redemptionType": kind,
        }
        for source in ["rajwin", "rajluck"]
    ]
    return {
        "taskNumber": "202611010001",
        "dateFrom": "2026-11-01",
        "dateTo": "2026-11-02",
        "columns": columns,
        "rows": [
            {
                "date": date(2026, 11, 1),
                "cells": {
                    "rajwin": {"count": 0, "complete": True, "configurationIds": ["42"]},
                    "rajluck": {"count": 3, "complete": False, "error": "更新失败"},
                },
            },
            {
                "date": date(2026, 11, 2),
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


@pytest.mark.parametrize(
    "kind,title",
    [
        ("PREVIOUS_DAY_DEPOSIT", "每日存款兑换码"),
        ("SEVEN_DAY_DEPOSIT", "近7天兑换码"),
        ("AGENT", "代理兑换码"),
    ],
)
def test_template_market_blocks_current_values_and_statuses(kind, title):
    workbook = load_workbook(BytesIO(matrix_workbook(sample(kind))))
    assert workbook.sheetnames == [title]
    sheet = workbook.active
    assert [sheet.cell(1, col).value for col in [1, 5, 9]] == ["win", "luck", "全部盘口"]
    assert sheet["A3"].value.date() == date(2026, 11, 1)
    assert sheet["B3"].value == 0 and sheet["B3"].data_type == "n"
    assert sheet["F3"].value == "3（部分）"
    assert sheet["B4"].value == "待同步"
    assert sheet["J3"].value == "3（部分）"
    assert sheet["J5"].value == "7（部分）"
    assert "42" in sheet["B3"].comment.text
    assert copy(sheet["B3"].fill) == copy(load_workbook(TEMPLATE).active["B3"].fill)
    assert set(map(str, sheet.merged_cells.ranges)) >= {"A1:C1", "E1:G1", "I1:J1"}
    assert sheet.freeze_panes == "B3"


def test_single_market_filter_has_no_other_markets_or_template_example_data():
    data = sample()
    data["columns"] = data["columns"][:1]
    sheet = load_workbook(BytesIO(matrix_workbook(data))).active
    assert sheet["A1"].value == "win"
    assert sheet.max_column == 3
    assert sheet["B5"].value == "0（部分）"
    assert "luck" not in [c.value for row in sheet for c in row]
    assert 514 not in [c.value for row in sheet for c in row]


def test_remote_tier_names_are_plain_text_and_arbitrary_tiers_are_not_dropped():
    data = sample()
    data["columns"][0]["tierName"] = '=HYPERLINK("https://example.test")'
    sheet = load_workbook(BytesIO(matrix_workbook(data))).active
    assert sheet["B2"].value == data["columns"][0]["tierName"]
    assert sheet["B2"].data_type == "s"
