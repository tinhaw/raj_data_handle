"""Resolve the one credential source shared by analysis and ERP.

New accounts own their ciphertext. ``LEGACY_SOURCE`` is a temporary bridge for
the credentials that predate the unified account table; callers still resolve
that bridge through a remote-account record instead of reading ``SourceConfig``
directly. The no-account fallback only supports databases created before the
unified-account migration and can be removed after the transition is closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.security import SecurityValidationError, decrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import RemoteAccount, RemoteAccountCapability, SourceConfig
from packages.domain.services.remote_account_identity import remote_account_credential_scope

ANALYSIS_READ_CAPABILITY = "ANALYSIS_READ"
LEGACY_SOURCE_CREDENTIAL_MODE = "LEGACY_SOURCE"


class RemoteAccountCredentialsError(ValueError):
    """The selected unified account does not contain usable login credentials."""


@dataclass(frozen=True, slots=True)
class RemoteAccountCredentialEnvelope:
    source_id: str
    account_id: str | None
    login_username: str | None
    encrypted_credentials: str
    credential_scope: str
    credential_version: int
    credential_mode: str


def credential_envelope_for_account(
    *,
    account: RemoteAccount,
    source: SourceConfig,
) -> RemoteAccountCredentialEnvelope | None:
    """Return secret metadata for one selected account without decrypting it."""

    if account.credential_mode == LEGACY_SOURCE_CREDENTIAL_MODE:
        if not source.encrypted_credentials:
            return None
        return RemoteAccountCredentialEnvelope(
            source_id=source.source_id,
            account_id=account.id,
            login_username=account.login_username,
            encrypted_credentials=source.encrypted_credentials,
            credential_scope=source.source_id,
            credential_version=source.credential_version,
            credential_mode=account.credential_mode,
        )
    if not account.login_username or not account.encrypted_credentials:
        return None
    return RemoteAccountCredentialEnvelope(
        source_id=source.source_id,
        account_id=account.id,
        login_username=account.login_username,
        encrypted_credentials=account.encrypted_credentials,
        credential_scope=remote_account_credential_scope(account.id),
        credential_version=account.credential_version,
        credential_mode=account.credential_mode,
    )


async def resolve_default_remote_account_credentials(
    session: AsyncSession,
    *,
    source: SourceConfig,
) -> RemoteAccountCredentialEnvelope | None:
    """Resolve the enabled default account used by automatic analysis work."""

    account = await session.scalar(
        select(RemoteAccount)
        .join(
            RemoteAccountCapability,
            (RemoteAccountCapability.account_id == RemoteAccount.id)
            & (RemoteAccountCapability.capability == ANALYSIS_READ_CAPABILITY)
            & RemoteAccountCapability.enabled.is_(True),
        )
        .where(
            RemoteAccount.source_id == source.source_id,
            RemoteAccount.enabled.is_(True),
            RemoteAccount.is_default.is_(True),
        )
        .limit(1)
    )
    if account is not None:
        return credential_envelope_for_account(account=account, source=source)

    # Compatibility for test/dev databases or old snapshots that have not yet
    # run the unified-account migration. Once any account exists, a missing
    # default is treated as a real configuration error and never bypassed.
    account_count = int(
        await session.scalar(
            select(func.count(RemoteAccount.id)).where(
                RemoteAccount.source_id == source.source_id
            )
        )
        or 0
    )
    if account_count or not source.encrypted_credentials:
        return None
    return RemoteAccountCredentialEnvelope(
        source_id=source.source_id,
        account_id=None,
        login_username=None,
        encrypted_credentials=source.encrypted_credentials,
        credential_scope=source.source_id,
        credential_version=source.credential_version,
        credential_mode=LEGACY_SOURCE_CREDENTIAL_MODE,
    )


def decrypt_remote_account_credentials(
    envelope: RemoteAccountCredentialEnvelope,
    *,
    settings: Settings,
) -> dict[str, str]:
    """Decrypt and normalize username/password/TOTP for a resolved account."""

    try:
        values = decrypt_credentials(
            envelope.encrypted_credentials,
            source_id=envelope.credential_scope,
            credential_version=envelope.credential_version,
            settings=settings,
        )
    except SecurityValidationError as exc:
        raise RemoteAccountCredentialsError("统一远端账号凭据无法解密。") from exc
    normalized = {
        "username": (envelope.login_username or values.get("username") or "").strip(),
        "password": (values.get("password") or "").strip(),
        "totp_secret": (values.get("totp_secret") or "").strip(),
    }
    if not all(normalized.values()):
        raise RemoteAccountCredentialsError("统一远端账号凭据配置不完整。")
    return normalized
