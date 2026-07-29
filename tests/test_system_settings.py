from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.routers.system_settings import _response
from packages.common.settings import Settings
from packages.domain.models import Base, SecurityAuditLog, SystemRetentionSetting
from packages.domain.schemas.system_setting import RetentionSettingsUpdateRequest
from packages.domain.services.session_setting_service import get_session_settings
from packages.domain.services.system_setting_service import (
    get_retention_settings,
    update_retention_settings,
)


@pytest.mark.parametrize("refresh_interval_hours", [1, 24])
async def test_retention_defaults_and_versioned_update(refresh_interval_hours: int) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        defaults = Settings(
            secret_key="test-secret-key-that-is-longer-than-32-characters",
            database_url="sqlite+aiosqlite:///:memory:",
            uploaded_file_retention_days=3,
            result_retention_days=30,
            remote_cache_retention_days=30,
            session_ttl_days=30,
        )
        current = await get_retention_settings(session, defaults=defaults)
        session_settings = await get_session_settings(session, defaults=defaults)
        assert current.uploaded_file_retention_days == 3
        assert current.result_retention_days == 30
        assert current.remote_cache_retention_days == 30
        assert current.withdraw_order_refresh_interval_hours == 1
        assert session_settings is not None
        assert session_settings.session_ttl_days == 30

        updated, updated_session_settings = await update_retention_settings(
            session,
            payload=RetentionSettingsUpdateRequest(
                uploadedFileRetentionDays=5,
                resultRetentionDays=45,
                remoteCacheRetentionDays=60,
                withdrawOrderRefreshIntervalHours=refresh_interval_hours,
                sessionTtlDays=45,
            ),
            actor_user_id=1,
        )
        audit = await session.scalar(
            select(SecurityAuditLog).where(SecurityAuditLog.action == "system.settings.update")
        )

    assert updated.config_version == 2
    assert updated.uploaded_file_retention_days == 5
    assert updated.result_retention_days == 45
    assert updated.remote_cache_retention_days == 60
    assert updated.withdraw_order_refresh_interval_hours == refresh_interval_hours
    assert updated_session_settings.session_ttl_days == 45
    assert audit is not None
    assert audit.metadata_json["previous"]["withdrawOrderRefreshIntervalHours"] == 1
    assert (
        audit.metadata_json["current"]["withdrawOrderRefreshIntervalHours"]
        == refresh_interval_hours
    )
    await engine.dispose()


def test_system_settings_api_response_exposes_refresh_interval_in_camel_case() -> None:
    response = _response(
        SystemRetentionSetting(
            id=1,
            uploaded_file_retention_days=3,
            result_retention_days=30,
            remote_cache_retention_days=30,
            withdraw_order_refresh_interval_hours=24,
            config_version=1,
            updated_at=datetime.now(UTC),
        ),
        session_ttl_days=30,
    )

    assert response.model_dump(by_alias=True)["withdrawOrderRefreshIntervalHours"] == 24


@pytest.mark.parametrize("value", [1, 24])
def test_withdraw_order_refresh_interval_accepts_configured_boundaries(value: int) -> None:
    payload = RetentionSettingsUpdateRequest(
        uploadedFileRetentionDays=3,
        resultRetentionDays=30,
        remoteCacheRetentionDays=30,
        withdrawOrderRefreshIntervalHours=value,
        sessionTtlDays=30,
    )

    assert payload.withdraw_order_refresh_interval_hours == value


@pytest.mark.parametrize("value", [0, 25])
def test_withdraw_order_refresh_interval_is_limited_to_one_through_twenty_four(
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        RetentionSettingsUpdateRequest(
            uploadedFileRetentionDays=3,
            resultRetentionDays=30,
            remoteCacheRetentionDays=30,
            withdrawOrderRefreshIntervalHours=value,
            sessionTtlDays=30,
        )
