from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.settings import Settings
from packages.domain.models import Base
from packages.domain.schemas.remote_account import (
    ErpCompatibilityRemoteCreateOptions,
    ErpCompatibilityRemoteCreateRequest,
    ErpCompatibilityRemotePublishRequest,
    RemoteAccountCreateRequest,
    RemoteAccountCredentialsWrite,
)
from packages.domain.schemas.source import SourceCreateRequest, SourcePatchRequest
from packages.domain.services.erp_compatibility_id_service import get_erp_compatibility_ids
from packages.domain.services.erp_compatibility_redemption_remote_service import (
    ErpCompatibilityRemoteExecutionError,
    execute_compatibility_remote_create,
    execute_compatibility_remote_publish,
)
from packages.domain.services.remote_account_service import create_remote_account
from packages.domain.services.source_service import create_source, upsert_source


def _settings() -> Settings:
    return Settings(
        environment="development",
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )


def _payload(account_id: int) -> ErpCompatibilityRemoteCreateRequest:
    return ErpCompatibilityRemoteCreateRequest(
        account_id=account_id,
        issue_id=42,
        description="NEW-901到907存款100",
        claim_date=date(2026, 9, 8),
        label_ids=[901091],
        bonus_amount=Decimal("1"),
        bonus_max_amount=Decimal("3"),
        options=ErpCompatibilityRemoteCreateOptions(
            publish_environment="test",
            flow_times=5,
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
        ),
        execution_confirmed=True,
    )


@pytest.mark.asyncio
async def test_compatibility_create_uses_mapped_unified_account_without_legacy_secret() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings()
    captured: dict[str, object] = {}

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
            payload=_payload(compatibility_id),
            actor_user_id=1,
            settings=settings,
            transport=httpx.MockTransport(handler),
        )

    assert result.remote_configuration_id == "cfg-1"
    assert result.remote_group_key == "group-1"
    assert result.remote_request_id == "create-1"
    assert captured["label_array"] == [901091]
    assert captured["reward_min"] == "1"
    assert captured["reward_max"] == "3"
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
