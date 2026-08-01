from __future__ import annotations

from datetime import UTC, date, datetime, time

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


def _settings(**values: object) -> Settings:
    return Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
        **values,
    )


def test_withdraw_export_settings_default_to_previous_business_day() -> None:
    settings = _settings()

    assert settings.withdraw_order_export_date_mode == "previous_day"
    assert settings.withdraw_order_export_specific_date is None


def test_order_export_time_defaults_preserve_the_staggered_schedule() -> None:
    settings = _settings()

    assert settings.charge_order_export_time == time(0, 0, 1)
    assert settings.withdraw_order_export_time == time(0, 5, 1)
    assert settings.automatic_sync_retry_limit == 3
    assert settings.automatic_sync_retry_interval_minutes == 5

    with pytest.raises(ValidationError, match="timezone or UTC offset"):
        _settings(charge_order_export_time="01:02:03+05:30")


def test_order_export_times_accept_seconds_and_reject_microseconds() -> None:
    payload = RetentionSettingsUpdateRequest(
        uploadedFileRetentionDays=3,
        resultRetentionDays=30,
        remoteCacheRetentionDays=30,
        chargeOrderExportTime="01:02:03",
        withdrawOrderExportTime="04:05:06",
        sessionTtlDays=30,
    )

    assert payload.charge_order_export_time == time(1, 2, 3)
    assert payload.withdraw_order_export_time == time(4, 5, 6)

    with pytest.raises(ValidationError, match="自动导出时间必须精确到秒"):
        RetentionSettingsUpdateRequest(
            uploadedFileRetentionDays=3,
            resultRetentionDays=30,
            remoteCacheRetentionDays=30,
            chargeOrderExportTime="01:02:03.123456",
            sessionTtlDays=30,
        )

    with pytest.raises(ValidationError, match="自动导出时间不能包含时区或 UTC 偏移"):
        RetentionSettingsUpdateRequest(
            uploadedFileRetentionDays=3,
            resultRetentionDays=30,
            remoteCacheRetentionDays=30,
            chargeOrderExportTime="01:02:03+05:30",
            sessionTtlDays=30,
        )


def test_automatic_sync_retry_settings_are_bounded() -> None:
    payload = RetentionSettingsUpdateRequest(
        uploadedFileRetentionDays=3,
        resultRetentionDays=30,
        remoteCacheRetentionDays=30,
        automaticSyncRetryLimit=0,
        automaticSyncRetryIntervalMinutes=60,
        sessionTtlDays=30,
    )

    assert payload.automatic_sync_retry_limit == 0
    assert payload.automatic_sync_retry_interval_minutes == 60

    with pytest.raises(ValidationError):
        RetentionSettingsUpdateRequest(
            uploadedFileRetentionDays=3,
            resultRetentionDays=30,
            remoteCacheRetentionDays=30,
            automaticSyncRetryLimit=11,
            sessionTtlDays=30,
        )
    with pytest.raises(ValidationError):
        RetentionSettingsUpdateRequest(
            uploadedFileRetentionDays=3,
            resultRetentionDays=30,
            remoteCacheRetentionDays=30,
            automaticSyncRetryIntervalMinutes=0,
            sessionTtlDays=30,
        )


def test_spin_refresh_settings_use_safe_backfill_defaults() -> None:
    settings = _settings()

    assert settings.spin_order_refresh_interval_hours == 2
    assert settings.spin_order_refresh_page_size == 100
    assert settings.spin_order_query_range == "previous_business_day_to_completed_slot"


def test_withdraw_export_settings_accept_a_specific_date() -> None:
    settings = _settings(
        withdraw_order_export_date_mode="specific_date",
        withdraw_order_export_specific_date="2026-07-29",
    )

    assert settings.withdraw_order_export_date_mode == "specific_date"
    assert settings.withdraw_order_export_specific_date == date(2026, 7, 29)


def test_specific_withdraw_export_date_requires_a_date() -> None:
    with pytest.raises(ValidationError, match="提现订单选择指定日期"):
        RetentionSettingsUpdateRequest(
            uploadedFileRetentionDays=3,
            resultRetentionDays=30,
            remoteCacheRetentionDays=30,
            withdrawOrderExportDateMode="specific_date",
            sessionTtlDays=30,
        )


def test_specific_charge_export_date_still_requires_a_date() -> None:
    with pytest.raises(ValidationError, match="充值订单选择指定日期"):
        RetentionSettingsUpdateRequest(
            uploadedFileRetentionDays=3,
            resultRetentionDays=30,
            remoteCacheRetentionDays=30,
            chargeOrderExportDateMode="specific_date",
            sessionTtlDays=30,
        )


@pytest.mark.asyncio
async def test_retention_update_persists_withdraw_export_policy_and_audits_it() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        defaults = _settings(
            uploaded_file_retention_days=3,
            result_retention_days=30,
            remote_cache_retention_days=30,
            session_ttl_days=30,
        )
        current = await get_retention_settings(session, defaults=defaults)
        session_settings = await get_session_settings(session, defaults=defaults)

        assert current.withdraw_order_export_date_mode == "previous_day"
        assert current.withdraw_order_export_specific_date is None
        assert current.charge_order_export_time == time(0, 0, 1)
        assert current.withdraw_order_export_time == time(0, 5, 1)
        assert current.automatic_sync_retry_limit == 3
        assert current.automatic_sync_retry_interval_minutes == 5
        assert session_settings is not None
        assert session_settings.session_ttl_days == 30

        updated, updated_session_settings = await update_retention_settings(
            session,
            payload=RetentionSettingsUpdateRequest(
                uploadedFileRetentionDays=5,
                resultRetentionDays=45,
                remoteCacheRetentionDays=60,
                syncLogRetentionDays=90,
                withdrawOrderExportDateMode="specific_date",
                withdrawOrderExportSpecificDate="2026-07-29",
                withdrawOrderExportTime="02:03:04",
                automaticSyncRetryLimit=2,
                automaticSyncRetryIntervalMinutes=15,
                chargeOrderExportDateMode="specific_date",
                chargeOrderExportSpecificDate="2026-07-28",
                chargeOrderExportTime="01:02:03",
                spinOrderRefreshIntervalHours=4,
                spinOrderRefreshPageSize=50,
                spinOrderQueryRange="business_day_to_completed_slot",
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
    assert updated.sync_log_retention_days == 90
    assert updated.withdraw_order_export_date_mode == "specific_date"
    assert updated.withdraw_order_export_specific_date == date(2026, 7, 29)
    assert updated.withdraw_order_export_time == time(2, 3, 4)
    assert updated.automatic_sync_retry_limit == 2
    assert updated.automatic_sync_retry_interval_minutes == 15
    assert updated.charge_order_export_date_mode == "specific_date"
    assert updated.charge_order_export_specific_date == date(2026, 7, 28)
    assert updated.charge_order_export_time == time(1, 2, 3)
    assert updated.spin_order_refresh_interval_hours == 4
    assert updated.spin_order_refresh_page_size == 50
    assert updated.spin_order_query_range == "business_day_to_completed_slot"
    assert updated_session_settings.session_ttl_days == 45
    assert audit is not None
    assert audit.metadata_json["previous"]["withdrawOrderExportDateMode"] == "previous_day"
    assert audit.metadata_json["previous"]["syncLogRetentionDays"] == 30
    assert audit.metadata_json["current"]["syncLogRetentionDays"] == 90
    assert audit.metadata_json["previous"]["withdrawOrderExportSpecificDate"] is None
    assert audit.metadata_json["previous"]["withdrawOrderExportTime"] == "00:05:01"
    assert audit.metadata_json["previous"]["automaticSyncRetryLimit"] == 3
    assert audit.metadata_json["current"]["automaticSyncRetryLimit"] == 2
    assert audit.metadata_json["previous"]["automaticSyncRetryIntervalMinutes"] == 5
    assert audit.metadata_json["current"]["automaticSyncRetryIntervalMinutes"] == 15
    assert audit.metadata_json["current"]["withdrawOrderExportDateMode"] == "specific_date"
    assert audit.metadata_json["current"]["withdrawOrderExportSpecificDate"] == "2026-07-29"
    assert audit.metadata_json["current"]["withdrawOrderExportTime"] == "02:03:04"
    assert audit.metadata_json["previous"]["chargeOrderExportTime"] == "00:00:01"
    assert audit.metadata_json["current"]["chargeOrderExportTime"] == "01:02:03"
    assert audit.metadata_json["previous"]["spinOrderRefreshIntervalHours"] == 2
    assert audit.metadata_json["current"]["spinOrderRefreshIntervalHours"] == 4
    await engine.dispose()


def test_system_settings_response_exposes_withdraw_export_policy_in_camel_case() -> None:
    response = _response(
        SystemRetentionSetting(
            id=1,
            uploaded_file_retention_days=3,
            result_retention_days=30,
            remote_cache_retention_days=30,
            withdraw_order_export_date_mode="specific_date",
            withdraw_order_export_specific_date=date(2026, 7, 29),
            withdraw_order_export_time=time(2, 3, 4),
            charge_order_export_time=time(1, 2, 3),
            config_version=1,
            updated_at=datetime.now(UTC),
        ),
        session_ttl_days=30,
    )

    payload = response.model_dump(by_alias=True)
    assert payload["syncLogRetentionDays"] == 30
    assert payload["withdrawOrderExportDateMode"] == "specific_date"
    assert payload["withdrawOrderExportSpecificDate"] == date(2026, 7, 29)
    assert payload["withdrawOrderExportTime"] == time(2, 3, 4)
    assert payload["chargeOrderExportDateMode"] == "previous_day"
    assert payload["chargeOrderExportSpecificDate"] is None
    assert payload["chargeOrderExportTime"] == time(1, 2, 3)
    assert payload["automaticSyncRetryLimit"] == 3
    assert payload["automaticSyncRetryIntervalMinutes"] == 5
    assert payload["spinOrderRefreshIntervalHours"] == 2
    assert payload["spinOrderRefreshPageSize"] == 100
    assert payload["spinOrderQueryRange"] == "previous_business_day_to_completed_slot"
