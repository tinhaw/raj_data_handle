from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.routers.remote_accounts import _response
from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    RemoteAccount,
    RemoteAccountCapability,
    SecurityAuditLog,
    SourceConfig,
)
from packages.domain.schemas.remote_account import (
    RemoteAccountConnectionRequest,
    RemoteAccountCreateRequest,
    RemoteAccountCredentialsWrite,
    RemoteAccountPatchRequest,
    RemoteAccountSessionPolicyWrite,
)
from packages.domain.schemas.source import SourceCreateRequest, SourcePatchRequest
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    ErpRemoteAccountReadGrant,
    RajAdminGiftCodeAdapter,
)
from packages.domain.services.remote_account_connection_service import (
    operate_account_connection,
    run_due_account_relogins,
    save_session_policy,
)
from packages.domain.services.remote_account_credentials import credential_envelope_for_account
from packages.domain.services.remote_account_service import (
    create_remote_account,
    get_remote_account,
    update_remote_account,
)
from packages.domain.services.remote_account_session_service import (
    RemoteSessionError,
    account_session,
    session_public_state,
    token_expiry,
)
from packages.domain.services.remote_charge_service import RajAdminChargeClient
from packages.domain.services.source_service import create_source, upsert_source


@pytest.fixture
async def registry(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sessions.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        environment="development", secret_key="synthetic-unit-test-secret-32-characters"
    )
    ids = []
    async with factory() as session:
        for source_id in ("rajwin", "rajluck"):
            await create_source(
                session,
                request=SourceCreateRequest(
                    source_id=source_id,
                    display_name=source_id,
                    base_url=f"https://{source_id}.example",
                    enabled=False,
                ),
                actor_user_id=1,
                settings=settings,
            )
            view = await create_remote_account(
                session,
                request=RemoteAccountCreateRequest(
                    source_id=source_id,
                    login_username="mock-user",
                    display_name="Mock account",
                    credentials=RemoteAccountCredentialsWrite(
                        password="mock-password",
                        totp_secret="JBSWY3DPEHPK3PXP",
                    ),
                ),
                actor_user_id=1,
                settings=settings,
            )
            ids.append(view.account.id)
            await upsert_source(
                session,
                source_id=source_id,
                request=SourcePatchRequest(enabled=True),
                actor_user_id=1,
                settings=settings,
            )
    yield factory, settings, ids
    await engine.dispose()


async def provider(registry, index=0):
    factory, settings, ids = registry
    async with factory() as session:
        account = await session.get(RemoteAccount, ids[index])
        source = await session.get(SourceConfig, account.source_id)
        return account_session(
            session,
            envelope=credential_envelope_for_account(
                account=account,
                source=source,
            ),
            base_url=source.base_url,
            settings=settings,
        )


async def mutate(registry, **values):
    factory, _, ids = registry
    async with factory() as session:
        account = await session.get(RemoteAccount, ids[0])
        for key, value in values.items():
            setattr(account, key, value)
        await session.commit()


def grant(account_id):
    return ErpRemoteAccountReadGrant(
        account_id=account_id, source_id="rajwin", operation="CHECK", capability="ERP_REMOTE_CHECK"
    )


async def adapter(registry, handler):
    return RajAdminGiftCodeAdapter(
        account_id=registry[2][0],
        source_id="rajwin",
        base_url="https://rajwin.example",
        username="mock-user",
        password="mock-password",
        totp_secret="JBSWY3DPEHPK3PXP",
        business_timezone="Asia/Shanghai",
        transport=httpx.MockTransport(handler),
        remote_session=await provider(registry),
    )


@pytest.mark.asyncio
async def test_concurrent_and_cross_instance_login_is_single_and_durable(registry):
    logins = 0

    async def login():
        nonlocal logins
        logins += 1
        await asyncio.sleep(0.01)
        return "mock-session"

    providers = [await provider(registry) for _ in range(10)]
    await asyncio.gather(*(shared.token(login) for shared in providers))
    assert logins == 1
    await (await provider(registry)).token(login)
    assert logins == 1
    async with registry[0]() as session:
        view = await get_remote_account(session, account_id=registry[2][0])
        assert view.account.session_ciphertext.startswith("v1:")
        body = _response(view).model_dump()
        assert "session_ciphertext" not in body and "session_identity" not in body
        assert body["has_active_session"] is True
        assert body["session_expiry_estimated"] is True
        audits = list(
            await session.scalars(
                select(SecurityAuditLog).where(
                    SecurityAuditLog.action == "remote_account.login",
                )
            )
        )
        assert len(audits) == 1
        assert audits[0].metadata_json == {"reason": "request"}


@pytest.mark.asyncio
async def test_accounts_do_not_share_sessions(registry):
    logins = 0

    async def login():
        nonlocal logins
        logins += 1
        return "mock-session"

    for index in (0, 1, 0, 1):
        await (await provider(registry, index)).token(login)
    assert logins == 2


@pytest.mark.asyncio
async def test_erp_and_analysis_share_one_login(registry):
    logins = 0

    def handler(request):
        nonlocal logins
        if request.url.path == "/api/system/login":
            logins += 1
            return httpx.Response(200, json={"data": {"token": "mock-session"}})
        return httpx.Response(200, json={"data": [{"value": "mock", "label": "Mock"}]})

    async with await adapter(registry, handler) as client:
        await client.check_connection(grant=grant(registry[2][0]))
    async with RajAdminChargeClient(
        base_url="https://rajwin.example",
        username="mock-user",
        password="mock-password",
        totp_secret="JBSWY3DPEHPK3PXP",
        transport=httpx.MockTransport(handler),
        remote_session=await provider(registry),
    ) as analysis:
        await analysis.fetch_channels()
    async with await adapter(registry, handler) as client:
        await client.check_connection(grant=grant(registry[2][0]))
    assert logins == 1


@pytest.mark.asyncio
async def test_expiry_auto_login_and_manual_when_disabled(registry):
    logins = 0

    async def login():
        nonlocal logins
        logins += 1
        return f"mock-session-{logins}"

    shared = await provider(registry)
    await shared.token(login)
    past = datetime.now(UTC) - timedelta(minutes=1)
    await mutate(registry, session_expires_at=past, last_login_attempt_at=past)
    await shared.token(login)
    assert logins == 2
    await mutate(registry, session_expires_at=past, last_login_attempt_at=past, auto_relogin=False)
    with pytest.raises(RemoteSessionError, match="自动重登已关闭"):
        await shared.token(login)
    assert logins == 2
    await shared.token(login, force=True, reason="manual", actor_user_id=1)
    assert logins == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "auth_response",
    [(401, {}), (200, {"code": 401}), (200, {"success": False, "msg": "登录已过期"})],
)
async def test_expired_http_or_business_response_relogs_once(registry, auth_response):
    logins = 0
    checks = 0

    def handler(request):
        nonlocal logins, checks
        if request.url.path == "/api/system/login":
            logins += 1
            return httpx.Response(200, json={"data": {"token": f"mock-session-{logins}"}})
        checks += 1
        if checks == 2:
            return httpx.Response(auth_response[0], json=auth_response[1])
        return httpx.Response(200, json={"data": {"items": []}})

    async with await adapter(registry, handler) as client:
        await client.check_connection(grant=grant(registry[2][0]))
    await mutate(registry, last_login_attempt_at=datetime.now(UTC) - timedelta(minutes=1))
    async with await adapter(registry, handler) as client:
        await client.check_connection(grant=grant(registry[2][0]))
    assert logins == 2 and checks == 3


@pytest.mark.asyncio
async def test_permission_403_does_not_trigger_login_storm(registry):
    logins = 0

    def handler(request):
        nonlocal logins
        if request.url.path == "/api/system/login":
            logins += 1
            return httpx.Response(200, json={"data": {"token": "mock-session"}})
        return httpx.Response(403, json={"msg": "无操作权限"})

    for _ in range(2):
        async with await adapter(registry, handler) as client:
            with pytest.raises(ErpRedemptionRemoteHttpError):
                await client.check_connection(grant=grant(registry[2][0]))
    assert logins == 1


@pytest.mark.asyncio
async def test_rejected_fresh_login_stops_after_one_retry(registry):
    logins = 0
    checks = 0

    def handler(request):
        nonlocal logins, checks
        if request.url.path == "/api/system/login":
            logins += 1
            return httpx.Response(200, json={"data": {"token": f"mock-session-{logins}"}})
        checks += 1
        return httpx.Response(200, json={"data": []}) if checks == 1 else httpx.Response(401)

    async with await adapter(registry, handler) as client:
        await client.check_connection(grant=grant(registry[2][0]))
    await mutate(registry, last_login_attempt_at=datetime.now(UTC) - timedelta(minutes=1))
    async with await adapter(registry, handler) as client:
        with pytest.raises(ErpRedemptionRemoteHttpError, match="停止重试"):
            await client.check_connection(grant=grant(registry[2][0]))
    assert logins == 2 and checks == 3
    async with registry[0]() as session:
        view = await get_remote_account(session, account_id=registry[2][0])
        assert session_public_state(view.account, view.source)["session_status"] == "COOLDOWN"
        assert not view.account.session_ciphertext


@pytest.mark.asyncio
async def test_late_rejection_does_not_invalidate_another_callers_new_token(registry):
    shared = await provider(registry)

    async def first():
        return "mock-session-old"

    async def second():
        return "mock-session-new"

    old = await shared.token(first)
    await mutate(registry, last_login_attempt_at=datetime.now(UTC) - timedelta(minutes=1))
    await shared.token(second, force=True, reason="manual")
    await shared.reject(old)

    async def forbidden():
        pytest.fail("A newer shared session must be reused")

    await shared.token(forbidden, force=True, rejected_token=old)


@pytest.mark.asyncio
async def test_rate_limit_cooldown_survives_new_service_and_blocks_manual_retry(registry):
    calls = 0

    async def limited():
        nonlocal calls
        calls += 1
        raise ValueError("登录次数上限，稍后再尝试")

    with pytest.raises(RemoteSessionError, match="次数受限"):
        await (await provider(registry)).token(limited)
    with pytest.raises(RemoteSessionError, match="冷却"):
        await (await provider(registry)).token(limited, force=True, reason="manual")
    assert calls == 1
    async with registry[0]() as session:
        row = await session.get(RemoteAccount, registry[2][0])
        assert row.login_failure_count == 1
        assert row.session_last_error == "远端登录次数受限，已进入冷却，请勿反复重新登录。"


@pytest.mark.asyncio
async def test_explicit_check_then_relogin_and_status_persistence(registry):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"data": {"token": "mock-session", "items": []}})

    async with registry[0]() as session:
        await operate_account_connection(
            session,
            account_id=registry[2][0],
            operation="CHECK",
            execution_confirmed=True,
            actor_user_id=1,
            settings=registry[1],
            transport=httpx.MockTransport(handler),
        )
    await mutate(registry, last_login_attempt_at=datetime.now(UTC) - timedelta(minutes=1))
    async with registry[0]() as session:
        await operate_account_connection(
            session,
            account_id=registry[2][0],
            operation="RELOGIN",
            execution_confirmed=True,
            actor_user_id=1,
            settings=registry[1],
            transport=httpx.MockTransport(handler),
        )
        row = await session.get(RemoteAccount, registry[2][0])
        assert row.last_test_status == "SUCCESS" and row.last_tested_at is not None
        assert row.last_logged_in_at is not None
    assert paths == ["/api/system/login", "/api/common/giftCodeConfig/index", "/api/system/login"]


@pytest.mark.asyncio
async def test_periodic_login_is_opt_in_durable_and_not_driven_by_browser(registry):
    calls = 0

    def handler(request):
        nonlocal calls
        assert request.url.path == "/api/system/login"
        calls += 1
        return httpx.Response(200, json={"data": {"token": "mock-session"}})

    factory, settings, ids = registry
    async with factory() as session:
        assert (
            await run_due_account_relogins(
                session, settings=settings, transport=httpx.MockTransport(handler)
            )
            == 0
        )
        await save_session_policy(
            session,
            account_id=ids[0],
            actor_user_id=1,
            request=RemoteAccountSessionPolicyWrite(
                relogin_interval_minutes=15, execution_confirmed=True
            ),
        )
    assert calls == 0
    await mutate(registry, next_relogin_at=datetime.now(UTC) - timedelta(seconds=1))
    async with factory() as session:
        assert (
            await run_due_account_relogins(
                session, settings=settings, transport=httpx.MockTransport(handler)
            )
            == 1
        )
    async with factory() as session:
        assert (
            await run_due_account_relogins(
                session, settings=settings, transport=httpx.MockTransport(handler)
            )
            == 0
        )
        await save_session_policy(
            session, account_id=ids[0], actor_user_id=1, request=RemoteAccountSessionPolicyWrite()
        )
    assert calls == 1
    await mutate(registry, next_relogin_at=datetime.now(UTC) - timedelta(seconds=1))
    async with factory() as session:
        assert (
            await run_due_account_relogins(
                session, settings=settings, transport=httpx.MockTransport(handler)
            )
            == 0
        )


@pytest.mark.asyncio
async def test_disabled_account_and_missing_check_grant_make_no_remote_calls(registry):
    async def never():
        pytest.fail("disabled accounts must not log in")

    shared = await provider(registry)
    await mutate(registry, enabled=False)
    with pytest.raises(RemoteSessionError, match="停用"):
        await shared.token(never)
    await mutate(registry, enabled=True)
    async with registry[0]() as session:
        cap = await session.scalar(
            select(RemoteAccountCapability).where(
                RemoteAccountCapability.account_id == registry[2][0],
                RemoteAccountCapability.capability == "ERP_REMOTE_CHECK",
            )
        )
        cap.enabled = False
        await session.commit()
        with pytest.raises(RemoteSessionError, match="未获"):
            await operate_account_connection(
                session,
                account_id=registry[2][0],
                operation="CHECK",
                execution_confirmed=True,
                actor_user_id=1,
                settings=registry[1],
            )


@pytest.mark.parametrize("value", [0, 1, 14, 10081, 15.5])
def test_interval_validation(value):
    with pytest.raises(ValidationError):
        RemoteAccountSessionPolicyWrite(relogin_interval_minutes=value, execution_confirmed=True)


def test_explicit_confirmation_required_and_opaque_expiry_labelled():
    with pytest.raises(ValidationError):
        RemoteAccountConnectionRequest(operation="RELOGIN")
    with pytest.raises(ValidationError):
        RemoteAccountSessionPolicyWrite(relogin_interval_minutes=60)
    now = datetime.now(UTC)
    expiry, estimated = token_expiry("opaque-mock", now)
    assert expiry == now + timedelta(minutes=30) and estimated


@pytest.mark.asyncio
async def test_credential_changes_reject_old_identity_and_keep_cooldown(registry):
    old_provider = await provider(registry)

    async def initial_login():
        return "mock-session"

    await old_provider.token(initial_login)
    retry_after = datetime.now(UTC) + timedelta(minutes=15)
    await mutate(registry, login_retry_after=retry_after)
    async with registry[0]() as session:
        await update_remote_account(
            session,
            account_id=registry[2][0],
            request=RemoteAccountPatchRequest(
                credentials=RemoteAccountCredentialsWrite(password="new-mock-password")
            ),
            actor_user_id=1,
            settings=registry[1],
        )
        row = await session.get(RemoteAccount, registry[2][0])
        assert row.session_ciphertext is None
        assert row.login_retry_after is not None

    async def forbidden():
        pytest.fail("Stale credentials or a cooldown must block remote login")

    with pytest.raises(RemoteSessionError, match="配置已变化"):
        await old_provider.token(forbidden)
    with pytest.raises(RemoteSessionError, match="冷却"):
        await (await provider(registry)).token(forbidden)


@pytest.mark.asyncio
async def test_base_url_change_never_reuses_another_origins_session(registry):
    shared = await provider(registry)

    async def login():
        return "mock-session"

    await shared.token(login)
    async with registry[0]() as session:
        source = await session.get(SourceConfig, "rajwin")
        source.base_url = "https://changed.example"
        await session.commit()
        row = await session.get(RemoteAccount, registry[2][0])
        assert not session_public_state(row, source)["has_active_session"]
    with pytest.raises(RemoteSessionError, match="配置已变化"):
        await shared.token(login)


@pytest.mark.asyncio
async def test_scheduled_failure_advances_retry_without_login_storm(registry):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    await mutate(
        registry,
        relogin_interval_minutes=15,
        next_relogin_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    async with registry[0]() as session:
        assert (
            await run_due_account_relogins(
                session, settings=registry[1], transport=httpx.MockTransport(handler)
            )
            == 1
        )
    async with registry[0]() as session:
        assert (
            await run_due_account_relogins(
                session, settings=registry[1], transport=httpx.MockTransport(handler)
            )
            == 0
        )
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_schedules_refresh_once_and_do_not_audit_skipped_login(registry):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"token": "mock-session"}})

    await mutate(
        registry,
        relogin_interval_minutes=15,
        next_relogin_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    async def worker():
        async with registry[0]() as session:
            await operate_account_connection(
                session,
                account_id=registry[2][0],
                operation="SCHEDULED",
                execution_confirmed=True,
                actor_user_id=None,
                settings=registry[1],
                transport=httpx.MockTransport(handler),
            )

    await asyncio.gather(worker(), worker())
    assert calls == 1
    async with registry[0]() as session:
        audits = list(
            await session.scalars(
                select(SecurityAuditLog).where(
                    SecurityAuditLog.action == "remote_account.connection",
                )
            )
        )
        assert len(audits) == 1
