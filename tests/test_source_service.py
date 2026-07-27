from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.settings import Settings
from packages.domain.models import Base, ReconciliationBatch, SourceConfig
from packages.domain.schemas.source import SourceCreateRequest
from packages.domain.services.source_service import (
    SourceConflictError,
    SourceValidationError,
    create_source,
    delete_source,
    normalize_base_url,
    validate_source_id,
    validate_timezone,
)


def development_settings() -> Settings:
    return Settings(
        environment="development",
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )


def test_base_url_is_normalized_without_business_path() -> None:
    configured = development_settings()
    assert (
        normalize_base_url("https://admin.example.com/", configured) == "https://admin.example.com"
    )
    assert normalize_base_url("http://localhost:9000", configured) == "http://localhost:9000"


@pytest.mark.parametrize(
    "value",
    [
        "http://admin.example.com",
        "https://user:password@admin.example.com",
        "https://admin.example.com/api/orders",
        "https://admin.example.com?token=secret",
    ],
)
def test_unsafe_base_urls_are_rejected(value: str) -> None:
    with pytest.raises(SourceValidationError):
        normalize_base_url(value, development_settings())


def test_timezone_uses_iana_dictionary() -> None:
    assert validate_timezone("Asia/Kolkata") == "Asia/Kolkata"
    with pytest.raises(SourceValidationError):
        validate_timezone("IST")


@pytest.mark.parametrize("value", ["rajstar", "raj_star-2", "a1"])
def test_source_id_accepts_stable_slug(value: str) -> None:
    assert validate_source_id(value) == value


@pytest.mark.parametrize("value", ["Rajasthan", "1raj", "a", "raj star", "raj/star"])
def test_source_id_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(SourceValidationError):
        validate_source_id(value)


@pytest.mark.asyncio
async def test_custom_source_can_be_created_and_deleted() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        request = SourceCreateRequest(
            source_id="rajstar",
            display_name="RajStar",
        )
        created = await create_source(
            session,
            request=request,
            actor_user_id=1,
            settings=development_settings(),
        )
        assert created.source_id == "rajstar"
        assert created.enabled is False

        with pytest.raises(SourceConflictError):
            await create_source(
                session,
                request=request,
                actor_user_id=1,
                settings=development_settings(),
            )

        await delete_source(session, source_id="rajstar", actor_user_id=1)
        assert await session.get(SourceConfig, "rajstar") is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_preset_source_can_be_deleted_but_historically_used_source_cannot() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        preset = SourceConfig(
            source_id="rajwin",
            display_name="RajWin",
            business_timezone="Asia/Kolkata",
            currency="INR",
        )
        custom = SourceConfig(
            source_id="rajstar",
            display_name="RajStar",
            business_timezone="Asia/Kolkata",
            currency="INR",
        )
        session.add_all([preset, custom])
        await session.commit()

        await delete_source(session, source_id="rajwin", actor_user_id=1)
        assert await session.get(SourceConfig, "rajwin") is None

        batch = ReconciliationBatch(
            source_id="rajstar",
            source_display_name="RajStar",
            source_config_version=1,
            source_business_timezone="Asia/Kolkata",
            source_currency="INR",
            business_type="payin",
            uploaded_file_name="test.xlsx",
            uploaded_file_sha256="a" * 64,
            execution_requested_by=1,
            created_by=1,
            result_expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        session.add(batch)
        await session.commit()

        with pytest.raises(SourceConflictError, match="历史比对批次"):
            await delete_source(session, source_id="rajstar", actor_user_id=1)

    await engine.dispose()
