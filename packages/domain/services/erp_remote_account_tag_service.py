"""Live tag-directory refreshes through the unified remote-account boundary."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings
from packages.domain.models import RemoteAccount, RemoteAccountCapability, SourceConfig
from packages.domain.schemas.remote_account import (
    RemoteTag,
    RemoteTagSnapshotResponse,
    RemoteTagSnapshotWrite,
)
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
from packages.domain.services.remote_account_service import save_remote_tag_snapshot

TAG_SYNC_CAPABILITY = "ERP_TAG_SYNC"


class RemoteAccountTagSyncError(ValueError):
    """Safe-to-display failure from a live tag-directory refresh."""


async def sync_remote_account_tags(
    session: AsyncSession,
    *,
    account_id: str,
    actor_user_id: int,
    execution_authorized: bool,
    settings: Settings,
    transport=None,
) -> RemoteTagSnapshotResponse:
    """Fetch current tags remotely, then replace the account's local snapshot."""

    try:
        if not execution_authorized:
            raise RemoteAccountTagSyncError("必须明确确认本次远端标签同步。")
        account = await session.get(RemoteAccount, account_id)
        if account is None:
            raise RemoteAccountTagSyncError("远端账号不存在。")
        if not account.enabled:
            raise RemoteAccountTagSyncError("远端账号已停用。")
        source = await session.get(SourceConfig, account.source_id)
        if source is None or not source.enabled or not source.base_url:
            raise RemoteAccountTagSyncError("远端账号所属盘口不存在、已停用或缺少地址。")
        capability_enabled = await session.scalar(
            select(RemoteAccountCapability.enabled).where(
                RemoteAccountCapability.account_id == account.id,
                RemoteAccountCapability.capability == TAG_SYNC_CAPABILITY,
            )
        )
        if not capability_enabled:
            raise RemoteAccountTagSyncError(
                f"远端账号未获得 {TAG_SYNC_CAPABILITY} 能力授权。"
            )
        envelope = credential_envelope_for_account(account=account, source=source)
        if envelope is None:
            raise RemoteAccountTagSyncError("统一远端账号凭据配置不完整。")
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
            remote_tags, request_id = await adapter.fetch_tags(
                grant=ErpRemoteAccountReadGrant(
                    account_id=account.id,
                    source_id=source.source_id,
                    operation="TAGS",
                    capability=TAG_SYNC_CAPABILITY,
                )
            )
        tags_by_id = {
            tag.id: RemoteTag(id=tag.id, name=tag.name)
            for tag in remote_tags
        }
        snapshot = await save_remote_tag_snapshot(
            session,
            account_id=account.id,
            request=RemoteTagSnapshotWrite(
                tags=list(tags_by_id.values()),
                source="REMOTE",
            ),
            actor_user_id=actor_user_id,
        )
    except (
        RemoteAccountTagSyncError,
        RemoteAccountCredentialsError,
        ErpRedemptionRemoteHttpError,
    ) as exc:
        await write_audit(
            session,
            action="remote_account.tags_sync",
            actor_user_id=actor_user_id,
            target_type="remote_account",
            target_id=account_id,
            result="failure",
            metadata={"operation": "TAGS"},
        )
        await session.commit()
        raise RemoteAccountTagSyncError(str(exc)) from exc

    await write_audit(
        session,
        action="remote_account.tags_sync",
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account.id,
        metadata={
            "operation": "TAGS",
            "tag_count": len(snapshot.tags),
            "remote_request_recorded": bool(request_id),
        },
    )
    await session.commit()
    return snapshot
