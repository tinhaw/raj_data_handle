"""Append-only, safe operational logs for local data synchronization runs.

This module intentionally does not start remote requests.  Refresh/import
workflows call its small lifecycle helpers while they execute their own
read-only source operations.  That keeps the log page local-only and prevents
remote credentials, payloads, workbooks, or exception traces from becoming
operational-log data.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import AppUser, DataSyncRun, DataSyncRunEvent, SourceConfig
from packages.domain.schemas.sync_log import SyncLogQueryRequest

SYNC_RUN_BUSINESS_TYPES = frozenset(
    {"charge_orders", "withdraw_orders", "withdraw_scoring_import", "spin_orders"}
)
SYNC_RUN_OPERATION_KINDS = frozenset({"remote_sync", "excel_import"})
SYNC_RUN_TRIGGER_TYPES = frozenset({"automatic", "manual", "upload"})
SYNC_RUN_STATUSES = frozenset(
    {"queued", "running", "succeeded", "partial", "failed", "superseded", "cancelled"}
)
SYNC_RUN_TERMINAL_STATUSES = frozenset(
    {"succeeded", "partial", "failed", "superseded", "cancelled"}
)
SYNC_RUN_TREND_STATUSES = ("queued", "running", "succeeded", "partial", "failed")
_ERROR_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,79}$")


class DataSyncRunValidationError(ValueError):
    """A caller supplied an invalid non-sensitive run property."""


class DataSyncRunNotFoundError(DataSyncRunValidationError):
    """The requested local run record does not exist."""


class DataSyncRunSchemaPendingError(RuntimeError):
    """The application has been released before the log migration completed."""


@dataclass(frozen=True, slots=True)
class SyncRunMetrics:
    """Counters emitted by a completed remote sync or Excel import."""

    remote_total: int | None = None
    export_row_count: int | None = None
    cached_total: int | None = None
    fetched_pages: int | None = None
    imported_count: int | None = None
    created_count: int | None = None
    updated_count: int | None = None
    duplicate_count: int | None = None
    matched_count: int | None = None
    unmatched_count: int | None = None
    resolved_uid_count: int | None = None
    unresolved_uid_count: int | None = None


@dataclass(frozen=True, slots=True)
class DataSyncRunQueryResult:
    items: list[dict[str, Any]]
    total: int
    summary: dict[str, Any]
    trend: list[dict[str, Any]]
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class DataSyncRunDetailResult:
    run: dict[str, Any]
    events: list[dict[str, Any]]


def _now(value: datetime | None = None) -> datetime:
    candidate = value or datetime.now(UTC)
    return candidate if candidate.tzinfo else candidate.replace(tzinfo=UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _bounded_text(value: object | None, *, limit: int) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized[:limit] if normalized else None


def _safe_json_value(value: object, *, depth: int = 0) -> Any:
    """Limit extension metadata to a small JSON-safe operational projection."""

    if depth >= 3:
        return _bounded_text(value, limit=200)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, nested in list(value.items())[:40]:
            key_text = _bounded_text(key, limit=64)
            if key_text:
                normalized[key_text] = _safe_json_value(nested, depth=depth + 1)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_safe_json_value(item, depth=depth + 1) for item in value[:40]]
    return _bounded_text(value, limit=200)


def _safe_metadata(value: dict[str, object] | None) -> dict[str, Any]:
    if not value:
        return {}
    normalized = _safe_json_value(value)
    return normalized if isinstance(normalized, dict) else {}


def _validate_choice(value: str, *, choices: frozenset[str], label: str) -> str:
    normalized = value.strip()
    if normalized not in choices:
        raise DataSyncRunValidationError(f"不支持的{label}。")
    return normalized


def _validate_counter(value: int | None, *, label: str) -> int | None:
    if value is None:
        return None
    if value < 0:
        raise DataSyncRunValidationError(f"{label}不能小于 0。")
    return value


def _apply_metrics(run: DataSyncRun, metrics: SyncRunMetrics | None) -> None:
    if metrics is None:
        return
    for field_name, raw_value in (
        ("remote_total", metrics.remote_total),
        ("export_row_count", metrics.export_row_count),
        ("cached_total", metrics.cached_total),
        ("fetched_pages", metrics.fetched_pages),
        ("imported_count", metrics.imported_count),
        ("created_count", metrics.created_count),
        ("updated_count", metrics.updated_count),
        ("duplicate_count", metrics.duplicate_count),
        ("matched_count", metrics.matched_count),
        ("unmatched_count", metrics.unmatched_count),
        ("resolved_uid_count", metrics.resolved_uid_count),
        ("unresolved_uid_count", metrics.unresolved_uid_count),
    ):
        if raw_value is not None:
            setattr(run, field_name, _validate_counter(raw_value, label=field_name))


def _merge_metadata(run: DataSyncRun, metadata: dict[str, object] | None) -> None:
    if metadata is None:
        return
    merged = dict(run.metadata_json or {})
    merged.update(_safe_metadata(metadata))
    run.metadata_json = merged


async def add_sync_run_event(
    session: AsyncSession,
    *,
    run: DataSyncRun,
    event_type: str,
    status: str | None = None,
    message: str | None = None,
    metadata: dict[str, object] | None = None,
    occurred_at: datetime | None = None,
) -> DataSyncRunEvent:
    """Append one safe lifecycle event without committing the outer work."""

    normalized_type = _bounded_text(event_type, limit=48)
    if normalized_type is None:
        raise DataSyncRunValidationError("同步日志事件类型不能为空。")
    normalized_status = status.strip() if status else None
    if normalized_status is not None and normalized_status not in SYNC_RUN_STATUSES:
        raise DataSyncRunValidationError("同步日志事件状态无效。")
    event = DataSyncRunEvent(
        run_id=run.id,
        event_type=normalized_type,
        status=normalized_status,
        message=_bounded_text(message, limit=500),
        metadata_json=_safe_metadata(metadata),
        occurred_at=_now(occurred_at),
    )
    session.add(event)
    await session.flush()
    return event


async def create_sync_run(
    session: AsyncSession,
    *,
    source: SourceConfig,
    business_type: str,
    trigger_type: str,
    operation_kind: str = "remote_sync",
    requested_by_user_id: int | None = None,
    requested_by_display_name: str | None = None,
    requested_at: datetime | None = None,
    window_start_utc: datetime | None = None,
    window_end_utc: datetime | None = None,
    query_range: str | None = None,
    page_size: int | None = None,
    status: str = "queued",
    input_filename: str | None = None,
    input_size_bytes: int | None = None,
    metadata: dict[str, object] | None = None,
) -> DataSyncRun:
    """Create a queued/running run record and its first lifecycle event.

    The helper only flushes.  The caller owns the transaction boundary so a
    refresh-state update and its log record remain atomic.
    """

    normalized_business_type = _validate_choice(
        business_type,
        choices=SYNC_RUN_BUSINESS_TYPES,
        label="同步业务类型",
    )
    normalized_trigger_type = _validate_choice(
        trigger_type,
        choices=SYNC_RUN_TRIGGER_TYPES,
        label="同步触发方式",
    )
    normalized_operation_kind = _validate_choice(
        operation_kind,
        choices=SYNC_RUN_OPERATION_KINDS,
        label="同步操作类型",
    )
    normalized_status = _validate_choice(status, choices=SYNC_RUN_STATUSES, label="同步状态")
    if normalized_status not in {"queued", "running"}:
        raise DataSyncRunValidationError("新建同步日志只能处于排队中或同步中状态。")
    if page_size is not None:
        _validate_counter(page_size, label="分页大小")
    if input_size_bytes is not None:
        _validate_counter(input_size_bytes, label="导入文件大小")

    actor_name = _bounded_text(requested_by_display_name, limit=120)
    if actor_name is None and requested_by_user_id is not None:
        actor = await session.get(AppUser, requested_by_user_id)
        actor_name = actor.display_name if actor is not None else None
    created_at = _now(requested_at)
    run = DataSyncRun(
        source_id=source.source_id,
        source_display_name=source.display_name,
        business_timezone=source.business_timezone,
        source_config_version=source.config_version,
        business_type=normalized_business_type,
        operation_kind=normalized_operation_kind,
        trigger_type=normalized_trigger_type,
        status=normalized_status,
        requested_by_user_id=requested_by_user_id,
        requested_by_display_name=actor_name,
        requested_at=created_at,
        started_at=created_at if normalized_status == "running" else None,
        window_start_utc=_as_utc(window_start_utc),
        window_end_utc=_as_utc(window_end_utc),
        query_range=_bounded_text(query_range, limit=64),
        page_size=page_size,
        input_filename=_bounded_text(input_filename, limit=255),
        input_size_bytes=input_size_bytes,
        metadata_json=_safe_metadata(metadata),
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(run)
    await session.flush()
    await add_sync_run_event(
        session,
        run=run,
        event_type=normalized_status,
        status=normalized_status,
        occurred_at=created_at,
    )
    return run


async def get_sync_run_for_update(
    session: AsyncSession,
    *,
    run_id: str,
) -> DataSyncRun | None:
    return await session.scalar(
        select(DataSyncRun).where(DataSyncRun.id == run_id).with_for_update()
    )


async def mark_sync_run_running(
    session: AsyncSession,
    *,
    run: DataSyncRun,
    started_at: datetime | None = None,
    window_start_utc: datetime | None = None,
    window_end_utc: datetime | None = None,
    query_range: str | None = None,
    page_size: int | None = None,
    metadata: dict[str, object] | None = None,
) -> DataSyncRun:
    """Transition a queued run to running and preserve its exact run ID."""

    if run.status in SYNC_RUN_TERMINAL_STATUSES:
        raise DataSyncRunValidationError("已结束的同步日志不能重新开始。")
    effective_started_at = _now(started_at)
    changed = run.status != "running"
    run.status = "running"
    run.started_at = run.started_at or effective_started_at
    if window_start_utc is not None:
        run.window_start_utc = _as_utc(window_start_utc)
    if window_end_utc is not None:
        run.window_end_utc = _as_utc(window_end_utc)
    if query_range is not None:
        run.query_range = _bounded_text(query_range, limit=64)
    if page_size is not None:
        run.page_size = _validate_counter(page_size, label="分页大小")
    _merge_metadata(run, metadata)
    run.updated_at = effective_started_at
    if changed:
        await add_sync_run_event(
            session,
            run=run,
            event_type="running",
            status="running",
            occurred_at=effective_started_at,
        )
    await session.flush()
    return run


async def complete_sync_run(
    session: AsyncSession,
    *,
    run: DataSyncRun,
    complete: bool | None = True,
    metrics: SyncRunMetrics | None = None,
    status: str | None = None,
    finished_at: datetime | None = None,
    metadata: dict[str, object] | None = None,
) -> DataSyncRun:
    """Finish a run as succeeded or partial, without committing the session."""

    if run.status in SYNC_RUN_TERMINAL_STATUSES:
        raise DataSyncRunValidationError("已结束的同步日志不能重复完成。")
    effective_status = status or ("partial" if complete is False else "succeeded")
    effective_status = _validate_choice(
        effective_status,
        choices=frozenset({"succeeded", "partial"}),
        label="完成状态",
    )
    completed_at = _now(finished_at)
    _apply_metrics(run, metrics)
    _merge_metadata(run, metadata)
    run.status = effective_status
    run.complete = complete
    run.finished_at = completed_at
    run.error_code = None
    run.error_message = None
    run.updated_at = completed_at
    await add_sync_run_event(
        session,
        run=run,
        event_type="completed" if effective_status == "succeeded" else "partially_completed",
        status=effective_status,
        occurred_at=completed_at,
    )
    await session.flush()
    return run


async def fail_sync_run(
    session: AsyncSession,
    *,
    run: DataSyncRun,
    error_code: str,
    error_message: str | None = None,
    finished_at: datetime | None = None,
    metadata: dict[str, object] | None = None,
) -> DataSyncRun:
    """Finish a run with a caller-supplied, safe error code/message."""

    if run.status in SYNC_RUN_TERMINAL_STATUSES:
        raise DataSyncRunValidationError("已结束的同步日志不能重复失败。")
    normalized_code = _bounded_text(error_code, limit=80)
    if normalized_code is None or not _ERROR_CODE_PATTERN.fullmatch(normalized_code):
        raise DataSyncRunValidationError("同步失败代码格式无效。")
    failed_at = _now(finished_at)
    _merge_metadata(run, metadata)
    run.status = "failed"
    run.complete = False
    run.finished_at = failed_at
    run.error_code = normalized_code
    run.error_message = _bounded_text(error_message, limit=500) or "同步未完成，请稍后重试。"
    run.updated_at = failed_at
    await add_sync_run_event(
        session,
        run=run,
        event_type="failed",
        status="failed",
        message=run.error_message,
        occurred_at=failed_at,
    )
    await session.flush()
    return run


async def supersede_sync_run(
    session: AsyncSession,
    *,
    run: DataSyncRun,
    finished_at: datetime | None = None,
) -> DataSyncRun:
    """Mark an unclaimed queued run as replaced by a newer manual request."""

    if run.status != "queued":
        raise DataSyncRunValidationError("只有排队中的同步日志可以被替代。")
    completed_at = _now(finished_at)
    run.status = "superseded"
    run.complete = None
    run.finished_at = completed_at
    run.updated_at = completed_at
    await add_sync_run_event(
        session,
        run=run,
        event_type="superseded",
        status="superseded",
        occurred_at=completed_at,
    )
    await session.flush()
    return run


async def cancel_sync_run(
    session: AsyncSession,
    *,
    run: DataSyncRun,
    finished_at: datetime | None = None,
    message: str | None = None,
) -> DataSyncRun:
    """Record an interrupted run without presenting it as a remote failure."""

    if run.status in SYNC_RUN_TERMINAL_STATUSES:
        raise DataSyncRunValidationError("已结束的同步日志不能重复取消。")
    cancelled_at = _now(finished_at)
    run.status = "cancelled"
    run.complete = False
    run.finished_at = cancelled_at
    run.updated_at = cancelled_at
    run.error_code = None
    run.error_message = _bounded_text(message, limit=500)
    await add_sync_run_event(
        session,
        run=run,
        event_type="cancelled",
        status="cancelled",
        message=run.error_message,
        occurred_at=cancelled_at,
    )
    await session.flush()
    return run


def sync_run_to_dict(run: DataSyncRun) -> dict[str, Any]:
    started_at = _as_utc(run.started_at)
    finished_at = _as_utc(run.finished_at)
    duration_ms: int | None = None
    if started_at is not None and finished_at is not None:
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1_000))
    return {
        "id": run.id,
        "source_id": run.source_id,
        "source_display_name": run.source_display_name,
        "business_timezone": run.business_timezone,
        "source_config_version": run.source_config_version,
        "business_type": run.business_type,
        "operation_kind": run.operation_kind,
        "trigger_type": run.trigger_type,
        "status": run.status,
        "requested_by_user_id": run.requested_by_user_id,
        "requested_by_display_name": run.requested_by_display_name,
        "requested_at": _as_utc(run.requested_at),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "window_start_utc": _as_utc(run.window_start_utc),
        "window_end_utc": _as_utc(run.window_end_utc),
        "query_range": run.query_range,
        "page_size": run.page_size,
        "remote_total": run.remote_total,
        "export_row_count": run.export_row_count,
        "cached_total": run.cached_total,
        "fetched_pages": run.fetched_pages,
        "imported_count": run.imported_count,
        "created_count": run.created_count,
        "updated_count": run.updated_count,
        "duplicate_count": run.duplicate_count,
        "matched_count": run.matched_count,
        "unmatched_count": run.unmatched_count,
        "resolved_uid_count": run.resolved_uid_count,
        "unresolved_uid_count": run.unresolved_uid_count,
        "complete": run.complete,
        "input_filename": run.input_filename,
        "input_size_bytes": run.input_size_bytes,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "metadata": dict(run.metadata_json or {}),
        "created_at": _as_utc(run.created_at),
        "updated_at": _as_utc(run.updated_at),
    }


def sync_run_event_to_dict(event: DataSyncRunEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "status": event.status,
        "message": event.message,
        "metadata": dict(event.metadata_json or {}),
        "occurred_at": _as_utc(event.occurred_at),
    }


def _execution_at_expression() -> Any:
    return func.coalesce(DataSyncRun.started_at, DataSyncRun.requested_at)


def _query_filters(request: SyncLogQueryRequest) -> list[Any]:
    filters: list[Any] = []
    execution_at = _execution_at_expression()
    if request.source_id:
        filters.append(DataSyncRun.source_id == request.source_id)
    if request.business_types:
        filters.append(DataSyncRun.business_type.in_(request.business_types))
    if request.trigger_types:
        filters.append(DataSyncRun.trigger_type.in_(request.trigger_types))
    if request.statuses:
        filters.append(DataSyncRun.status.in_(request.statuses))
    if request.started_at:
        filters.append(execution_at >= _as_utc(request.started_at))
    if request.ended_at:
        filters.append(execution_at <= _as_utc(request.ended_at))
    if request.keyword:
        pattern = f"%{request.keyword.lower()}%"
        filters.append(
            or_(
                func.lower(DataSyncRun.id).like(pattern),
                func.lower(DataSyncRun.source_display_name).like(pattern),
                func.lower(DataSyncRun.business_type).like(pattern),
                func.lower(DataSyncRun.error_code).like(pattern),
                func.lower(DataSyncRun.input_filename).like(pattern),
                func.lower(DataSyncRun.requested_by_display_name).like(pattern),
            )
        )
    return filters


def _trend_bucket(value: datetime, *, hourly: bool) -> datetime:
    normalized = _as_utc(value) or datetime.now(UTC)
    if hourly:
        return normalized.replace(minute=0, second=0, microsecond=0)
    return normalized.replace(hour=0, minute=0, second=0, microsecond=0)


def _summarize_rows(
    rows: list[tuple[str, datetime, datetime | None, datetime | None]],
    *,
    generated_at: datetime,
    request: SyncLogQueryRequest,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    counts = {status: 0 for status in SYNC_RUN_STATUSES}
    latest_succeeded_at: datetime | None = None
    recent_success = 0
    recent_problem = 0
    cutoff = generated_at - timedelta(hours=24)
    span = (
        (_as_utc(request.ended_at) - _as_utc(request.started_at))
        if request.started_at is not None and request.ended_at is not None
        else None
    )
    hourly = span is not None and span <= timedelta(days=3)
    trends: dict[datetime, dict[str, int]] = defaultdict(
        lambda: {status: 0 for status in SYNC_RUN_TREND_STATUSES}
    )
    for status, requested_at, started_at, finished_at in rows:
        counts[status] = counts.get(status, 0) + 1
        event_time = _as_utc(started_at) or _as_utc(requested_at) or generated_at
        completed_at = _as_utc(finished_at) or event_time
        if status == "succeeded":
            if completed_at >= cutoff:
                recent_success += 1
            if latest_succeeded_at is None or completed_at > latest_succeeded_at:
                latest_succeeded_at = completed_at
        if status in {"failed", "partial"} and completed_at >= cutoff:
            recent_problem += 1
        if status in SYNC_RUN_TREND_STATUSES:
            trends[_trend_bucket(event_time, hourly=hourly)][status] += 1

    return (
        {
            "total": sum(counts.values()),
            "queued_count": counts["queued"],
            "running_count": counts["running"],
            "succeeded_count": counts["succeeded"],
            "partial_count": counts["partial"],
            "failed_count": counts["failed"],
            "superseded_count": counts["superseded"],
            "cancelled_count": counts["cancelled"],
            "in_progress_count": counts["queued"] + counts["running"],
            "last_24_hours_succeeded_count": recent_success,
            "last_24_hours_problem_count": recent_problem,
            "latest_succeeded_at": latest_succeeded_at,
        },
        [
            {
                "bucket_start": bucket_start,
                "queued_count": counts_by_status["queued"],
                "running_count": counts_by_status["running"],
                "succeeded_count": counts_by_status["succeeded"],
                "partial_count": counts_by_status["partial"],
                "failed_count": counts_by_status["failed"],
            }
            for bucket_start, counts_by_status in sorted(trends.items())
        ],
    )


def _is_missing_sync_run_schema(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    return ("data_sync_runs" in message or "data_sync_run_events" in message) and (
        "does not exist" in message or "no such table" in message
    )


async def query_sync_runs(
    session: AsyncSession,
    *,
    request: SyncLogQueryRequest,
    now: datetime | None = None,
) -> DataSyncRunQueryResult:
    """Query only local logs, summaries and a compact status trend."""

    generated_at = _now(now)
    filters = _query_filters(request)
    try:
        total = int(
            await session.scalar(select(func.count()).select_from(DataSyncRun).where(*filters)) or 0
        )
        runs = list(
            await session.scalars(
                select(DataSyncRun)
                .where(*filters)
                .order_by(desc(DataSyncRun.requested_at), desc(DataSyncRun.created_at))
                .offset((request.page - 1) * request.page_size)
                .limit(request.page_size)
            )
        )
        summary_rows = list(
            await session.execute(
                select(
                    DataSyncRun.status,
                    DataSyncRun.requested_at,
                    DataSyncRun.started_at,
                    DataSyncRun.finished_at,
                ).where(*filters)
            )
        )
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_sync_run_schema(exc):
            raise
        await session.rollback()
        raise DataSyncRunSchemaPendingError(
            "同步日志正在初始化，请在数据库迁移完成后重试。"
        ) from exc

    summary, trend = _summarize_rows(
        summary_rows,
        generated_at=generated_at,
        request=request,
    )
    return DataSyncRunQueryResult(
        items=[sync_run_to_dict(run) for run in runs],
        total=total,
        summary=summary,
        trend=trend,
        generated_at=generated_at,
    )


async def get_sync_run_detail(
    session: AsyncSession,
    *,
    run_id: str,
) -> DataSyncRunDetailResult:
    normalized_id = _bounded_text(run_id, limit=36)
    if normalized_id is None:
        raise DataSyncRunNotFoundError("同步日志不存在。")
    try:
        run = await session.get(DataSyncRun, normalized_id)
        if run is None:
            raise DataSyncRunNotFoundError("同步日志不存在。")
        events = list(
            await session.scalars(
                select(DataSyncRunEvent)
                .where(DataSyncRunEvent.run_id == run.id)
                .order_by(DataSyncRunEvent.occurred_at.asc(), DataSyncRunEvent.id.asc())
            )
        )
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_sync_run_schema(exc):
            raise
        await session.rollback()
        raise DataSyncRunSchemaPendingError(
            "同步日志正在初始化，请在数据库迁移完成后重试。"
        ) from exc
    return DataSyncRunDetailResult(
        run=sync_run_to_dict(run),
        events=[sync_run_event_to_dict(event) for event in events],
    )
