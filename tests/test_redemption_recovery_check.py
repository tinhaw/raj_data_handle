from io import BytesIO

import httpx
import pytest
from openpyxl import Workbook
from test_redemption_reuse_check import expectation, remote_read

from packages.domain.schemas.remote_account import ErpCompatibilityRemoteRecoveryCheckRequest
from packages.domain.services.erp_redemption_remote_gate import ErpRemoteExecutionGrant
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    ErpRemoteAccountReadGrant,
    RajAdminGiftCodeAdapter,
)


def workbook(codes):
    book = Workbook()
    book.active.append(["兑换码号码"])
    for code in codes:
        book.active.append([code])
    content = BytesIO()
    book.save(content)
    book.close()
    return content.getvalue()


async def probe(*, mutation=None, read=None, inventory=False, export=None, denied=False):
    requests, scans = [], []
    payload = ErpCompatibilityRemoteRecoveryCheckRequest(
        **expectation().model_dump(), check_inventory=inventory, remote_group_key="prior-group"
    )

    def handler(request):
        requests.append((request.method, request.url.path))
        if denied:
            return httpx.Response(403, json={"code": 1003, "message": "Access denied"})
        if "/read/" in request.url.path:
            data = [] if read is None else read
        elif request.url.path.endswith("/export"):
            assert request.url.params["groupKey"] == "prior-group"
            return httpx.Response(200, content=workbook([]) if export is None else export)
        else:
            assert request.url.path.endswith("/index") and request.method == "GET"
            page = int(request.url.params["page"])
            scans.append(page)
            data = {
                "items": [{"id": page + 5000, "gift_code": f"unrelated{page}"}],
                "pageInfo": {"currentPage": page, "total": 2, "totalPage": 2},
            }
            if mutation:
                mutation(data, len(scans))
        return httpx.Response(200, json={"code": 200, "success": True, "data": data})

    async with RajAdminGiftCodeAdapter(
        account_id="fixture-account",
        source_id="rajwin",
        base_url="https://fixture.example",
        username="fixture",
        password="synthetic-test-password",
        totp_secret="JBSWY3DPEHPK3PXP",
        business_timezone="Asia/Kolkata",
        transport=httpx.MockTransport(handler),
    ) as adapter:
        adapter._token = "test-only-session"
        result = await adapter.check_configuration_recovery(
            grant=ErpRemoteAccountReadGrant(
                account_id="fixture-account",
                source_id="rajwin",
                operation="CHECK",
                capability="ERP_REMOTE_CHECK",
            ),
            payload=payload,
            inventory_grant=ErpRemoteExecutionGrant(
                account_id="fixture-account",
                source_id="rajwin",
                operation="DOWNLOAD",
                capability="ERP_REDEMPTION_DOWNLOAD",
            )
            if inventory
            else None,
        )
    return result, requests, scans


@pytest.mark.asyncio
async def test_empty_read_requires_two_full_identical_directories_and_no_write():
    result, requests, scans = await probe()
    assert result.state == "ABSENT" and result.scanned_rows == 2
    assert scans == [1, 2, 1, 2]
    assert all(method == "GET" for method, _ in requests)


@pytest.mark.asyncio
async def test_present_configuration_is_never_a_rebuild_candidate():
    result, requests, scans = await probe(read=remote_read())
    assert result.state == "PRESENT" and not scans
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong", [{"id": 7}, {"items": []}, None, "", False])
async def test_wrong_identity_or_malformed_read_is_not_absence(wrong):
    if wrong is None:
        wrong = {"id": None}
    with pytest.raises(ErpRedemptionRemoteHttpError, match="身份或结构"):
        await probe(read=wrong)


@pytest.mark.asyncio
async def test_authorization_failure_is_not_absence():
    with pytest.raises(ErpRedemptionRemoteHttpError):
        await probe(denied=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        lambda data, n: data["items"][0].update(gift_code=expectation().gift_code.upper()),
        lambda data, n: data["items"][0].update(id=int(expectation().remote_configuration_id)),
        lambda data, n: data["pageInfo"].update(total=4),
        lambda data, n: data["pageInfo"].update(totalPage=201),
        lambda data, n: data["pageInfo"].update(currentPage="1"),
        lambda data, n: data["items"][0].update(id=5000),
        lambda data, n: data["items"][0].update(gift_code=f"changed{n}") if n > 2 else None,
        lambda data, n: data.pop("pageInfo"),
        lambda data, n: data.update(items=[]) if n == 2 else None,
    ],
)
async def test_same_code_old_id_incomplete_unstable_and_invalid_pagination_never_prove_absence(
    mutation,
):
    with pytest.raises(ErpRedemptionRemoteHttpError):
        await probe(mutation=mutation)


@pytest.mark.asyncio
async def test_imported_configuration_also_requires_proven_empty_native_export():
    result, requests, _ = await probe(inventory=True)
    assert result.state == "ABSENT"
    assert requests[-1] == ("POST", "/api/common/giftCodeConfig/export")


@pytest.mark.asyncio
@pytest.mark.parametrize("export", [workbook(["still-live"]), b"", b"not-excel"])
async def test_remaining_inventory_or_invalid_export_blocks_rebuild(export):
    with pytest.raises(ErpRedemptionRemoteHttpError):
        await probe(inventory=True, export=export)
