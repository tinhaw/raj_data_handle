from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_erp_compatibility_redemption_remote_service import _settings

from packages.domain.models import Base, RemoteAccountCapability
from packages.domain.schemas.remote_account import (
    ErpCompatibilityRemoteDuplicateCheckRequest,
    RemoteAccountCreateRequest,
    RemoteAccountCredentialsWrite,
)
from packages.domain.schemas.source import SourceCreateRequest, SourcePatchRequest
from packages.domain.services.erp_compatibility_id_service import get_erp_compatibility_ids
from packages.domain.services.erp_compatibility_redemption_remote_service import (
    ErpCompatibilityRemoteExecutionError,
)
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    ErpRemoteAccountReadGrant,
    RajAdminGiftCodeAdapter,
)
from packages.domain.services.remote_account_service import create_remote_account
from packages.domain.services.source_service import create_source, upsert_source


async def scan(handler, codes=None, grant=None):
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
        return await adapter.check_duplicate_codes(
            grant=grant
            or ErpRemoteAccountReadGrant(
                account_id="fixture-account",
                source_id="rajwin",
                operation="CHECK",
                capability="ERP_REMOTE_CHECK",
            ),
            gift_codes=codes or ["1113rajfree"],
        )


def response(items, page=1, pages=1, total=None):
    return httpx.Response(
        200,
        json={
            "code": 200,
            "success": True,
            "data": {
                "items": items,
                "pageInfo": {
                    "currentPage": page,
                    "totalPage": pages,
                    "total": len(items) if total is None else total,
                },
            },
        },
    )


@pytest.mark.asyncio
async def test_one_scan_per_market_is_shared_by_1000_codes_and_retains_multiple_owners():
    calls = []

    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/common/giftCodeConfig/index"
        assert "gift_code" not in request.url.params
        page = int(request.url.params["page"])
        calls.append(page)
        return response([{"id": page, "gift_code": "1113RAJFREE"}], page, 2, 2)

    result = await scan(handler, ["1113rajfree"] + [f"code{i}" for i in range(999)])
    assert calls == [1, 2, 1, 2]
    assert result["complete"]
    assert result["matches"] == [
        {"gift_code": "1113rajfree", "configuration_id": "1"},
        {"gift_code": "1113rajfree", "configuration_id": "2"},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem", ["missing_page", "changed", "duplicate_id", "count", "missing_code"]
)
async def test_incomplete_or_changing_directory_never_reports_clear(problem):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if problem == "missing_page":
            return httpx.Response(200, json={"code": 200, "data": {"items": []}})
        if problem == "changed":
            return response([{"id": calls, "gift_code": "other"}])
        if problem == "duplicate_id":
            return response([{"id": 1, "gift_code": "other"}] * 2)
        if problem == "count":
            return response([], total=5)
        return response([{"id": 1}])

    with pytest.raises(ErpRedemptionRemoteHttpError):
        await scan(handler)


@pytest.mark.asyncio
async def test_wrong_account_grant_never_reaches_remote():
    def unexpected(request):
        pytest.fail("Incorrect read grant reached remote")

    with pytest.raises(ErpRedemptionRemoteHttpError):
        await scan(
            unexpected,
            grant=ErpRemoteAccountReadGrant(
                account_id="other-account",
                source_id="rajwin",
                operation="CHECK",
                capability="ERP_REMOTE_CHECK",
            ),
        )


@pytest.mark.asyncio
async def test_empty_stable_directory_is_valid_but_403_is_not_empty():
    assert (await scan(lambda request: response([])))["matches"] == []
    with pytest.raises(ErpRedemptionRemoteHttpError):
        await scan(lambda request: httpx.Response(403, json={"message": "Forbidden"}))


def test_schema_rejects_empty_or_invalid_codes_and_normalizes_case():
    value = ErpCompatibilityRemoteDuplicateCheckRequest(
        account_id=1, gift_codes=["1113RAJFREE", "1113rajfree"]
    )
    assert value.gift_codes == ["1113rajfree"]
    for codes in ([], [""], ["1;DELETE"], ["x" * 256]):
        with pytest.raises(ValidationError):
            ErpCompatibilityRemoteDuplicateCheckRequest(account_id=1, gift_codes=codes)


@pytest.mark.asyncio
@pytest.mark.parametrize("read_allowed", [False, True])
async def test_optional_duplicate_scan_uses_only_unified_read_capability(
    read_allowed,
):

    from packages.domain.services.erp_compatibility_redemption_remote_service import (
        check_compatibility_remote_duplicates,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings()
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/system/login":
            return httpx.Response(
                200, json={"success": True, "data": {"token": "test-reuse-session"}}
            )
        assert request.method == "GET" and request.url.path == "/api/common/giftCodeConfig/index"
        return response([{"id": 3403, "gift_code": "1113RAJFREE"}])

    try:
        async with factory() as session:
            await create_source(
                session,
                request=SourceCreateRequest(
                    source_id="rajwin",
                    display_name="Reuse fixture",
                    base_url="https://fixture.example",
                    enabled=False,
                ),
                actor_user_id=1,
                settings=settings,
            )
            account = await create_remote_account(
                session,
                request=RemoteAccountCreateRequest(
                    source_id="rajwin",
                    login_username="reuse-fixture",
                    display_name="Reuse fixture",
                    credentials=RemoteAccountCredentialsWrite(
                        password="fixture-password", totp_secret="JBSWY3DPEHPK3PXP"
                    ),
                ),
                actor_user_id=1,
                settings=settings,
            )
            await upsert_source(
                session,
                source_id="rajwin",
                request=SourcePatchRequest(enabled=True),
                actor_user_id=1,
                settings=settings,
            )
            account_id = account.account.id
            await session.execute(
                update(RemoteAccountCapability)
                .where(RemoteAccountCapability.account_id == account_id)
                .values(enabled=False)
            )
            await session.execute(
                update(RemoteAccountCapability)
                .where(
                    RemoteAccountCapability.account_id == account_id,
                    RemoteAccountCapability.capability == "ERP_REMOTE_CHECK",
                )
                .values(enabled=read_allowed)
            )
            await session.commit()
            projection = (
                await get_erp_compatibility_ids(
                    session, entity_type="remote_account", canonical_ids=[account_id]
                )
            )[account_id]
            payload = ErpCompatibilityRemoteDuplicateCheckRequest(
                account_id=projection, gift_codes=["1113rajfree"]
            )
            if read_allowed:
                result = await check_compatibility_remote_duplicates(
                    session,
                    payload=payload,
                    actor_user_id=1,
                    settings=settings,
                    transport=httpx.MockTransport(handler),
                )
                assert result["complete"] and len(result["matches"]) == 1
                assert requests == [
                    ("POST", "/api/system/login"),
                    ("GET", "/api/common/giftCodeConfig/index"),
                    ("GET", "/api/common/giftCodeConfig/index"),
                ]
            else:
                with pytest.raises(ErpCompatibilityRemoteExecutionError, match="配置读取能力"):
                    await check_compatibility_remote_duplicates(
                        session,
                        payload=payload,
                        actor_user_id=1,
                        settings=settings,
                        transport=httpx.MockTransport(handler),
                    )
                assert requests == []
    finally:
        await engine.dispose()
