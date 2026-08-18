"""Port definitions for ERP redemption remote backends.

Only contracts live here. No concrete network adapter is registered, so the
application cannot contact a remote ERP merely because orchestration plans
exist in the local database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from packages.domain.services.erp_redemption_remote_gate import ErpRemoteExecutionGrant


@dataclass(frozen=True, slots=True)
class RemoteCreationOptions:
    publish_environment: str
    flow_times: int
    activity_recharge: Decimal | None
    activity_recharge_count: int | None
    activity_id: int | None
    key_number: int
    single_user_limit: int
    single_key_limit: int
    require_bind_bank_card: bool
    require_bind_phone: bool
    check_uuid: bool
    uuid_reward_limit: int
    check_login_ip: bool
    login_ip_reward_limit: int
    check_register_ip: bool
    register_ip_reward_limit: int


@dataclass(frozen=True, slots=True)
class RemoteCreateCommand:
    issue_id: str
    description: str
    claim_date: date
    deposit_window_start: date
    deposit_window_end: date
    label_ids: tuple[int, ...]
    bonus_amount: Decimal
    bonus_max_amount: Decimal
    options: RemoteCreationOptions


@dataclass(frozen=True, slots=True)
class RemoteCreateResult:
    remote_configuration_id: str
    remote_group_key: str | None = None
    remote_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class RemotePublishCommand:
    publish_environment: str
    mode: str
    scheduled_publish_at: datetime | None
    fallback_to_scheduled: bool


@dataclass(frozen=True, slots=True)
class RemotePublishResult:
    remote_publish_task_id: str
    scheduled_publish_at: datetime | None = None
    remote_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteDownloadCommand:
    issue_id: str
    remote_configuration_id: str
    remote_group_key: str | None


@dataclass(frozen=True, slots=True)
class RemoteDownloadResult:
    redemption_code: str
    remote_group_key: str | None = None
    remote_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteCancelPublishCommand:
    remote_publish_task_id: str


@dataclass(frozen=True, slots=True)
class RemoteCancelPublishResult:
    remote_request_id: str | None = None


class ErpRedemptionRemoteAdapter(Protocol):
    async def create_configuration(
        self,
        *,
        grant: ErpRemoteExecutionGrant,
        command: RemoteCreateCommand,
    ) -> RemoteCreateResult: ...

    async def publish(
        self,
        *,
        grant: ErpRemoteExecutionGrant,
        command: RemotePublishCommand,
    ) -> RemotePublishResult: ...

    async def download(
        self,
        *,
        grant: ErpRemoteExecutionGrant,
        command: RemoteDownloadCommand,
    ) -> RemoteDownloadResult: ...

    async def cancel_publish(
        self,
        *,
        grant: ErpRemoteExecutionGrant,
        command: RemoteCancelPublishCommand,
    ) -> RemoteCancelPublishResult: ...
