"""Unified-account execution for the preserved Java redemption facade.

The Java compatibility service owns the historical task tables and workflow
state.  This module owns the only sensitive boundary: resolving the public
numeric account projection to a unified ``RemoteAccount``, checking the
capability again and decrypting its credentials inside the main application.
No legacy Java credential record is read here.
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings
from packages.domain.models import RemoteAccount, SourceConfig
from packages.domain.schemas.remote_account import (
    ErpCompatibilityRemoteCreateRequest,
    ErpCompatibilityRemoteDownloadRequest,
    ErpCompatibilityRemotePublishRequest,
)
from packages.domain.services.auth_service import write_audit
from packages.domain.services.erp_compatibility_id_service import (
    ErpCompatibilityIdError,
    resolve_erp_compatibility_id,
)
from packages.domain.services.erp_redemption_remote_adapter import (
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
    authorize_erp_redemption_remote_execution,
)
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    RajAdminGiftCodeAdapter,
)
from packages.domain.services.remote_account_credentials import (
    RemoteAccountCredentialsError,
    credential_envelope_for_account,
    decrypt_remote_account_credentials,
)


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
            result="failure",
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
