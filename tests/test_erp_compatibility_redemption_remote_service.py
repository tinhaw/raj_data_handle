from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

import httpx
import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.settings import Settings
from packages.domain.models import Base, SecurityAuditLog
from packages.domain.schemas.remote_account import (
    ErpCompatibilityRemoteCreateOptions,
    ErpCompatibilityRemoteCreateRequest,
    ErpCompatibilityRemoteDownloadRequest,
    ErpCompatibilityRemotePublishRequest,
    RemoteAccountCreateRequest,
    RemoteAccountCredentialsWrite,
)
from packages.domain.schemas.source import SourceCreateRequest, SourcePatchRequest
from packages.domain.services.erp_compatibility_id_service import get_erp_compatibility_ids
from packages.domain.services.erp_compatibility_redemption_remote_service import (
    ErpCompatibilityRemoteExecutionError,
    execute_compatibility_remote_create,
    execute_compatibility_remote_download,
    execute_compatibility_remote_publish,
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


def _payload(account_id: int, key_number: int = 1) -> ErpCompatibilityRemoteCreateRequest:
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
        options=ErpCompatibilityRemoteCreateOptions(
            publish_environment="test",
            flow_times=5,
            key_number=key_number,
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
        ),
        execution_confirmed=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("key_number", [1, 5])
async def test_compatibility_create_uses_mapped_unified_account_without_legacy_secret(
    key_number: int,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings()
    captured: dict[str, object] = {}
    codes = [f"TEST-CODE-{index}" for index in range(key_number)]
    workbook = Workbook()
    workbook.active.append(["兑换码号码"])
    for code in codes:
        workbook.active.append([code])
    output = BytesIO()
    workbook.save(output)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/system/login":
            # The credentials remain inside the Python executor.  This mocked
            # remote endpoint sees only the normal login request, not a Java
            # compatibility credential payload.
            return httpx.Response(200, json={"success": True, "data": {"token": "test-jwt"}})
        if request.url.path == "/api/common/giftCodeConfig/save":
            captured.update(json.loads(request.content))
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

        result = await execute_compatibility_remote_create(
            session,
            payload=_payload(compatibility_id, key_number),
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
    assert captured["reward_min"] == "1"
    assert captured["reward_max"] == "3"
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
