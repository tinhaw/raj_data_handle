"""Server-side synchronization of reviewed scoring cases into the local cache."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from math import ceil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.security import SecurityValidationError, decrypt_credentials
from packages.common.settings import Settings, get_settings
from packages.domain.services.data_sync_run_service import (
    SyncRunMetrics,
    add_sync_run_event,
    cancel_sync_run,
    complete_sync_run,
    create_sync_run,
    fail_sync_run,
    get_sync_run_for_update,
)
from packages.domain.services.remote_scoring_review_service import (
    MAX_SCORING_REVIEW_PAGE_SIZE,
    RemoteScoringReviewError,
    ScoringReviewRemoteClient,
)
from packages.domain.services.source_service import (
    _scoring_api_credential_scope,
    get_source,
)
from packages.domain.services.withdraw_scoring_import_service import (
    WithdrawScoringCacheSchemaPendingError,
    WithdrawScoringImportError,
    WithdrawScoringImportResult,
    import_scoring_reviewed_cases,
)

MAX_SCORING_REVIEW_SYNC_PAGES = 50
MAX_SCORING_REVIEW_SYNC_CASES = MAX_SCORING_REVIEW_SYNC_PAGES * MAX_SCORING_REVIEW_PAGE_SIZE
WALL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class ScoringReviewSyncError(ValueError):
    """Safe validation failure for a configured remote scoring sync."""


def _sync_log_schema_is_pending(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    return ("data_sync_runs" in message or "data_sync_run_events" in message) and (
        "does not exist" in message or "no such table" in message
    )


async def _record_remote_sync_failure(
    session: AsyncSession,
    *,
    sync_run_id: str,
    error_code: str,
    error_message: str,
) -> None:
    """Best-effort safe terminal state after a remote scoring-read failure."""

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
        # The original user-facing remote-sync error remains authoritative;
        # operational logging must not replace it or store a raw exception.
        await session.rollback()


async def _record_remote_sync_cancelled(
    session: AsyncSession,
    *,
    sync_run_id: str,
) -> None:
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
        await cancel_sync_run(
            session,
            run=run,
            message="评分审核远端同步在完成前被取消。",
        )
        await session.commit()
    except Exception:
        await session.rollback()


def _range_endpoint(value: str, *, timezone_name: str) -> datetime:
    try:
        wall_time = datetime.strptime(value, WALL_TIME_FORMAT)
        timezone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ScoringReviewSyncError("盘口业务时区或评分审核同步时间范围无效。") from exc
    return wall_time.replace(tzinfo=timezone)


async def sync_scoring_reviewed_cases_from_remote(
    session: AsyncSession,
    *,
    source_id: str,
    create_time_start: str,
    create_time_end: str,
    actor_user_id: int | None,
    settings: Settings | None = None,
) -> WithdrawScoringImportResult:
    """Fetch one bounded source/date range then atomically persist its projection.

    The remote API is never exposed to the browser.  All pages are read before
    any local cache mutation, and a changing or incomplete remote result aborts
    the sync instead of partially overwriting a score supplement.
    """

    current_settings = settings or get_settings()
    source = await get_source(session, source_id)
    if not source.enabled:
        raise ScoringReviewSyncError("所选盘口尚未启用，不能同步评分审核数据。")
    if not source.scoring_api_base_url or not source.encrypted_scoring_api_key:
        raise ScoringReviewSyncError("所选盘口尚未配置评分审核 API Base URL 或 API Key。")
    if source.scoring_api_last_test_status != "passed":
        raise ScoringReviewSyncError("请先通过该盘口的评分审核 API 连接测试。")
    start_at = _range_endpoint(create_time_start, timezone_name=source.business_timezone)
    end_at = _range_endpoint(create_time_end, timezone_name=source.business_timezone)
    if start_at > end_at:
        raise ScoringReviewSyncError("评分审核同步时间范围的开始时间不能晚于结束时间。")
    try:
        credentials = decrypt_credentials(
            source.encrypted_scoring_api_key,
            source_id=_scoring_api_credential_scope(source.source_id),
            credential_version=source.scoring_api_key_version,
            settings=current_settings,
        )
        api_key = credentials["api_key"]
    except (SecurityValidationError, KeyError) as exc:
        raise ScoringReviewSyncError("已保存的评分审核 API Key 无法解密，请重新配置。") from exc

    # Persist a small, safe execution record before the first remote request.
    # This is deliberately after configuration validation: an invalid setup is
    # not a data synchronization attempt, while any actual remote read should
    # remain traceable even if it later fails.
    requested_at = datetime.now(UTC)
    try:
        sync_run = await create_sync_run(
            session,
            source=source,
            business_type="withdraw_scoring_import",
            operation_kind="remote_sync",
            trigger_type="manual",
            requested_by_user_id=actor_user_id,
            requested_at=requested_at,
            window_start_utc=start_at.astimezone(UTC),
            window_end_utc=end_at.astimezone(UTC),
            page_size=MAX_SCORING_REVIEW_PAGE_SIZE,
            status="running",
        )
        await add_sync_run_event(
            session,
            run=sync_run,
            event_type="scoring_remote_fetch_started",
            status="running",
            message="开始读取评分审核远端数据。",
        )
        await session.commit()
    except (OperationalError, ProgrammingError) as exc:
        await session.rollback()
        if _sync_log_schema_is_pending(exc):
            raise WithdrawScoringCacheSchemaPendingError(
                "评分审核同步日志正在初始化，请在数据库迁移完成后重试。"
            ) from exc
        raise

    try:
        async with ScoringReviewRemoteClient(
            base_url=source.scoring_api_base_url,
            api_key=api_key,
        ) as client:
            first_page = await client.fetch_reviewed_cases(
                page=1,
                page_size=MAX_SCORING_REVIEW_PAGE_SIZE,
                create_time_start=start_at,
                create_time_end=end_at,
            )
            if first_page.total > MAX_SCORING_REVIEW_SYNC_CASES:
                raise ScoringReviewSyncError(
                    "评分审核结果过多，请缩小创建时间范围后再同步。"
                )
            expected_pages = (
                ceil(first_page.total / first_page.page_size) if first_page.total else 0
            )
            if expected_pages > MAX_SCORING_REVIEW_SYNC_PAGES:
                raise ScoringReviewSyncError(
                    "评分审核结果分页过多，请缩小创建时间范围后再同步。"
                )
            cases = list(first_page.cases)
            for page_number in range(2, expected_pages + 1):
                page = await client.fetch_reviewed_cases(
                    page=page_number,
                    page_size=first_page.page_size,
                    create_time_start=start_at,
                    create_time_end=end_at,
                )
                if page.total != first_page.total or page.page_size != first_page.page_size:
                    raise ScoringReviewSyncError("评分审核远端数据在同步期间发生变化，请重试。")
                cases.extend(page.cases)
        if len(cases) != first_page.total:
            raise ScoringReviewSyncError("评分审核远端分页结果不完整，请稍后重试。")
        case_ids = [case.withdraw_order_id for case in cases]
        if len(case_ids) != len(set(case_ids)):
            raise ScoringReviewSyncError("评分审核远端分页结果包含重复案件号，请稍后重试。")

        sync_run = await get_sync_run_for_update(session, run_id=sync_run.id)
        if sync_run is not None:
            await add_sync_run_event(
                session,
                run=sync_run,
                event_type="scoring_remote_fetch_fetched",
                status="running",
                message="评分审核远端数据读取完成，准备补充本地提现订单。",
                metadata={
                    "remoteTotal": first_page.total,
                    "fetchedPages": expected_pages,
                },
            )
        await session.commit()

        result = await import_scoring_reviewed_cases(
            session,
            source_id=source.source_id,
            cases=cases,
            source_row_count=first_page.total,
            actor_user_id=actor_user_id,
            audit_action="withdraw_scoring.remote_sync",
            audit_metadata={
                "createTimeStart": create_time_start,
                "createTimeEnd": create_time_end,
                "remotePages": expected_pages,
            },
        )
        sync_run = await get_sync_run_for_update(session, run_id=sync_run.id)
        if sync_run is not None:
            await complete_sync_run(
                session,
                run=sync_run,
                metrics=SyncRunMetrics(
                    remote_total=first_page.total,
                    export_row_count=result.source_row_count,
                    fetched_pages=expected_pages,
                    imported_count=result.source_row_count,
                    created_count=result.created_count,
                    updated_count=result.updated_count,
                    duplicate_count=0,
                    matched_count=result.matched_count,
                    unmatched_count=result.unmatched_count,
                ),
                metadata={"remotePages": expected_pages},
            )
        await session.commit()
        return result
    except asyncio.CancelledError:
        await _record_remote_sync_cancelled(session, sync_run_id=sync_run.id)
        raise
    except RemoteScoringReviewError as exc:
        await _record_remote_sync_failure(
            session,
            sync_run_id=sync_run.id,
            error_code="remote_scoring_review_sync_failed",
            error_message="评分审核远端数据读取失败，请稍后重试。",
        )
        raise ScoringReviewSyncError(str(exc)) from exc
    except (ScoringReviewSyncError, WithdrawScoringImportError):
        await _record_remote_sync_failure(
            session,
            sync_run_id=sync_run.id,
            error_code="remote_scoring_review_sync_failed",
            error_message="评分审核远端同步未完成，请稍后重试。",
        )
        raise
    except (OperationalError, ProgrammingError) as exc:
        await _record_remote_sync_failure(
            session,
            sync_run_id=sync_run.id,
            error_code="remote_scoring_review_sync_failed",
            error_message="评分审核远端同步未完成，请稍后重试。",
        )
        if _sync_log_schema_is_pending(exc):
            raise WithdrawScoringCacheSchemaPendingError(
                "评分审核同步日志正在初始化，请在数据库迁移完成后重试。"
            ) from exc
        raise
    except Exception:
        await _record_remote_sync_failure(
            session,
            sync_run_id=sync_run.id,
            error_code="remote_scoring_review_sync_failed",
            error_message="评分审核远端同步未完成，请稍后重试。",
        )
        raise
