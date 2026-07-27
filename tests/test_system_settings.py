from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.settings import Settings
from packages.domain.models import Base
from packages.domain.schemas.system_setting import RetentionSettingsUpdateRequest
from packages.domain.services.system_setting_service import (
    get_retention_settings,
    update_retention_settings,
)


async def test_retention_defaults_and_versioned_update() -> None:
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
        )
        current = await get_retention_settings(session, defaults=defaults)
        assert current.uploaded_file_retention_days == 3
        assert current.result_retention_days == 30
        assert current.remote_cache_retention_days == 30

        updated = await update_retention_settings(
            session,
            payload=RetentionSettingsUpdateRequest(
                uploadedFileRetentionDays=5,
                resultRetentionDays=45,
                remoteCacheRetentionDays=60,
            ),
            actor_user_id=1,
        )

    assert updated.config_version == 2
    assert updated.uploaded_file_retention_days == 5
    assert updated.result_retention_days == 45
    assert updated.remote_cache_retention_days == 60
    await engine.dispose()
