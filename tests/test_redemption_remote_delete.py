import json

import httpx
import pytest
from test_redemption_reuse_check import remote_read

from packages.domain.schemas.remote_account import ErpCompatibilityRemoteDeleteRequest
from packages.domain.services.erp_redemption_remote_gate import ErpRemoteExecutionGrant
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    ErpRemoteAccountReadGrant,
    RajAdminGiftCodeAdapter,
)


async def scenario(
    *,
    mode="success",
    capability="ERP_REDEMPTION_DELETE",
    confirmed=True,
    native_codes=("common:giftCodeConfig:realDelete",),
):
    calls = []
    current = remote_read()
    current.update(group_key="fixture-group", group_desc="fixture")
    deleted = False

    def handler(request):
        nonlocal deleted
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/system/getInfo":
            data = {} if native_codes is None else {"codes": list(native_codes)}
            return httpx.Response(200, json={"success": True, "code": 200, "data": data})
        if request.method == "DELETE":
            assert request.url.path == "/api/common/giftCodeConfig/realDelete"
            assert json.loads(request.content) == {"ids": [3403]}
            if mode == "timeout":
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            if mode == "forbidden":
                return httpx.Response(403)
            if mode == "business_rejected":
                return httpx.Response(
                    200, json={"success": False, "code": 400, "message": "synthetic rejection"}
                )
            if mode == "unauthenticated":
                return httpx.Response(401)
            deleted = mode != "no_effect"
            return httpx.Response(200, json={"success": True, "code": 200, "data": {}})
        if request.url.path.endswith("/index"):
            data = {"items": [], "pageInfo": {"currentPage": 1, "total": 0, "totalPage": 1}}
            if mode == "bad_pagination":
                data = {"items": []}
        else:
            data = [] if deleted else current
        return httpx.Response(200, json={"success": True, "code": 200, "data": data})

    async with RajAdminGiftCodeAdapter(
        account_id="fixture",
        source_id="rajwin",
        base_url="https://fixture.example",
        username="fixture",
        password="synthetic-password",
        totp_secret="JBSWY3DPEHPK3PXP",
        business_timezone="Asia/Kolkata",
        transport=httpx.MockTransport(handler),
    ) as adapter:
        adapter._token = "synthetic-session"
        read = ErpRemoteAccountReadGrant("fixture", "rajwin", "CHECK", "ERP_REMOTE_CHECK")
        preview = await adapter.inspect_deletion(grant=read, configuration_id="3403")
        assert not any(method == "DELETE" for method, _ in calls)
        if mode == "changed":
            current["group_key"] = "replacement"
        request = ErpCompatibilityRemoteDeleteRequest(
            account_id=1,
            issue_id=1,
            remote_configuration_id="3403",
            expected_fingerprint=preview["fingerprint"],
            execution_confirmed=confirmed,
        )
        try:
            result = await adapter.delete_configuration(
                grant=ErpRemoteExecutionGrant("fixture", "rajwin", "DELETE", capability),
                read_grant=read,
                payload=request,
            )
        finally:
            assert sum(method == "DELETE" for method, _ in calls) <= 1
            if (
                native_codes is None
                or "common:giftCodeConfig:realDelete" not in native_codes
                and "*" not in native_codes
            ):
                assert not any(method == "DELETE" for method, _ in calls)
            assert all(method in {"GET", "DELETE"} for method, _ in calls)
    return result, calls


@pytest.mark.asyncio
async def test_confirmed_delete_sends_only_selected_id_and_proves_absence():
    result, calls = await scenario()
    assert result["state"] == "ABSENT"
    assert sum(method == "DELETE" for method, _ in calls) == 1
    assert sum(path.endswith("/index") for _, path in calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["changed", "timeout", "unauthenticated", "no_effect", "bad_pagination"]
)
async def test_change_unknown_write_and_incomplete_absence_never_report_deleted_or_replay(mode):
    with pytest.raises(ErpRedemptionRemoteHttpError):
        await scenario(mode=mode)


@pytest.mark.asyncio
async def test_other_write_capability_cannot_authorize_permanent_delete():
    with pytest.raises(ErpRedemptionRemoteHttpError, match="授权"):
        await scenario(capability="ERP_REDEMPTION_UPDATE")


@pytest.mark.asyncio
async def test_unconfirmed_deletion_is_read_only():
    with pytest.raises(ErpRedemptionRemoteHttpError, match="确认"):
        await scenario(confirmed=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("codes", [(), ("common:giftCodeConfig:save",), None, (123,)])
async def test_local_grant_cannot_replace_native_delete_permission(codes):
    with pytest.raises(ErpRedemptionRemoteHttpError, match="远端.*权限") as failure:
        await scenario(native_codes=codes)
    assert failure.value.reason_code in {
        "REMOTE_DELETE_PERMISSION_MISSING",
        "REMOTE_DELETE_PERMISSION_UNAVAILABLE",
    }
    assert failure.value.deletion_stage == "PRE_DELETE_CHECK"


@pytest.mark.asyncio
async def test_native_wildcard_permission_allows_confirmed_deletion():
    result, calls = await scenario(native_codes=("*",))
    assert result["state"] == "ABSENT"
    assert sum(method == "DELETE" for method, _ in calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["forbidden", "timeout", "business_rejected"])
async def test_write_failure_retains_safe_phase_and_http_status_without_replay(mode):
    with pytest.raises(ErpRedemptionRemoteHttpError) as failure:
        await scenario(mode=mode)
    assert failure.value.deletion_stage == "DELETE_REQUEST"
    assert failure.value.http_status == (403 if mode == "forbidden" else None)
