from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.security import SecurityValidationError, decrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import Base, RemoteAccount
from packages.domain.schemas.remote_account import (
    RemoteAccountCapabilityUpdateRequest,
    RemoteAccountCreateRequest,
    RemoteAccountCredentialsWrite,
    RemoteAccountPatchRequest,
    RemoteTag,
    RemoteTagSnapshotWrite,
    RewardTierPresetTier,
    RewardTierPresetWrite,
)
from packages.domain.schemas.source import SourceCreateRequest
from packages.domain.services.remote_account_identity import remote_account_credential_scope
from packages.domain.services.remote_account_service import (
    LEGACY_SOURCE_CREDENTIAL_MODE,
    RemoteAccountValidationError,
    create_remote_account,
    get_reward_tier_preset,
    remote_account_has_capability,
    save_remote_tag_snapshot,
    save_reward_tier_preset,
    update_remote_account,
    update_remote_account_capabilities,
)
from packages.domain.services.source_service import create_source


def development_settings() -> Settings:
    return Settings(
        environment="development",
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )


@pytest.mark.asyncio
async def test_managed_remote_account_has_own_credential_scope_and_explicit_capabilities() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = development_settings()

    async with factory() as session:
        await create_source(
            session,
            request=SourceCreateRequest(source_id="rajwin", display_name="RajWin"),
            actor_user_id=1,
            settings=settings,
        )
        account = await create_remote_account(
            session,
            request=RemoteAccountCreateRequest(
                source_id="rajwin",
                login_username="reader-1",
                display_name="分析只读账号",
                credentials=RemoteAccountCredentialsWrite(
                    password="test-password",
                    totp_secret="JBSWY3DPEHPK3PXP",
                ),
            ),
            actor_user_id=1,
            settings=settings,
        )

        assert account.account.credential_mode == "MANAGED"
        assert account.capabilities["ANALYSIS_READ"] is False
        with pytest.raises(SecurityValidationError):
            decrypt_credentials(
                account.account.encrypted_credentials or "",
                source_id="rajwin",
                credential_version=account.account.credential_version,
                settings=settings,
            )
        assert decrypt_credentials(
            account.account.encrypted_credentials or "",
            source_id=remote_account_credential_scope(account.account.id),
            credential_version=account.account.credential_version,
            settings=settings,
        ) == {"password": "test-password", "totp_secret": "JBSWY3DPEHPK3PXP"}

        updated = await update_remote_account_capabilities(
            session,
            account_id=account.account.id,
            request=RemoteAccountCapabilityUpdateRequest(
                capabilities={"analysis_read": True, "erp_redemption_publish": True}
            ),
            actor_user_id=1,
        )
        assert updated.capabilities["ANALYSIS_READ"] is True
        assert updated.capabilities["ERP_REDEMPTION_PUBLISH"] is True
        assert await remote_account_has_capability(
            session,
            account_id=account.account.id,
            capability="ERP_REDEMPTION_PUBLISH",
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_source_account_cannot_copy_or_overwrite_existing_source_credentials() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        await create_source(
            session,
            request=SourceCreateRequest(source_id="rajluck", display_name="RajLuck"),
            actor_user_id=1,
            settings=development_settings(),
        )
        legacy = RemoteAccount(
            source_id="rajluck",
            display_name="历史分析默认账号",
            credential_mode=LEGACY_SOURCE_CREDENTIAL_MODE,
        )
        session.add(legacy)
        await session.commit()

        with pytest.raises(RemoteAccountValidationError, match="不能复制或重写"):
            await update_remote_account(
                session,
                account_id=legacy.id,
                request=RemoteAccountPatchRequest(
                    credentials=RemoteAccountCredentialsWrite(password="new-password")
                ),
                actor_user_id=1,
                settings=development_settings(),
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_unified_account_keeps_tag_snapshot_and_marks_reward_preset_stale() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = development_settings()
    async with factory() as session:
        await create_source(
            session,
            request=SourceCreateRequest(source_id="rajspin", display_name="RajSpin"),
            actor_user_id=1,
            settings=settings,
        )
        account = await create_remote_account(
            session,
            request=RemoteAccountCreateRequest(
                source_id="rajspin",
                login_username="erp-main",
                display_name="ERP 主账号",
                credentials=RemoteAccountCredentialsWrite(
                    password="test-password", totp_secret="JBSWY3DPEHPK3PXP"
                ),
            ),
            actor_user_id=1,
            settings=settings,
        )
        tags = [RemoteTag(id=10, name="近7天充值100-499")]
        await save_remote_tag_snapshot(
            session,
            account_id=account.account.id,
            request=RemoteTagSnapshotWrite(tags=tags, source="MIGRATED"),
            actor_user_id=1,
        )
        saved = await save_reward_tier_preset(
            session,
            account_id=account.account.id,
            request=RewardTierPresetWrite(
                tiers=[
                    RewardTierPresetTier(
                        label_ids=[10],
                        display_name="100-499",
                        min_deposit_amount="100",
                        bonus_amount="10",
                        bonus_max_amount="10",
                    )
                ],
                tag_snapshot=tags,
            ),
            actor_user_id=1,
        )
        assert saved.exists and not saved.stale

        await save_remote_tag_snapshot(
            session,
            account_id=account.account.id,
            request=RemoteTagSnapshotWrite(
                tags=[RemoteTag(id=11, name="新标签")], source="MIGRATED"
            ),
            actor_user_id=1,
        )
        assert (await get_reward_tier_preset(session, account_id=account.account.id)).stale
    await engine.dispose()
