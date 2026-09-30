from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.security import SecurityValidationError, decrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import Base, SecurityAuditLog, SourceConfig, TotpAccount
from packages.domain.schemas.totp_code import (
    TotpAccountCreateRequest,
    TotpAccountPatchRequest,
)
from packages.domain.services.totp_code_service import (
    TotpAccountError,
    _secret_scope,
    create_totp_account,
    delete_totp_account,
    generate_totp_codes,
    update_totp_account,
)


def development_settings() -> Settings:
    return Settings(
        environment="development",
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )


@pytest.mark.asyncio
async def test_standalone_totp_account_lifecycle_keeps_secrets_encrypted() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = development_settings()
    secret = "JBSWY3DPEHPK3PXP"

    async with factory() as session:
        account = await create_totp_account(
            session,
            request=TotpAccountCreateRequest(
                display_name="Raj Admin",
                account_name="standalone-reader",
                totp_secret=secret,
            ),
            actor_user_id=1,
            settings=settings,
        )
        original_ciphertext = account.encrypted_secret
        assert secret not in original_ciphertext
        assert decrypt_credentials(
            account.encrypted_secret,
            source_id=_secret_scope(account.id),
            credential_version=account.secret_version,
            settings=settings,
        ) == {"totp_secret": secret}
        with pytest.raises(SecurityValidationError):
            decrypt_credentials(
                account.encrypted_secret,
                source_id=account.id,
                credential_version=account.secret_version,
                settings=settings,
            )

        snapshot = await generate_totp_codes(
            session,
            actor_user_id=1,
            now=datetime.fromtimestamp(59, tz=UTC),
            settings=settings,
        )
        assert snapshot.items[0].account_id == account.id
        assert snapshot.items[0].account_name == "standalone-reader"
        assert snapshot.items[0].code == "996554"
        assert await session.scalar(select(func.count()).select_from(SourceConfig)) == 0

        account = await update_totp_account(
            session,
            account_id=account.id,
            request=TotpAccountPatchRequest(display_name="Renamed"),
            actor_user_id=1,
            settings=settings,
        )
        assert account.encrypted_secret == original_ciphertext
        assert account.secret_version == 1

        account = await update_totp_account(
            session,
            account_id=account.id,
            request=TotpAccountPatchRequest(
                totp_secret="GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
                enabled=False,
            ),
            actor_user_id=1,
            settings=settings,
        )
        assert account.encrypted_secret != original_ciphertext
        assert account.secret_version == 2
        disabled = await generate_totp_codes(
            session,
            actor_user_id=1,
            now=datetime.fromtimestamp(59, tz=UTC),
            settings=settings,
        )
        assert disabled.items[0].status == "disabled"
        assert disabled.items[0].code is None

        audits = list(await session.scalars(select(SecurityAuditLog)))
        audit_text = json.dumps(
            [
                {
                    "action": audit.action,
                    "metadata": audit.metadata_json,
                }
                for audit in audits
            ]
        )
        assert secret not in audit_text
        assert "996554" not in audit_text

        account_id = account.id
        await delete_totp_account(session, account_id=account_id, actor_user_id=1)
        assert await session.get(TotpAccount, account_id) is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_invalid_totp_secret_is_rejected_before_persistence() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        with pytest.raises(TotpAccountError, match="Base32"):
            await create_totp_account(
                session,
                request=TotpAccountCreateRequest(
                    display_name="Invalid",
                    account_name="invalid-reader",
                    totp_secret="not-base32!",
                ),
                actor_user_id=1,
                settings=development_settings(),
            )
        assert await session.scalar(select(func.count()).select_from(TotpAccount)) == 0

    await engine.dispose()
