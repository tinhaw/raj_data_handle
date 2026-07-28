from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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
from packages.domain.services.remote_charge_service import RajAdminChargeClient


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
        )

    assert result.complete is True
    assert len(result.orders) == 1
    assert {query["pay_method"] for query in queries} == {"948"}
    assert {(query["order_num"], query["out_trade_no"]) for query in queries} == {
        ("", "platform-1"),
    }


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
