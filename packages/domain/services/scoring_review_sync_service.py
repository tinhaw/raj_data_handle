"""Server-side synchronization of reviewed scoring cases into the local cache."""

from __future__ import annotations

from datetime import datetime
from math import ceil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.security import SecurityValidationError, decrypt_credentials
from packages.common.settings import Settings, get_settings
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
    WithdrawScoringImportResult,
    import_scoring_reviewed_cases,
)

MAX_SCORING_REVIEW_SYNC_PAGES = 50
MAX_SCORING_REVIEW_SYNC_CASES = MAX_SCORING_REVIEW_SYNC_PAGES * MAX_SCORING_REVIEW_PAGE_SIZE
WALL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class ScoringReviewSyncError(ValueError):
    """Safe validation failure for a configured remote scoring sync."""


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
    except RemoteScoringReviewError as exc:
        raise ScoringReviewSyncError(str(exc)) from exc

    if len(cases) != first_page.total:
        raise ScoringReviewSyncError("评分审核远端分页结果不完整，请稍后重试。")
    case_ids = [case.withdraw_order_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ScoringReviewSyncError("评分审核远端分页结果包含重复案件号，请稍后重试。")
    return await import_scoring_reviewed_cases(
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
