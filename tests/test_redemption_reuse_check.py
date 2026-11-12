from datetime import date

import httpx
import pytest

from packages.domain.schemas.remote_account import ErpCompatibilityRemoteReuseCheckRequest
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    ErpRemoteAccountReadGrant,
    RajAdminGiftCodeAdapter,
)


def expectation():
    return ErpCompatibilityRemoteReuseCheckRequest(
        account_id=6,
        issue_id=66,
        remote_configuration_id="3403",
        description="Reuse fixture",
        claim_date=date(2026, 11, 12),
        label_ids=[],
        bonus_amount=1,
        bonus_max_amount=3,
        gift_code="1112rajfree",
        options={
            "flow_times": 5,
            "single_user_limit": 1,
            "single_key_limit": 3000,
            "require_bind_bank_card": False,
            "require_bind_phone": True,
            "check_uuid": True,
            "uuid_reward_limit": 1,
            "check_login_ip": True,
            "login_ip_reward_limit": 1,
            "check_register_ip": True,
            "register_ip_reward_limit": 1,
        },
    )


def remote_read():
    # Sanitized native /read contract: the rewards are raw thousandths, unlike /index.
    return {
        "id": 3403,
        "key_number": 1,
        "gift_code": "1112RAJFREE",
        "gift_type": 1,
        "reward_min": 1000,
        "reward_max": 3000,
        "activity_recharge": 0,
        "activity_recharge_count": 0,
        "activity_id": 0,
        "flow_times": 5,
        "single_user_limit": 1,
        "single_key_limit": 3000,
        "start_time": 1794421800,
        "end_time": 1794508199,
        "start_timestamp": "2026-11-12 00:00:00",
        "end_timestamp": "2026-11-12 23:59:59",
        "is_need_bind_bank_card": 0,
        "is_need_bind_phone": 1,
        "user_type": 0,
        "label_array": [],
        "user_array": None,
        "status": 1,
        "is_need_check_uuid": 1,
        "uuid_reward_limit": 1,
        "is_need_check_login_ip": 1,
        "login_ip_reward_limit": 1,
        "is_need_check_register_ip": 1,
        "register_ip_reward_limit": 1,
        "refresh_flag": 0,
        "agent_uid": 0,
        "agent_reward_array": [],
        "reward_condition_type": 0,
        "company_array": [],
        "channel_type": 1,
        "channel_list": [],
        "clear_status": 0,
    }


async def check(data, grant=None):
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        assert request.method == "GET"
        assert request.url.path == "/api/common/giftCodeConfig/read/3403"
        return httpx.Response(200, json={"code": 200, "success": True, "data": data})

    async with RajAdminGiftCodeAdapter(
        account_id="fixture-account",
        source_id="rajwin",
        base_url="https://fixture.example",
        username="",
        password="",
        totp_secret="",
        business_timezone="Asia/Kolkata",
        transport=httpx.MockTransport(handler),
    ) as adapter:
        adapter._token = "test-only-session"
        result = await adapter.check_reusable_configuration(
            payload=expectation(),
            grant=grant
            or ErpRemoteAccountReadGrant(
                account_id="fixture-account",
                source_id="rajwin",
                operation="CHECK",
                capability="ERP_REMOTE_CHECK",
            ),
        )
    assert requests == [("GET", "/api/common/giftCodeConfig/read/3403")]
    return result


@pytest.mark.asyncio
async def test_native_money_units_case_insensitive_code_and_3000_match_without_any_write():
    result = await check(remote_read())
    assert result.matched and result.differences == []
    assert result.remote_configuration_id == "3403"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("single_key_limit", 3),
        ("reward_min", 1),
        ("reward_max", 3),
        ("label_array", [901]),
        ("user_type", 1),
        ("flow_times", 10),
        ("gift_code", "1112raj200"),
        ("key_number", 2),
        ("gift_type", 0),
        ("single_user_limit", 2),
        ("is_need_bind_bank_card", 1),
        ("is_need_bind_phone", 0),
        ("is_need_check_uuid", 0),
        ("uuid_reward_limit", 3),
        ("is_need_check_login_ip", 0),
        ("login_ip_reward_limit", 3),
        ("is_need_check_register_ip", 0),
        ("register_ip_reward_limit", 3),
        ("status", -1),
        ("refresh_flag", 1),
        ("activity_id", 1),
        ("activity_recharge", 1000),
        ("user_array", [123]),
        ("channel_list", [12]),
        ("clear_status", 1),
    ],
)
async def test_each_policy_difference_blocks_reuse(field, value):
    result = await check({**remote_read(), field: value})
    assert not result.matched and field in result.differences


@pytest.mark.asyncio
async def test_expiration_difference_and_missing_policy_field_are_not_guessed():
    data = remote_read()
    data["end_timestamp"] = "2026-11-13 23:59:59"
    del data["single_key_limit"]
    result = await check(data)
    assert not result.matched
    assert set(result.differences) == {"valid_time", "single_key_limit"}


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [[], {**remote_read(), "id": 999}], ids=["empty-data", "wrong-id"])
async def test_missing_or_wrong_remote_identity_does_not_establish_a_link(data):
    with pytest.raises(ErpRedemptionRemoteHttpError, match="指定 ID"):
        await check(data)


@pytest.mark.asyncio
async def test_read_grant_cannot_cross_account_boundary():
    with pytest.raises(ErpRedemptionRemoteHttpError, match="读取授权"):
        await check(
            remote_read(),
            ErpRemoteAccountReadGrant(
                account_id="another-account",
                source_id="rajwin",
                operation="CHECK",
                capability="ERP_REMOTE_CHECK",
            ),
        )
