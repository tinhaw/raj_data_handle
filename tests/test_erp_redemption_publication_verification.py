from __future__ import annotations

import httpx
import pytest

from packages.domain.schemas.remote_account import (
    ErpCompatibilityRemoteVerifyRequest,
    ErpRemoteConfigurationReference,
)
from packages.domain.services.erp_redemption_remote_gate import ErpRemoteExecutionGrant
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    RajAdminGiftCodeAdapter,
)


def payload():
    return ErpCompatibilityRemoteVerifyRequest(
        account_id=23,
        batch_id=54,
        remote_publish_task_id="222",
        publish_environment="test",
        configurations=[
            ErpRemoteConfigurationReference(
                configuration_id="174", group_key="group-174", key_number=200
            )
        ],
    )


def adapter(handler):
    return RajAdminGiftCodeAdapter(
        account_id="a",
        source_id="s",
        base_url="https://remote.example",
        username="test",
        password="test",
        totp_secret="JBSWY3DPEHPK3PXP",
        business_timezone="Asia/Kolkata",
        transport=httpx.MockTransport(handler),
    )


def grant():
    return ErpRemoteExecutionGrant(
        account_id="a", source_id="s", operation="DOWNLOAD", capability="ERP_REDEMPTION_DOWNLOAD"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,state",
    [
        (0, "WAITING"),
        (1, "RUNNING"),
        (2, "FAILED"),
        (3, "COMPLETED"),
        (4, "COMPLETED"),
        (5, "CANCELLED"),
        (99, "UNKNOWN"),
    ],
)
async def test_remote_status_is_authoritative_and_missing_config_is_not_success(status, state):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"data": {"token": "test-jwt"}})
        assert request.method == "GET"
        if request.url.path.endswith("/publishTask/index"):
            items = [
                {"id": 222, "env": "test", "cfg_type": 19, "status": status, "publish_type": 2}
            ]
        else:
            assert request.url.path.endswith("/giftCodeConfig/index")
            items = []
        return httpx.Response(
            200, json={"data": {"items": items, "pageInfo": {"currentPage": 1, "totalPage": 1}}}
        )

    async with adapter(handler) as remote:
        result = await remote.verify_publication(grant=grant(), payload=payload())
    assert result.publication_state == state
    assert result.can_cancel is (status == 0)
    assert result.configurations[0].state == ("MISSING" if state == "COMPLETED" else "UNKNOWN")
    assert calls.count("/api/common/giftCodeConfig/index") == (1 if state == "COMPLETED" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("matched", "MATCHED"),
        ("group_changed", "MISMATCH"),
        ("count_changed", "MISMATCH"),
        ("wrong_environment", "UNKNOWN"),
        ("wrong_type", "UNKNOWN"),
        ("missing_task", "UNKNOWN"),
    ],
)
async def test_checks_identity_environment_config_type_group_count_and_all_pages(
    scenario, expected
):
    def handler(request):
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"data": {"token": "test-jwt"}})
        assert request.method == "GET"
        page = int(request.url.params["page"])
        items = []
        if page == 2:
            if request.url.path.endswith("/publishTask/index"):
                if scenario != "missing_task":
                    items = [
                        {
                            "id": 222,
                            "status": 4,
                            "env": "prod" if scenario == "wrong_environment" else "test",
                            "cfg_type": 3 if scenario == "wrong_type" else 19,
                        }
                    ]
            else:
                items = [
                    {
                        "id": 174,
                        "group_key": "changed" if scenario == "group_changed" else "group-174",
                        "key_number": 1 if scenario == "count_changed" else 200,
                    }
                ]
        return httpx.Response(
            200, json={"data": {"items": items, "pageInfo": {"currentPage": page, "totalPage": 2}}}
        )

    async with adapter(handler) as remote:
        result = await remote.verify_publication(grant=grant(), payload=payload())
    assert result.configurations[0].state == expected
    assert result.publication_state == ("UNKNOWN" if expected == "UNKNOWN" else "COMPLETED")


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["forbidden", "malformed", "repeated_page", "too_many_pages"])
async def test_unavailable_verification_never_claims_completion(scenario):
    calls = []

    def handler(request):
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"data": {"token": "test-jwt"}})
        calls.append(request.url.path)
        if scenario == "forbidden":
            return httpx.Response(403)
        page = int(request.url.params["page"])
        page_info = {"currentPage": 1 if scenario == "repeated_page" else page, "totalPage": 100}
        return httpx.Response(
            200,
            json={"data": {"items": [], "pageInfo": {} if scenario == "malformed" else page_info}},
        )

    async with adapter(handler) as remote:
        with pytest.raises(ErpRedemptionRemoteHttpError):
            await remote.verify_publication(grant=grant(), payload=payload())
    assert len(calls) <= 50


@pytest.mark.asyncio
async def test_configuration_query_denied_does_not_erase_confirmed_publication():
    def handler(request):
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"data": {"token": "test-jwt"}})
        if request.url.path.endswith("/publishTask/index"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "items": [{"id": 222, "env": "test", "cfg_type": 19, "status": 4}],
                        "pageInfo": {"currentPage": 1, "totalPage": 1},
                    }
                },
            )
        return httpx.Response(403)

    async with adapter(handler) as remote:
        result = await remote.verify_publication(grant=grant(), payload=payload())
    assert result.publication_state == "COMPLETED"
    assert result.configurations[0].state == "UNKNOWN"
    assert result.configuration_error
