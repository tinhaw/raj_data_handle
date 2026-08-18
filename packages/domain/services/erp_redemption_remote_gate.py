"""Authorization gate for future ERP redemption remote adapters.

This module performs local authorization checks only. It intentionally does
not read credentials, create an HTTP client, or execute any remote operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import RemoteAccount, RemoteAccountCapability, SourceConfig

ErpRedemptionRemoteOperation = Literal["CREATE", "PUBLISH", "DOWNLOAD", "CANCEL"]

ERP_REDEMPTION_REMOTE_CAPABILITIES: dict[ErpRedemptionRemoteOperation, str] = {
    "CREATE": "ERP_REDEMPTION_CREATE",
    "PUBLISH": "ERP_REDEMPTION_PUBLISH",
    "DOWNLOAD": "ERP_REDEMPTION_DOWNLOAD",
    "CANCEL": "ERP_REDEMPTION_CANCEL",
}


class ErpRemoteExecutionGateError(ValueError):
    pass


class ErpRemoteExecutionNotAuthorizedError(ErpRemoteExecutionGateError):
    pass


class ErpRemoteExecutionUnavailableError(ErpRemoteExecutionGateError):
    pass


@dataclass(frozen=True, slots=True)
class ErpRemoteExecutionGrant:
    account_id: str
    source_id: str
    operation: ErpRedemptionRemoteOperation
    capability: str


async def authorize_erp_redemption_remote_execution(
    session: AsyncSession,
    *,
    account_id: str,
    operation: ErpRedemptionRemoteOperation,
    execution_authorized: bool,
) -> ErpRemoteExecutionGrant:
    """Return a non-secret grant only when both authorization layers pass."""

    if not execution_authorized:
        raise ErpRemoteExecutionNotAuthorizedError(
            f"尚未获得本次远端兑换码{operation}操作的明确执行授权。"
        )
    capability = ERP_REDEMPTION_REMOTE_CAPABILITIES.get(operation)
    if capability is None:
        raise ErpRemoteExecutionUnavailableError("不支持的远端兑换码操作。")

    account = await session.get(RemoteAccount, account_id)
    if account is None:
        raise ErpRemoteExecutionUnavailableError("远端账号不存在。")
    if not account.enabled:
        raise ErpRemoteExecutionUnavailableError("远端账号已停用。")

    source = await session.get(SourceConfig, account.source_id)
    if source is None or not source.enabled:
        raise ErpRemoteExecutionUnavailableError("远端账号所属盘口不存在或已停用。")

    capability_enabled = await session.scalar(
        select(RemoteAccountCapability.enabled).where(
            RemoteAccountCapability.account_id == account.id,
            RemoteAccountCapability.capability == capability,
        )
    )
    if not capability_enabled:
        raise ErpRemoteExecutionNotAuthorizedError(
            f"远端账号未获得 {capability} 能力授权。"
        )

    return ErpRemoteExecutionGrant(
        account_id=account.id,
        source_id=source.source_id,
        operation=operation,
        capability=capability,
    )
