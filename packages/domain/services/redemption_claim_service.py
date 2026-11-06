"""Local-only query and queue boundary for compatibility ERP claim statistics."""

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import (
    AppUser,
    ErpCompatibilityIdMap,
    RedemptionClaimDaily,
    RedemptionClaimGroup,
    RedemptionClaimRecord,
    RedemptionClaimRun,
    RedemptionClaimSchedule,
    SourceConfig,
)
from packages.domain.models.entities import new_uuid
from packages.domain.services.auth_service import write_audit
from packages.domain.services.erp_access_service import (
    ERP_PERMISSION_REDEMPTION_STATS_SYNC,
    ERP_PERMISSION_REDEMPTION_VIEW,
    user_has_erp_permission,
)

INTERVALS = (30, 60, 120, 180, 360, 720, 1440)
ACTIVE = ("queued", "running")


class ClaimError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def day(value: object) -> date:
    return date.fromisoformat(str(value)[:10])


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


async def authorize(session: AsyncSession, user_id: int, *, sync: bool = False) -> None:
    user = await session.get(AppUser, user_id, populate_existing=True)
    required = [ERP_PERMISSION_REDEMPTION_VIEW]
    if sync:
        required.append(ERP_PERMISSION_REDEMPTION_STATS_SYNC)
    if user is None or not user.is_active:
        raise ClaimError("操作账号不存在或已停用。", 403)
    for permission in required:
        if not await user_has_erp_permission(session, user_id=user_id, permission=permission):
            raise ClaimError("没有兑换码领取统计权限。", 403)


async def task_projection(session: AsyncSession, task_id: int) -> tuple[dict, list[dict]]:
    task = (
        (
            await session.execute(
                text(
                    "SELECT id, task_date, daily_sequence "
                    "FROM erp_compat_redemption_code_tasks WHERE id=:id"
                ),
                {"id": task_id},
            )
        )
        .mappings()
        .first()
    )
    if task is None:
        raise ClaimError("兑换码任务不存在。", 404)
    rows = (
        (
            await session.execute(
                text("""
        SELECT i.id AS issue_id, i.batch_id, i.remote_market_id, i.remote_configuration_id,
               i.remote_group_key, i.tier_name, i.claim_date, i.min_deposit_amount,
               i.bonus_amount, i.bonus_max_amount, i.remote_label_ids_json, i.redemption_code,
               b.remote_connection_id, b.redemption_type, b.lookback_days,
               b.valid_from_day_offset, b.valid_to_day_offset, c.name AS campaign_name
        FROM erp_compat_redemption_code_issues i
        JOIN erp_compat_redemption_code_batches b ON b.id=i.batch_id
        JOIN erp_compat_redemption_campaigns c ON c.id=b.campaign_id
        WHERE b.task_id=:id ORDER BY b.id, i.claim_date, i.campaign_tier_id
    """),
                {"id": task_id},
            )
        )
        .mappings()
        .all()
    )
    task_data = dict(task)
    task_data["number"] = (
        day(task["task_date"]).strftime("%Y%m%d") + f"{task['daily_sequence']:04d}"
    )
    return task_data, [dict(row) for row in rows]


async def projected_groups(
    session: AsyncSession, task_id: int
) -> tuple[dict, list[RedemptionClaimGroup]]:
    task, rows = await task_projection(session, task_id)
    persisted = list(
        await session.scalars(
            select(RedemptionClaimGroup)
            .where(RedemptionClaimGroup.task_id == task_id)
            .execution_options(populate_existing=True)
        )
    )
    for group in persisted:
        if hasattr(group, "inventory_codes"):
            del group.inventory_codes
    sources = {s.source_id: s for s in await session.scalars(select(SourceConfig))}
    mappings = {
        m.legacy_id: m.canonical_id
        for m in await session.scalars(
            select(ErpCompatibilityIdMap).where(ErpCompatibilityIdMap.entity_type == "source")
        )
    }
    codes = (
        await session.execute(
            text("""
        SELECT codes.issue_id, codes.code FROM erp_compat_redemption_issue_codes codes
        JOIN erp_compat_redemption_code_issues i ON i.id=codes.issue_id
        JOIN erp_compat_redemption_code_batches b ON b.id=i.batch_id
        WHERE b.task_id=:id ORDER BY codes.issue_id, codes.code_index
    """),
            {"id": task_id},
        )
    ).all()
    by_issue: dict[int, list[str]] = defaultdict(list)
    for issue, code in codes:
        by_issue[issue].append(code)
    # Retain historical real groups, but hide an unresolved placeholder after
    # its issue has acquired a real configuration/group identity.
    identities = {
        (r["issue_id"], r["remote_configuration_id"], r["remote_group_key"]) for r in rows
    }
    result = [
        g
        for g in persisted
        if g.group_key or (g.issue_id, g.configuration_id, g.group_key) in identities
    ]
    for row in rows:
        source_id = mappings.get(row["remote_market_id"], f"unmapped:{row['remote_market_id']}")
        source = sources.get(source_id)
        labels = sorted(json.loads(row["remote_label_ids_json"] or "[]"))
        semantic = {
            "tierName": row["tier_name"] or f"充值 ≥ {row['min_deposit_amount']}",
            "minDeposit": str(Decimal(str(row["min_deposit_amount"])).normalize()),
            "rewardMin": str(Decimal(str(row["bonus_amount"])).normalize()),
            "rewardMax": str(Decimal(str(row["bonus_max_amount"])).normalize()),
            "labels": labels,
            "redemptionType": row["redemption_type"],
            "lookbackDays": row["lookback_days"],
        }
        existing = next(
            (
                g
                for g in persisted
                if g.issue_id == row["issue_id"]
                and g.configuration_id == row["remote_configuration_id"]
                and g.group_key == row["remote_group_key"]
            ),
            None,
        )
        if existing:
            existing.inventory_codes = by_issue[row["issue_id"]] or existing.snapshot["codes"]
            continue
        claim_day = day(row["claim_date"])
        snapshot = {
            **semantic,
            "sourceName": source.display_name if source else "盘口未关联",
            "timezone": source.business_timezone if source else "Asia/Kolkata",
            "currency": source.currency if source else "INR",
            "claimDate": claim_day.isoformat(),
            "description": row["tier_name"] or "兑换码组",
            "validFrom": (claim_day + timedelta(days=row["valid_from_day_offset"])).isoformat(),
            "validTo": (claim_day + timedelta(days=row["valid_to_day_offset"])).isoformat(),
            "codes": by_issue[row["issue_id"]]
            or ([row["redemption_code"]] if row["redemption_code"] else []),
        }
        result.append(
            RedemptionClaimGroup(
                id=f"pending:{row['issue_id']}:{fingerprint(row['remote_configuration_id'])[:8]}",
                task_id=task_id,
                issue_id=row["issue_id"],
                batch_id=row["batch_id"],
                source_id=source_id,
                account_projection_id=row["remote_connection_id"],
                configuration_id=row["remote_configuration_id"],
                group_key=row["remote_group_key"],
                column_key=fingerprint([source_id, semantic]),
                snapshot=snapshot,
                version=0,
            )
        )
    return task, result


async def materialize_groups(session: AsyncSession, task_id: int) -> list[RedemptionClaimGroup]:
    _, groups = await projected_groups(session, task_id)
    for group in groups:
        if not group.id.startswith("pending:") and hasattr(group, "inventory_codes"):
            group.snapshot = {**group.snapshot, "codes": group.inventory_codes}
        if group.id.startswith("pending:"):
            if group.group_key:
                duplicate = await session.scalar(
                    select(RedemptionClaimGroup).where(
                        RedemptionClaimGroup.source_id == group.source_id,
                        RedemptionClaimGroup.group_key == group.group_key,
                    )
                )
                if duplicate:
                    raise ClaimError("远端兑换码组已绑定其他配置，请先核对任务归属。")
            group.id = new_uuid()
            session.add(group)
    await session.flush()
    return groups


def known_codes(group: RedemptionClaimGroup) -> list[str]:
    return getattr(group, "inventory_codes", group.snapshot["codes"])


def query_version(groups: list[RedemptionClaimGroup]) -> str:
    return fingerprint(sorted((g.id, g.version or 0, g.last_error, known_codes(g)) for g in groups))


def check_version(groups: list[RedemptionClaimGroup], version: str | None) -> str:
    current = query_version(groups)
    if version and version != current:
        raise ClaimError("统计数据已更新，请刷新后重新查询。")
    return current


def is_future(group: RedemptionClaimGroup, value: date, now: datetime) -> bool:
    return value > now.astimezone(ZoneInfo(group.snapshot["timezone"])).date()


def covers_day(group: RedemptionClaimGroup, value: date) -> bool:
    return bool(
        group.last_succeeded_at
        and value
        <= utc(group.last_succeeded_at).astimezone(ZoneInfo(group.snapshot["timezone"])).date()
    )


def cell(
    groups: list[RedemptionClaimGroup],
    value: date,
    counts: dict,
    now: datetime,
    *,
    include_configuration_ids: bool = False,
) -> dict:
    if all(is_future(g, value, now) for g in groups):
        return {"count": None, "state": "future", "complete": False}
    groups = [
        g
        for g in groups
        if covers_day(g, value)
        or counts.get((g.id, value), 0)
        or day(g.snapshot["validFrom"]) <= value <= day(g.snapshot["validTo"])
    ]
    if not groups:
        return {"count": None, "state": "notApplicable", "complete": True}
    known = [g for g in groups if covers_day(g, value)]
    success = [g for g in known if not g.last_error]
    complete = len(success) == len(groups)
    timestamps = [utc(g.last_succeeded_at) for g in known]
    return {
        "count": sum(counts.get((g.id, value), 0) for g in known) if known else None,
        "complete": complete,
        "state": "complete" if complete else "partial" if known else "pending",
        "coveredGroups": len(success),
        "expectedGroups": len(groups),
        "asOf": min(timestamps) if timestamps else None,
        "error": next((g.last_error for g in groups if g.last_error), None),
        **(
            {"configurationIds": sorted({g.configuration_id for g in groups if g.configuration_id})}
            if include_configuration_ids
            else {}
        ),
    }


async def summary(
    session: AsyncSession,
    task_id: int,
    start: date | None,
    end: date | None,
    source_id: str | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    task, groups = await projected_groups(session, task_id)
    version = query_version(groups)
    if source_id:
        groups = [g for g in groups if g.source_id == source_id]
    if not groups:
        raise ClaimError("当前任务没有匹配的盘口或配置。", 404)
    end = end or max(now.astimezone(ZoneInfo(g.snapshot["timezone"])).date() for g in groups)
    start = start or min(
        end, max(min(day(g.snapshot["validFrom"]) for g in groups), end - timedelta(days=30))
    )
    if end < start:
        raise ClaimError("结束日期不能早于开始日期。", 422)
    if (end - start).days > 365:
        raise ClaimError("统计日期范围不能超过 366 天。", 422)
    data = (
        await session.execute(
            select(
                RedemptionClaimDaily.group_id,
                RedemptionClaimDaily.claim_date,
                func.sum(RedemptionClaimDaily.count),
            )
            .where(
                RedemptionClaimDaily.group_id.in_([g.id for g in groups]),
                RedemptionClaimDaily.claim_date.between(start, end),
            )
            .group_by(RedemptionClaimDaily.group_id, RedemptionClaimDaily.claim_date)
        )
    ).all()
    counts = {(g, d): n for g, d, n in data}
    columns: dict[str, list[RedemptionClaimGroup]] = {}
    for g in groups:
        columns.setdefault(g.column_key, []).append(g)
    column_data = [
        {
            "key": key,
            "sourceId": gs[0].source_id,
            **{k: v for k, v in gs[0].snapshot.items() if k != "codes"},
        }
        for key, gs in columns.items()
    ]
    rows = []
    for offset in range((end - start).days + 1):
        value = start + timedelta(days=offset)
        cells = {
            key: cell(gs, value, counts, now, include_configuration_ids=True)
            for key, gs in columns.items()
        }
        rows.append({"date": value, "cells": cells, "total": cell(groups, value, counts, now)})
    totals = {}
    for key in [*columns, "total"]:
        values = [row["total"] if key == "total" else row["cells"][key] for row in rows]
        known = [v["count"] for v in values if v["count"] is not None]
        totals[key] = {
            "count": sum(known) if known else None,
            "complete": all(v["complete"] for v in values),
            "state": "notApplicable"
            if all(v["state"] == "notApplicable" for v in values)
            else "future"
            if all(v["state"] == "future" for v in values)
            else "pending",
        }
    schedule = await get_schedule(session, task_id)
    return {
        "taskId": str(task_id),
        "taskNumber": task["number"],
        "queryVersion": version,
        "dateFrom": start,
        "dateTo": end,
        "columns": column_data,
        "rows": rows,
        "totals": totals,
        "schedule": schedule,
    }


async def code_details(
    session: AsyncSession,
    task_id: int,
    value: date,
    column_key: str,
    version: str | None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    _, groups = await projected_groups(session, task_id)
    current = check_version(groups, version)
    selected = [g for g in groups if g.column_key == column_key]
    if not selected:
        raise ClaimError("统计档位不存在。", 404)
    rows = []
    values = (
        await session.execute(
            select(
                RedemptionClaimDaily.group_id, RedemptionClaimDaily.code, RedemptionClaimDaily.count
            ).where(
                RedemptionClaimDaily.group_id.in_([g.id for g in selected]),
                RedemptionClaimDaily.claim_date == value,
            )
        )
    ).all()
    all_counts: dict[str, dict] = defaultdict(dict)
    for group_id, code, count in values:
        all_counts[group_id][code] = count
    for group in selected:
        by_code = all_counts[group.id]
        for code in sorted(set(known_codes(group)) | set(by_code)):
            rows.append(
                {
                    "groupId": group.id,
                    "configurationId": group.configuration_id,
                    "description": group.snapshot["description"],
                    "claimDate": group.snapshot["claimDate"],
                    "code": code,
                    "count": by_code.get(code, 0) if covers_day(group, value) else None,
                    "complete": bool(covers_day(group, value) and not group.last_error),
                    "matched": code in known_codes(group),
                }
            )
    return {
        "items": rows[(page - 1) * page_size : page * page_size],
        "total": len(rows),
        "queryVersion": current,
    }


async def record_details(
    session: AsyncSession,
    task_id: int,
    value: date,
    group_id: str,
    code: str,
    version: str | None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    _, groups = await projected_groups(session, task_id)
    current = check_version(groups, version)
    if group_id not in {g.id for g in groups}:
        raise ClaimError("兑换码组不属于当前任务。", 404)
    filters = [
        RedemptionClaimRecord.group_id == group_id,
        RedemptionClaimRecord.code == code,
        RedemptionClaimRecord.claim_date == value,
    ]
    total = await session.scalar(
        select(func.count()).select_from(RedemptionClaimRecord).where(*filters)
    )
    records = list(
        await session.scalars(
            select(RedemptionClaimRecord)
            .where(*filters)
            .order_by(RedemptionClaimRecord.received_at, RedemptionClaimRecord.remote_id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return {
        "items": [
            {
                "id": r.remote_id,
                "uid": r.uid,
                "code": r.code,
                "receiveTime": r.receive_time,
                "amount": str(r.amount),
            }
            for r in records
        ],
        "total": total,
        "queryVersion": current,
    }


async def get_schedule(session: AsyncSession, task_id: int) -> dict:
    setting = await session.get(RedemptionClaimSchedule, task_id)
    run = (
        await session.get(RedemptionClaimRun, setting.active_run_id)
        if setting and setting.active_run_id
        else None
    )
    last_run = await session.scalar(
        select(RedemptionClaimRun)
        .where(RedemptionClaimRun.task_id == task_id)
        .order_by(RedemptionClaimRun.created_at.desc(), RedemptionClaimRun.id.desc())
        .limit(1)
    )
    return {
        "enabled": setting.enabled if setting else False,
        "intervalMinutes": setting.interval_minutes if setting else 30,
        "rowVersion": setting.row_version if setting else 0,
        "nextRunAt": setting.next_run_at if setting else None,
        "lastSucceededAt": setting.last_succeeded_at if setting else None,
        "activeRun": run_response(run) if run else None,
        "lastRun": run_response(last_run) if last_run else None,
    }


def run_response(run: RedemptionClaimRun) -> dict:
    return {
        "id": run.id,
        "taskId": str(run.task_id),
        "status": run.status,
        "trigger": run.trigger,
        "startedAt": run.started_at,
        "finishedAt": run.finished_at,
        "progress": run.progress,
    }


async def locked_schedule(
    session: AsyncSession, task_id: int, actor: int
) -> RedemptionClaimSchedule:
    setting = await session.get(
        RedemptionClaimSchedule, task_id, with_for_update=True, populate_existing=True
    )
    if setting is None:
        try:
            async with session.begin_nested():
                setting = RedemptionClaimSchedule(task_id=task_id, actor_user_id=actor)
                session.add(setting)
                await session.flush()
        except IntegrityError:
            setting = await session.get(
                RedemptionClaimSchedule, task_id, with_for_update=True, populate_existing=True
            )
    if setting is None:
        raise ClaimError("同步设置正在变更，请重试。")
    return setting


async def queue_run(
    session: AsyncSession,
    setting: RedemptionClaimSchedule,
    actor: int,
    trigger: str,
) -> RedemptionClaimRun:
    if setting.active_run_id:
        active = await session.get(RedemptionClaimRun, setting.active_run_id)
        if active and active.status in ACTIVE:
            return active
    run = RedemptionClaimRun(task_id=setting.task_id, actor_user_id=actor, trigger=trigger)
    session.add(run)
    await session.flush()
    setting.active_run_id = run.id
    setting.next_run_at = None
    return run


async def request_sync(session: AsyncSession, task_id: int, actor: int) -> dict:
    await authorize(session, actor, sync=True)
    await task_projection(session, task_id)
    setting = await locked_schedule(session, task_id, actor)
    run = await queue_run(session, setting, actor, "manual")
    await write_audit(
        session,
        action="redemption_claims.sync_requested",
        actor_user_id=actor,
        target_type="redemption_task",
        target_id=str(task_id),
    )
    await session.commit()
    return run_response(run)


async def save_schedule(
    session: AsyncSession,
    task_id: int,
    actor: int,
    enabled: bool,
    interval: int,
    version: int,
) -> dict:
    if interval not in INTERVALS:
        raise ClaimError("不支持的领取统计同步间隔。", 422)
    await authorize(session, actor, sync=True)
    await task_projection(session, task_id)
    setting = await locked_schedule(session, task_id, actor)
    if setting.row_version != version:
        raise ClaimError("同步设置已被修改，请刷新后重试。")
    was_enabled = setting.enabled
    setting.enabled = enabled
    setting.interval_minutes = interval
    setting.actor_user_id = actor
    setting.row_version += 1
    if not enabled:
        setting.next_run_at = None
        run = (
            await session.get(RedemptionClaimRun, setting.active_run_id)
            if setting.active_run_id
            else None
        )
        if run and run.status == "queued" and run.trigger == "automatic":
            run.status = "cancelled"
            run.finished_at = datetime.now(UTC)
            setting.active_run_id = None
    elif not was_enabled:
        await queue_run(session, setting, actor, "automatic")
    elif not setting.active_run_id:
        setting.next_run_at = (utc(setting.last_finished_at) or datetime.now(UTC)) + timedelta(
            minutes=interval
        )
    await write_audit(
        session,
        action="redemption_claims.schedule_saved",
        actor_user_id=actor,
        target_type="redemption_task",
        target_id=str(task_id),
        metadata={"enabled": enabled, "interval_minutes": interval},
    )
    await session.commit()
    return await get_schedule(session, task_id)


async def publish_group(
    session: AsyncSession, group: RedemptionClaimGroup, records: list[dict]
) -> None:
    old_ids = set(
        await session.scalars(
            select(RedemptionClaimRecord.remote_id).where(
                RedemptionClaimRecord.group_id == group.id
            )
        )
    )
    if old_ids - {r["remote_id"] for r in records}:
        raise ClaimError("远端领取记录减少，需核对后再更新；已保留上次完整结果。")
    await session.execute(
        delete(RedemptionClaimRecord).where(RedemptionClaimRecord.group_id == group.id)
    )
    await session.execute(
        delete(RedemptionClaimDaily).where(RedemptionClaimDaily.group_id == group.id)
    )
    counts: dict[tuple[str, date], int] = defaultdict(int)
    for r in records:
        session.add(RedemptionClaimRecord(group_id=group.id, **r))
        counts[(r["code"], r["claim_date"])] += 1
    for (code, value), count in counts.items():
        session.add(
            RedemptionClaimDaily(group_id=group.id, code=code, claim_date=value, count=count)
        )
    group.version += 1
    group.last_succeeded_at = datetime.now(UTC)
    group.last_error = None
