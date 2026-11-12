from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

import httpx
import pytest
from openpyxl import Workbook
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.settings import Settings
from packages.domain.models import Base, RemoteAccountCapability, SecurityAuditLog
from packages.domain.schemas.remote_account import (
    ErpCompatibilityRemoteCancelRequest,
    ErpCompatibilityRemoteCreateOptions,
    ErpCompatibilityRemoteCreateRequest,
    ErpCompatibilityRemoteDownloadRequest,
    ErpCompatibilityRemotePublishRequest,
    ErpCompatibilityRemoteVerifyRequest,
    RemoteAccountCreateRequest,
    RemoteAccountCredentialsWrite,
)
from packages.domain.schemas.source import SourceCreateRequest, SourcePatchRequest
from packages.domain.services.erp_compatibility_id_service import get_erp_compatibility_ids
from packages.domain.services.erp_compatibility_redemption_remote_service import (
    ErpCompatibilityRemoteExecutionError,
    execute_compatibility_remote_cancel,
    execute_compatibility_remote_create,
    execute_compatibility_remote_download,
    execute_compatibility_remote_publish,
    execute_compatibility_remote_verify,
)
from packages.domain.services.erp_remote_account_tag_service import (
    sync_remote_account_tags,
)
from packages.domain.services.remote_account_service import create_remote_account
from packages.domain.services.source_service import create_source, upsert_source


def _settings() -> Settings:
    return Settings(
        environment="development",
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )


def _payload(
    account_id: int, key_number: int = 1, gift_code: str | None = None
) -> ErpCompatibilityRemoteCreateRequest:
    return ErpCompatibilityRemoteCreateRequest(
        account_id=account_id,
        issue_id=42,
        description="NEW-901到907存款100",
        claim_date=date(2026, 9, 8),
        valid_from=date(2026, 9, 9),
        valid_to=date(2026, 9, 10),
        label_ids=[901091],
        bonus_amount=Decimal("1"),
        bonus_max_amount=Decimal("3"),
        gift_code=gift_code,
        options=ErpCompatibilityRemoteCreateOptions(
            publish_environment="test",
            flow_times=5,
            key_number=key_number,
            single_user_limit=1,
            single_key_limit=3,
            require_bind_bank_card=False,
            require_bind_phone=True,
            check_uuid=True,
            uuid_reward_limit=1,
            check_login_ip=True,
            login_ip_reward_limit=1,
            check_register_ip=True,
            register_ip_reward_limit=1,
        ),
        execution_confirmed=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key_number,gift_code,pending_review",
    [
        (1, "0908raj7days100", False),
        (1, "0908rajfree", False),
        (1, "0908raj200", False),
        (1, None, False),
        (5, None, False),
        (50, None, False),
        (1, "0908raj3000", True),
    ],
)
async def test_compatibility_create_uses_mapped_unified_account_without_legacy_secret(
    key_number: int, gift_code: str | None, pending_review: bool
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings()
    captured: dict[str, object] = {}
    special = gift_code is not None
    login_count = 0
    codes = [gift_code] if gift_code else [f"TEST-CODE-{index}" for index in range(key_number)]
    workbook = Workbook()
    workbook.active.append(["兑换码号码"])
    for code in codes:
        workbook.active.append([code])
    output = BytesIO()
    workbook.save(output)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_count
        if request.url.path == "/api/system/login":
            login_count += 1
            # The credentials remain inside the Python executor.  This mocked
            # remote endpoint sees only the normal login request, not a Java
            # compatibility credential payload.
            return httpx.Response(200, json={"success": True, "data": {"token": "test-jwt"}})
        if request.url.path == "/api/common/giftCodeConfig/save":
            captured.update(json.loads(request.content))
            if pending_review:
                return httpx.Response(
                    200,
                    json={
                        "code": 200,
                        "success": True,
                        "data": {"id": -1},
                        "message": (
                            "你提交的配置触发风控规则，需主管审核通过后才可以生成配置，"
                            "配置生成后需自行发布配置兑换码才生效"
                        ),
                    },
                )
            if any(type(captured.get(field)) is not int for field in ("reward_min", "reward_max")):
                return httpx.Response(500, json={"message": "money must be of type int"})
            if captured.get("gift_type") != int(special):
                return httpx.Response(
                    200,
                    json={"success": False, "message": "兑换码类型 字段是必须的"},
                )
            if captured.get("reward_condition_type") != 0:
                return httpx.Response(
                    200,
                    json={"success": False, "message": "领奖判断条件 字段是必须的"},
                )
            if captured.get("refresh_flag") != 0:
                return httpx.Response(
                    200,
                    json={"success": False, "message": "是否刷新每日兑换码配置 字段是必须的"},
                )
            return httpx.Response(
                200,
                headers={"x-request-id": "create-1"},
                json={"data": {"id": "cfg-1"}},
            )
        if request.url.path == "/api/common/giftCodeConfig/index":
            return httpx.Response(
                200,
                json={"data": {"items": [{"id": "cfg-1", "group_key": "group-1"}]}},
            )
        if request.url.path == "/api/common/giftCodeConfig/export":
            assert request.url.params["groupKey"] == "group-1"
            return httpx.Response(200, content=output.getvalue())
        raise AssertionError(request.url)

    async with factory() as session:
        await create_source(
            session,
            request=SourceCreateRequest(
                source_id="rajwin",
                display_name="RajWin",
                base_url="https://remote.example",
                enabled=False,
            ),
            actor_user_id=1,
            settings=settings,
        )
        account = await create_remote_account(
            session,
            request=RemoteAccountCreateRequest(
                source_id="rajwin",
                login_username="current-enabled-account",
                display_name="当前启用账号",
                credentials=RemoteAccountCredentialsWrite(
                    password="test-password",
                    totp_secret="JBSWY3DPEHPK3PXP",
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
        compatibility_id = (
            await get_erp_compatibility_ids(
                session,
                entity_type="remote_account",
                canonical_ids=[account.account.id],
            )
        )[account.account.id]

        if pending_review:
            with pytest.raises(ErpCompatibilityRemoteExecutionError, match="待远端主管审核"):
                await execute_compatibility_remote_create(
                    session,
                    payload=_payload(compatibility_id, key_number, gift_code),
                    actor_user_id=1,
                    settings=settings,
                    transport=httpx.MockTransport(handler),
                )
            audits = (
                await session.scalars(
                    select(SecurityAuditLog).where(
                        SecurityAuditLog.action == "erp_compatibility_redemption.remote_create"
                    )
                )
            ).all()
            assert len(audits) == 1
            assert audits[0].result == "pending_review"
            assert audits[0].metadata_json == {"issue_id": 42, "operation": "CREATE"}
            assert login_count == 1
            await session.close()
            await engine.dispose()
            return

        result = await execute_compatibility_remote_create(
            session,
            payload=_payload(compatibility_id, key_number, gift_code),
            actor_user_id=1,
            settings=settings,
            transport=httpx.MockTransport(handler),
        )

        assert result.remote_configuration_id == "cfg-1"
        receipt = await session.scalar(
            select(SecurityAuditLog).where(
                SecurityAuditLog.action == "erp_compatibility_redemption.remote_create",
                SecurityAuditLog.result == "success",
            )
        )
        assert receipt.metadata_json["remote_configuration_id"] == "cfg-1"
        assert receipt.metadata_json["source_id"] == "rajwin"
        assert receipt.metadata_json["issue_id"] == 42
        assert captured["valid_time"] == [
            "2026-09-09 00:00:00",
            "2026-09-10 23:59:59",
        ]
        download_request = ErpCompatibilityRemoteDownloadRequest(
            account_id=compatibility_id,
            issue_id=42,
            remote_configuration_id="cfg-1",
            remote_group_key="group-1",
            key_number=key_number,
            execution_confirmed=True,
        )
        downloaded = await execute_compatibility_remote_download(
            session,
            payload=download_request,
            actor_user_id=1,
            settings=settings,
            transport=httpx.MockTransport(handler),
        )
        assert downloaded.redemption_code.splitlines() == codes
        assert login_count == 1  # New adapter instances reuse the unified account session.

        def remote_must_not_be_called(request: httpx.Request) -> httpx.Response:
            raise AssertionError("Unconfirmed download must not reach the remote")

        with pytest.raises(ErpCompatibilityRemoteExecutionError):
            await execute_compatibility_remote_download(
                session,
                payload=download_request.model_copy(update={"execution_confirmed": False}),
                actor_user_id=1,
                settings=settings,
                transport=httpx.MockTransport(remote_must_not_be_called),
            )
    assert result.remote_group_key == "group-1"
    assert result.remote_request_id == "create-1"
    assert captured["label_array"] == [901091]
    assert captured["gift_type"] == int(special)
    assert captured["reward_condition_type"] == 0
    assert captured["refresh_flag"] == 0
    assert captured["no_label_array"] == []
    assert captured["channel_type"] == 1
    assert captured["face_channel"] == []
    assert captured["no_face_channel"] == []
    assert type(captured["reward_min"]) is int and captured["reward_min"] == 1
    assert type(captured["reward_max"]) is int and captured["reward_max"] == 3
    assert captured["single_key_limit"] == 3
    if special:
        assert "key_number" not in captured
        assert captured["gift_code"] == gift_code
    else:
        assert "gift_code" not in captured
        assert int(captured["key_number"]) == key_number
    await engine.dispose()


@pytest.mark.asyncio
async def test_compatibility_create_rejects_an_unknown_numeric_account_before_remote_io() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    def remote_must_not_be_called(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected remote request: {request.url}")

    async with factory() as session:
        with pytest.raises(ErpCompatibilityRemoteExecutionError, match="兼容 ID"):
            await execute_compatibility_remote_create(
                session,
                payload=_payload(9_000_000_000_123),
                actor_user_id=1,
                settings=_settings(),
                transport=httpx.MockTransport(remote_must_not_be_called),
            )
    await engine.dispose()


@pytest.mark.asyncio
async def test_compatibility_publish_uses_mapped_unified_account_and_publish_capability() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings()
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/system/login":
            return httpx.Response(200, json={"success": True, "data": {"token": "test-jwt"}})
        if request.url.path == "/api/common/publishTask/save":
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                headers={"x-request-id": "publish-request-1"},
                json={"data": {"id": "publish-1"}},
            )
        raise AssertionError(request.url)

    async with factory() as session:
        await create_source(
            session,
            request=SourceCreateRequest(
                source_id="rajwin",
                display_name="RajWin",
                base_url="https://remote.example",
                enabled=False,
            ),
            actor_user_id=1,
            settings=settings,
        )
        account = await create_remote_account(
            session,
            request=RemoteAccountCreateRequest(
                source_id="rajwin",
                login_username="current-enabled-account",
                display_name="当前启用账号",
                credentials=RemoteAccountCredentialsWrite(
                    password="test-password",
                    totp_secret="JBSWY3DPEHPK3PXP",
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
        compatibility_id = (
            await get_erp_compatibility_ids(
                session,
                entity_type="remote_account",
                canonical_ids=[account.account.id],
            )
        )[account.account.id]

        result = await execute_compatibility_remote_publish(
            session,
            payload=ErpCompatibilityRemotePublishRequest(
                account_id=compatibility_id,
                batch_id=24,
                publish_environment="prod",
                mode="SCHEDULED",
                scheduled_time=datetime(2026, 9, 5, 18, 30),
                fallback_to_scheduled=False,
                execution_confirmed=True,
            ),
            actor_user_id=1,
            settings=settings,
            transport=httpx.MockTransport(handler),
        )

    assert result.remote_publish_task_id == "publish-1"
    assert result.remote_request_id == "publish-request-1"
    assert captured == {
        "env": "prod",
        "publish_type": "2",
        "cfg_type": 19,
        "scheduled_time": "2026-09-05 18:30:00",
    }
    await engine.dispose()


@pytest.mark.asyncio
async def test_tag_sync_uses_unified_account_and_replaces_the_local_snapshot() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/system/login":
            return httpx.Response(200, json={"success": True, "data": {"token": "test-jwt"}})
        if request.url.path == "/api/common/profileTag/remote":
            body = json.loads(request.content)
            assert body["remoteOption"]["select"] == ["tag_id", "name"]
            return httpx.Response(
                200,
                headers={"x-request-id": "tags-1"},
                json={
                    "success": True,
                    "data": [
                        {"tag_id": 901990, "name": "(901990)日充值100-199 "},
                        {"tag_id": 901991, "name": "(901991)日充值200-999 "},
                    ],
                },
            )
        raise AssertionError(request.url)

    async with factory() as session:
        await create_source(
            session,
            request=SourceCreateRequest(
                source_id="rajwin",
                display_name="RajWin",
                base_url="https://remote.example",
                enabled=False,
            ),
            actor_user_id=1,
            settings=settings,
        )
        account = await create_remote_account(
            session,
            request=RemoteAccountCreateRequest(
                source_id="rajwin",
                login_username="current-enabled-account",
                display_name="当前启用账号",
                credentials=RemoteAccountCredentialsWrite(
                    password="test-password",
                    totp_secret="JBSWY3DPEHPK3PXP",
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

        result = await sync_remote_account_tags(
            session,
            account_id=account.account.id,
            actor_user_id=1,
            execution_authorized=True,
            settings=settings,
            transport=httpx.MockTransport(handler),
        )

    assert result.exists is True
    assert result.source == "REMOTE"
    assert [tag.id for tag in result.tags] == [901990, 901991]
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", ["success", "rejected", "unconfirmed", "no_capability", "unknown_account"]
)
async def test_compatibility_cancel_uses_unified_authorization_and_remote_task_id(
    scenario: str,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings()
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/api/system/login":
            return httpx.Response(200, json={"success": True, "data": {"token": "test-jwt"}})
        assert request.url.path == "/api/common/publishTask/cancelAuto"
        assert request.method == "POST"
        assert json.loads(request.content) == {"id": 17717}
        return httpx.Response(
            200,
            headers={"x-request-id": "cancel-1"},
            json={
                "success": True,
                "data": {"ret": 0 if scenario == "rejected" else 1},
            },
        )

    async with factory() as session:
        await create_source(
            session,
            request=SourceCreateRequest(
                source_id="rajwin",
                display_name="RajWin",
                base_url="https://remote.example",
                enabled=False,
            ),
            actor_user_id=1,
            settings=settings,
        )
        account = await create_remote_account(
            session,
            request=RemoteAccountCreateRequest(
                source_id="rajwin",
                login_username="current-enabled-account",
                display_name="当前启用账号",
                credentials=RemoteAccountCredentialsWrite(
                    password="test-password",
                    totp_secret="JBSWY3DPEHPK3PXP",
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
        compatibility_id = (
            await get_erp_compatibility_ids(
                session,
                entity_type="remote_account",
                canonical_ids=[account.account.id],
            )
        )[account.account.id]

        if scenario == "no_capability":
            await session.execute(
                update(RemoteAccountCapability)
                .where(
                    RemoteAccountCapability.account_id == account.account.id,
                    RemoteAccountCapability.capability == "ERP_REDEMPTION_CANCEL",
                )
                .values(enabled=False)
            )
            await session.commit()
        payload = ErpCompatibilityRemoteCancelRequest(
            account_id=compatibility_id if scenario != "unknown_account" else 9_000_000_000_999,
            batch_id=24,
            remote_publish_task_id="17717",
            execution_confirmed=True,
        )
        if scenario == "unconfirmed":
            payload = payload.model_copy(update={"execution_confirmed": False})
        kwargs = dict(
            payload=payload,
            actor_user_id=1,
            settings=settings,
            transport=httpx.MockTransport(handler),
        )
        if scenario == "success":
            result = await execute_compatibility_remote_cancel(session, **kwargs)
            assert result.remote_request_id == "cancel-1"
        else:
            with pytest.raises(ErpCompatibilityRemoteExecutionError):
                await execute_compatibility_remote_cancel(session, **kwargs)
        audit = await session.scalar(
            select(SecurityAuditLog).where(
                SecurityAuditLog.action == "erp_compatibility_redemption.remote_cancel",
            )
        )
        assert audit.result == ("success" if scenario == "success" else "failure")
        assert audit.metadata_json["batch_id"] == 24
        if scenario in {"no_capability", "unconfirmed", "unknown_account"}:
            assert requests == []
        else:
            assert requests.count("/api/common/publishTask/cancelAuto") == 1
    await engine.dispose()


@pytest.mark.parametrize("task_id,confirmed", [("", True), ("PENDING:123", True), ("17717", False)])
def test_compatibility_cancel_rejects_invalid_task_or_missing_confirmation(task_id, confirmed):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ErpCompatibilityRemoteCancelRequest(
            account_id=23,
            batch_id=24,
            remote_publish_task_id=task_id,
            execution_confirmed=confirmed,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [True, False])
async def test_publication_verification_uses_unified_account_read_capability(authorized):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings()
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/system/login":
            return httpx.Response(200, json={"data": {"token": "test-jwt"}})
        assert request.method == "GET"
        assert request.url.path == "/api/common/publishTask/index"
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [{"id": 222, "status": 4, "env": "test", "cfg_type": 19}],
                    "pageInfo": {"currentPage": 1, "totalPage": 1},
                }
            },
        )

    async with factory() as session:
        await create_source(
            session,
            request=SourceCreateRequest(
                source_id="rajwin",
                display_name="RajWin",
                base_url="https://remote.example",
                enabled=False,
            ),
            actor_user_id=1,
            settings=settings,
        )
        account = await create_remote_account(
            session,
            request=RemoteAccountCreateRequest(
                source_id="rajwin",
                login_username="current-enabled-account",
                display_name="当前启用账号",
                credentials=RemoteAccountCredentialsWrite(
                    password="test-password",
                    totp_secret="JBSWY3DPEHPK3PXP",
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
        compatibility_id = (
            await get_erp_compatibility_ids(
                session,
                entity_type="remote_account",
                canonical_ids=[account.account.id],
            )
        )[account.account.id]

        if not authorized:
            await session.execute(
                update(RemoteAccountCapability)
                .where(
                    RemoteAccountCapability.account_id == account.account.id,
                    RemoteAccountCapability.capability == "ERP_REDEMPTION_DOWNLOAD",
                )
                .values(enabled=False)
            )
            await session.commit()
        request = ErpCompatibilityRemoteVerifyRequest(
            account_id=compatibility_id,
            batch_id=54,
            remote_publish_task_id="222",
            publish_environment="test",
        )
        if authorized:
            result = await execute_compatibility_remote_verify(
                session,
                payload=request,
                actor_user_id=1,
                settings=settings,
                transport=httpx.MockTransport(handler),
            )
            assert result.publication_state == "COMPLETED"
        else:
            with pytest.raises(ErpCompatibilityRemoteExecutionError):
                await execute_compatibility_remote_verify(
                    session,
                    payload=request,
                    actor_user_id=1,
                    settings=settings,
                    transport=httpx.MockTransport(handler),
                )
            assert calls == []
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("read_allowed", [False, True])
async def test_reuse_check_requires_read_capability_and_never_uses_business_write_capabilities(
    read_allowed,
):
    from test_redemption_reuse_check import expectation, remote_read

    from packages.domain.services.erp_compatibility_redemption_remote_service import (
        check_compatibility_remote_reuse,
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
        assert (
            request.method == "GET" and request.url.path == "/api/common/giftCodeConfig/read/3403"
        )
        return httpx.Response(200, json={"success": True, "data": remote_read()})

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
            payload = expectation().model_copy(update={"account_id": projection})
            if read_allowed:
                result = await check_compatibility_remote_reuse(
                    session,
                    payload=payload,
                    actor_user_id=1,
                    settings=settings,
                    transport=httpx.MockTransport(handler),
                )
                assert result.matched
                assert requests == [
                    ("POST", "/api/system/login"),
                    ("GET", "/api/common/giftCodeConfig/read/3403"),
                ]
            else:
                with pytest.raises(ErpCompatibilityRemoteExecutionError, match="配置读取能力"):
                    await check_compatibility_remote_reuse(
                        session,
                        payload=payload,
                        actor_user_id=1,
                        settings=settings,
                        transport=httpx.MockTransport(handler),
                    )
                assert requests == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "read_allowed,download_allowed,imported",
    [
        (False, True, True),
        (True, False, True),
        (True, False, False),
        (True, True, True),
    ],
)
async def test_missing_recovery_uses_read_and_inventory_capabilities_without_granting_create(
    read_allowed,
    download_allowed,
    imported,
):
    from test_redemption_reuse_check import expectation

    from packages.domain.schemas.remote_account import ErpCompatibilityRemoteRecoveryCheckRequest
    from packages.domain.services.erp_compatibility_redemption_remote_service import (
        check_compatibility_remote_recovery,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings, requests = _settings(), []
    book = Workbook()
    book.active.append(["兑换码号码"])
    output = BytesIO()
    book.save(output)
    book.close()

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/system/login":
            return httpx.Response(200, json={"success": True, "data": {"token": "fixture"}})
        if "/read/" in request.url.path:
            data = []
        elif request.url.path.endswith("/index"):
            data = {"items": [], "pageInfo": {"currentPage": 1, "totalPage": 1, "total": 0}}
        elif request.url.path.endswith("/export"):
            return httpx.Response(200, content=output.getvalue())
        else:
            raise AssertionError("Recovery checks must never create, update, or publish")
        return httpx.Response(200, json={"code": 200, "success": True, "data": data})

    try:
        async with factory() as session:
            await create_source(
                session,
                request=SourceCreateRequest(
                    source_id="rajwin",
                    display_name="Recovery fixture",
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
                    login_username="recovery-fixture",
                    display_name="Fixture",
                    credentials=RemoteAccountCredentialsWrite(
                        password="synthetic-fixture-password",
                        totp_secret="JBSWY3DPEHPK3PXP",
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
                .where(
                    RemoteAccountCapability.account_id == account_id,
                )
                .values(enabled=False)
            )
            for capability, enabled in (
                ("ERP_REMOTE_CHECK", read_allowed),
                ("ERP_REDEMPTION_DOWNLOAD", download_allowed),
            ):
                await session.execute(
                    update(RemoteAccountCapability)
                    .where(
                        RemoteAccountCapability.account_id == account_id,
                        RemoteAccountCapability.capability == capability,
                    )
                    .values(enabled=enabled)
                )
            await session.commit()
            projection = (
                await get_erp_compatibility_ids(
                    session,
                    entity_type="remote_account",
                    canonical_ids=[account_id],
                )
            )[account_id]
            payload = ErpCompatibilityRemoteRecoveryCheckRequest(
                **{**expectation().model_dump(), "account_id": projection},
                check_inventory=imported,
                remote_group_key="original-group",
            )
            if not read_allowed or imported and not download_allowed:
                with pytest.raises(ErpCompatibilityRemoteExecutionError, match="能力"):
                    await check_compatibility_remote_recovery(
                        session,
                        payload=payload,
                        actor_user_id=1,
                        settings=settings,
                        transport=httpx.MockTransport(handler),
                    )
                assert not requests
            else:
                result = await check_compatibility_remote_recovery(
                    session,
                    payload=payload,
                    actor_user_id=1,
                    settings=settings,
                    transport=httpx.MockTransport(handler),
                )
                assert result.state == "ABSENT"
                assert sum(path.endswith("/index") for _, path in requests) == 2
                assert sum(path.endswith("/export") for _, path in requests) == int(imported)
    finally:
        await engine.dispose()
