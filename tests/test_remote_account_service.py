from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.security import SecurityValidationError, decrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    RemoteAccount,
    RemoteAccountRewardTierPreset,
    RemoteAccountTagSnapshot,
    SourceConfig,
)
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
from packages.domain.services.remote_account_credentials import (
    decrypt_remote_account_credentials,
    resolve_default_remote_account_credentials,
)
from packages.domain.services.remote_account_identity import remote_account_credential_scope
from packages.domain.services.remote_account_service import (
    LEGACY_SOURCE_CREDENTIAL_MODE,
    RemoteAccountValidationError,
    create_remote_account,
    delete_legacy_remote_account,
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
async def test_managed_remote_account_has_own_scope_full_capabilities_and_default() -> None:
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
        assert account.account.is_default is True
        assert all(account.capabilities.values())
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
        source = await session.get(SourceConfig, "rajwin")
        assert source is not None
        envelope = await resolve_default_remote_account_credentials(session, source=source)
        assert envelope is not None and envelope.account_id == account.account.id
        assert decrypt_remote_account_credentials(envelope, settings=settings) == {
            "username": "reader-1",
            "password": "test-password",
            "totp_secret": "JBSWY3DPEHPK3PXP",
        }

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
async def test_deleting_legacy_account_migrates_local_configuration_to_managed_default() -> None:
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
        managed = await create_remote_account(
            session,
            request=RemoteAccountCreateRequest(
                source_id="rajwin",
                login_username="current-account",
                display_name="Current account",
                credentials=RemoteAccountCredentialsWrite(
                    password="test-password",
                    totp_secret="JBSWY3DPEHPK3PXP",
                ),
            ),
            actor_user_id=1,
            settings=settings,
        )
        legacy = RemoteAccount(
            source_id="rajwin",
            display_name="Legacy analysis account",
            enabled=True,
            is_default=False,
            credential_mode=LEGACY_SOURCE_CREDENTIAL_MODE,
        )
        session.add(legacy)
        await session.commit()

        tags = [
            RemoteTag(id=901091, name="Seven-day deposit 100-499"),
            RemoteTag(id=901027, name="日充值200+"),
        ]
        await save_remote_tag_snapshot(
            session,
            account_id=legacy.id,
            request=RemoteTagSnapshotWrite(tags=tags, source="MIGRATED"),
            actor_user_id=1,
        )
        await save_reward_tier_preset(
            session,
            account_id=legacy.id,
            request=RewardTierPresetWrite(
                tiers=[
                    RewardTierPresetTier(
                        label_ids=[901091],
                        display_name="100-499",
                        min_deposit_amount="100",
                        bonus_amount="3",
                        bonus_max_amount="5",
                    )
                ],
                tag_snapshot=tags,
            ),
            actor_user_id=1,
        )

        await save_reward_tier_preset(
            session,
            account_id=legacy.id,
            redemption_type="PREVIOUS_DAY_DEPOSIT",
            request=RewardTierPresetWrite(
                tiers=[
                    RewardTierPresetTier(
                        user_type="ALL_USERS",
                        label_ids=[],
                        display_name="全部用户",
                        min_deposit_amount="0",
                        bonus_amount="10",
                        bonus_max_amount="10",
                    ),
                    RewardTierPresetTier(
                        user_type="LABEL_USERS",
                        label_ids=[901027],
                        display_name="日充值200+",
                        min_deposit_amount="200",
                        bonus_amount="30",
                        bonus_max_amount="30",
                    ),
                ],
                tag_snapshot=tags,
            ),
            actor_user_id=1,
        )
        async with factory() as reopened:
            snapshot = await reopened.get(RemoteAccountTagSnapshot, legacy.id)
            assert 901027 in [tag["id"] for tag in snapshot.tags_json]
            daily = await get_reward_tier_preset(
                reopened, account_id=legacy.id, redemption_type="PREVIOUS_DAY_DEPOSIT"
            )
            seven = await get_reward_tier_preset(reopened, account_id=legacy.id)
            assert daily.tiers[0].user_type == "ALL_USERS"
            assert daily.tiers[1].label_ids == [901027]
            assert seven.tiers[0].label_ids == [901091]

        await delete_legacy_remote_account(
            session,
            account_id=legacy.id,
            actor_user_id=1,
        )

        assert await session.get(RemoteAccount, legacy.id) is None
        assert await session.get(RemoteAccountTagSnapshot, managed.account.id) is not None
        assert (
            await session.get(
                RemoteAccountRewardTierPreset, (managed.account.id, "SEVEN_DAY_DEPOSIT")
            )
            is not None
        )
        assert (
            await session.get(
                RemoteAccountRewardTierPreset, (managed.account.id, "PREVIOUS_DAY_DEPOSIT")
            )
            is not None
        )
        remaining = list(await session.scalars(select(RemoteAccount)))
        assert [account.id for account in remaining] == [managed.account.id]

    await engine.dispose()


@pytest.mark.asyncio
async def test_setting_another_account_default_switches_the_market_default() -> None:
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
        first = await create_remote_account(
            session,
            request=RemoteAccountCreateRequest(
                source_id="rajwin",
                login_username="reader-1",
                display_name="主账号",
                credentials=RemoteAccountCredentialsWrite(
                    password="password-1",
                    totp_secret="JBSWY3DPEHPK3PXP",
                ),
            ),
            actor_user_id=1,
            settings=settings,
        )
        second = await create_remote_account(
            session,
            request=RemoteAccountCreateRequest(
                source_id="rajwin",
                login_username="reader-2",
                display_name="备用账号",
                credentials=RemoteAccountCredentialsWrite(
                    password="password-2",
                    totp_secret="JBSWY3DPEHPK3PXP",
                ),
            ),
            actor_user_id=1,
            settings=settings,
        )
        assert first.account.is_default
        assert not second.account.is_default

        switched = await update_remote_account(
            session,
            account_id=second.account.id,
            request=RemoteAccountPatchRequest(is_default=True),
            actor_user_id=1,
            settings=settings,
        )
        await session.refresh(first.account)
        assert switched.account.is_default
        assert not first.account.is_default

    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_source_account_requires_complete_credentials_for_takeover() -> None:
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

        with pytest.raises(RemoteAccountValidationError, match="同时填写"):
            await update_remote_account(
                session,
                account_id=legacy.id,
                request=RemoteAccountPatchRequest(
                    credentials=RemoteAccountCredentialsWrite(password="new-password")
                ),
                actor_user_id=1,
                settings=development_settings(),
            )

        taken_over = await update_remote_account(
            session,
            account_id=legacy.id,
            request=RemoteAccountPatchRequest(
                login_username="reader-legacy",
                credentials=RemoteAccountCredentialsWrite(
                    password="new-password",
                    totp_secret="JBSWY3DPEHPK3PXP",
                ),
            ),
            actor_user_id=1,
            settings=development_settings(),
        )
        assert taken_over.account.credential_mode == "MANAGED"
        assert taken_over.account.login_username == "reader-legacy"
        assert taken_over.account.encrypted_credentials

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
                        user_type="ALL_USERS",
                        label_ids=[],
                        display_name="全部用户",
                        min_deposit_amount="0",
                        bonus_amount="1",
                        bonus_max_amount="3",
                    ),
                    RewardTierPresetTier(
                        label_ids=[10],
                        display_name="100-499",
                        min_deposit_amount="100",
                        bonus_amount="10",
                        bonus_max_amount="10",
                    ),
                ],
                tag_snapshot=tags,
            ),
            actor_user_id=1,
        )
        assert saved.exists and not saved.stale
        assert saved.tiers[0].user_type == "ALL_USERS"
        assert saved.tiers[0].label_ids == []

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
