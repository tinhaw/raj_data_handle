"""One encrypted session per unified account, shared by API and worker.

Login is serialized with a database row lock (across processes) and a local
async lock (also supports SQLite tests). The short independent transaction
commits login/cooldown facts even when the caller's business operation fails.
No credential, token, or raw remote response is written to logs/audits/UI.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from weakref import WeakKeyDictionary

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.common.security import (
    SecurityValidationError,
    decrypt_credentials,
    encrypt_credentials,
)
from packages.common.settings import Settings
from packages.domain.models import RemoteAccount, RemoteAccountCapability, SourceConfig
from packages.domain.services.auth_service import write_audit
from packages.domain.services.remote_account_credentials import (
    RemoteAccountCredentialEnvelope,
    credential_envelope_for_account,
)

_locks: WeakKeyDictionary = WeakKeyDictionary()
MIN_LOGIN_GAP_SECONDS = 30
RATE_LIMIT_COOLDOWN_SECONDS = 15 * 60


class RemoteSessionError(ValueError):
    """Only fixed, safe-to-display messages may cross this boundary."""


def utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def session_identity(envelope: RemoteAccountCredentialEnvelope, base_url: str) -> str:
    value = json.dumps(
        [
            envelope.account_id,
            envelope.source_id,
            base_url.rstrip("/"),
            envelope.login_username,
            envelope.credential_scope,
            envelope.credential_version,
            envelope.encrypted_credentials,
        ]
    )
    return hashlib.sha256(value.encode()).hexdigest()


def token_expiry(token: str, now: datetime) -> tuple[datetime, bool]:
    # Unverified JWT exp is only a cache hint, never an authorization decision.
    # Opaque tokens have a conservative, explicitly labelled cache lifetime.
    try:
        part = token.split(".")[1]
        exp = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))["exp"]
        expiry = datetime.fromtimestamp(float(exp), UTC) - timedelta(seconds=30)
        if expiry <= now:
            raise RemoteSessionError("远端返回的登录会话已过期，请稍后重新登录。")
        return min(expiry, now + timedelta(days=7)), False
    except RemoteSessionError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        return now + timedelta(minutes=30), True


def response_requires_relogin(response: httpx.Response) -> bool:
    if response.status_code in {401, 419, 440}:
        return True
    # A plain 403 is a permission failure, not evidence of an expired session.
    try:
        payload = response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    if str(payload.get("code", "")).upper() in {"401", "419", "440", "TOKEN_EXPIRED"}:
        return True
    message = str(payload.get("message") or payload.get("msg") or "").lower()
    return any(
        word in message
        for word in (
            "token expired",
            "token has expired",
            "token失效",
            "token已过期",
            "登录已过期",
            "登录过期",
            "登录失效",
            "请重新登录",
            "未登录",
        )
    )


def session_public_state(account: RemoteAccount, source: SourceConfig) -> dict:
    now = datetime.now(UTC)
    envelope = credential_envelope_for_account(account=account, source=source)
    identity_valid = bool(
        envelope
        and source.base_url
        and account.session_identity == session_identity(envelope, source.base_url)
    )
    active = bool(
        account.enabled
        and source.enabled
        and identity_valid
        and account.session_ciphertext
        and utc(account.session_expires_at)
        and utc(account.session_expires_at) > now
    )
    if not account.enabled or not source.enabled:
        state = "DISABLED"
    elif utc(account.login_retry_after) and utc(account.login_retry_after) > now:
        state = "COOLDOWN"
    elif active:
        state = "AVAILABLE"
    elif account.session_last_error:
        state = "ERROR"
    elif account.last_logged_in_at:
        state = "EXPIRED"
    else:
        state = "NOT_CONNECTED"
    return {
        "session_status": state,
        "has_active_session": active,
        "session_expires_at": account.session_expires_at if identity_valid else None,
        "session_expiry_estimated": account.session_expiry_estimated,
        "last_logged_in_at": account.last_logged_in_at,
        "session_last_error": account.session_last_error,
        "login_retry_after": account.login_retry_after,
        "auto_relogin": account.auto_relogin,
        "relogin_interval_minutes": account.relogin_interval_minutes,
        "next_relogin_at": account.next_relogin_at,
    }


class RemoteAccountSession:
    def __init__(self, factory, *, account_id: str, identity: str, settings: Settings):
        self.factory = factory
        self.account_id = account_id
        self.identity = identity
        self.settings = settings

    async def reject(self, token: str | None) -> None:
        """Invalidate only the actually rejected session, not a newer login."""
        async with self.factory() as session:
            account = await session.scalar(
                select(RemoteAccount).where(RemoteAccount.id == self.account_id).with_for_update()
            )
            if (
                not account
                or account.session_identity != self.identity
                or not account.session_ciphertext
            ):
                return
            try:
                cached = decrypt_credentials(
                    account.session_ciphertext,
                    source_id=f"remote-session:{account.id}:{self.identity}",
                    credential_version=1,
                    settings=self.settings,
                ).get("token")
            except SecurityValidationError:
                cached = None
            if cached == token:
                account.session_ciphertext = None
                account.session_expires_at = None
                account.session_last_error = "远端拒绝了登录会话，请稍后重新登录或核对账号。"
                account.login_retry_after = datetime.now(UTC) + timedelta(seconds=30)
                await session.commit()

    async def token(
        self,
        login: Callable[[], Awaitable[str]],
        *,
        force: bool = False,
        rejected_token: str | None = None,
        reason: str = "request",
        actor_user_id: int | None = None,
    ) -> str:
        loop_locks = _locks.setdefault(asyncio.get_running_loop(), {})
        lock = loop_locks.setdefault((id(self.factory.kw["bind"]), self.account_id), asyncio.Lock())
        async with lock, self.factory() as session:
            account = await session.scalar(
                select(RemoteAccount).where(RemoteAccount.id == self.account_id).with_for_update()
            )
            source = await session.get(SourceConfig, account.source_id) if account else None
            if not account or not source or not account.enabled or not source.enabled:
                raise RemoteSessionError("远端账号或所属盘口已停用，不能登录。")
            envelope = credential_envelope_for_account(account=account, source=source)
            if not envelope or session_identity(envelope, source.base_url or "") != self.identity:
                raise RemoteSessionError("远端账号或盘口配置已变化，请刷新后重试。")
            now = datetime.now(UTC)
            scope = f"remote-session:{account.id}:{self.identity}"
            cached = None
            if account.session_identity == self.identity and account.session_ciphertext:
                try:
                    cached = decrypt_credentials(
                        account.session_ciphertext,
                        source_id=scope,
                        credential_version=1,
                        settings=self.settings,
                    ).get("token")
                except SecurityValidationError:
                    pass
            if reason == "scheduled":
                # Re-check inside the lock: two workers must not both refresh.
                if not account.relogin_interval_minutes or not account.next_relogin_at:
                    return ""
                if utc(account.next_relogin_at) > now:
                    return ""
                capability = await session.scalar(
                    select(RemoteAccountCapability.enabled).where(
                        RemoteAccountCapability.account_id == account.id,
                        RemoteAccountCapability.capability == "ERP_REMOTE_CHECK",
                    )
                )
                if not capability:
                    raise RemoteSessionError("账号未获连接检测授权，已跳过定时登录。")
            live = bool(
                cached and utc(account.session_expires_at) and utc(account.session_expires_at) > now
            )
            # Another caller may already have replaced the rejected token.
            if live and (not force or (rejected_token is not None and cached != rejected_token)):
                return cached
            if rejected_token is not None and cached == rejected_token:
                account.session_ciphertext = None
                account.session_expires_at = None
            if reason == "request" and account.last_logged_in_at and not account.auto_relogin:
                account.session_last_error = "登录会话已失效，自动重登已关闭，请手动重新登录。"
                await session.commit()
                raise RemoteSessionError(account.session_last_error)
            if utc(account.login_retry_after) and utc(account.login_retry_after) > now:
                await session.commit()
                raise RemoteSessionError("远端登录处于冷却期，请在页面显示的可重试时间后操作。")
            if utc(account.last_login_attempt_at) and now < utc(
                account.last_login_attempt_at
            ) + timedelta(seconds=MIN_LOGIN_GAP_SECONDS):
                account.login_retry_after = utc(account.last_login_attempt_at) + timedelta(
                    seconds=MIN_LOGIN_GAP_SECONDS
                )
                account.session_last_error = "登录请求过于频繁，已暂停重复登录。"
                await session.commit()
                raise RemoteSessionError(account.session_last_error)
            account.last_login_attempt_at = now
            try:
                token = await login()
                expiry, estimated = token_expiry(token, now)
                ciphertext = encrypt_credentials(
                    {"token": token},
                    source_id=scope,
                    credential_version=1,
                    settings=self.settings,
                )
            except Exception as exc:
                # Never persist raw exception/response text (may include secrets).
                rate_limited = any(
                    word in str(exc).lower()
                    for word in (
                        "登录次数",
                        "频繁",
                        "too many",
                        "rate limit",
                        "429",
                    )
                )
                failures = min((account.login_failure_count or 0) + 1, 8)
                delay = min(
                    3600,
                    max(
                        30 * 2 ** (failures - 1), RATE_LIMIT_COOLDOWN_SECONDS if rate_limited else 0
                    ),
                )
                account.login_failure_count = failures
                account.login_retry_after = now + timedelta(seconds=delay)
                account.session_last_error = (
                    "远端登录次数受限，已进入冷却，请勿反复重新登录。"
                    if rate_limited
                    else "远端登录失败，已进入冷却；请检查账号凭据及远端服务。"
                )
                account.next_relogin_at = (
                    max(
                        account.login_retry_after,
                        now + timedelta(minutes=account.relogin_interval_minutes),
                    )
                    if account.relogin_interval_minutes
                    else None
                )
                await write_audit(
                    session,
                    action="remote_account.login",
                    actor_user_id=actor_user_id,
                    target_type="remote_account",
                    target_id=account.id,
                    result="failure",
                    metadata={"reason": reason, "rate_limited": rate_limited},
                )
                await session.commit()
                raise RemoteSessionError(account.session_last_error) from None
            account.session_ciphertext = ciphertext
            account.session_identity = self.identity
            account.session_expires_at = expiry
            account.session_expiry_estimated = estimated
            account.last_logged_in_at = now
            account.login_failure_count = 0
            account.login_retry_after = None
            account.session_last_error = None
            account.next_relogin_at = (
                now + timedelta(minutes=account.relogin_interval_minutes)
                if account.relogin_interval_minutes
                else None
            )
            await write_audit(
                session,
                action="remote_account.login",
                actor_user_id=actor_user_id,
                target_type="remote_account",
                target_id=account.id,
                metadata={"reason": reason},
            )
            await session.commit()
            return token


def account_session(
    session: AsyncSession,
    *,
    envelope: RemoteAccountCredentialEnvelope,
    base_url: str,
    settings: Settings,
) -> RemoteAccountSession | None:
    # Only pre-migration fixtures can lack an account; never build an ERP-only cache.
    if not envelope.account_id:
        return None
    return RemoteAccountSession(
        async_sessionmaker(session.bind, expire_on_commit=False),
        account_id=envelope.account_id,
        identity=session_identity(envelope, base_url),
        settings=settings,
    )
