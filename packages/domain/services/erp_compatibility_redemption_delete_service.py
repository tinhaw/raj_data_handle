"""Explicit permanent configuration deletion through the unified account/session boundary."""

import asyncio
import json

from sqlalchemy import select, text

from packages.domain.models import RemoteAccount, RemoteAccountCapability, SourceConfig
from packages.domain.services.auth_service import write_audit
from packages.domain.services.erp_compatibility_id_service import (
    ErpCompatibilityIdError,
    resolve_erp_compatibility_id,
)
from packages.domain.services.erp_compatibility_redemption_remote_service import (
    ErpCompatibilityRemoteExecutionError,
)
from packages.domain.services.erp_redemption_remote_gate import (
    authorize_erp_redemption_remote_execution,
)
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRemoteAccountReadGrant,
    RajAdminGiftCodeAdapter,
)
from packages.domain.services.remote_account_credentials import (
    credential_envelope_for_account,
    decrypt_remote_account_credentials,
)
from packages.domain.services.remote_account_session_service import account_session


async def operate_compatibility_deletion(
    session, *, payload, actor_user_id, settings, operation, transport=None
):
    """Preview/reconcile are read-only; DELETE needs its separate default-off grant."""
    if operation not in {"preview", "execute", "permission"}:
        raise ErpCompatibilityRemoteExecutionError("不支持的删除操作。")
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
            raise ValueError("统一远端账号或盘口不可用。")
        allowed = await session.scalar(
            select(RemoteAccountCapability.enabled).where(
                RemoteAccountCapability.account_id == account_id,
                RemoteAccountCapability.capability == "ERP_REMOTE_CHECK",
            )
        )
        if not allowed:
            raise ValueError("账号未获得独立配置读取能力。")
        grant = None
        if operation in {"execute", "permission"}:
            grant = await authorize_erp_redemption_remote_execution(
                session,
                account_id=account_id,
                operation="DELETE",
                execution_authorized=operation == "permission" or payload.execution_confirmed,
            )
        if operation == "permission":
            return {"allowed": True}
        envelope = credential_envelope_for_account(account=account, source=source)
        if envelope is None:
            raise ValueError("统一远端账号凭据不完整。")
        if operation == "execute":
            # Atomic across both services; duplicate HTTP requests cannot replay DELETE.
            row = (
                (
                    await session.execute(
                        text("""SELECT d.* FROM erp_compat_redemption_deletions d
                JOIN erp_compat_redemption_code_issues i ON i.id=d.owner_issue_id
                WHERE d.requested_issue_id=:issue AND d.configuration_id=:config
                  AND d.status='DELETING' AND d.remote_attempted=false
                  AND i.remote_deletion_state='DELETING'"""),
                        {"issue": payload.issue_id, "config": payload.remote_configuration_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                not row
                or json.loads(row["snapshot_json"])["accountId"] != payload.account_id
                or json.loads(row["remote_json"])["fingerprint"] != payload.expected_fingerprint
            ):
                raise ValueError("未取得本次删除的有效一次性执行记录；禁止重复提交。")
            claimed = await session.scalar(
                text("""UPDATE erp_compat_redemption_deletions
                SET remote_attempted=true WHERE id=:id AND status='DELETING'
                AND remote_attempted=false RETURNING id"""),
                {"id": row["id"]},
            )
            if claimed is None:
                raise ValueError("删除请求已经领取执行，禁止重复提交。")
            await session.commit()
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
            read_grant = ErpRemoteAccountReadGrant(
                account_id=account.id,
                source_id=source.source_id,
                operation="CHECK",
                capability="ERP_REMOTE_CHECK",
            )
            if operation == "execute":
                result = await asyncio.wait_for(
                    adapter.delete_configuration(
                        grant=grant, read_grant=read_grant, payload=payload
                    ),
                    timeout=75,
                )
            else:
                result = await asyncio.wait_for(
                    adapter.inspect_deletion(
                        grant=read_grant, configuration_id=payload.remote_configuration_id
                    ),
                    timeout=75,
                )
    except (ValueError, TimeoutError, ErpCompatibilityIdError) as exc:
        await write_audit(
            session,
            action="erp_compatibility_redemption.delete_" + operation,
            actor_user_id=actor_user_id,
            target_type="erp_compatibility_remote_account",
            target_id=str(payload.account_id),
            result="failure",
            metadata={
                "issue_id": payload.issue_id,
                "configuration_id": payload.remote_configuration_id,
            },
        )
        await session.commit()
        raise ErpCompatibilityRemoteExecutionError(
            str(exc) or "删除核验超时；请只读核对结果。"
        ) from exc
    await write_audit(
        session,
        action="erp_compatibility_redemption.delete_" + operation,
        actor_user_id=actor_user_id,
        target_type="remote_account",
        target_id=account_id,
        metadata={
            "issue_id": payload.issue_id,
            "configuration_id": payload.remote_configuration_id,
            "state": result["state"],
        },
    )
    await session.commit()
    return result
