"""Unified-account execution for the preserved Java redemption facade.

The Java compatibility service owns the historical task tables and workflow
state.  This module owns the only sensitive boundary: resolving the public
numeric account projection to a unified ``RemoteAccount``, checking the
capability again and decrypting its credentials inside the main application.
No legacy Java credential record is read here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings
from packages.domain.models import RemoteAccount, RemoteAccountCapability, SourceConfig
from packages.domain.schemas.remote_account import (
    ErpCompatibilityRemoteAbsenceCheckRequest,
    ErpCompatibilityRemoteAbsenceCheckResponse,
    ErpCompatibilityRemoteCancelRequest,
    ErpCompatibilityRemoteCreateRequest,
    ErpCompatibilityRemoteDownloadRequest,
    ErpCompatibilityRemoteDuplicateCheckRequest,
    ErpCompatibilityRemotePublishRequest,
    ErpCompatibilityRemoteRecoveryCheckRequest,
    ErpCompatibilityRemoteRecoveryCheckResponse,
    ErpCompatibilityRemoteReuseCheckRequest,
    ErpCompatibilityRemoteReuseCheckResponse,
    ErpCompatibilityRemoteRewardUpdateRequest,
    ErpCompatibilityRemoteVerifyRequest,
    ErpCompatibilityRemoteVerifyResponse,
)
from packages.domain.services.auth_service import write_audit
from packages.domain.services.erp_compatibility_id_service import (
    ErpCompatibilityIdError,
    resolve_erp_compatibility_id,
)
from packages.domain.services.erp_redemption_remote_adapter import (
    RemoteCancelPublishCommand,
    RemoteCancelPublishResult,
    RemoteCreateCommand,
    RemoteCreateResult,
    RemoteCreationOptions,
    RemoteDownloadCommand,
    RemoteDownloadResult,
    RemotePublishCommand,
    RemotePublishResult,
)
from packages.domain.services.erp_redemption_remote_gate import (
    ErpRemoteExecutionGateError,
    ErpRemoteExecutionGrant,
    authorize_erp_redemption_remote_execution,
)
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    ErpRedemptionRemoteReviewPending,
    ErpRemoteAccountReadGrant,
    RajAdminGiftCodeAdapter,
)
from packages.domain.services.remote_account_credentials import (
    RemoteAccountCredentialsError,
    credential_envelope_for_account,
    decrypt_remote_account_credentials,
)
from packages.domain.services.remote_account_session_service import account_session


class ErpCompatibilityRemoteExecutionError(ValueError):
    """Safe-to-display failure from the unified remote execution boundary."""


@dataclass(frozen=True, slots=True)
class CompatibilityRemoteCreateResult:
    remote_configuration_id: str
    remote_group_key: str | None
    remote_request_id: str | None


@dataclass(frozen=True, slots=True)
class CompatibilityRemotePublishResult:
    remote_publish_task_id: str
    remote_request_id: str | None


def _options(payload: ErpCompatibilityRemoteCreateRequest) -> RemoteCreationOptions:
    options = payload.options
    return RemoteCreationOptions(
        publish_environment=options.publish_environment,
        flow_times=options.flow_times,
        activity_recharge=options.activity_recharge,
        activity_recharge_count=options.activity_recharge_count,
        activity_id=options.activity_id,
        key_number=options.key_number,
        single_user_limit=options.single_user_limit,
        single_key_limit=options.single_key_limit,
        require_bind_bank_card=options.require_bind_bank_card,
        require_bind_phone=options.require_bind_phone,
        check_uuid=options.check_uuid,
        uuid_reward_limit=options.uuid_reward_limit,
        check_login_ip=options.check_login_ip,
        login_ip_reward_limit=options.login_ip_reward_limit,
        check_register_ip=options.check_register_ip,
        register_ip_reward_limit=options.register_ip_reward_limit,
    )


async def execute_compatibility_remote_create(
    session: AsyncSession,
    *,
    payload: ErpCompatibilityRemoteCreateRequest,
    actor_user_id: int,
    settings: Settings,
    transport=None,
) -> CompatibilityRemoteCreateResult:
    """Create one remote configuration using only the current unified account.

    ``execution_confirmed`` is part of the operator's confirmed UI action; it
    is deliberately checked before credentials are resolved or an HTTP client
    is constructed.  Tests can supply an ``httpx.MockTransport``; production
    always uses the regular adapter transport.
    """

    try:
        account_id = await resolve_erp_compatibility_id(
            session, entity_type="remote_account", legacy_id=payload.account_id
        )
        grant = await authorize_erp_redemption_remote_execution(
            session,
            account_id=account_id,
            operation="CREATE",
            execution_authorized=payload.execution_confirmed,
        )
        account = await session.get(RemoteAccount, account_id)
        source = await session.get(SourceConfig, grant.source_id)
        if account is None or source is None or not source.base_url:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号或盘口配置不可用。")
        envelope = credential_envelope_for_account(account=account, source=source)
        if envelope is None:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号凭据配置不完整。")
        credentials = decrypt_remote_account_credentials(envelope, settings=settings)
        async with RajAdminGiftCodeAdapter(
            remote_session=account_session(
                session, envelope=envelope, base_url=source.base_url, settings=settings
            ),
            account_id=account.id,
            source_id=source.source_id,
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            business_timezone=settings.default_business_timezone,
            transport=transport,
        ) as adapter:
            result: RemoteCreateResult = await adapter.create_configuration(
                grant=grant,
                command=RemoteCreateCommand(
                    issue_id=str(payload.issue_id),
                    description=payload.description,
                    claim_date=payload.claim_date,
                    deposit_window_start=payload.claim_date,
                    deposit_window_end=payload.claim_date,
                    label_ids=tuple(payload.label_ids),
                    bonus_amount=payload.bonus_amount,
                    bonus_max_amount=payload.bonus_max_amount,
                    options=_options(payload),
                    valid_from=payload.valid_from or payload.claim_date,
                    valid_to=payload.valid_to or payload.claim_date,
                    gift_code=payload.gift_code,
                ),
            )
    except (
        ErpCompatibilityRemoteExecutionError,
        ErpCompatibilityIdError,
        ErpRemoteExecutionGateError,
        RemoteAccountCredentialsError,
        ErpRedemptionRemoteHttpError,
    ) as exc:
        await write_audit(
            session,
            action="erp_compatibility_redemption.remote_create",
            actor_user_id=actor_user_id,
            target_type="erp_compatibility_remote_account",
            target_id=str(payload.account_id),
            result=(
                "pending_review" if isinstance(exc, ErpRedemptionRemoteReviewPending) else "failure"
            ),
            metadata={"issue_id": payload.issue_id, "operation": "CREATE"},
        )
        await session.commit()
        raise ErpCompatibilityRemoteExecutionError(str(exc)) from exc

    await write_audit(
        session,
        action="erp_compatibility_redemption.remote_create",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={
            "compatibility_account_id": payload.account_id,
            "issue_id": payload.issue_id,
            "operation": "CREATE",
            "remote_configuration_recorded": True,
            # Durable response receipt for reconciliation if Java registration fails.
            "remote_configuration_id": result.remote_configuration_id,
            "source_id": account.source_id,
        },
    )
    await session.commit()
    return CompatibilityRemoteCreateResult(
        remote_configuration_id=result.remote_configuration_id,
        remote_group_key=result.remote_group_key,
        remote_request_id=result.remote_request_id,
    )


async def execute_compatibility_remote_download(
    session: AsyncSession,
    *,
    payload: ErpCompatibilityRemoteDownloadRequest,
    actor_user_id: int,
    settings: Settings,
    transport=None,
) -> RemoteDownloadResult:
    try:
        account_id = await resolve_erp_compatibility_id(
            session, entity_type="remote_account", legacy_id=payload.account_id
        )
        grant = await authorize_erp_redemption_remote_execution(
            session,
            account_id=account_id,
            operation="DOWNLOAD",
            execution_authorized=payload.execution_confirmed,
        )
        account = await session.get(RemoteAccount, account_id)
        source = await session.get(SourceConfig, grant.source_id)
        if account is None or source is None or not source.base_url:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号或盘口配置不可用。")
        envelope = credential_envelope_for_account(account=account, source=source)
        if envelope is None:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号凭据配置不完整。")
        credentials = decrypt_remote_account_credentials(envelope, settings=settings)
        async with RajAdminGiftCodeAdapter(
            remote_session=account_session(
                session, envelope=envelope, base_url=source.base_url, settings=settings
            ),
            account_id=account.id,
            source_id=source.source_id,
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            business_timezone=settings.default_business_timezone,
            transport=transport,
        ) as adapter:
            result = await adapter.download(
                grant=grant,
                command=RemoteDownloadCommand(
                    issue_id=str(payload.issue_id),
                    remote_configuration_id=payload.remote_configuration_id,
                    remote_group_key=payload.remote_group_key,
                    key_number=payload.key_number,
                ),
            )
    except (
        ErpCompatibilityRemoteExecutionError,
        ErpCompatibilityIdError,
        ErpRemoteExecutionGateError,
        RemoteAccountCredentialsError,
        ErpRedemptionRemoteHttpError,
    ) as exc:
        await write_audit(
            session,
            action="erp_compatibility_redemption.remote_download",
            actor_user_id=actor_user_id,
            target_type="erp_compatibility_remote_account",
            target_id=str(payload.account_id),
            result="failure",
            metadata={"issue_id": payload.issue_id, "operation": "DOWNLOAD"},
        )
        await session.commit()
        raise ErpCompatibilityRemoteExecutionError(str(exc)) from exc
    await write_audit(
        session,
        action="erp_compatibility_redemption.remote_download",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={
            "issue_id": payload.issue_id,
            "operation": "DOWNLOAD",
            "code_count": payload.key_number,
        },
    )
    await session.commit()
    return result


async def execute_compatibility_remote_publish(
    session: AsyncSession,
    *,
    payload: ErpCompatibilityRemotePublishRequest,
    actor_user_id: int,
    settings: Settings,
    transport=None,
) -> CompatibilityRemotePublishResult:
    """Publish using the unified account selected by the Java batch."""

    try:
        account_id = await resolve_erp_compatibility_id(
            session, entity_type="remote_account", legacy_id=payload.account_id
        )
        grant = await authorize_erp_redemption_remote_execution(
            session,
            account_id=account_id,
            operation="PUBLISH",
            execution_authorized=payload.execution_confirmed,
        )
        account = await session.get(RemoteAccount, account_id)
        source = await session.get(SourceConfig, grant.source_id)
        if account is None or source is None or not source.base_url:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号或盘口配置不可用。")
        envelope = credential_envelope_for_account(account=account, source=source)
        if envelope is None:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号凭据配置不完整。")
        credentials = decrypt_remote_account_credentials(envelope, settings=settings)
        scheduled_time = payload.scheduled_time
        if scheduled_time is not None:
            business_timezone = ZoneInfo(settings.default_business_timezone)
            scheduled_time = (
                scheduled_time.replace(tzinfo=business_timezone)
                if scheduled_time.tzinfo is None
                else scheduled_time.astimezone(business_timezone)
            )
        async with RajAdminGiftCodeAdapter(
            remote_session=account_session(
                session, envelope=envelope, base_url=source.base_url, settings=settings
            ),
            account_id=account.id,
            source_id=source.source_id,
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            business_timezone=settings.default_business_timezone,
            transport=transport,
        ) as adapter:
            result: RemotePublishResult = await adapter.publish(
                grant=grant,
                command=RemotePublishCommand(
                    publish_environment=payload.publish_environment,
                    mode=payload.mode,
                    scheduled_publish_at=scheduled_time,
                    fallback_to_scheduled=payload.fallback_to_scheduled,
                ),
            )
    except (
        ErpCompatibilityRemoteExecutionError,
        ErpCompatibilityIdError,
        ErpRemoteExecutionGateError,
        RemoteAccountCredentialsError,
        ErpRedemptionRemoteHttpError,
    ) as exc:
        await write_audit(
            session,
            action="erp_compatibility_redemption.remote_publish",
            actor_user_id=actor_user_id,
            target_type="erp_compatibility_remote_account",
            target_id=str(payload.account_id),
            result="failure",
            metadata={
                "batch_id": payload.batch_id,
                "operation": "PUBLISH",
                "mode": payload.mode,
            },
        )
        await session.commit()
        raise ErpCompatibilityRemoteExecutionError(str(exc)) from exc

    await write_audit(
        session,
        action="erp_compatibility_redemption.remote_publish",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={
            "compatibility_account_id": payload.account_id,
            "batch_id": payload.batch_id,
            "operation": "PUBLISH",
            "mode": payload.mode,
            "remote_publish_task_recorded": True,
        },
    )
    await session.commit()
    return CompatibilityRemotePublishResult(
        remote_publish_task_id=result.remote_publish_task_id,
        remote_request_id=result.remote_request_id,
    )


async def execute_compatibility_remote_cancel(
    session: AsyncSession,
    *,
    payload: ErpCompatibilityRemoteCancelRequest,
    actor_user_id: int,
    settings: Settings,
    transport=None,
) -> RemoteCancelPublishResult:
    try:
        account_id = await resolve_erp_compatibility_id(
            session, entity_type="remote_account", legacy_id=payload.account_id
        )
        grant = await authorize_erp_redemption_remote_execution(
            session,
            account_id=account_id,
            operation="CANCEL",
            execution_authorized=payload.execution_confirmed,
        )
        account = await session.get(RemoteAccount, account_id)
        source = await session.get(SourceConfig, grant.source_id)
        if account is None or source is None or not source.base_url:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号或盘口配置不可用。")
        envelope = credential_envelope_for_account(account=account, source=source)
        if envelope is None:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号凭据配置不完整。")
        credentials = decrypt_remote_account_credentials(envelope, settings=settings)
        async with RajAdminGiftCodeAdapter(
            remote_session=account_session(
                session, envelope=envelope, base_url=source.base_url, settings=settings
            ),
            account_id=account.id,
            source_id=source.source_id,
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            business_timezone=settings.default_business_timezone,
            transport=transport,
        ) as adapter:
            result = await adapter.cancel_publish(
                grant=grant,
                command=RemoteCancelPublishCommand(
                    remote_publish_task_id=payload.remote_publish_task_id,
                ),
            )
    except (
        ErpCompatibilityRemoteExecutionError,
        ErpCompatibilityIdError,
        ErpRemoteExecutionGateError,
        RemoteAccountCredentialsError,
        ErpRedemptionRemoteHttpError,
    ) as exc:
        await write_audit(
            session,
            action="erp_compatibility_redemption.remote_cancel",
            actor_user_id=actor_user_id,
            target_type="erp_compatibility_remote_account",
            target_id=str(payload.account_id),
            result="failure",
            metadata={"batch_id": payload.batch_id, "operation": "CANCEL"},
        )
        await session.commit()
        raise ErpCompatibilityRemoteExecutionError(str(exc)) from exc
    await write_audit(
        session,
        action="erp_compatibility_redemption.remote_cancel",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={
            "batch_id": payload.batch_id,
            "operation": "CANCEL",
            "remote_publish_task_id": payload.remote_publish_task_id,
        },
    )
    await session.commit()
    return result


async def execute_compatibility_remote_verify(
    session: AsyncSession,
    *,
    payload: ErpCompatibilityRemoteVerifyRequest,
    actor_user_id: int,
    settings: Settings,
    transport=None,
) -> ErpCompatibilityRemoteVerifyResponse:
    try:
        account_id = await resolve_erp_compatibility_id(
            session, entity_type="remote_account", legacy_id=payload.account_id
        )
        grant = await authorize_erp_redemption_remote_execution(
            session,
            account_id=account_id,
            operation="DOWNLOAD",
            execution_authorized=True,
        )
        account = await session.get(RemoteAccount, account_id)
        source = await session.get(SourceConfig, grant.source_id)
        if account is None or source is None or not source.base_url:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号或盘口配置不可用。")
        envelope = credential_envelope_for_account(account=account, source=source)
        if envelope is None:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号凭据配置不完整。")
        credentials = decrypt_remote_account_credentials(envelope, settings=settings)
        async with RajAdminGiftCodeAdapter(
            remote_session=account_session(
                session, envelope=envelope, base_url=source.base_url, settings=settings
            ),
            account_id=account.id,
            source_id=source.source_id,
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            business_timezone=settings.default_business_timezone,
            transport=transport,
        ) as adapter:
            result = await adapter.verify_publication(grant=grant, payload=payload)
    except (
        ErpCompatibilityRemoteExecutionError,
        ErpCompatibilityIdError,
        ErpRemoteExecutionGateError,
        RemoteAccountCredentialsError,
        ErpRedemptionRemoteHttpError,
    ) as exc:
        await write_audit(
            session,
            action="erp_compatibility_redemption.remote_verify",
            actor_user_id=actor_user_id,
            target_type="erp_compatibility_remote_account",
            target_id=str(payload.account_id),
            result="failure",
            metadata={"batch_id": payload.batch_id, "operation": "VERIFY"},
        )
        await session.commit()
        raise ErpCompatibilityRemoteExecutionError(str(exc)) from exc
    await write_audit(
        session,
        action="erp_compatibility_redemption.remote_verify",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={
            "batch_id": payload.batch_id,
            "operation": "VERIFY",
            "remote_publish_task_id": payload.remote_publish_task_id,
        },
    )
    await session.commit()
    return result


async def check_compatibility_remote_duplicates(
    session: AsyncSession,
    *,
    payload: ErpCompatibilityRemoteDuplicateCheckRequest,
    actor_user_id: int,
    settings: Settings,
    transport=None,
) -> dict:
    """Optional batch duplicate scan using the unified read capability and session."""
    try:
        account_id = await resolve_erp_compatibility_id(
            session, entity_type="remote_account", legacy_id=payload.account_id
        )
        account = await session.get(RemoteAccount, account_id)
        source = await session.get(SourceConfig, account.source_id) if account else None
        if (
            not account
            or not source
            or not account.enabled
            or not source.enabled
            or not source.base_url
        ):
            raise ErpCompatibilityRemoteExecutionError("统一远端账号或盘口不可用。")
        allowed = await session.scalar(
            select(RemoteAccountCapability.enabled).where(
                RemoteAccountCapability.account_id == account_id,
                RemoteAccountCapability.capability == "ERP_REMOTE_CHECK",
            )
        )
        if not allowed:
            raise ErpCompatibilityRemoteExecutionError(
                "账号未获远端配置读取能力，不能执行远端查重。"
            )
        envelope = credential_envelope_for_account(account=account, source=source)
        if envelope is None:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号凭据配置不完整。")
        credentials = decrypt_remote_account_credentials(envelope, settings=settings)
        async with RajAdminGiftCodeAdapter(
            remote_session=account_session(
                session, envelope=envelope, base_url=source.base_url, settings=settings
            ),
            account_id=account.id,
            source_id=source.source_id,
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            business_timezone=source.business_timezone,
            transport=transport,
        ) as adapter:
            result = await asyncio.wait_for(adapter.check_duplicate_codes(
                grant=ErpRemoteAccountReadGrant(
                    account_id=account.id,
                    source_id=source.source_id,
                    operation="CHECK",
                    capability="ERP_REMOTE_CHECK",
                ),
                gift_codes=payload.gift_codes,
            ), timeout=75)
    except (
        TimeoutError,
        ErpCompatibilityRemoteExecutionError,
        ErpCompatibilityIdError,
        RemoteAccountCredentialsError,
        ErpRedemptionRemoteHttpError,
    ) as exc:
        await write_audit(
            session,
            action="erp_compatibility_redemption.duplicate_check",
            actor_user_id=actor_user_id,
            target_type="erp_compatibility_remote_account",
            target_id=str(payload.account_id),
            result="failure",
            metadata={"code_count": len(payload.gift_codes), "operation": "READ_DUPLICATES"},
        )
        await session.commit()
        raise ErpCompatibilityRemoteExecutionError(
            str(exc) or "远端查重超时，本次查重未完成。"
        ) from exc
    await write_audit(
        session,
        action="erp_compatibility_redemption.duplicate_check",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={"code_count": len(payload.gift_codes), "operation": "READ_DUPLICATES",
                  "matched_count": len(result["matches"])},
    )
    await session.commit()
    return result


async def check_compatibility_remote_reuse(
    session: AsyncSession,
    *,
    payload: ErpCompatibilityRemoteReuseCheckRequest,
    actor_user_id: int,
    settings: Settings,
    transport=None,
) -> ErpCompatibilityRemoteReuseCheckResponse:
    """Verify the live policy through the unified read capability and session only."""
    try:
        account_id = await resolve_erp_compatibility_id(
            session, entity_type="remote_account", legacy_id=payload.account_id
        )
        account = await session.get(RemoteAccount, account_id)
        source = await session.get(SourceConfig, account.source_id) if account else None
        if (
            not account
            or not source
            or not account.enabled
            or not source.enabled
            or not source.base_url
        ):
            raise ErpCompatibilityRemoteExecutionError("统一远端账号或盘口不可用。")
        allowed = await session.scalar(
            select(RemoteAccountCapability.enabled).where(
                RemoteAccountCapability.account_id == account_id,
                RemoteAccountCapability.capability == "ERP_REMOTE_CHECK",
            )
        )
        if not allowed:
            raise ErpCompatibilityRemoteExecutionError("账号未获远端配置读取能力，不能核验复用。")
        envelope = credential_envelope_for_account(account=account, source=source)
        if envelope is None:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号凭据配置不完整。")
        credentials = decrypt_remote_account_credentials(envelope, settings=settings)
        async with RajAdminGiftCodeAdapter(
            remote_session=account_session(
                session, envelope=envelope, base_url=source.base_url, settings=settings
            ),
            account_id=account.id,
            source_id=source.source_id,
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            business_timezone=source.business_timezone,
            transport=transport,
        ) as adapter:
            result = await adapter.check_reusable_configuration(
                grant=ErpRemoteAccountReadGrant(
                    account_id=account.id,
                    source_id=source.source_id,
                    operation="CHECK",
                    capability="ERP_REMOTE_CHECK",
                ),
                payload=payload,
            )
    except (
        ErpCompatibilityRemoteExecutionError,
        ErpCompatibilityIdError,
        RemoteAccountCredentialsError,
        ErpRedemptionRemoteHttpError,
    ) as exc:
        await write_audit(
            session,
            action="erp_compatibility_redemption.reuse_check",
            actor_user_id=actor_user_id,
            target_type="erp_compatibility_remote_account",
            target_id=str(payload.account_id),
            result="failure",
            metadata={"issue_id": payload.issue_id, "operation": "READ_REUSE"},
        )
        await session.commit()
        raise ErpCompatibilityRemoteExecutionError(str(exc)) from exc
    await write_audit(
        session,
        action="erp_compatibility_redemption.reuse_check",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={
            "issue_id": payload.issue_id,
            "configuration_id": payload.remote_configuration_id,
            "matched": result.matched,
            "differences": result.differences,
        },
    )
    await session.commit()
    return result


async def check_compatibility_remote_recovery(
    session: AsyncSession,
    *,
    payload: ErpCompatibilityRemoteRecoveryCheckRequest,
    actor_user_id: int,
    settings: Settings,
    transport=None,
) -> ErpCompatibilityRemoteRecoveryCheckResponse:
    """Verify the live policy through the unified read capability and session only."""
    try:
        account_id = await resolve_erp_compatibility_id(
            session, entity_type="remote_account", legacy_id=payload.account_id
        )
        account = await session.get(RemoteAccount, account_id)
        source = await session.get(SourceConfig, account.source_id) if account else None
        if (
            not account
            or not source
            or not account.enabled
            or not source.enabled
            or not source.base_url
        ):
            raise ErpCompatibilityRemoteExecutionError("统一远端账号或盘口不可用。")
        allowed = await session.scalar(
            select(RemoteAccountCapability.enabled).where(
                RemoteAccountCapability.account_id == account_id,
                RemoteAccountCapability.capability == "ERP_REMOTE_CHECK",
            )
        )
        if not allowed:
            raise ErpCompatibilityRemoteExecutionError("账号未获远端配置读取能力，不能核验复用。")
        if payload.check_inventory:
            download_allowed = await session.scalar(
                select(RemoteAccountCapability.enabled).where(
                    RemoteAccountCapability.account_id == account_id,
                    RemoteAccountCapability.capability == "ERP_REDEMPTION_DOWNLOAD",
                )
            )
            if not download_allowed:
                raise ErpCompatibilityRemoteExecutionError(
                    "账号未获兑换码下载能力，不能核验历史库存。"
                )
        envelope = credential_envelope_for_account(account=account, source=source)
        if envelope is None:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号凭据配置不完整。")
        credentials = decrypt_remote_account_credentials(envelope, settings=settings)
        async with RajAdminGiftCodeAdapter(
            remote_session=account_session(
                session, envelope=envelope, base_url=source.base_url, settings=settings
            ),
            account_id=account.id,
            source_id=source.source_id,
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            business_timezone=source.business_timezone,
            transport=transport,
        ) as adapter:
            result = await asyncio.wait_for(
                adapter.check_configuration_recovery(
                    grant=ErpRemoteAccountReadGrant(
                        account_id=account.id,
                        source_id=source.source_id,
                        operation="CHECK",
                        capability="ERP_REMOTE_CHECK",
                    ),
                    payload=payload,
                    inventory_grant=ErpRemoteExecutionGrant(
                        account_id=account.id,
                        source_id=source.source_id,
                        operation="DOWNLOAD",
                        capability="ERP_REDEMPTION_DOWNLOAD",
                    )
                    if payload.check_inventory
                    else None,
                ),
                timeout=35,
            )
    except (
        TimeoutError,
        ErpCompatibilityRemoteExecutionError,
        ErpCompatibilityIdError,
        RemoteAccountCredentialsError,
        ErpRedemptionRemoteHttpError,
    ) as exc:
        await write_audit(
            session,
            action="erp_compatibility_redemption.recovery_check",
            actor_user_id=actor_user_id,
            target_type="erp_compatibility_remote_account",
            target_id=str(payload.account_id),
            result="failure",
            metadata={"issue_id": payload.issue_id, "operation": "READ_RECOVERY"},
        )
        await session.commit()
        raise ErpCompatibilityRemoteExecutionError(
            str(exc) or "远端目录核验超时；未重新创建。"
        ) from exc
    await write_audit(
        session,
        action="erp_compatibility_redemption.recovery_check",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={
            "issue_id": payload.issue_id,
            "configuration_id": payload.remote_configuration_id,
            "state": result.state,
            "scanned_rows": result.scanned_rows,
            "scanned_pages": result.scanned_pages,
        },
    )
    await session.commit()
    return result


async def execute_compatibility_remote_reward_update(
    session: AsyncSession,
    *,
    payload: ErpCompatibilityRemoteRewardUpdateRequest,
    actor_user_id: int,
    settings: Settings,
    transport=None,
) -> ErpCompatibilityRemoteReuseCheckResponse:
    """Verify the live policy through the unified read capability and session only."""
    try:
        account_id = await resolve_erp_compatibility_id(
            session, entity_type="remote_account", legacy_id=payload.account_id
        )
        account = await session.get(RemoteAccount, account_id)
        source = await session.get(SourceConfig, account.source_id) if account else None
        if (
            not account
            or not source
            or not account.enabled
            or not source.enabled
            or not source.base_url
        ):
            raise ErpCompatibilityRemoteExecutionError("统一远端账号或盘口不可用。")
        allowed = await session.scalar(
            select(RemoteAccountCapability.enabled).where(
                RemoteAccountCapability.account_id == account_id,
                RemoteAccountCapability.capability == "ERP_REMOTE_CHECK",
            )
        )
        if not allowed:
            raise ErpCompatibilityRemoteExecutionError("账号未获远端配置读取能力，不能核验复用。")
        grant = await authorize_erp_redemption_remote_execution(
            session,
            account_id=account_id,
            operation="UPDATE",
            execution_authorized=payload.execution_confirmed,
        )
        envelope = credential_envelope_for_account(account=account, source=source)
        if envelope is None:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号凭据配置不完整。")
        credentials = decrypt_remote_account_credentials(envelope, settings=settings)
        async with RajAdminGiftCodeAdapter(
            remote_session=account_session(
                session, envelope=envelope, base_url=source.base_url, settings=settings
            ),
            account_id=account.id,
            source_id=source.source_id,
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            business_timezone=source.business_timezone,
            transport=transport,
        ) as adapter:
            result = await adapter.update_reward_policy(
                grant=grant,
                read_grant=ErpRemoteAccountReadGrant(
                    account_id=account.id,
                    source_id=source.source_id,
                    operation="CHECK",
                    capability="ERP_REMOTE_CHECK",
                ),
                payload=payload,
            )
    except (
        ErpRemoteExecutionGateError,
        ErpCompatibilityRemoteExecutionError,
        ErpCompatibilityIdError,
        RemoteAccountCredentialsError,
        ErpRedemptionRemoteHttpError,
    ) as exc:
        await write_audit(
            session,
            action="erp_compatibility_redemption.reward_update",
            actor_user_id=actor_user_id,
            target_type="erp_compatibility_remote_account",
            target_id=str(payload.account_id),
            result="failure",
            metadata={"issue_id": payload.issue_id, "operation": "UPDATE_REWARD"},
        )
        await session.commit()
        raise ErpCompatibilityRemoteExecutionError(str(exc)) from exc
    await write_audit(
        session,
        action="erp_compatibility_redemption.reward_update",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={
            "issue_id": payload.issue_id,
            "configuration_id": payload.remote_configuration_id,
            "matched": result.matched,
            "differences": result.differences,
            "operation": "UPDATE_REWARD",
            "bonus_amount": str(payload.bonus_amount),
            "bonus_max_amount": str(payload.bonus_max_amount),
        },
    )
    await session.commit()
    return result

async def check_compatibility_remote_absence(
    session: AsyncSession,
    *,
    payload: ErpCompatibilityRemoteAbsenceCheckRequest,
    actor_user_id: int,
    settings: Settings,
    transport=None,
) -> ErpCompatibilityRemoteAbsenceCheckResponse:
    """Prove absence without changing any original task or remote configuration."""
    try:
        account_id = await resolve_erp_compatibility_id(
            session, entity_type="remote_account", legacy_id=payload.account_id
        )
        account = await session.get(RemoteAccount, account_id)
        source = await session.get(SourceConfig, account.source_id) if account else None
        if (
            not account
            or not source
            or not account.enabled
            or not source.enabled
            or not source.base_url
        ):
            raise ErpCompatibilityRemoteExecutionError("统一远端账号或盘口不可用。")
        allowed = await session.scalar(
            select(RemoteAccountCapability.enabled).where(
                RemoteAccountCapability.account_id == account_id,
                RemoteAccountCapability.capability == "ERP_REMOTE_CHECK",
            )
        )
        if not allowed:
            raise ErpCompatibilityRemoteExecutionError("账号未获远端配置读取能力，不能核验复用。")
        envelope = credential_envelope_for_account(account=account, source=source)
        if envelope is None:
            raise ErpCompatibilityRemoteExecutionError("统一远端账号凭据配置不完整。")
        credentials = decrypt_remote_account_credentials(envelope, settings=settings)
        async with RajAdminGiftCodeAdapter(
            remote_session=account_session(
                session, envelope=envelope, base_url=source.base_url, settings=settings
            ),
            account_id=account.id,
            source_id=source.source_id,
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
            business_timezone=source.business_timezone,
            transport=transport,
        ) as adapter:
            try:
                rows, pages = await asyncio.wait_for(
                    adapter.confirm_special_code_absent(
                        grant=ErpRemoteAccountReadGrant(
                            account_id=account.id,
                            source_id=source.source_id,
                            operation="CHECK",
                            capability="ERP_REMOTE_CHECK",
                        ),
                        gift_code=payload.gift_code,
                    ),
                    timeout=35,
                )
            except TimeoutError as exc:
                raise ErpCompatibilityRemoteExecutionError(
                    "完整远端目录核验超时；未重新创建。"
                ) from exc
            result = ErpCompatibilityRemoteAbsenceCheckResponse(
                gift_code=payload.gift_code,
                confirmed_absent=True,
                scanned_rows=rows,
                scanned_pages=pages,
                checked_at=datetime.now(UTC),
            )
    except (
        ErpCompatibilityRemoteExecutionError,
        ErpCompatibilityIdError,
        RemoteAccountCredentialsError,
        ErpRedemptionRemoteHttpError,
    ) as exc:
        await write_audit(
            session,
            action="erp_compatibility_redemption.absence_check",
            actor_user_id=actor_user_id,
            target_type="erp_compatibility_remote_account",
            target_id=str(payload.account_id),
            result="failure",
            metadata={"issue_id": payload.issue_id, "operation": "READ_ABSENCE"},
        )
        await session.commit()
        raise ErpCompatibilityRemoteExecutionError(str(exc)) from exc
    await write_audit(
        session,
        action="erp_compatibility_redemption.absence_check",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={
            "issue_id": payload.issue_id,
            "gift_code": payload.gift_code,
            "confirmed_absent": result.confirmed_absent,
            "scanned_rows": result.scanned_rows,
            "scanned_pages": result.scanned_pages,
        },
    )
    await session.commit()
    return result


