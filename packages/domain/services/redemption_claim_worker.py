"""Durable interval scheduling and leased, source-serial claim reads."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text
from sqlalchemy.exc import IntegrityError

from packages.common.database import AsyncSessionLocal
from packages.common.settings import get_settings
from packages.domain.models import (
    ErpCompatibilityIdMap,
    RedemptionClaimGroup,
    RedemptionClaimLease,
    RedemptionClaimRun,
    RedemptionClaimSchedule,
    RemoteAccount,
    RemoteAccountCapability,
    SourceConfig,
)
from packages.domain.models.entities import new_uuid
from packages.domain.services.auth_service import write_audit
from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    ErpRemoteAccountReadGrant,
    RajAdminGiftCodeAdapter,
)
from packages.domain.services.redemption_claim_reader import ClaimReadError, fetch_claim_snapshot
from packages.domain.services.redemption_claim_service import (
    ClaimError,
    authorize,
    day,
    materialize_groups,
    publish_group,
    queue_run,
    utc,
)
from packages.domain.services.remote_account_credentials import (
    RemoteAccountCredentialsError,
    credential_envelope_for_account,
    decrypt_remote_account_credentials,
)
from packages.domain.services.remote_account_session_service import account_session

LEASE_TIME = timedelta(minutes=30)
CAPABILITY = "ERP_REDEMPTION_CLAIM_READ"


class ClaimAccountUnavailable(ClaimError):
    """An initially unavailable account may be replaced by another granted account."""


class ClaimReadAccountsFailed(ClaimError):
    def __init__(self, account_ids: list[str], *, retryable: bool) -> None:
        super().__init__(f"本组已尝试 {len(account_ids)} 个同盘口授权账号，均未能读取领取记录。")
        self.account_ids = tuple(account_ids)
        self.retryable = retryable


@dataclass(frozen=True)
class GroupReadResult:
    records: list[dict]
    pages: int
    source_id: str
    account_id: str
    account_name: str
    primary_account_id: str
    attempted_account_ids: tuple[str, ...]


async def _binding_context(session, group: RedemptionClaimGroup, actor: int):
    await authorize(session, actor, sync=True)
    row = (
        (
            await session.execute(
                text("""
        SELECT b.remote_connection_id, i.remote_market_id,
               i.remote_configuration_id, i.remote_group_key
        FROM erp_compat_redemption_code_issues i
        JOIN erp_compat_redemption_code_batches b ON b.id=i.batch_id
        WHERE i.id=:issue AND b.task_id=:task
    """),
                {"issue": group.issue_id, "task": group.task_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["remote_connection_id"] is None:
        raise ClaimError("当前任务没有可读取的统一远端账号。", 403)
    source_id = await session.scalar(
        select(ErpCompatibilityIdMap.canonical_id).where(
            ErpCompatibilityIdMap.entity_type == "source",
            ErpCompatibilityIdMap.legacy_id == row["remote_market_id"],
        )
    )
    account_id = await session.scalar(
        select(ErpCompatibilityIdMap.canonical_id).where(
            ErpCompatibilityIdMap.entity_type == "remote_account",
            ErpCompatibilityIdMap.legacy_id == row["remote_connection_id"],
        )
    )
    account = (
        await session.get(RemoteAccount, account_id, populate_existing=True) if account_id else None
    )
    source = (
        await session.get(SourceConfig, source_id, populate_existing=True) if source_id else None
    )
    if (
        account is None
        or source is None
        or not source.enabled
        or not source.base_url
        or account.source_id != group.source_id
        or source_id != group.source_id
    ):
        raise ClaimError("任务盘口与统一账号不匹配，或账号/盘口已停用。", 403)
    scope = (
        account.id,
        account.enabled,
        source.source_id,
        row["remote_connection_id"],
        row["remote_configuration_id"],
        row["remote_group_key"],
        source.config_version,
        source.base_url,
        account.login_username,
        account.credential_mode,
        account.credential_version,
        source.credential_version,
    )
    return account, source, scope


async def binding_authorization(
    session, group: RedemptionClaimGroup, actor: int, *, account_id=None, expected_binding=None
):
    bound, source, binding = await _binding_context(session, group, actor)
    if expected_binding is not None and binding != expected_binding:
        raise ClaimError("同步期间任务账号或远端配置已变化，请重新同步。")
    account = (
        await session.get(RemoteAccount, account_id, populate_existing=True)
        if account_id is not None
        else bound
    )
    if account is None or account.source_id != source.source_id:
        raise ClaimError("读取账号不属于任务盘口，已停止同步。", 403)
    if not account.enabled:
        raise ClaimAccountUnavailable("统一远端账号已停用。", 403)
    enabled = await session.scalar(
        select(RemoteAccountCapability.enabled).where(
            RemoteAccountCapability.account_id == account.id,
            RemoteAccountCapability.capability == CAPABILITY,
        )
    )
    if not enabled:
        raise ClaimAccountUnavailable("统一远端账号尚未获得兑换码领取记录读取能力。", 403)
    scope = binding + (
        account.id,
        account.login_username,
        account.credential_mode,
        account.credential_version,
    )
    return account, source, scope


async def read_group(
    factory,
    run_id,
    token,
    group_id,
    actor,
    *,
    transport=None,
    settings=None,
    preferred_account_id=None,
):
    """Try one complete snapshot per account; never combine pages between accounts."""
    async with factory() as session:
        await owned_run(session, run_id, token)
        group = await session.get(RedemptionClaimGroup, group_id)
        bound, source, binding = await _binding_context(session, group, actor)
        primary_id = bound.id
        candidates = list(
            await session.scalars(
                select(RemoteAccount)
                .join(
                    RemoteAccountCapability, RemoteAccountCapability.account_id == RemoteAccount.id
                )
                .where(
                    RemoteAccount.source_id == source.source_id,
                    RemoteAccount.enabled.is_(True),
                    RemoteAccountCapability.capability == CAPABILITY,
                    RemoteAccountCapability.enabled.is_(True),
                )
                .order_by(
                    RemoteAccount.is_default.desc(), RemoteAccount.created_at, RemoteAccount.id
                )
            )
        )
        candidates = [
            account
            for account in candidates
            if credential_envelope_for_account(account=account, source=source) is not None
        ]
        # A successful backup stays preferred for this task binding in this run.
        # New runs start with the original explicitly bound account again.
        first = (
            preferred_account_id
            if preferred_account_id in {a.id for a in candidates}
            else primary_id
        )
        candidates.sort(key=lambda account: 0 if account.id == first else 1)
        if not candidates:
            await binding_authorization(session, group, actor)
            raise ClaimError("没有已启用且具备领取读取授权和凭据的同盘口账号。", 403)
    attempted = []
    last_error = None
    retryable = False
    for candidate in candidates:
        attempted.append(candidate.id)
        try:
            result = await _read_group_using_account(
                factory,
                run_id,
                token,
                group_id,
                actor,
                account_id=candidate.id,
                expected_binding=binding,
                transport=transport,
                settings=settings,
            )
            return GroupReadResult(
                result.records,
                result.pages,
                source.source_id,
                candidate.id,
                candidate.display_name,
                primary_id,
                tuple(attempted),
            )
        except ClaimAccountUnavailable as exc:
            last_error = exc
        except ErpRedemptionRemoteHttpError as exc:
            if not exc.fallback_allowed:
                raise
            last_error = exc
            retryable = retryable or exc.retryable
    assert last_error is not None
    if len(attempted) > 1:
        raise ClaimReadAccountsFailed(attempted, retryable=retryable) from last_error
    raise last_error


async def schedule_due(factory=AsyncSessionLocal, *, now=None) -> None:
    now = now or datetime.now(UTC)
    async with factory() as session:
        due = list(
            await session.scalars(
                select(RedemptionClaimSchedule)
                .where(
                    RedemptionClaimSchedule.enabled.is_(True),
                    RedemptionClaimSchedule.active_run_id.is_(None),
                    RedemptionClaimSchedule.next_run_at <= now,
                )
                .with_for_update(skip_locked=True)
                .limit(20)
            )
        )
        for setting in due:
            await queue_run(session, setting, setting.actor_user_id, "automatic")
        await session.commit()


async def claim_next(factory=AsyncSessionLocal):
    now = datetime.now(UTC)
    async with factory() as session:
        run = await session.scalar(
            select(RedemptionClaimRun)
            .where(
                or_(
                    RedemptionClaimRun.status == "queued",
                    (RedemptionClaimRun.status == "running")
                    & (RedemptionClaimRun.lease_expires_at <= now),
                )
            )
            .order_by(RedemptionClaimRun.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if run is None:
            return None
        setting = await session.get(RedemptionClaimSchedule, run.task_id, with_for_update=True)
        if not setting or setting.active_run_id != run.id:
            run.status = "superseded"
            await session.commit()
            return None
        run.status = "running"
        run.started_at = now
        run.lease_token = new_uuid()
        run.lease_expires_at = now + LEASE_TIME
        run.progress = {
            "totalGroups": 0,
            "completedGroups": 0,
            "failedGroups": 0,
            "pages": 0,
            "records": 0,
            "backupGroups": 0,
            "accountUsage": [],
            "errors": [],
        }
        await session.commit()
        return run.id, run.lease_token, run.task_id, run.actor_user_id, run.trigger


async def owned_run(session, run_id: str, token: str) -> RedemptionClaimRun:
    run = await session.get(
        RedemptionClaimRun, run_id, with_for_update=True, populate_existing=True
    )
    if (
        not run
        or run.status != "running"
        or run.lease_token != token
        or not run.lease_expires_at
        or utc(run.lease_expires_at) <= datetime.now(UTC)
    ):
        raise ClaimError("同步执行租约已失效，旧执行已停止。")
    return run


async def acquire_source(session, source_id: str, token: str) -> bool:
    now = datetime.now(UTC)
    lease = await session.get(RedemptionClaimLease, source_id, with_for_update=True)
    if lease and utc(lease.expires_at) > now and lease.token != token:
        return False
    if not lease:
        try:
            async with session.begin_nested():
                lease = RedemptionClaimLease(
                    source_id=source_id, token=token, expires_at=now + LEASE_TIME
                )
                session.add(lease)
                await session.flush()
        except IntegrityError:
            return False
    lease.token = token
    lease.expires_at = now + LEASE_TIME
    return True


async def _read_group_using_account(
    factory,
    run_id,
    token,
    group_id,
    actor,
    *,
    account_id,
    expected_binding,
    transport=None,
    settings=None,
):
    settings = settings or get_settings()
    async with factory() as session:
        await owned_run(session, run_id, token)
        group = await session.get(RedemptionClaimGroup, group_id)
        account, source, expected_scope = await binding_authorization(
            session, group, actor, account_id=account_id, expected_binding=expected_binding
        )
        if not group.group_key:
            raise ClaimError("远端兑换码组标识尚未登记，请先核对配置。")
        if not await acquire_source(session, source.source_id, token):
            raise ClaimError("该盘口已有同步运行，本轮稍后重试。")
        envelope = credential_envelope_for_account(account=account, source=source)
        if envelope is None:
            raise ClaimAccountUnavailable("统一远端账号凭据尚未配置。")
        try:
            credentials = decrypt_remote_account_credentials(envelope, settings=settings)
        except RemoteAccountCredentialsError as exc:
            raise ClaimAccountUnavailable("统一远端账号凭据不可用。") from exc
        grant = ErpRemoteAccountReadGrant(account.id, source.source_id, "CLAIMS", CAPABILITY)
        remote_session = account_session(
            session, envelope=envelope, base_url=source.base_url, settings=settings
        )
        await session.commit()

        async def heartbeat():
            async with factory() as checkpoint:
                current = await owned_run(checkpoint, run_id, token)
                current_group = await checkpoint.get(RedemptionClaimGroup, group_id)
                try:
                    _, _, scope = await binding_authorization(
                        checkpoint,
                        current_group,
                        actor,
                        account_id=account_id,
                        expected_binding=expected_binding,
                    )
                except ClaimAccountUnavailable as exc:
                    raise ClaimError("同步期间读取账号授权已变化，已停止本组同步。", 403) from exc
                if scope != expected_scope:
                    raise ClaimError("同步期间任务账号或远端配置已变化，请重新同步。")
                lease = await checkpoint.get(
                    RedemptionClaimLease, source.source_id, with_for_update=True
                )
                if not lease or lease.token != token or utc(lease.expires_at) <= datetime.now(UTC):
                    raise ClaimError("盘口同步租约已失效。")
                current.lease_expires_at = datetime.now(UTC) + LEASE_TIME
                lease.expires_at = datetime.now(UTC) + LEASE_TIME
                await checkpoint.commit()

        try:
            async with RajAdminGiftCodeAdapter(
                account_id=account.id,
                source_id=source.source_id,
                base_url=source.base_url,
                username=credentials["username"],
                password=credentials["password"],
                totp_secret=credentials["totp_secret"],
                business_timezone=group.snapshot["timezone"],
                remote_session=remote_session,
                transport=transport,
            ) as adapter:
                result = await fetch_claim_snapshot(
                    adapter, grant, group.group_key, group.snapshot["timezone"], heartbeat
                )
            await heartbeat()
            async with factory() as checkpoint:
                await owned_run(checkpoint, run_id, token)
                current_group = await checkpoint.get(
                    RedemptionClaimGroup, group_id, with_for_update=True
                )
                try:
                    _, _, scope = await binding_authorization(
                        checkpoint,
                        current_group,
                        actor,
                        account_id=account_id,
                        expected_binding=expected_binding,
                    )
                except ClaimAccountUnavailable as exc:
                    raise ClaimError("同步期间读取账号授权已变化，未发布本组结果。", 403) from exc
                if scope != expected_scope:
                    raise ClaimError("统计归属发生变化，未更新可见结果。")
                await publish_group(checkpoint, current_group, result.records)
                await checkpoint.commit()
            return result
        finally:
            async with factory() as cleanup:
                lease = await cleanup.get(
                    RedemptionClaimLease, source.source_id, with_for_update=True
                )
                if lease and lease.token == token:
                    lease.expires_at = datetime.now(UTC)
                    await cleanup.commit()


async def process_claim_sync(factory=AsyncSessionLocal, *, transport=None, settings=None) -> bool:
    await schedule_due(factory)
    claim = await claim_next(factory)
    if claim is None:
        return False
    run_id, token, task_id, actor, trigger = claim
    progress = {
        "totalGroups": 0,
        "completedGroups": 0,
        "failedGroups": 0,
        "pages": 0,
        "records": 0,
        "skippedGroups": 0,
        "backupGroups": 0,
        "accountUsage": [],
        "errors": [],
    }
    preferred_accounts = {}
    account_usage = {}
    recorded_switches = set()
    try:
        async with factory() as session:
            await owned_run(session, run_id, token)
            await authorize(session, actor, sync=True)
            groups = await materialize_groups(session, task_id)
            ids = [g.id for g in groups]
            progress["totalGroups"] = len(ids)
            await session.commit()
        for group_id in ids:
            async with factory() as session:
                await owned_run(session, run_id, token)
                group = await session.get(RedemptionClaimGroup, group_id)
                routing_key = (group.source_id, group.account_projection_id)
                today = datetime.now(UTC).astimezone(ZoneInfo(group.snapshot["timezone"])).date()
                if trigger == "automatic" and (
                    today < day(group.snapshot["validFrom"])
                    or (
                        today > day(group.snapshot["validTo"]) + timedelta(days=3)
                        and group.last_succeeded_at
                        and utc(group.last_succeeded_at)
                        .astimezone(ZoneInfo(group.snapshot["timezone"]))
                        .date()
                        >= day(group.snapshot["validTo"]) + timedelta(days=3)
                        and not group.last_error
                    )
                ):
                    progress["skippedGroups"] += 1
                    continue
            error = None
            read_result = None
            failed_account_ids = []
            for attempt in range(3):
                try:
                    result = await read_group(
                        factory,
                        run_id,
                        token,
                        group_id,
                        actor,
                        transport=transport,
                        settings=settings,
                        preferred_account_id=preferred_accounts.get(routing_key),
                    )
                    read_result = result
                    preferred_accounts[routing_key] = result.account_id
                    progress["completedGroups"] += 1
                    progress["pages"] += result.pages
                    progress["records"] += len(result.records)
                    backup = result.account_id != result.primary_account_id
                    progress["backupGroups"] += int(backup)
                    usage = account_usage.setdefault(
                        result.account_id,
                        {
                            "sourceId": result.source_id,
                            "accountId": result.account_id,
                            "accountName": result.account_name,
                            "backup": backup,
                            "groups": 0,
                        },
                    )
                    usage["groups"] += 1
                    progress["accountUsage"] = list(account_usage.values())
                    error = None
                    break
                except (ClaimError, ClaimReadError, ErpRedemptionRemoteHttpError) as exc:
                    error = str(exc)
                    failed_account_ids = (
                        list(exc.account_ids) if isinstance(exc, ClaimReadAccountsFailed) else []
                    )
                    # Fail closed for authorization/configuration/pagination errors.
                    transient = (
                        isinstance(exc, (ErpRedemptionRemoteHttpError, ClaimReadAccountsFailed))
                        and exc.retryable
                    )
                    if not transient or attempt == 2:
                        break
                    await asyncio.sleep(attempt + 1)
            async with factory() as session:
                run = await owned_run(session, run_id, token)
                if read_result and read_result.account_id != read_result.primary_account_id:
                    switch = (
                        read_result.source_id,
                        read_result.primary_account_id,
                        read_result.account_id,
                    )
                    if switch not in recorded_switches:
                        await write_audit(
                            session,
                            action="redemption_claims.read_account_fallback",
                            actor_user_id=actor,
                            target_type="redemption_task",
                            target_id=str(task_id),
                            metadata={
                                "runId": run_id,
                                "sourceId": read_result.source_id,
                                "fromAccountId": read_result.primary_account_id,
                                "toAccountId": read_result.account_id,
                                "attemptedAccountIds": list(read_result.attempted_account_ids),
                            },
                        )
                        recorded_switches.add(switch)
                if error:
                    group = await session.get(RedemptionClaimGroup, group_id)
                    group.last_error = error[:500]
                    progress["failedGroups"] += 1
                    progress["errors"].append({"groupId": group_id, "message": error[:500]})
                    if failed_account_ids:
                        progress["errors"][-1]["accountIds"] = failed_account_ids
                run.progress = dict(progress)
                await session.commit()
    except Exception as exc:
        # Never persist arbitrary adapter/SQL exception strings or credentials.
        message = (
            str(exc) if isinstance(exc, (ClaimError, ClaimReadError)) else "同步执行异常，请重试。"
        )
        progress["errors"].append({"message": message[:500]})
        progress["failedGroups"] += 1
    async with factory() as session:
        try:
            run = await owned_run(session, run_id, token)
        except ClaimError:
            return True
        setting = await session.get(RedemptionClaimSchedule, task_id, with_for_update=True)
        run.finished_at = datetime.now(UTC)
        run.status = (
            ("partial" if progress["completedGroups"] else "failed")
            if (progress["failedGroups"])
            else "succeeded"
        )
        run.progress = progress
        run.lease_expires_at = None
        if setting and setting.active_run_id == run.id:
            setting.active_run_id = None
            setting.last_finished_at = run.finished_at
            if run.status == "succeeded":
                setting.last_succeeded_at = run.finished_at
            setting.next_run_at = (
                run.finished_at + timedelta(minutes=setting.interval_minutes)
                if (setting.enabled)
                else None
            )
        await session.commit()
    return True
