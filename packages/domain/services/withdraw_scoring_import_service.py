"""Persist scoring-review Excel supplements without creating withdrawal orders."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import WithdrawOrderSnapshot, WithdrawScoringSnapshot
from packages.domain.services.auth_service import write_audit
from packages.domain.services.data_sync_run_service import (
    SyncRunMetrics,
    add_sync_run_event,
    complete_sync_run,
    create_sync_run,
    fail_sync_run,
    get_sync_run_for_update,
)
from packages.domain.services.scoring_reviewed_cases_import_service import (
    ScoringReviewedCase,
    ScoringReviewedCasesImportError,
    parse_scoring_reviewed_cases_export,
)
from packages.domain.services.source_service import get_source

CASE_ID_QUERY_CHUNK_SIZE = 500
WALL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class WithdrawScoringImportError(ValueError):
    """A safe validation failure for a score-review workbook import."""


class WithdrawScoringCacheSchemaPendingError(RuntimeError):
    """The scoring supplement table has not been migrated yet."""


@dataclass(frozen=True, slots=True)
class WithdrawScoringImportResult:
    source_id: str
    source_row_count: int
    matched_count: int
    created_count: int
    updated_count: int
    unmatched_count: int
    synced_at: datetime


def _now(value: datetime | None) -> datetime:
    candidate = value or datetime.now(UTC)
    return candidate if candidate.tzinfo else candidate.replace(tzinfo=UTC)


def _chunks(values: Iterable[str], size: int = CASE_ID_QUERY_CHUNK_SIZE) -> Iterable[list[str]]:
    iterator = iter(values)
    while chunk := list(islice(iterator, size)):
        yield chunk


def _timestamp(value: str | None, *, timezone_name: str) -> datetime | None:
    if value is None:
        return None
    if len(value) > 32:
        raise WithdrawScoringImportError("评分审核导出表格包含超长时间字段。")
    parsed: datetime | None = None
    for parser in (
        lambda: datetime.strptime(value, WALL_TIME_FORMAT),
        lambda: datetime.fromisoformat(value),
    ):
        try:
            parsed = parser()
            break
        except ValueError:
            continue
    if parsed is None:
        raise WithdrawScoringImportError("评分审核导出表格包含无效时间字段。")
    if parsed.tzinfo is None:
        try:
            return parsed.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(UTC)
        except ZoneInfoNotFoundError as exc:
            raise WithdrawScoringImportError("盘口业务时区无效，无法导入评分审核数据。") from exc
    return parsed.astimezone(UTC)


def _bounded(value: str | None, *, limit: int) -> str | None:
    if value is not None and len(value) > limit:
        raise WithdrawScoringImportError("评分审核导出表格包含超长字段。")
    return value


async def _withdrawals_by_case_id(
    session: AsyncSession,
    *,
    source_id: str,
    case_ids: Iterable[str],
) -> dict[str, WithdrawOrderSnapshot]:
    rows_by_case_id: dict[str, WithdrawOrderSnapshot] = {}
    for chunk in _chunks(case_ids):
        rows = list(
            await session.scalars(
                select(WithdrawOrderSnapshot)
                .where(
                    WithdrawOrderSnapshot.source_id == source_id,
                    WithdrawOrderSnapshot.remote_order_id.in_(chunk),
                )
                .with_for_update()
            )
        )
        rows_by_case_id.update({row.remote_order_id: row for row in rows})
    return rows_by_case_id


async def _scoring_rows_by_case_id(
    session: AsyncSession,
    *,
    source_id: str,
    case_ids: Iterable[str],
) -> dict[str, WithdrawScoringSnapshot]:
    rows_by_case_id: dict[str, WithdrawScoringSnapshot] = {}
    for chunk in _chunks(case_ids):
        rows = list(
            await session.scalars(
                select(WithdrawScoringSnapshot)
                .where(
                    WithdrawScoringSnapshot.source_id == source_id,
                    WithdrawScoringSnapshot.withdraw_order_id.in_(chunk),
                )
                .with_for_update()
            )
        )
        rows_by_case_id.update({row.withdraw_order_id: row for row in rows})
    return rows_by_case_id


def _apply_scoring_case(
    snapshot: WithdrawScoringSnapshot,
    *,
    case: ScoringReviewedCase,
    timezone_name: str,
    synced_at: datetime,
) -> None:
    """Copy only score-specific columns; master withdrawal data is untouched."""

    snapshot.global_hard_condition = _bounded(case.global_hard_condition, limit=120)
    snapshot.scenario_review = _bounded(case.scenario_review, limit=120)
    snapshot.score_review = _bounded(case.score_review, limit=80)
    snapshot.decision_stage = _bounded(case.decision_stage, limit=120)
    snapshot.final_review_suggestion = _bounded(case.final_review_suggestion, limit=120)
    snapshot.operation_result = _bounded(case.operation_result, limit=120)
    snapshot.review_summary = _bounded(case.review_summary, limit=2_000)
    snapshot.current_status = _bounded(case.current_status, limit=120)
    snapshot.review_completed_at = _timestamp(
        case.review_completed_at,
        timezone_name=timezone_name,
    )
    snapshot.review_duration = _bounded(case.review_duration, limit=80)
    snapshot.queue_duration = _bounded(case.queue_duration, limit=80)
    snapshot.entered_queue_at = _timestamp(case.entered_queue_at, timezone_name=timezone_name)
    snapshot.exited_queue_at = _timestamp(case.exited_queue_at, timezone_name=timezone_name)
    snapshot.last_seen_at = synced_at
    snapshot.synced_at = synced_at


def _is_missing_scoring_schema(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    return (
        "withdraw_scoring_snapshots" in message
        or "data_sync_runs" in message
        or "data_sync_run_events" in message
    ) and ("does not exist" in message or "no such table" in message)


def _safe_input_filename(value: str | None) -> str | None:
    """Keep only a display-safe file name, never a browser-provided path."""

    normalized = (value or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    normalized = "".join(
        character for character in normalized if character >= " " and character != "\x7f"
    )
    return normalized[:255] or None


async def _record_excel_import_failure(
    session: AsyncSession,
    *,
    sync_run_id: str,
    error_code: str,
    error_message: str,
) -> None:
    """Best-effort terminal log after the workbook transaction has rolled back.

    The initial running record is committed before parsing begins.  That lets a
    malformed workbook remain visible as a failed import without retaining its
    contents or an exception trace.  Failure logging must not replace the
    original user-facing import error.
    """

    await session.rollback()
    try:
        run = await get_sync_run_for_update(session, run_id=sync_run_id)
        if run is None or run.status in {
            "succeeded",
            "partial",
            "failed",
            "superseded",
            "cancelled",
        }:
            return
        await fail_sync_run(
            session,
            run=run,
            error_code=error_code,
            error_message=error_message,
        )
        await session.commit()
    except Exception:
        # Logging is intentionally best effort.  Do not leak a lower-level
        # database error in place of the workbook parser's safe validation
        # message, and do not write raw exception data into the sync log.
        await session.rollback()


async def import_scoring_reviewed_cases_export(
    session: AsyncSession,
    *,
    source_id: str,
    content: bytes,
    actor_user_id: int | None,
    now: datetime | None = None,
    input_filename: str | None = None,
) -> WithdrawScoringImportResult:
    """Enrich existing source-scoped withdrawal snapshots from one XLSX.

    ``案件号`` is treated as a foreign key, not a master-order identifier to
    insert.  A scoring-only row is counted as unmatched and deliberately
    omitted.  Existing scoring supplements are updated in place, while score
    snapshots not present in this import are retained for later incremental
    imports.  A separate, safe sync-run record is committed before parsing so
    parse failures are visible without storing the submitted workbook.
    """

    synced_at = _now(now)
    try:
        source = await get_source(session, source_id)
        sync_run = await create_sync_run(
            session,
            source=source,
            business_type="withdraw_scoring_import",
            trigger_type="upload",
            operation_kind="excel_import",
            requested_by_user_id=actor_user_id,
            requested_at=synced_at,
            status="running",
            input_filename=_safe_input_filename(input_filename),
            input_size_bytes=len(content),
        )
        resolved_source_id = source.source_id
        sync_run_id = sync_run.id
        await add_sync_run_event(
            session,
            run=sync_run,
            event_type="excel_parse_started",
            status="running",
            message="开始校验评分审核 Excel 文件。",
            occurred_at=synced_at,
        )
        # Persist the initial lifecycle event independently from the data
        # mutation below so a parse or validation error can be marked failed.
        await session.commit()
    except (OperationalError, ProgrammingError) as exc:
        await session.rollback()
        if _is_missing_scoring_schema(exc):
            raise WithdrawScoringCacheSchemaPendingError(
                "评分审核本地缓存或同步日志正在初始化，请在数据库迁移完成后重试。"
            ) from exc
        raise

    try:
        parsed = parse_scoring_reviewed_cases_export(content)
        sync_run = await get_sync_run_for_update(session, run_id=sync_run_id)
        if sync_run is None:
            raise WithdrawScoringImportError("评分审核导入运行记录不存在。")
        await add_sync_run_event(
            session,
            run=sync_run,
            event_type="excel_parse_completed",
            status="running",
            message="评分审核 Excel 校验完成，准备补充本地提现订单。",
            metadata={"sourceRowCount": parsed.source_row_count},
            occurred_at=synced_at,
        )
        # Retain the parse-stage projection even when a later local join or
        # field validation fails. The workbook itself is still never stored.
        await session.commit()
        return await import_scoring_reviewed_cases(
            session,
            source_id=resolved_source_id,
            cases=parsed.cases,
            source_row_count=parsed.source_row_count,
            actor_user_id=actor_user_id,
            now=synced_at,
            sync_run_id=sync_run_id,
        )
    except ScoringReviewedCasesImportError as exc:
        await _record_excel_import_failure(
            session,
            sync_run_id=sync_run_id,
            error_code="withdraw_scoring_excel_validation_failed",
            error_message=str(exc),
        )
        raise
    except WithdrawScoringCacheSchemaPendingError as exc:
        await _record_excel_import_failure(
            session,
            sync_run_id=sync_run_id,
            error_code="withdraw_scoring_excel_schema_pending",
            error_message=str(exc),
        )
        raise
    except WithdrawScoringImportError as exc:
        await _record_excel_import_failure(
            session,
            sync_run_id=sync_run_id,
            error_code="withdraw_scoring_excel_validation_failed",
            error_message=str(exc),
        )
        raise
    except (OperationalError, ProgrammingError) as exc:
        await _record_excel_import_failure(
            session,
            sync_run_id=sync_run_id,
            error_code="withdraw_scoring_excel_import_failed",
            error_message="评分审核 Excel 导入未完成，请稍后重试。",
        )
        if _is_missing_scoring_schema(exc):
            raise WithdrawScoringCacheSchemaPendingError(
                "评分审核本地缓存或同步日志正在初始化，请在数据库迁移完成后重试。"
            ) from exc
        raise
    except Exception:
        await _record_excel_import_failure(
            session,
            sync_run_id=sync_run_id,
            error_code="withdraw_scoring_excel_import_failed",
            error_message="评分审核 Excel 导入未完成，请稍后重试。",
        )
        raise


async def import_scoring_reviewed_cases(
    session: AsyncSession,
    *,
    source_id: str,
    cases: list[ScoringReviewedCase],
    source_row_count: int,
    actor_user_id: int | None,
    now: datetime | None = None,
    audit_action: str = "withdraw_scoring.import",
    audit_metadata: dict[str, object] | None = None,
    sync_run_id: str | None = None,
) -> WithdrawScoringImportResult:
    """Atomically persist validated score cases from an approved transport.

    Both the workbook parser and the scoring-review API are intentionally
    reduced to the same :class:`ScoringReviewedCase` projection before this
    function runs.  This prevents a new transport from becoming a route for
    master withdrawal fields or arbitrary remote JSON to enter the cache.
    """

    if source_row_count != len(cases):
        raise WithdrawScoringImportError("评分审核数据行数与案件数不一致。")
    case_ids = [case.withdraw_order_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise WithdrawScoringImportError("评分审核数据包含重复案件号。")
    synced_at = _now(now)
    try:
        source = await get_source(session, source_id)
        if sync_run_id is not None:
            sync_run = await get_sync_run_for_update(session, run_id=sync_run_id)
            if sync_run is None:
                raise WithdrawScoringImportError("评分审核导入运行记录不存在。")
            await add_sync_run_event(
                session,
                run=sync_run,
                event_type="import_started",
                status="running",
                message="开始将评分审核结果补充到本地提现订单。",
                metadata={"sourceRowCount": source_row_count},
                occurred_at=synced_at,
            )
        masters = await _withdrawals_by_case_id(
            session,
            source_id=source.source_id,
            case_ids=case_ids,
        )
        existing = await _scoring_rows_by_case_id(
            session,
            source_id=source.source_id,
            case_ids=masters,
        )

        created_count = 0
        updated_count = 0
        for case in cases:
            if case.withdraw_order_id not in masters:
                continue
            snapshot = existing.get(case.withdraw_order_id)
            if snapshot is None:
                snapshot = WithdrawScoringSnapshot(
                    source_id=source.source_id,
                    withdraw_order_id=case.withdraw_order_id,
                    first_seen_at=synced_at,
                    last_seen_at=synced_at,
                    synced_at=synced_at,
                )
                session.add(snapshot)
                created_count += 1
            else:
                updated_count += 1
            _apply_scoring_case(
                snapshot,
                case=case,
                timezone_name=source.business_timezone,
                synced_at=synced_at,
            )

        matched_count = created_count + updated_count
        unmatched_count = source_row_count - matched_count
        await session.flush()
        metadata: dict[str, object] = {
            "sourceRows": source_row_count,
            "matchedRows": matched_count,
            "createdRows": created_count,
            "updatedRows": updated_count,
            "unmatchedRows": unmatched_count,
        }
        if audit_metadata:
            metadata.update(audit_metadata)
        await write_audit(
            session,
            action=audit_action,
            actor_user_id=actor_user_id,
            target_type="source",
            target_id=source.source_id,
            metadata=metadata,
        )
        if sync_run_id is not None:
            sync_run = await get_sync_run_for_update(session, run_id=sync_run_id)
            if sync_run is None:
                raise WithdrawScoringImportError("评分审核导入运行记录不存在。")
            # The workbook parser rejects duplicate case IDs, so every
            # successful Excel import has zero tolerated duplicates.  The
            # imported count is the number of validated input rows; matched
            # and unmatched make explicit which rows enriched a local order.
            await complete_sync_run(
                session,
                run=sync_run,
                metrics=SyncRunMetrics(
                    export_row_count=source_row_count,
                    imported_count=source_row_count,
                    created_count=created_count,
                    updated_count=updated_count,
                    duplicate_count=0,
                    matched_count=matched_count,
                    unmatched_count=unmatched_count,
                ),
                finished_at=synced_at,
            )
        await session.commit()
    except (OperationalError, ProgrammingError) as exc:
        await session.rollback()
        if _is_missing_scoring_schema(exc):
            raise WithdrawScoringCacheSchemaPendingError(
                "评分审核本地缓存正在初始化，请在数据库迁移完成后重试。"
            ) from exc
        raise
    except Exception:
        await session.rollback()
        raise

    return WithdrawScoringImportResult(
        source_id=source.source_id,
        source_row_count=source_row_count,
        matched_count=matched_count,
        created_count=created_count,
        updated_count=updated_count,
        unmatched_count=unmatched_count,
        synced_at=synced_at,
    )
