from __future__ import annotations

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
        assert session_settings is not None
        assert session_settings.session_ttl_days == 30

        updated, updated_session_settings = await update_retention_settings(
            session,
            payload=RetentionSettingsUpdateRequest(
                uploadedFileRetentionDays=5,
                resultRetentionDays=45,
                remoteCacheRetentionDays=60,
                withdrawOrderExportDateMode="specific_date",
                withdrawOrderExportSpecificDate="2026-07-29",
                chargeOrderExportDateMode="specific_date",
                chargeOrderExportSpecificDate="2026-07-28",
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
    assert updated.withdraw_order_export_date_mode == "specific_date"
    assert updated.withdraw_order_export_specific_date == date(2026, 7, 29)
    assert updated.charge_order_export_date_mode == "specific_date"
    assert updated.charge_order_export_specific_date == date(2026, 7, 28)
    assert updated_session_settings.session_ttl_days == 45
    assert audit is not None
    assert audit.metadata_json["previous"]["withdrawOrderExportDateMode"] == "previous_day"
    assert audit.metadata_json["previous"]["withdrawOrderExportSpecificDate"] is None
    assert audit.metadata_json["current"]["withdrawOrderExportDateMode"] == "specific_date"
    assert audit.metadata_json["current"]["withdrawOrderExportSpecificDate"] == "2026-07-29"
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
            config_version=1,
            updated_at=datetime.now(UTC),
        ),
        session_ttl_days=30,
    )

    payload = response.model_dump(by_alias=True)
    assert payload["withdrawOrderExportDateMode"] == "specific_date"
    assert payload["withdrawOrderExportSpecificDate"] == date(2026, 7, 29)
    assert payload["chargeOrderExportDateMode"] == "previous_day"
    assert payload["chargeOrderExportSpecificDate"] is None
