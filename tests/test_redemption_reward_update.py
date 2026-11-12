import json
from decimal import Decimal

import httpx
import pytest
from test_redemption_reuse_check import expectation, remote_read

from packages.domain.schemas.remote_account import ErpCompatibilityRemoteRewardUpdateRequest
from packages.domain.services.erp_redemption_remote_gate import ErpRemoteExecutionGrant
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    ErpRemoteAccountReadGrant,
    RajAdminGiftCodeAdapter,
)


async def update(*, change=None, already=False, timeout=False, operation="UPDATE"):
    calls, forms = [], []
    current = remote_read()
    current.update(
        group_desc="OriginalName",
        remark="OriginalRemark",
        group_key="OriginalGroup",
        code_key="OriginalKey",
        valid_type=1,
    )
    if already:
        current["reward_max"] = 7000
    if change:
        current.update(change)

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"code": 200, "success": True, "data": current})
        assert request.method == "PUT" and request.url.path.endswith("/update/3403")
        forms.append(json.loads(request.content))
        # The native CRUD sends the PK in both the route and its edit form.
        assert forms[-1]["id"] == current["id"]
        if timeout:
            raise httpx.ReadTimeout("synthetic response timeout", request=request)
        current["reward_min"] = forms[-1]["reward_min"] * 1000
        current["reward_max"] = forms[-1]["reward_max"] * 1000
        return httpx.Response(200, json={"code": 200, "success": True, "data": {"ret": 1}})

    request = ErpCompatibilityRemoteRewardUpdateRequest(
        **{**expectation().model_dump(), "bonus_max_amount": Decimal(7)},
        execution_confirmed=True,
    )
    async with RajAdminGiftCodeAdapter(
        account_id="fixture",
        source_id="rajwin",
        base_url="https://fixture.example",
        username="fixture",
        password="synthetic-fixture-password",
        totp_secret="JBSWY3DPEHPK3PXP",
        business_timezone="Asia/Kolkata",
        transport=httpx.MockTransport(handler),
    ) as adapter:
        adapter._token = "synthetic-test-session"
        try:
            result = await adapter.update_reward_policy(
                payload=request,
                grant=ErpRemoteExecutionGrant(
                    account_id="fixture",
                    source_id="rajwin",
                    operation=operation,
                    capability="ERP_REDEMPTION_UPDATE",
                ),
                read_grant=ErpRemoteAccountReadGrant(
                    account_id="fixture",
                    source_id="rajwin",
                    operation="CHECK",
                    capability="ERP_REMOTE_CHECK",
                ),
            )
        except ErpRedemptionRemoteHttpError:
            assert sum(method == "PUT" for method, _ in calls) <= 1
            assert not any(method in {"POST", "DELETE"} for method, _ in calls)
            raise
    return result, forms, calls


@pytest.mark.asyncio
async def test_reward_only_update_preserves_identity_policy_and_native_money_units():
    result, forms, calls = await update()
    assert result.matched and result.actual_bonus_max_amount == 7
    assert len(forms) == 1
    form = forms[0]
    assert str(form["id"]) == "3403"
    assert (form["reward_min"], form["reward_max"]) == (1, 7)
    assert form["group_desc"] == "OriginalName" and form["remark"] == "OriginalRemark"
    assert form["gift_code"] == "1112RAJFREE" and form["single_key_limit"] == 3000
    assert form["status"] == 1 and form["group_key"] == "OriginalGroup"
    assert form["code_key"] == "OriginalKey" and form["valid_type"] == 1
    assert form["valid_time"] == ["2026-11-12 00:00:00", "2026-11-12 23:59:59"]
    assert calls == [
        ("GET", "/api/common/giftCodeConfig/read/3403"),
        ("PUT", "/api/common/giftCodeConfig/update/3403"),
        ("GET", "/api/common/giftCodeConfig/read/3403"),
    ]


@pytest.mark.asyncio
async def test_already_matching_update_is_read_only():
    result, forms, calls = await update(already=True)
    assert result.matched and not forms and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"id": 9},
        {"single_key_limit": 2},
        {"gift_code": "other"},
        {"reward_min": None},
        {"label_array": [9]},
        {"status": 9},
        {"start_timestamp": "2027-01-01 00:00:00"},
        {"group_desc": ""},
    ],
)
async def test_missing_identity_invalid_money_and_non_reward_drift_are_not_overwritten(change):
    with pytest.raises(ErpRedemptionRemoteHttpError):
        await update(change=change)


@pytest.mark.asyncio
async def test_create_grant_cannot_authorize_update():
    with pytest.raises(ErpRedemptionRemoteHttpError, match="授权"):
        await update(operation="CREATE")


@pytest.mark.asyncio
async def test_unknown_write_is_never_replayed_by_adapter():
    with pytest.raises(ErpRedemptionRemoteHttpError):
        await update(timeout=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "read_allowed,update_allowed", [(True, False), (False, True), (True, True)]
)
async def test_unified_reward_update_requires_independent_read_and_update_grants(
    read_allowed, update_allowed
):
    from sqlalchemy import update as sql_update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from test_erp_compatibility_redemption_remote_service import _settings

    from packages.domain.models import Base, RemoteAccountCapability
    from packages.domain.schemas.remote_account import (
        RemoteAccountCreateRequest,
        RemoteAccountCredentialsWrite,
    )
    from packages.domain.schemas.source import SourceCreateRequest, SourcePatchRequest
    from packages.domain.services.erp_compatibility_id_service import get_erp_compatibility_ids
    from packages.domain.services.erp_compatibility_redemption_remote_service import (
        ErpCompatibilityRemoteExecutionError,
        execute_compatibility_remote_reward_update,
    )
    from packages.domain.services.remote_account_service import create_remote_account
    from packages.domain.services.source_service import create_source, upsert_source

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings, calls = _settings(), []
    current = remote_read()
    current.update(group_desc="Original", remark="OriginalRemark", group_key="OriginalGroup")

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/system/login":
            return httpx.Response(200, json={"success": True, "data": {"token": "fixture"}})
        if request.method == "PUT":
            assert request.url.path.endswith("/update/3403")
            form = json.loads(request.content)
            current["reward_min"], current["reward_max"] = (
                form["reward_min"] * 1000,
                form["reward_max"] * 1000,
            )
            return httpx.Response(200, json={"code": 200, "success": True, "data": {"ret": 1}})
        assert request.method == "GET" and "/read/" in request.url.path
        return httpx.Response(200, json={"code": 200, "success": True, "data": current})

    try:
        async with factory() as session:
            await create_source(
                session,
                request=SourceCreateRequest(
                    source_id="rajwin",
                    display_name="Fixture",
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
                    login_username="reward-fixture",
                    display_name="Fixture",
                    credentials=RemoteAccountCredentialsWrite(
                        password="synthetic-fixture-password", totp_secret="JBSWY3DPEHPK3PXP"
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
                sql_update(RemoteAccountCapability)
                .where(
                    RemoteAccountCapability.account_id == account_id,
                )
                .values(enabled=False)
            )
            for capability, enabled in (
                ("ERP_REMOTE_CHECK", read_allowed),
                ("ERP_REDEMPTION_UPDATE", update_allowed),
            ):
                await session.execute(
                    sql_update(RemoteAccountCapability)
                    .where(
                        RemoteAccountCapability.account_id == account_id,
                        RemoteAccountCapability.capability == capability,
                    )
                    .values(enabled=enabled)
                )
            await session.commit()
            projection = (
                await get_erp_compatibility_ids(
                    session, entity_type="remote_account", canonical_ids=[account_id]
                )
            )[account_id]
            payload = ErpCompatibilityRemoteRewardUpdateRequest(
                **{
                    **expectation().model_dump(),
                    "account_id": projection,
                    "bonus_max_amount": Decimal(7),
                },
                execution_confirmed=True,
            )
            if not read_allowed or not update_allowed:
                with pytest.raises(ErpCompatibilityRemoteExecutionError, match="能力|授权"):
                    await execute_compatibility_remote_reward_update(
                        session,
                        payload=payload,
                        actor_user_id=1,
                        settings=settings,
                        transport=httpx.MockTransport(handler),
                    )
                assert not calls
            else:
                result = await execute_compatibility_remote_reward_update(
                    session,
                    payload=payload,
                    actor_user_id=1,
                    settings=settings,
                    transport=httpx.MockTransport(handler),
                )
                assert result.matched and result.actual_bonus_max_amount == 7
                assert sum(method == "PUT" for method, _ in calls) == 1
                assert not any("/save" in path or method == "DELETE" for method, path in calls)
    finally:
        await engine.dispose()
