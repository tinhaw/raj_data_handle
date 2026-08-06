from __future__ import annotations

from datetime import datetime
from io import BytesIO

import pytest
from openpyxl import Workbook

from packages.domain.services import scoring_reviewed_cases_import_service as service
from packages.domain.services.scoring_reviewed_cases_import_service import (
    SCORING_REVIEWED_CASES_EXPORT_COLUMNS,
    ScoringReviewedCase,
    ScoringReviewedCasesImportError,
    parse_scoring_reviewed_cases_export,
)


def _workbook_bytes(
    rows: list[dict[str, object]],
    *,
    headers: tuple[str, ...] = SCORING_REVIEWED_CASES_EXPORT_COLUMNS,
) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(headers)
    for row in rows:
        worksheet.append([row.get(header) for header in headers])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "案件号": "withdraw-100",
        "UID": "user-must-not-copy",
        "提现金额": "9999.99",
        "渠道": "channel-must-not-copy",
        "全局硬性条件": "已通过",
        "场景审核": "未命中",
        "评分审核": -35,
        "决断阶段": "评分审核",
        "最终审核建议": "出款",
        "操作结果": "出款成功",
        "摘要": "评分审核摘要",
        "当前状态": "已提交代付 (1)",
        "审核完成时间": datetime(2026, 7, 31, 18, 37, 27),
        "审核耗时": "10秒",
        "队列中耗时": "9秒",
        "进入队列时间": "2026-07-31 18:37:17",
        "退出队列时间": "2026-07-31 18:37:27",
        "提现时间": "2026-07-31 18:37:11",
    }
    row.update(overrides)
    return row


def test_parser_returns_only_scoring_fields_keyed_by_withdraw_order_id() -> None:
    result = parse_scoring_reviewed_cases_export(_workbook_bytes([_row()]))

    assert result.source_row_count == 1
    assert result.cases == [
        ScoringReviewedCase(
            withdraw_order_id="withdraw-100",
            global_hard_condition="已通过",
            scenario_review="未命中",
            score_review="-35",
            decision_stage="评分审核",
            final_review_suggestion="出款",
            operation_result="出款成功",
            review_summary="评分审核摘要",
            current_status="已提交代付 (1)",
            review_completed_at="2026-07-31 18:37:27",
            review_duration="10秒",
            queue_duration="9秒",
            entered_queue_at="2026-07-31 18:37:17",
            exited_queue_at="2026-07-31 18:37:27",
        )
    ]
    case = result.cases[0]
    for source_owned_field in ("uid", "amount", "channel", "withdraw_time"):
        assert not hasattr(case, source_owned_field)


def test_parser_rejects_missing_or_duplicate_required_headers() -> None:
    missing_headers = tuple(
        header for header in SCORING_REVIEWED_CASES_EXPORT_COLUMNS if header != "案件号"
    )
    with pytest.raises(ScoringReviewedCasesImportError, match="表头"):
        parse_scoring_reviewed_cases_export(_workbook_bytes([_row()], headers=missing_headers))

    duplicate_headers = (*SCORING_REVIEWED_CASES_EXPORT_COLUMNS, "案件号")
    with pytest.raises(ScoringReviewedCasesImportError, match="表头"):
        parse_scoring_reviewed_cases_export(_workbook_bytes([_row()], headers=duplicate_headers))


def test_parser_rejects_missing_or_duplicate_case_ids() -> None:
    with pytest.raises(ScoringReviewedCasesImportError, match="缺少案件号"):
        parse_scoring_reviewed_cases_export(_workbook_bytes([_row(案件号="")]))

    with pytest.raises(ScoringReviewedCasesImportError, match="重复案件号"):
        parse_scoring_reviewed_cases_export(
            _workbook_bytes([_row(案件号="withdraw-100"), _row(案件号="withdraw-100")])
        )


@pytest.mark.parametrize(
    "content",
    [b"", "案件号,评分审核\nwithdraw-100,-35\n".encode(), b"PKnot-an-xlsx"],
)
def test_parser_rejects_non_xlsx_content(content: bytes) -> None:
    with pytest.raises(ScoringReviewedCasesImportError, match="文件"):
        parse_scoring_reviewed_cases_export(content)


def test_parser_rejects_oversized_content_before_opening_workbook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _workbook_bytes([_row()])
    monkeypatch.setattr(service, "MAX_SCORING_REVIEWED_CASES_EXPORT_BYTES", len(content) - 1)

    with pytest.raises(ScoringReviewedCasesImportError, match="超过大小限制"):
        parse_scoring_reviewed_cases_export(content)
