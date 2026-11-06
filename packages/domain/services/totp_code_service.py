from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.security import (
    SecurityValidationError,
    decrypt_credentials,
    encrypt_credentials,
)
from packages.common.settings import Settings, get_settings
from packages.common.totp import extract_totp_secret, generate_totp
from packages.domain.models import TotpAccount
from packages.domain.schemas.totp_code import (
    TotpAccountCreateRequest,
    TotpAccountPatchRequest,
)
from packages.domain.services.auth_service import write_audit

TOTP_PERIOD_SECONDS = 30


class TotpAccountError(ValueError):
    pass


class TotpAccountNotFoundError(TotpAccountError):
    pass


@dataclass(frozen=True, slots=True)
class TotpCodeItem:
    account_id: str
    display_name: str
    account_name: str
    enabled: bool
    status: str
    code: str | None
    message: str | None


@dataclass(frozen=True, slots=True)
class TotpCodeSnapshot:
    generated_at: datetime
    expires_at: datetime
    period_seconds: int
    items: list[TotpCodeItem]


def _utc_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _secret_scope(account_id: str) -> str:
    return f"totp-account:{account_id}"


def _required_text(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise TotpAccountError(f"{label}不能为空。")
    return normalized


def _normalize_secret(value: str) -> str:
    try:
        normalized = extract_totp_secret(value).replace(" ", "").upper()
        generate_totp(normalized, timestamp=0)
    except ValueError as exc:
        raise TotpAccountError("TOTP Secret 不是有效的 Base32 或 otpauth URI。") from exc
    return normalized


def _encrypted_secret(
    *,
    account_id: str,
    secret_version: int,
    secret: str,
    settings: Settings,
) -> str:
    return encrypt_credentials(
        {"totp_secret": secret},
        source_id=_secret_scope(account_id),
        credential_version=secret_version,
        settings=settings,
    )


async def list_totp_accounts(session: AsyncSession) -> list[TotpAccount]:
    return list(
        await session.scalars(
            select(TotpAccount).order_by(
                TotpAccount.display_order.asc(),
                TotpAccount.created_at.asc(),
            )
        )
    )


async def create_totp_account(
    session: AsyncSession,
    *,
    request: TotpAccountCreateRequest,
    actor_user_id: int,
    settings: Settings | None = None,
) -> TotpAccount:
    current_settings = settings or get_settings()
    account_id = str(uuid.uuid4())
    secret = _normalize_secret(request.totp_secret)
    now = datetime.now(UTC)
    max_order = await session.scalar(select(func.max(TotpAccount.display_order)))
    account = TotpAccount(
        id=account_id,
        display_name=_required_text(request.display_name, label="显示名称"),
        account_name=_required_text(request.account_name, label="账号标识"),
        display_order=(max_order or 0) + 1,
        enabled=request.enabled,
        encrypted_secret=_encrypted_secret(
            account_id=account_id,
            secret_version=1,
            secret=secret,
            settings=current_settings,
        ),
        secret_version=1,
        secret_updated_at=now,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(account)
    await write_audit(
        session,
        action="totp_account.create",
        actor_user_id=actor_user_id,
        target_type="totp_account",
        target_id=account.id,
        metadata={"enabled": account.enabled},
    )
    await session.commit()
    return account


async def update_totp_account(
    session: AsyncSession,
    *,
    account_id: str,
    request: TotpAccountPatchRequest,
    actor_user_id: int,
    settings: Settings | None = None,
) -> TotpAccount:
    current_settings = settings or get_settings()
    account = await session.get(TotpAccount, account_id)
    if account is None:
        raise TotpAccountNotFoundError("TOTP 账号不存在。")

    changed_fields: list[str] = []
    if request.display_name is not None:
        account.display_name = _required_text(request.display_name, label="显示名称")
        changed_fields.append("display_name")
    if request.account_name is not None:
        account.account_name = _required_text(request.account_name, label="账号标识")
        changed_fields.append("account_name")
    if request.enabled is not None:
        account.enabled = request.enabled
        changed_fields.append("enabled")
    if request.totp_secret is not None:
        secret = _normalize_secret(request.totp_secret)
        account.secret_version += 1
        account.encrypted_secret = _encrypted_secret(
            account_id=account.id,
            secret_version=account.secret_version,
            secret=secret,
            settings=current_settings,
        )
        account.secret_updated_at = datetime.now(UTC)
        changed_fields.append("totp_secret")
    account.updated_by = actor_user_id

    await write_audit(
        session,
        action="totp_account.update",
        actor_user_id=actor_user_id,
        target_type="totp_account",
        target_id=account.id,
        metadata={"changed_fields": sorted(set(changed_fields))},
    )
    await session.commit()
    return account


async def delete_totp_account(
    session: AsyncSession,
    *,
    account_id: str,
    actor_user_id: int,
) -> None:
    account = await session.get(TotpAccount, account_id)
    if account is None:
        raise TotpAccountNotFoundError("TOTP 账号不存在。")
    await write_audit(
        session,
        action="totp_account.delete",
        actor_user_id=actor_user_id,
        target_type="totp_account",
        target_id=account.id,
    )
    await session.delete(account)
    await session.commit()


async def generate_totp_codes(
    session: AsyncSession,
    *,
    actor_user_id: int,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> TotpCodeSnapshot:
    """Generate codes for standalone accounts without exposing saved secrets."""

    current_settings = settings or get_settings()
    generated_at = _utc_now(now)
    timestamp = int(generated_at.timestamp())
    expires_at = datetime.fromtimestamp(
        ((timestamp // TOTP_PERIOD_SECONDS) + 1) * TOTP_PERIOD_SECONDS,
        tz=UTC,
    )
    accounts = await list_totp_accounts(session)
    items: list[TotpCodeItem] = []
    invalid_count = 0
    enabled_count = 0
    generated_count = 0
    for account in accounts:
        if not account.enabled:
            items.append(
                TotpCodeItem(
                    account_id=account.id,
                    display_name=account.display_name,
                    account_name=account.account_name,
                    enabled=False,
                    status="disabled",
                    code=None,
                    message="该 TOTP 账号已停用。",
                )
            )
            continue

        enabled_count += 1
        try:
            payload = decrypt_credentials(
                account.encrypted_secret,
                source_id=_secret_scope(account.id),
                credential_version=account.secret_version,
                settings=current_settings,
            )
            code = generate_totp(payload.get("totp_secret") or "", timestamp=timestamp)
        except (SecurityValidationError, ValueError):
            invalid_count += 1
            items.append(
                TotpCodeItem(
                    account_id=account.id,
                    display_name=account.display_name,
                    account_name=account.account_name,
                    enabled=True,
                    status="invalid",
                    code=None,
                    message="已保存的 TOTP Secret 无法生成验证码，请重新配置。",
                )
            )
            continue

        generated_count += 1
        items.append(
            TotpCodeItem(
                account_id=account.id,
                display_name=account.display_name,
                account_name=account.account_name,
                enabled=True,
                status="available",
                code=code,
                message=None,
            )
        )

    await write_audit(
        session,
        action="totp_codes.generate",
        actor_user_id=actor_user_id,
        target_type="totp_account",
        result="partial" if invalid_count else "success",
        metadata={
            "account_count": len(accounts),
            "enabled_count": enabled_count,
            "generated_count": generated_count,
            "invalid_count": invalid_count,
        },
    )
    await session.commit()
    return TotpCodeSnapshot(
        generated_at=generated_at,
        expires_at=expires_at,
        period_seconds=TOTP_PERIOD_SECONDS,
        items=items,
    )
