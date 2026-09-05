"""Explicit account connection actions and opt-in background relogin."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings
from packages.domain.models import RemoteAccount, RemoteAccountCapability, SourceConfig
from packages.domain.schemas.remote_account import RemoteAccountSessionPolicyWrite
from packages.domain.services.auth_service import write_audit
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    ErpRemoteAccountReadGrant,
    RajAdminGiftCodeAdapter,
)
from packages.domain.services.remote_account_credentials import (
    RemoteAccountCredentialsError,
    credential_envelope_for_account,
    decrypt_remote_account_credentials,
)
from packages.domain.services.remote_account_session_service import (
    RemoteSessionError,
    account_session,
    utc,
)


async def save_session_policy(
    session: AsyncSession,
    *,
    account_id: str,
    request: RemoteAccountSessionPolicyWrite,
    actor_user_id: int,
) -> None:
    account = await session.get(
        RemoteAccount, account_id, with_for_update=True, populate_existing=True
    )
    if account is None:
        raise RemoteSessionError("远端账号不存在。")
    now = datetime.now(UTC)
    account.auto_relogin = request.auto_relogin
    # Identical saves do not postpone the existing schedule.
    if account.relogin_interval_minutes != request.relogin_interval_minutes:
        account.relogin_interval_minutes = request.relogin_interval_minutes
        account.next_relogin_at = (
            now + timedelta(minutes=request.relogin_interval_minutes)
            if request.relogin_interval_minutes
            else None
        )
    account.updated_by = actor_user_id
    await write_audit(
        session,
        action="remote_account.session_policy",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={
            "auto_relogin": request.auto_relogin,
            "relogin_interval_minutes": request.relogin_interval_minutes,
        },
    )
    await session.commit()


async def operate_account_connection(
    session: AsyncSession,
    *,
    account_id: str,
    operation: str,
    execution_confirmed: bool,
    actor_user_id: int | None,
    settings: Settings,
    transport=None,
) -> None:
    if not execution_confirmed or operation not in {"CHECK", "RELOGIN", "SCHEDULED"}:
        raise RemoteSessionError("必须明确确认本次远端连接操作。")
    account = await session.get(RemoteAccount, account_id, populate_existing=True)
    source = await session.get(SourceConfig, account.source_id) if account else None
    if (
        not account
        or not source
        or not account.enabled
        or not source.enabled
        or not source.base_url
    ):
        raise RemoteSessionError("远端账号或盘口不可用，请先完整配置并启用。")
    allowed = await session.scalar(
        select(RemoteAccountCapability.enabled).where(
            RemoteAccountCapability.account_id == account.id,
            RemoteAccountCapability.capability == "ERP_REMOTE_CHECK",
        )
    )
    if not allowed:
        raise RemoteSessionError("账号未获连接检测授权。")
    envelope = credential_envelope_for_account(account=account, source=source)
    if not envelope:
        raise RemoteSessionError("统一远端账号凭据配置不完整。")
    failure = None
    request_id = None
    try:
        credentials = decrypt_remote_account_credentials(envelope, settings=settings)
        shared = account_session(
            session, envelope=envelope, base_url=source.base_url, settings=settings
        )
        async with RajAdminGiftCodeAdapter(
            account_id=account.id,
            source_id=source.source_id,
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            business_timezone=settings.default_business_timezone,
            transport=transport,
            remote_session=shared,
        ) as adapter:
            if operation == "CHECK":
                _, request_id = await adapter.check_connection(
                    grant=ErpRemoteAccountReadGrant(
                        account_id=account.id,
                        source_id=source.source_id,
                        operation="CHECK",
                        capability="ERP_REMOTE_CHECK",
                    )
                )
            else:
                token = await shared.token(
                    adapter._login_uncached,
                    force=True,
                    reason="scheduled" if operation == "SCHEDULED" else "manual",
                    actor_user_id=actor_user_id,
                )
                if operation == "SCHEDULED" and not token:
                    # Another worker already handled it, or the policy was disabled.
                    # Do not record a successful login for an operation we skipped.
                    return
    except (RemoteAccountCredentialsError, ErpRedemptionRemoteHttpError, RemoteSessionError):
        failure = "远端连接操作失败，请核对凭据、权限及远端服务。"
    # The shared login transaction may have changed the same row.
    await session.refresh(account)
    if failure:
        failure = account.session_last_error or failure
        if operation == "SCHEDULED" and (
            not utc(account.next_relogin_at) or utc(account.next_relogin_at) <= datetime.now(UTC)
        ):
            account.next_relogin_at = datetime.now(UTC) + timedelta(
                minutes=account.relogin_interval_minutes or 15
            )
    if operation == "CHECK":
        account.last_tested_at = datetime.now(UTC)
        account.last_test_status = "FAILED" if failure else "SUCCESS"
        # Do not copy arbitrary remote response strings into our database.
        account.last_test_request_id = None
        if failure and not account.session_last_error:
            account.session_last_error = failure
        elif not failure:
            account.session_last_error = None
    await write_audit(
        session,
        action="remote_account.connection",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        result="failure" if failure else "success",
        metadata={"operation": operation, "remote_request_recorded": bool(request_id)},
    )
    await session.commit()
    if failure:
        raise RemoteSessionError(failure)


async def run_due_account_relogins(
    session: AsyncSession,
    *,
    settings: Settings,
    transport=None,
) -> int:
    now = datetime.now(UTC)
    account_ids = list(
        await session.scalars(
            select(RemoteAccount.id)
            .join(SourceConfig, SourceConfig.source_id == RemoteAccount.source_id)
            .join(RemoteAccountCapability, RemoteAccountCapability.account_id == RemoteAccount.id)
            .where(
                RemoteAccount.enabled.is_(True),
                SourceConfig.enabled.is_(True),
                RemoteAccountCapability.capability == "ERP_REMOTE_CHECK",
                RemoteAccountCapability.enabled.is_(True),
                RemoteAccount.relogin_interval_minutes.is_not(None),
                RemoteAccount.next_relogin_at <= now,
            )
            .order_by(RemoteAccount.next_relogin_at)
            .limit(100)
        )
    )
    for account_id in account_ids:
        try:
            await operate_account_connection(
                session,
                account_id=account_id,
                operation="SCHEDULED",
                execution_confirmed=True,
                actor_user_id=None,
                settings=settings,
                transport=transport,
            )
        except RemoteSessionError:
            # Safe failure/cooldown persisted by the shared session boundary.
            await session.rollback()
    return len(account_ids)
