from datetime import UTC, date, datetime

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


@pytest.mark.parametrize(
    "value",
    [
        "today",
        "last_1_hour",
        "last_2_hours",
        "last_3_hours",
        "last_6_hours",
        "last_12_hours",
        "last_24_hours",
        "last_48_hours",
    ],
)
def test_settings_accepts_configured_withdraw_order_query_range(value: str) -> None:
    settings = Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
        withdraw_order_query_range=value,
    )

    assert settings.withdraw_order_query_range == value


def test_settings_defaults_withdraw_order_refresh_page_size_to_one_hundred() -> None:
    settings = Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )

    assert settings.withdraw_order_refresh_page_size == 100


@pytest.mark.parametrize(
    ("value", "expected"),
    [(10, 10), ("20", 20), (30, 30), (50, 50), (100, 100)],
)
def test_settings_accepts_configured_withdraw_order_refresh_page_size(
    value: int | str,
    expected: int,
) -> None:
    settings = Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
        withdraw_order_refresh_page_size=value,
    )

    assert settings.withdraw_order_refresh_page_size == expected


@pytest.mark.parametrize("value", [0, 9, 11, 25, 40, 51, 99, 101])
def test_settings_rejects_other_withdraw_order_refresh_page_sizes(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(
            secret_key="test-secret-key-that-is-longer-than-32-characters",
            database_url="sqlite+aiosqlite:///:memory:",
            withdraw_order_refresh_page_size=value,
        )


@pytest.mark.parametrize(
    ("refresh_interval_hours", "refresh_page_size", "query_range"),
    [(1, 100, "today"), (24, 10, "last_48_hours"), (6, 50, "last_6_hours")],
)
async def test_retention_defaults_and_versioned_update(
    refresh_interval_hours: int,
    refresh_page_size: int,
    query_range: str,
) -> None:
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
        assert current.withdraw_order_refresh_page_size == 100
        assert current.withdraw_order_query_range == "today"
        assert current.charge_order_export_date_mode == "previous_day"
        assert current.charge_order_export_specific_date is None
        assert session_settings is not None
        assert session_settings.session_ttl_days == 30

        updated, updated_session_settings = await update_retention_settings(
            session,
            payload=RetentionSettingsUpdateRequest(
                uploadedFileRetentionDays=5,
                resultRetentionDays=45,
                remoteCacheRetentionDays=60,
                withdrawOrderRefreshIntervalHours=refresh_interval_hours,
                withdrawOrderRefreshPageSize=refresh_page_size,
                withdrawOrderQueryRange=query_range,
                chargeOrderExportDateMode="specific_date",
                chargeOrderExportSpecificDate="2026-07-29",
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
    assert updated.withdraw_order_refresh_page_size == refresh_page_size
    assert updated.withdraw_order_query_range == query_range
    assert updated.charge_order_export_date_mode == "specific_date"
    assert updated.charge_order_export_specific_date == date(2026, 7, 29)
    assert updated_session_settings.session_ttl_days == 45
    assert audit is not None
    assert audit.metadata_json["previous"]["withdrawOrderRefreshIntervalHours"] == 1
    assert (
        audit.metadata_json["current"]["withdrawOrderRefreshIntervalHours"]
        == refresh_interval_hours
    )
    assert audit.metadata_json["previous"]["withdrawOrderRefreshPageSize"] == 100
    assert audit.metadata_json["current"]["withdrawOrderRefreshPageSize"] == refresh_page_size
    assert audit.metadata_json["current"]["withdrawOrderQueryRange"] == query_range
    assert audit.metadata_json["current"]["chargeOrderExportDateMode"] == "specific_date"
    await engine.dispose()


def test_system_settings_api_response_exposes_withdraw_refresh_settings_in_camel_case() -> None:
    response = _response(
        SystemRetentionSetting(
            id=1,
            uploaded_file_retention_days=3,
            result_retention_days=30,
            remote_cache_retention_days=30,
            withdraw_order_refresh_interval_hours=24,
            withdraw_order_refresh_page_size=50,
            withdraw_order_query_range="last_24_hours",
            config_version=1,
            updated_at=datetime.now(UTC),
        ),
        session_ttl_days=30,
    )

    assert response.model_dump(by_alias=True)["withdrawOrderRefreshIntervalHours"] == 24
    assert response.model_dump(by_alias=True)["withdrawOrderRefreshPageSize"] == 50
    assert response.model_dump(by_alias=True)["withdrawOrderQueryRange"] == "last_24_hours"
    assert response.model_dump(by_alias=True)["chargeOrderExportDateMode"] == "previous_day"
    assert response.model_dump(by_alias=True)["chargeOrderExportSpecificDate"] is None


def test_specific_charge_export_date_requires_a_date() -> None:
    with pytest.raises(ValidationError):
        RetentionSettingsUpdateRequest(
            uploadedFileRetentionDays=3,
            resultRetentionDays=30,
            remoteCacheRetentionDays=30,
            chargeOrderExportDateMode="specific_date",
            sessionTtlDays=30,
        )


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


@pytest.mark.parametrize("value", [10, 20, 30, 50, 100])
def test_withdraw_order_refresh_page_size_accepts_remote_page_choices(value: int) -> None:
    payload = RetentionSettingsUpdateRequest(
        uploadedFileRetentionDays=3,
        resultRetentionDays=30,
        remoteCacheRetentionDays=30,
        withdrawOrderRefreshPageSize=value,
        sessionTtlDays=30,
    )

    assert payload.withdraw_order_refresh_page_size == value


@pytest.mark.parametrize("value", [0, 1, 9, 11, 25, 40, 51, 99, 101])
def test_withdraw_order_refresh_page_size_rejects_other_values(value: int) -> None:
    with pytest.raises(ValidationError):
        RetentionSettingsUpdateRequest(
            uploadedFileRetentionDays=3,
            resultRetentionDays=30,
            remoteCacheRetentionDays=30,
            withdrawOrderRefreshPageSize=value,
            sessionTtlDays=30,
        )


@pytest.mark.parametrize(
    "value",
    [
        "today",
        "last_1_hour",
        "last_2_hours",
        "last_3_hours",
        "last_6_hours",
        "last_12_hours",
        "last_24_hours",
        "last_48_hours",
    ],
)
def test_withdraw_order_query_range_accepts_only_configured_presets(value: str) -> None:
    payload = RetentionSettingsUpdateRequest(
        uploadedFileRetentionDays=3,
        resultRetentionDays=30,
        remoteCacheRetentionDays=30,
        withdrawOrderRefreshIntervalHours=1,
        withdrawOrderQueryRange=value,
        sessionTtlDays=30,
    )

    assert payload.withdraw_order_query_range == value


@pytest.mark.parametrize("value", ["last_4_hours", "last_13_hours", "all", "", "TODAY"])
def test_withdraw_order_query_range_rejects_other_values(value: str) -> None:
    with pytest.raises(ValidationError):
        RetentionSettingsUpdateRequest(
            uploadedFileRetentionDays=3,
            resultRetentionDays=30,
            remoteCacheRetentionDays=30,
            withdrawOrderRefreshIntervalHours=1,
            withdrawOrderQueryRange=value,
            sessionTtlDays=30,
        )
