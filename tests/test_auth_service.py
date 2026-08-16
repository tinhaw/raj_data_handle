from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.settings import Settings
from packages.domain.models import Base, SecurityAuditLog, SystemSessionSetting
from packages.domain.schemas.auth import UserLogQueryRequest
from packages.domain.services.auth_service import (
    AuthError,
    authenticate_user,
    create_user,
    query_user_logs,
    record_page_access,
    revoke_session,
    validate_session,
)


@pytest.mark.asyncio
async def test_session_is_persisted_and_revocable() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    configured = Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
        session_ttl_days=45,
    )

    async with factory() as session:
        user = await create_user(
            session,
            username="admin",
            password="correct horse battery staple",
            display_name="Admin",
            role="admin",
            actor_user_id=None,
        )
        authenticated, token = await authenticate_user(
            session,
            username="ADMIN",
            password="correct horse battery staple",
            client_ip="127.0.0.1",
            user_agent="pytest",
            settings=configured,
        )
        validated = await validate_session(session, token, configured)
        assert validated.user.id == user.id
        assert validated.expires_at > datetime.now(UTC) + timedelta(days=44)

        await revoke_session(
            session,
            auth_session=authenticated.session,
            actor_user_id=user.id,
        )
        with pytest.raises(AuthError):
            await validate_session(session, token, configured)

    await engine.dispose()


@pytest.mark.asyncio
async def test_new_session_uses_persisted_session_duration() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    configured = Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
        session_ttl_days=30,
    )

    async with factory() as session:
        session.add(SystemSessionSetting(id=1, session_ttl_days=7))
        await session.commit()
        await create_user(
            session,
            username="operator",
            password="correct horse battery staple",
            display_name="Operator",
            role="user",
            actor_user_id=None,
        )
        authenticated, _ = await authenticate_user(
            session,
            username="operator",
            password="correct horse battery staple",
            client_ip="127.0.0.1",
            user_agent="pytest",
            settings=configured,
        )

    remaining = authenticated.expires_at - datetime.now(UTC)
    assert timedelta(days=6, hours=23, minutes=58) < remaining <= timedelta(days=7, minutes=1)
    await engine.dispose()


@pytest.mark.asyncio
async def test_session_uses_default_while_session_settings_migration_is_pending() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    configured = Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
        session_ttl_days=30,
    )

    async with factory() as session:
        await create_user(
            session,
            username="operator",
            password="correct horse battery staple",
            display_name="Operator",
            role="user",
            actor_user_id=None,
        )
        await session.execute(text("DROP TABLE system_session_settings"))
        await session.commit()
        authenticated, _ = await authenticate_user(
            session,
            username="operator",
            password="correct horse battery staple",
            client_ip="127.0.0.1",
            user_agent="pytest",
            settings=configured,
        )

    remaining = authenticated.expires_at - datetime.now(UTC)
    assert timedelta(days=29, hours=23, minutes=58) < remaining <= timedelta(days=30, minutes=1)
    await engine.dispose()


@pytest.mark.asyncio
async def test_user_logs_include_successful_logins_and_page_access_only() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        user = await create_user(
            session,
            username="operator",
            password="correct horse battery staple",
            display_name="Operator",
            role="user",
            actor_user_id=None,
        )
        session.add_all(
            [
                SecurityAuditLog(
                    actor_user_id=user.id,
                    action="login",
                    result="success",
                    created_at=datetime(2026, 8, 10, 8, 0, tzinfo=UTC),
                ),
                SecurityAuditLog(
                    action="login",
                    result="failure",
                    metadata_json={"username_hash": "not-visible"},
                    created_at=datetime(2026, 8, 10, 8, 1, tzinfo=UTC),
                ),
                SecurityAuditLog(
                    actor_user_id=user.id,
                    action="user.update",
                    result="success",
                    created_at=datetime(2026, 8, 10, 8, 2, tzinfo=UTC),
                ),
            ]
        )
        await session.commit()
        await record_page_access(session, actor_user_id=user.id, path="/withdraw-orders")

        result = await query_user_logs(
            session,
            request=UserLogQueryRequest(page=1, pageSize=50),
        )
        access_only = await query_user_logs(
            session,
            request=UserLogQueryRequest(
                userId=user.id,
                eventTypes=["access"],
                page=1,
                pageSize=50,
            ),
        )

    assert result.total == 2
    assert {item.event_type for item in result.items} == {"login", "access"}
    assert all(item.username == "operator" for item in result.items)
    assert access_only.total == 1
    assert access_only.items[0].path == "/withdraw-orders"
    await engine.dispose()
