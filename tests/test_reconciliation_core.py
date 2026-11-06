from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from openpyxl import Workbook

from packages.common.totp import generate_totp
from packages.domain.services.payment_import_service import (
    PaymentOrderGroup,
    import_payment_orders,
)
from packages.domain.services.reconciliation_engine import compare_with_remote_orders
from packages.domain.services.remote_charge_service import (
    CHARGE_EXPORT_COLUMNS,
    RajAdminChargeClient,
    RemoteResponseError,
    parse_charge_order_export,
)


def _charge_export_workbook(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([*CHARGE_EXPORT_COLUMNS, "手机号"])
    for row in rows:
        sheet.append(row)
    content = BytesIO()
    workbook.save(content)
    return content.getvalue()


def _sample_charge_export_row(
    *,
    order_id: str = "export-1",
    order_num: str = "merchant-1",
    status: str = "已支付",
) -> list[object]:
    return [
        order_id,
        "1001",
        order_num,
        "product-1",
        "100 金额包",
        "渠道名称",
        "948",
        "UPI",
        "third-1",
        "100",
        "100",
        "0",
        status,
        "2026-07-29 10:00:00",
        "2026-07-29 10:01:00",
        "2026-07-29 10:02:00",
        "是",
        "用户渠道",
        "9999999999",
    ]


def test_charge_export_parser_excludes_test_pull_orders() -> None:
    content = _charge_export_workbook(
        [
            _sample_charge_export_row(),
            _sample_charge_export_row(order_id="test-pull-1", status="测试拉单"),
        ]
    )

    orders = parse_charge_order_export(content)

    assert [order["id"] for order in orders] == ["export-1"]


def test_charge_export_parser_still_rejects_unknown_statuses() -> None:
    content = _charge_export_workbook(
        [_sample_charge_export_row(status="远端新增但未约定的状态")]
    )

    with pytest.raises(RemoteResponseError, match="包含未识别的订单状态"):
        parse_charge_order_export(content)


def test_charge_export_parser_uses_excel_columns_and_deduplicates_by_order_id() -> None:
    content = _charge_export_workbook(
        [
            _sample_charge_export_row(),
            _sample_charge_export_row(order_num="merchant-1-updated"),
        ]
    )

    assert parse_charge_order_export(content) == [
        {
            "id": "export-1",
            "uid": "1001",
            "order_num": "merchant-1-updated",
            "charge_product_id": "product-1",
            "product_name": "100 金额包",
            "pay_channel_name": "渠道名称",
            "pay_method": "948",
            "pay_type": "UPI",
            "out_trade_no": "third-1",
            "amount": "100",
            "balance": "100",
            "extra": "0",
            "status": "1",
            "create_time": "2026-07-29 10:00:00",
            "pay_time": "2026-07-29 10:01:00",
            "update_time": "2026-07-29 10:02:00",
            "first_pay": "是",
            "channel": "用户渠道",
        }
    ]


@pytest.mark.asyncio
async def test_charge_export_client_posts_export_and_task_save_for_one_day() -> None:
    calls: list[tuple[str, str]] = []
    workbook = _charge_export_workbook([_sample_charge_export_row()])

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/api/system/login"):
            return httpx.Response(200, json={"data": {"token": "test-token"}})
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer test-token"
        assert body["create_time"] == ["2026-07-29 00:00:00", "2026-07-29 23:59:59"]
        if request.url.path.endswith("/api/operate/chargeOrder/export"):
            return httpx.Response(200, content=workbook)
        if request.url.path.endswith("/api/operate/exportTask/save"):
            assert body["status"] == 1
            assert body["export_type"] == 2
            assert body["download"] == "operate/chargeOrder/export"
            return httpx.Response(200, json={"data": {"id": "task-1"}})
        raise AssertionError(f"unexpected path: {request.url.path}")

    async with RajAdminChargeClient(
        base_url="https://admin.example.test",
        username="reader",
        password="password",
        totp_secret="JBSWY3DPEHPK3PXP",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await client.export_charge_orders(
            create_start="2026-07-29 00:00:00",
            create_end="2026-07-29 23:59:59",
        )

    assert result.remote_total == 1
    assert result.orders[0]["status"] == "1"
    assert calls == [
        ("POST", "/api/system/login"),
        ("POST", "/api/operate/chargeOrder/export"),
        ("POST", "/api/operate/exportTask/save"),
    ]


def test_totp_matches_rfc_6238_sha1_vector() -> None:
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert generate_totp(secret, timestamp=59, digits=8) == "94287082"


@pytest.mark.asyncio
async def test_remote_client_uses_login_channel_dictionary_and_complete_pagination() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/api/system/login"):
            return httpx.Response(200, json={"data": {"token": "test-token"}})
        if request.url.path.endswith("/payChannel"):
            assert request.headers["authorization"] == "Bearer test-token"
            return httpx.Response(
                200,
                json={"data": [{"label": "aelopay(HX)", "value": 948}]},
            )
        if request.url.path.endswith("/api/system/dataDict/list"):
            assert request.url.params["code"] == "pay_channel"
            return httpx.Response(
                200,
                json={"data": [{"id": 999, "title": "MasterPay(唤醒)", "key": 448}]},
            )
        page = int(request.url.params["page"])
        items = [{"order_num": f"merchant-{page}", "status": 1}]
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": items,
                    "pageInfo": {
                        "total": 2,
                        "currentPage": page,
                        "totalPage": 2,
                    },
                }
            },
        )

    async with RajAdminChargeClient(
        base_url="https://admin.example.test",
        username="reader",
        password="password",
        totp_secret="JBSWY3DPEHPK3PXP",
        page_size=1,
        transport=httpx.MockTransport(handler),
    ) as client:
        assert await client.fetch_channels() == [{"code": "948", "label": "aelopay(HX)"}]
        assert await client.fetch_payment_channels() == [
            {"code": "448", "label": "MasterPay(唤醒)"}
        ]
        rows, pages = await client.fetch_all_charge_orders(
            channels=[{"code": "948", "label": "aelopay(HX)"}],
            create_start="2026-07-01 00:00:00",
            create_end="2026-07-01 23:59:59",
        )
    assert pages == 2
    assert [row["order_num"] for row in rows] == ["merchant-1", "merchant-2"]
    assert {method for method, _ in calls} <= {"GET", "POST"}


@pytest.mark.asyncio
async def test_exact_search_uses_channel_id_and_platform_order_reference() -> None:
    queries: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/system/login"):
            return httpx.Response(200, json={"data": {"token": "test-token"}})
        params = dict(request.url.params)
        queries.append(params)
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {
                            "id": "remote-order-1",
                            "order_num": "merchant-1",
                            "out_trade_no": "platform-1",
                        }
                    ],
                    "pageInfo": {
                        "total": 1,
                        "currentPage": 1,
                        "totalPage": 1,
                    },
                }
            },
        )

    async with RajAdminChargeClient(
        base_url="https://admin.example.test",
        username="reader",
        password="password",
        totp_secret="JBSWY3DPEHPK3PXP",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await client.exact_search(
            channels=[{"code": "948", "label": "aelopay(HX)"}],
            platform_order_no="platform-1",
            create_start="2026-07-01 00:00:00",
            create_end="2026-07-01 23:59:59",
        )

    assert result.complete is True
    assert len(result.orders) == 1
    assert {query["pay_method"] for query in queries} == {"948"}
    assert {(query["order_num"], query["out_trade_no"]) for query in queries} == {
        ("", "platform-1"),
    }
    assert {(query["create_time[0]"], query["create_time[1]"]) for query in queries} == {
        ("2026-07-01 00:00:00", "2026-07-01 23:59:59"),
    }


@pytest.mark.asyncio
async def test_exact_search_paginates_all_rows_within_the_configured_window() -> None:
    pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/system/login"):
            return httpx.Response(200, json={"data": {"token": "test-token"}})
        page = int(request.url.params["page"])
        pages.append(str(page))
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {
                            "id": f"remote-order-{page}",
                            "order_num": f"merchant-{page}",
                            "out_trade_no": "platform-1",
                        }
                    ],
                    "pageInfo": {
                        "total": 2,
                        "currentPage": page,
                        "totalPage": 2,
                    },
                }
            },
        )

    async with RajAdminChargeClient(
        base_url="https://admin.example.test",
        username="reader",
        password="password",
        totp_secret="JBSWY3DPEHPK3PXP",
        page_size=1,
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await client.exact_search(
            channels=[{"code": "948", "label": "aelopay(HX)"}],
            platform_order_no="platform-1",
            create_start="2026-07-01 00:00:00",
            create_end="2026-07-02 00:00:00",
        )

    assert result.complete is True
    assert pages == ["1", "2"]
    assert [row["order_num"] for row in result.orders] == ["merchant-1", "merchant-2"]


def _payment_group(**overrides: object) -> PaymentOrderGroup:
    values: dict[str, object] = {
        "order_group_id": "group",
        "merchant_order_no": "merchant-1",
        "platform_order_no": "platform-1",
        "amount": Decimal("100.00"),
        "currency": "INR",
        "payment_status_raw": "成功",
        "payment_status_group": "success",
        "payment_time": datetime.fromisoformat("2026-07-01 12:00:00"),
        "source_sheet": "payin_1",
        "source_row_numbers": [2],
        "duplicate_count": 1,
        "preliminary_result_status": None,
        "platform_key": "aelopay",
    }
    values.update(overrides)
    return PaymentOrderGroup(**values)  # type: ignore[arg-type]


def test_payment_import_uses_platform_order_number_when_merchant_number_is_missing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sample.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "payin_test"
    sheet.append(["商户订单号", "平台订单号", "订单金额", "订单状态", "订单时间", "到账时间"])
    sheet.append(["", "platform-1", "100.00", "成功", "2026-07-01 12:00:00", ""])
    sheet.append(["merchant-2", "platform-2", "100.00", "成功", "2026-07-01 12:00:00", ""])
    sheet.append(["merchant-2", "platform-3", "20.00", "失败", "2026-06-30 12:00:00", ""])
    workbook.save(path)

    imported = import_payment_orders(
        path,
        platform_key="aelopay",
        source_sheet="payin_test",
        header_row=1,
        column_mapping={
            "merchant_order_no": "商户订单号",
            "platform_order_no": "平台订单号",
            "amount": "订单金额",
            "payment_status": "订单状态",
            "candidate_time_fields": ["订单时间", "到账时间"],
        },
        success_status_values=["成功"],
        payment_time_field="订单时间",
        payment_timezone="Asia/Kolkata",
        window_start="2026-07-01 00:00:00",
        window_end="2026-07-01 23:59:59",
        currency="INR",
    )
    assert imported.source_rows == 3
    assert imported.included_rows == 2
    assert imported.excluded_outside_window == 1
    assert [group.platform_order_no for group in imported.groups] == ["platform-1", "platform-2"]
    assert imported.groups[0].merchant_order_no is None
    assert all(group.preliminary_result_status is None for group in imported.groups)


def test_comparison_uses_out_trade_no_and_marks_duplicate_remote_references() -> None:
    remote = {
        "order_num": "unrelated-internal-order-number",
        "out_trade_no": "platform-1",
        "amount": "100.00",
        "status": 0,
    }
    status_decision = compare_with_remote_orders(_payment_group(), [remote])
    assert status_decision is not None
    assert status_decision.result_status == "remote_status_not_success"

    platform_only_decision = compare_with_remote_orders(
        _payment_group(merchant_order_no=None),
        [remote],
    )
    assert platform_only_decision is not None
    assert platform_only_decision.result_status == "remote_status_not_success"

    conflict_decision = compare_with_remote_orders(
        _payment_group(),
        [remote, {**remote, "id": "same-out-trade-no"}],
    )
    assert conflict_decision is not None
    assert conflict_decision.result_status == "order_reference_conflict"
