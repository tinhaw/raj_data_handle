"""Server-side synchronization of reviewed scoring cases into the local cache."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.security import SecurityValidationError, decrypt_credentials
from packages.common.settings import Settings, get_settings
from packages.domain.services.data_sync_run_service import (
    add_sync_run_event,
    cancel_sync_run,
    create_sync_run,
    fail_sync_run,
    get_sync_run_for_update,
)
from packages.domain.services.remote_scoring_review_service import (
    RemoteScoringReviewError,
    ScoringReviewRemoteClient,
)
from packages.domain.services.scoring_reviewed_cases_import_service import (
    ScoringReviewedCasesImportError,
    parse_scoring_reviewed_cases_export,
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
    trigger_type: Literal["automatic", "manual"] = "manual",
) -> WithdrawScoringImportResult:
    """Export one source/date range then atomically persist its projection.

    The remote API is never exposed to the browser.  The source-owned workbook
    is downloaded only into a bounded in-memory buffer and immediately parsed
    with the shared strict Excel whitelist before any local cache mutation.
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
            trigger_type=trigger_type,
            requested_by_user_id=actor_user_id,
            requested_at=requested_at,
            window_start_utc=start_at.astimezone(UTC),
            window_end_utc=end_at.astimezone(UTC),
            status="running",
            metadata={"transport": "excel_export"},
        )
        await add_sync_run_event(
            session,
            run=sync_run,
            event_type="scoring_remote_export_started",
            status="running",
            message="开始导出评分审核远端 Excel。",
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
            export_content = await client.export_reviewed_cases(
                create_time_start=start_at,
                create_time_end=end_at,
            )

        sync_run = await get_sync_run_for_update(session, run_id=sync_run.id)
        if sync_run is not None:
            # Only the byte length is retained for operational diagnosis; the
            # source workbook itself remains in memory and is discarded after
            # the strict projection below.
            sync_run.input_size_bytes = len(export_content)
            await add_sync_run_event(
                session,
                run=sync_run,
                event_type="scoring_remote_export_fetched",
                status="running",
                message="评分审核远端 Excel 导出完成，准备校验。",
                metadata={"exportBytes": len(export_content)},
            )
        await session.commit()

        parsed_export = parse_scoring_reviewed_cases_export(export_content)
        sync_run = await get_sync_run_for_update(session, run_id=sync_run.id)
        if sync_run is not None:
            await add_sync_run_event(
                session,
                run=sync_run,
                event_type="scoring_remote_export_parsed",
                status="running",
                message="评分审核 Excel 校验完成，准备补充本地提现订单。",
                metadata={"sourceRowCount": parsed_export.source_row_count},
            )
        await session.commit()

        result = await import_scoring_reviewed_cases(
            session,
            source_id=source.source_id,
            cases=parsed_export.cases,
            source_row_count=parsed_export.source_row_count,
            actor_user_id=actor_user_id,
            audit_action=(
                "withdraw_scoring.auto_sync"
                if trigger_type == "automatic"
                else "withdraw_scoring.remote_sync"
            ),
            audit_metadata={
                "createTimeStart": create_time_start,
                "createTimeEnd": create_time_end,
                "transport": "excel_export",
                "exportBytes": len(export_content),
            },
            sync_run_id=sync_run.id,
            remote_total=parsed_export.source_row_count,
        )
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
    except ScoringReviewedCasesImportError as exc:
        await _record_remote_sync_failure(
            session,
            sync_run_id=sync_run.id,
            error_code="remote_scoring_review_sync_failed",
            error_message="评分审核远端导出或校验未完成，请稍后重试。",
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
