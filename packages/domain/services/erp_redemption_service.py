"""Local redemption campaign and code-record service without remote operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import (
    ErpRedemptionCampaign,
    ErpRedemptionCampaignTier,
    ErpRedemptionCodeBatch,
    ErpRedemptionCodeIssue,
    ErpRedemptionTask,
    RemoteAccount,
    SourceConfig,
)
from packages.domain.schemas.erp_redemption import (
    ErpRedemptionBatchCreateRequest,
    ErpRedemptionBatchDetailResponse,
    ErpRedemptionBatchResponse,
    ErpRedemptionCampaignCreateRequest,
    ErpRedemptionCampaignResponse,
    ErpRedemptionCodeImportRequest,
    ErpRedemptionIssueResponse,
    ErpRedemptionTaskCreateRequest,
    ErpRedemptionTaskResponse,
    ErpRedemptionTaskSubtask,
    ErpRedemptionTierResponse,
)
from packages.domain.services.auth_service import write_audit
from packages.domain.services.erp_compatibility_id_service import (
    register_erp_compatibility_id,
)


class ErpRedemptionError(ValueError):
    pass


class ErpRedemptionNotFoundError(ErpRedemptionError):
    pass


class ErpRedemptionConflictError(ErpRedemptionError):
    pass


async def _tiers(
    session: AsyncSession,
    *,
    campaign_id: str,
) -> list[ErpRedemptionCampaignTier]:
    return list(
        (
            await session.scalars(
                select(ErpRedemptionCampaignTier)
                .where(ErpRedemptionCampaignTier.campaign_id == campaign_id)
                .order_by(
                    ErpRedemptionCampaignTier.sort_order.asc(),
                    ErpRedemptionCampaignTier.min_deposit_amount.asc(),
                )
            )
        ).all()
    )


async def _campaign(session: AsyncSession, *, campaign_id: str) -> ErpRedemptionCampaign:
    campaign = await session.get(ErpRedemptionCampaign, campaign_id)
    if campaign is None:
        raise ErpRedemptionNotFoundError("兑换码活动不存在。")
    return campaign


async def _batch(session: AsyncSession, *, batch_id: str) -> ErpRedemptionCodeBatch:
    batch = await session.get(ErpRedemptionCodeBatch, batch_id)
    if batch is None:
        raise ErpRedemptionNotFoundError("兑换码批次不存在。")
    return batch


async def _issues(
    session: AsyncSession,
    *,
    batch_id: str,
) -> list[ErpRedemptionCodeIssue]:
    return list(
        (
            await session.scalars(
                select(ErpRedemptionCodeIssue)
                .where(ErpRedemptionCodeIssue.batch_id == batch_id)
                .order_by(
                    ErpRedemptionCodeIssue.claim_date.asc(),
                    ErpRedemptionCodeIssue.min_deposit_amount.asc(),
                )
            )
        ).all()
    )


def _tier_response(tier: ErpRedemptionCampaignTier) -> ErpRedemptionTierResponse:
    return ErpRedemptionTierResponse.model_validate(tier)


def _issue_response(issue: ErpRedemptionCodeIssue) -> ErpRedemptionIssueResponse:
    return ErpRedemptionIssueResponse(
        id=issue.id,
        campaign_id=issue.campaign_id,
        campaign_tier_id=issue.campaign_tier_id,
        batch_id=issue.batch_id,
        claim_date=issue.claim_date,
        deposit_window_start=issue.deposit_window_start,
        deposit_window_end=issue.deposit_window_end,
        tier_name=issue.tier_name,
        min_deposit_amount=issue.min_deposit_amount,
        bonus_amount=issue.bonus_amount,
        bonus_max_amount=issue.bonus_max_amount,
        redemption_code=issue.redemption_code,
        local_reference=issue.local_reference,
        workflow_status=issue.workflow_status,
        state=issue.state,
        imported_at=issue.imported_at,
        remote_workflow_status=issue.remote_workflow_status,
        remote_configuration_id=issue.remote_configuration_id,
        remote_group_key=issue.remote_group_key,
        remote_label_ids=issue.remote_label_ids_json,
        remote_description=issue.remote_description,
        remote_error_code=issue.remote_error_code,
        remote_error_message=issue.remote_error_message,
        remote_created_at=issue.remote_created_at,
        remote_downloaded_at=issue.remote_downloaded_at,
        row_version=issue.row_version,
    )


async def _campaign_response(
    session: AsyncSession,
    campaign: ErpRedemptionCampaign,
) -> ErpRedemptionCampaignResponse:
    planned = await session.scalar(
        select(func.count(ErpRedemptionCodeIssue.id)).where(
            ErpRedemptionCodeIssue.campaign_id == campaign.id
        )
    )
    imported = await session.scalar(
        select(func.count(ErpRedemptionCodeIssue.id)).where(
            ErpRedemptionCodeIssue.campaign_id == campaign.id,
            ErpRedemptionCodeIssue.redemption_code.is_not(None),
        )
    )
    return ErpRedemptionCampaignResponse(
        id=campaign.id,
        code=campaign.code,
        name=campaign.name,
        status=campaign.status,
        lookback_days=campaign.lookback_days,
        description=campaign.description,
        tiers=[_tier_response(tier) for tier in await _tiers(session, campaign_id=campaign.id)],
        planned_code_count=planned or 0,
        imported_code_count=imported or 0,
        row_version=campaign.row_version,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


def _batch_response(
    batch: ErpRedemptionCodeBatch,
    issues: list[ErpRedemptionCodeIssue],
) -> ErpRedemptionBatchResponse:
    return ErpRedemptionBatchResponse(
        id=batch.id,
        campaign_id=batch.campaign_id,
        task_id=batch.task_id,
        source_id=batch.source_id,
        remote_account_id=batch.remote_account_id,
        execution_order=batch.execution_order,
        claim_date_from=batch.claim_date_from,
        claim_date_to=batch.claim_date_to,
        lookback_days=batch.lookback_days,
        expected_code_count=batch.expected_code_count,
        imported_code_count=sum(issue.redemption_code is not None for issue in issues),
        status=batch.status,
        published_at=batch.published_at,
        row_version=batch.row_version,
        created_at=batch.created_at,
    )


async def _batch_detail(
    session: AsyncSession,
    batch: ErpRedemptionCodeBatch,
) -> ErpRedemptionBatchDetailResponse:
    issues = await _issues(session, batch_id=batch.id)
    return ErpRedemptionBatchDetailResponse(
        batch=_batch_response(batch, issues),
        issues=[_issue_response(issue) for issue in issues],
    )


async def list_erp_redemption_campaigns(
    session: AsyncSession,
) -> list[ErpRedemptionCampaignResponse]:
    campaigns = list(
        (
            await session.scalars(
                select(ErpRedemptionCampaign).order_by(ErpRedemptionCampaign.created_at.desc())
            )
        ).all()
    )
    return [await _campaign_response(session, campaign) for campaign in campaigns]


async def create_erp_redemption_campaign(
    session: AsyncSession,
    *,
    request: ErpRedemptionCampaignCreateRequest,
    actor_user_id: int,
) -> ErpRedemptionCampaignResponse:
    if await session.scalar(
        select(ErpRedemptionCampaign.id).where(
            func.lower(ErpRedemptionCampaign.code) == request.code.lower()
        )
    ):
        raise ErpRedemptionConflictError("活动编码已存在。")
    deposits = {tier.min_deposit_amount.normalize() for tier in request.tiers}
    if len(deposits) != len(request.tiers):
        raise ErpRedemptionError("充值门槛不能重复。")
    campaign = ErpRedemptionCampaign(
        code=request.code,
        name=request.name,
        status="ACTIVE",
        lookback_days=request.lookback_days,
        description=request.description.strip() if request.description else None,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(campaign)
    await session.flush()
    await register_erp_compatibility_id(
        session,
        entity_type="redemption_campaign",
        canonical_id=campaign.id,
    )
    created_tiers: list[ErpRedemptionCampaignTier] = []
    for index, tier in enumerate(request.tiers, start=1):
        created_tier = ErpRedemptionCampaignTier(
            campaign_id=campaign.id,
            display_name=tier.display_name.strip() if tier.display_name else None,
            min_deposit_amount=tier.min_deposit_amount,
            bonus_amount=tier.bonus_amount,
            bonus_max_amount=tier.bonus_max_amount or tier.bonus_amount,
            sort_order=tier.sort_order if tier.sort_order is not None else index,
        )
        session.add(created_tier)
        created_tiers.append(created_tier)
    await session.flush()
    for tier in created_tiers:
        await register_erp_compatibility_id(
            session,
            entity_type="redemption_campaign_tier",
            canonical_id=tier.id,
        )
    result = await _campaign_response(session, campaign)
    await write_audit(
        session,
        action="erp_redemption_campaign.create",
        actor_user_id=actor_user_id,
        target_type="erp_redemption_campaign",
        target_id=campaign.id,
        metadata={"code": campaign.code, "tiers": len(request.tiers)},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ErpRedemptionConflictError("活动编码或充值门槛已存在。") from exc
    return result


async def create_erp_redemption_batch(
    session: AsyncSession,
    *,
    request: ErpRedemptionBatchCreateRequest,
    actor_user_id: int,
) -> ErpRedemptionBatchDetailResponse:
    campaign = await _campaign(session, campaign_id=request.campaign_id)
    if campaign.status != "ACTIVE":
        raise ErpRedemptionConflictError("只有进行中的活动可以创建批次。")
    duplicate = await session.scalar(
        select(ErpRedemptionCodeIssue.id).where(
            ErpRedemptionCodeIssue.campaign_id == campaign.id,
            ErpRedemptionCodeIssue.claim_date >= request.claim_date_from,
            ErpRedemptionCodeIssue.claim_date <= request.claim_date_to,
        )
    )
    if duplicate:
        raise ErpRedemptionConflictError("所选领取日期已有兑换码任务，不能重复创建。")
    tiers = await _tiers(session, campaign_id=campaign.id)
    if not tiers:
        raise ErpRedemptionError("活动至少需要一个充值分档。")
    day_count = (request.claim_date_to - request.claim_date_from).days + 1
    batch = ErpRedemptionCodeBatch(
        campaign_id=campaign.id,
        claim_date_from=request.claim_date_from,
        claim_date_to=request.claim_date_to,
        lookback_days=campaign.lookback_days,
        expected_code_count=day_count * len(tiers),
        created_by=actor_user_id,
    )
    session.add(batch)
    await session.flush()
    await register_erp_compatibility_id(
        session,
        entity_type="redemption_batch",
        canonical_id=batch.id,
    )
    claims = [request.claim_date_from + timedelta(days=offset) for offset in range(day_count)]
    created_issues: list[ErpRedemptionCodeIssue] = []
    for claim_date in claims:
        for tier in tiers:
            issue = ErpRedemptionCodeIssue(
                campaign_id=campaign.id,
                campaign_tier_id=tier.id,
                batch_id=batch.id,
                claim_date=claim_date,
                deposit_window_start=claim_date - timedelta(days=campaign.lookback_days),
                deposit_window_end=claim_date - timedelta(days=1),
                tier_name=tier.display_name,
                min_deposit_amount=tier.min_deposit_amount,
                bonus_amount=tier.bonus_amount,
                bonus_max_amount=tier.bonus_max_amount,
                created_by=actor_user_id,
            )
            session.add(issue)
            created_issues.append(issue)
    await session.flush()
    for issue in created_issues:
        await register_erp_compatibility_id(
            session,
            entity_type="redemption_issue",
            canonical_id=issue.id,
        )
    result = await _batch_detail(session, batch)
    await write_audit(
        session,
        action="erp_redemption_batch.create",
        actor_user_id=actor_user_id,
        target_type="erp_redemption_batch",
        target_id=batch.id,
        metadata={"campaign_id": campaign.id, "expected_code_count": batch.expected_code_count},
    )
    await session.commit()
    return result


async def _task_response(
    session: AsyncSession,
    task: ErpRedemptionTask,
) -> ErpRedemptionTaskResponse:
    rows = (
        await session.execute(
            select(ErpRedemptionCodeBatch, RemoteAccount, SourceConfig)
            .join(RemoteAccount, RemoteAccount.id == ErpRedemptionCodeBatch.remote_account_id)
            .join(SourceConfig, SourceConfig.source_id == ErpRedemptionCodeBatch.source_id)
            .where(ErpRedemptionCodeBatch.task_id == task.id)
            .order_by(ErpRedemptionCodeBatch.execution_order.asc())
        )
    ).all()
    subtasks = [
        ErpRedemptionTaskSubtask(
            batch_id=batch.id,
            execution_order=batch.execution_order,
            source_id=source.source_id,
            source_display_name=source.display_name,
            remote_account_id=account.id,
            remote_account_name=account.display_name,
            expected_code_count=batch.expected_code_count,
            imported_code_count=sum(
                issue.redemption_code is not None
                for issue in await _issues(session, batch_id=batch.id)
            ),
            status=batch.status,
        )
        for batch, account, source in rows
    ]
    expected = sum(item.expected_code_count for item in subtasks)
    imported = sum(item.imported_code_count for item in subtasks)
    status = "PUBLISHED_LOCAL" if subtasks and all(
        item.status == "PUBLISHED_LOCAL" for item in subtasks
    ) else "READY_LOCAL" if subtasks and all(
        item.status in {"READY_LOCAL", "PUBLISHED_LOCAL"} for item in subtasks
    ) else "PLANNED"
    return ErpRedemptionTaskResponse(
        id=task.id,
        campaign_id=task.campaign_id,
        task_name=task.task_name,
        claim_date_from=task.claim_date_from,
        claim_date_to=task.claim_date_to,
        lookback_days=task.lookback_days,
        export_group_key=task.export_group_key,
        status=status,
        expected_code_count=expected,
        imported_code_count=imported,
        row_version=task.row_version,
        created_at=task.created_at,
        subtasks=subtasks,
    )


async def create_erp_redemption_task(
    session: AsyncSession,
    *,
    request: ErpRedemptionTaskCreateRequest,
    actor_user_id: int,
) -> ErpRedemptionTaskResponse:
    campaign = await _campaign(session, campaign_id=request.campaign_id)
    if campaign.status != "ACTIVE":
        raise ErpRedemptionConflictError("只有进行中的活动可以创建任务组。")
    accounts = list(
        await session.scalars(
            select(RemoteAccount)
            .where(
                RemoteAccount.id.in_(request.remote_account_ids),
                RemoteAccount.enabled.is_(True),
            )
            .order_by(RemoteAccount.created_at.asc())
        )
    )
    if len(accounts) != len(request.remote_account_ids):
        raise ErpRedemptionError("包含不存在或已停用的远端账号。")
    tiers = await _tiers(session, campaign_id=campaign.id)
    if not tiers:
        raise ErpRedemptionError("活动至少需要一个充值分档。")
    day_count = (request.claim_date_to - request.claim_date_from).days + 1
    task = ErpRedemptionTask(
        campaign_id=campaign.id,
        task_name=(
            request.task_name or f"{campaign.code} {request.claim_date_from:%Y%m%d}"
        ).strip(),
        claim_date_from=request.claim_date_from,
        claim_date_to=request.claim_date_to,
        lookback_days=campaign.lookback_days,
        export_group_key=str(uuid.uuid4()),
        created_by=actor_user_id,
    )
    session.add(task)
    await session.flush()
    await register_erp_compatibility_id(
        session,
        entity_type="redemption_task",
        canonical_id=task.id,
    )
    created_issues: list[ErpRedemptionCodeIssue] = []
    for order, account_id in enumerate(request.remote_account_ids, start=1):
        account = next(account for account in accounts if account.id == account_id)
        batch = ErpRedemptionCodeBatch(
            campaign_id=campaign.id,
            task_id=task.id,
            remote_account_id=account.id,
            source_id=account.source_id,
            execution_order=order,
            claim_date_from=request.claim_date_from,
            claim_date_to=request.claim_date_to,
            lookback_days=campaign.lookback_days,
            expected_code_count=day_count * len(tiers),
            created_by=actor_user_id,
        )
        session.add(batch)
        await session.flush()
        await register_erp_compatibility_id(
            session,
            entity_type="redemption_batch",
            canonical_id=batch.id,
        )
        for offset in range(day_count):
            claim_date = request.claim_date_from + timedelta(days=offset)
            for tier in tiers:
                issue = ErpRedemptionCodeIssue(
                    campaign_id=campaign.id,
                    campaign_tier_id=tier.id,
                    batch_id=batch.id,
                    claim_date=claim_date,
                    deposit_window_start=claim_date - timedelta(days=campaign.lookback_days),
                    deposit_window_end=claim_date - timedelta(days=1),
                    tier_name=tier.display_name,
                    min_deposit_amount=tier.min_deposit_amount,
                    bonus_amount=tier.bonus_amount,
                    bonus_max_amount=tier.bonus_max_amount,
                    created_by=actor_user_id,
                )
                session.add(issue)
                created_issues.append(issue)
    await session.flush()
    for issue in created_issues:
        await register_erp_compatibility_id(
            session,
            entity_type="redemption_issue",
            canonical_id=issue.id,
        )
    result = await _task_response(session, task)
    await write_audit(
        session,
        action="erp_redemption_task.create",
        actor_user_id=actor_user_id,
        target_type="erp_redemption_task",
        target_id=task.id,
        metadata={
            "campaign_id": campaign.id,
            "subtask_count": len(accounts),
            "export_group_key": task.export_group_key,
        },
    )
    await session.commit()
    return result


async def get_erp_redemption_task(
    session: AsyncSession,
    *,
    task_id: str,
) -> ErpRedemptionTaskResponse:
    task = await session.get(ErpRedemptionTask, task_id)
    if task is None:
        raise ErpRedemptionNotFoundError("兑换码任务组不存在。")
    return await _task_response(session, task)


async def list_erp_redemption_tasks(
    session: AsyncSession,
    *,
    campaign_id: str | None = None,
) -> list[ErpRedemptionTaskResponse]:
    statement = select(ErpRedemptionTask).order_by(ErpRedemptionTask.created_at.desc())
    if campaign_id:
        await _campaign(session, campaign_id=campaign_id)
        statement = statement.where(ErpRedemptionTask.campaign_id == campaign_id)
    tasks = list((await session.scalars(statement)).all())
    return [await _task_response(session, task) for task in tasks]


async def get_erp_redemption_batch(
    session: AsyncSession,
    *,
    batch_id: str,
) -> ErpRedemptionBatchDetailResponse:
    return await _batch_detail(session, await _batch(session, batch_id=batch_id))


async def list_erp_redemption_batches(
    session: AsyncSession,
    *,
    campaign_id: str,
) -> list[ErpRedemptionBatchResponse]:
    await _campaign(session, campaign_id=campaign_id)
    batches = list(
        (
            await session.scalars(
                select(ErpRedemptionCodeBatch)
                .where(ErpRedemptionCodeBatch.campaign_id == campaign_id)
                .order_by(ErpRedemptionCodeBatch.created_at.desc())
            )
        ).all()
    )
    return [_batch_response(batch, await _issues(session, batch_id=batch.id)) for batch in batches]


async def import_erp_redemption_codes(
    session: AsyncSession,
    *,
    batch_id: str,
    request: ErpRedemptionCodeImportRequest,
    actor_user_id: int,
) -> ErpRedemptionBatchDetailResponse:
    batch = await _batch(session, batch_id=batch_id)
    if batch.status == "PUBLISHED_LOCAL":
        raise ErpRedemptionConflictError("本地发布后不能再修改兑换码。")
    issue_ids = [row.issue_id for row in request.rows]
    if len(issue_ids) != len(set(issue_ids)):
        raise ErpRedemptionError("导入内容包含重复任务。")
    codes = [row.redemption_code for row in request.rows]
    if len(codes) != len(set(codes)):
        raise ErpRedemptionError("导入内容包含重复兑换码。")
    issues = list(
        (
            await session.scalars(
                select(ErpRedemptionCodeIssue).where(
                    ErpRedemptionCodeIssue.batch_id == batch.id,
                    ErpRedemptionCodeIssue.id.in_(issue_ids),
                )
            )
        ).all()
    )
    if len(issues) != len(issue_ids):
        raise ErpRedemptionError("存在不属于当前批次的兑换码任务。")
    other_issues = list(
        (
            await session.scalars(
                select(ErpRedemptionCodeIssue).where(
                    ErpRedemptionCodeIssue.redemption_code.in_(codes),
                    ErpRedemptionCodeIssue.id.not_in(issue_ids),
                )
            )
        ).all()
    )
    if other_issues:
        raise ErpRedemptionConflictError("兑换码已登记到其他本地任务。")
    by_id = {issue.id: issue for issue in issues}
    for row in request.rows:
        issue = by_id[row.issue_id]
        if row.row_version is not None and row.row_version != issue.row_version:
            raise ErpRedemptionConflictError("兑换码任务已被修改，请刷新后重试。")
        if issue.redemption_code and issue.redemption_code != row.redemption_code:
            raise ErpRedemptionConflictError("已登记的兑换码不能覆盖。")
        issue.redemption_code = row.redemption_code
        issue.local_reference = row.local_reference.strip() if row.local_reference else None
        issue.workflow_status = "CODE_IMPORTED"
        issue.state = "GENERATED"
        issue.imported_at = datetime.now(UTC)
        issue.row_version += 1
    all_issues = await _issues(session, batch_id=batch.id)
    batch.status = (
        "READY_LOCAL" if all(issue.redemption_code for issue in all_issues) else "PLANNED"
    )
    batch.row_version += 1
    await session.flush()
    result = await _batch_detail(session, batch)
    await write_audit(
        session,
        action="erp_redemption_codes.import",
        actor_user_id=actor_user_id,
        target_type="erp_redemption_batch",
        target_id=batch.id,
        metadata={"submitted_count": len(request.rows), "batch_status": batch.status},
    )
    await session.commit()
    return result


async def publish_erp_redemption_batch_locally(
    session: AsyncSession,
    *,
    batch_id: str,
    row_version: int | None,
    actor_user_id: int,
) -> ErpRedemptionBatchDetailResponse:
    batch = await _batch(session, batch_id=batch_id)
    if row_version is None or row_version != batch.row_version:
        raise ErpRedemptionConflictError("批次已被其他人修改，请刷新后重试。")
    issues = await _issues(session, batch_id=batch.id)
    if batch.status != "READY_LOCAL" or any(issue.redemption_code is None for issue in issues):
        raise ErpRedemptionConflictError("请先登记全部本地兑换码，再标记本地发布。")
    batch.status = "PUBLISHED_LOCAL"
    batch.published_at = datetime.now(UTC)
    batch.published_by = actor_user_id
    batch.row_version += 1
    for issue in issues:
        issue.workflow_status = "PUBLISHED_LOCAL"
        issue.row_version += 1
    await session.flush()
    result = await _batch_detail(session, batch)
    await write_audit(
        session,
        action="erp_redemption_batch.publish_local",
        actor_user_id=actor_user_id,
        target_type="erp_redemption_batch",
        target_id=batch.id,
        metadata={"expected_code_count": batch.expected_code_count},
    )
    await session.commit()
    return result
