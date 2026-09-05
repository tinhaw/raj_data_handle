from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from io import BytesIO

import httpx
import pytest
from openpyxl import Workbook

from packages.domain.services.erp_redemption_remote_adapter import (
    RemoteCreateCommand,
    RemoteCreationOptions,
    RemoteDownloadCommand,
)
from packages.domain.services.erp_redemption_remote_gate import ErpRemoteExecutionGrant
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    ErpRemoteAccountReadGrant,
    RajAdminGiftCodeAdapter,
    _extract_code_text,
)


def _options() -> RemoteCreationOptions:
    return RemoteCreationOptions(
        publish_environment="test",
        flow_times=5,
        activity_recharge=None,
        activity_recharge_count=None,
        activity_id=None,
        key_number=1,
        single_user_limit=1,
        single_key_limit=2000,
        require_bind_bank_card=False,
        require_bind_phone=True,
        check_uuid=True,
        uuid_reward_limit=1,
        check_login_ip=True,
        login_ip_reward_limit=1,
        check_register_ip=True,
        register_ip_reward_limit=1,
    )


@pytest.mark.parametrize(
    "codes,expected_count", [([], 1), (["A"], 5), (["A", "A"], 2), (["A\nB"], 1)]
)
def test_download_rejects_incomplete_duplicate_or_invalid_codes(codes, expected_count):
    workbook = Workbook()
    workbook.active.append(["兑换码号码"])
    for code in codes:
        workbook.active.append([code])
    output = BytesIO()
    workbook.save(output)
    with pytest.raises(ErpRedemptionRemoteHttpError):
        _extract_code_text(output.getvalue(), expected_count)


@pytest.mark.asyncio
async def test_http_adapter_maps_current_cloud_create_contract() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/system/login":
            return httpx.Response(200, json={"success": True, "data": {"token": "test-jwt"}})
        if request.url.path == "/api/common/giftCodeConfig/save":
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"success": True, "data": {"id": "cfg-1"}})
        if request.url.path == "/api/common/giftCodeConfig/index":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"items": [{"id": "cfg-1", "group_key": "group-1"}]},
                },
            )
        raise AssertionError(request.url)

    grant = ErpRemoteExecutionGrant(
        account_id="account-1",
        source_id="rajwin",
        operation="CREATE",
        capability="ERP_REDEMPTION_CREATE",
    )
    async with RajAdminGiftCodeAdapter(
        account_id="account-1",
        source_id="rajwin",
        base_url="https://remote.example",
        username="operator",
        password="password",
        totp_secret="JBSWY3DPEHPK3PXP",
        business_timezone="Asia/Shanghai",
        transport=httpx.MockTransport(handler),
    ) as adapter:
        result = await adapter.create_configuration(
            grant=grant,
            command=RemoteCreateCommand(
                issue_id="issue-1",
                description="RajWin 2026-08-18 100-499",
                claim_date=date(2026, 8, 18),
                deposit_window_start=date(2026, 8, 11),
                deposit_window_end=date(2026, 8, 17),
                label_ids=(10, 20),
                bonus_amount=Decimal("10"),
                bonus_max_amount=Decimal("10"),
                options=_options(),
            ),
        )
    assert result.remote_configuration_id == "cfg-1"
    assert result.remote_group_key == "group-1"
    assert captured["label_array"] == [10, 20]
    assert captured["valid_time"] == ["2026-08-18 00:00:00", "2026-08-18 23:59:59"]


@pytest.mark.asyncio
async def test_http_adapter_maps_all_users_without_a_label_array() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/system/login":
            return httpx.Response(200, json={"success": True, "data": {"token": "test-jwt"}})
        if request.url.path == "/api/common/giftCodeConfig/save":
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"success": True, "data": {"id": "cfg-all"}})
        if request.url.path == "/api/common/giftCodeConfig/index":
            return httpx.Response(200, json={"success": True, "data": {"items": []}})
        raise AssertionError(request.url)

    grant = ErpRemoteExecutionGrant(
        account_id="account-1",
        source_id="rajwin",
        operation="CREATE",
        capability="ERP_REDEMPTION_CREATE",
    )
    async with RajAdminGiftCodeAdapter(
        account_id="account-1",
        source_id="rajwin",
        base_url="https://remote.example",
        username="operator",
        password="password",
        totp_secret="JBSWY3DPEHPK3PXP",
        business_timezone="Asia/Shanghai",
        transport=httpx.MockTransport(handler),
    ) as adapter:
        await adapter.create_configuration(
            grant=grant,
            command=RemoteCreateCommand(
                issue_id="issue-all",
                description="RajWin 2026-08-18 全部用户",
                claim_date=date(2026, 8, 18),
                deposit_window_start=date(2026, 8, 11),
                deposit_window_end=date(2026, 8, 17),
                label_ids=(),
                bonus_amount=Decimal("1"),
                bonus_max_amount=Decimal("3"),
                options=_options(),
            ),
        )

    assert captured["user_type"] == "0"
    assert "label_array" not in captured


@pytest.mark.asyncio
@pytest.mark.parametrize("key_number", [1, 5])
async def test_http_adapter_downloads_all_requested_codes(key_number: int) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["兑换码号码"])
    codes = [f"RAJ-TEST-CODE-{index}" for index in range(key_number)]
    for code in codes:
        sheet.append([code])
    buffer = BytesIO()
    workbook.save(buffer)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/system/login":
            return httpx.Response(200, json={"success": True, "token": "test-jwt"})
        if request.url.path == "/api/common/giftCodeConfig/export":
            assert request.url.params["groupKey"] == "group-1"
            return httpx.Response(200, content=buffer.getvalue())
        raise AssertionError(request.url)

    grant = ErpRemoteExecutionGrant(
        account_id="account-1",
        source_id="rajwin",
        operation="DOWNLOAD",
        capability="ERP_REDEMPTION_DOWNLOAD",
    )
    async with RajAdminGiftCodeAdapter(
        account_id="account-1",
        source_id="rajwin",
        base_url="https://remote.example",
        username="operator",
        password="password",
        totp_secret="JBSWY3DPEHPK3PXP",
        business_timezone="Asia/Shanghai",
        transport=httpx.MockTransport(handler),
    ) as adapter:
        result = await adapter.download(
            grant=grant,
            command=RemoteDownloadCommand(
                issue_id="issue-1",
                remote_configuration_id="cfg-1",
                remote_group_key="group-1",
                key_number=key_number,
            ),
        )
    assert result.redemption_code.splitlines() == codes


@pytest.mark.asyncio
async def test_http_adapter_checks_access_and_reads_current_tag_contract() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/system/login":
            return httpx.Response(200, json={"success": True, "token": "test-jwt"})
        if request.url.path == "/api/common/giftCodeConfig/index":
            assert request.url.params["pageSize"] == "1"
            return httpx.Response(
                200,
                headers={"x-request-id": "check-request"},
                json={"success": True, "data": {"items": []}},
            )
        if request.url.path == "/api/common/profileTag/remote":
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                headers={"x-request-id": "tags-request"},
                json={
                    "success": True,
                    "data": [
                        {"tag_id": 901091, "name": "近 7 天充值 100-499"},
                        {"tag_id": 0, "name": "invalid"},
                    ],
                },
            )
        raise AssertionError(request.url)

    async with RajAdminGiftCodeAdapter(
        account_id="account-1",
        source_id="rajwin",
        base_url="https://remote.example",
        username="operator",
        password="password",
        totp_secret="JBSWY3DPEHPK3PXP",
        business_timezone="Asia/Shanghai",
        transport=httpx.MockTransport(handler),
    ) as adapter:
        message, check_request_id = await adapter.check_connection(
            grant=ErpRemoteAccountReadGrant(
                account_id="account-1",
                source_id="rajwin",
                operation="CHECK",
                capability="ERP_REMOTE_CHECK",
            )
        )
        tags, tags_request_id = await adapter.fetch_tags(
            grant=ErpRemoteAccountReadGrant(
                account_id="account-1",
                source_id="rajwin",
                operation="TAGS",
                capability="ERP_TAG_READ",
            )
        )
    assert "连接正常" in message
    assert check_request_id == "check-request"
    assert tags_request_id == "tags-request"
    assert [(tag.id, tag.name) for tag in tags] == [(901091, "近 7 天充值 100-499")]
    assert captured["pageSize"] == 500
