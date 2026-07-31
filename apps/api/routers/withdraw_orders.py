from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context
from packages.common.database import get_db_session
from packages.domain.schemas.withdraw_order import (
    ScoringReviewOperatorSummaryRequest,
    ScoringReviewOperatorSummaryResponse,
    WithdrawChannelSummaryRequest,
    WithdrawChannelSummaryResponse,
    WithdrawOperatorSummaryRequest,
    WithdrawOperatorSummaryResponse,
    WithdrawOrderQueryRequest,
    WithdrawOrderQueryResponse,
    WithdrawOrderRefreshRequest,
    WithdrawOrderRefreshResponse,
    WithdrawScoringImportResponse,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.scoring_review_summary_service import (
    query_scoring_review_operator_summary,
)
from packages.domain.services.scoring_reviewed_cases_import_service import (
    MAX_SCORING_REVIEWED_CASES_EXPORT_BYTES,
    ScoringReviewedCasesImportError,
)
from packages.domain.services.source_service import SourceNotFoundError
from packages.domain.services.system_setting_service import SystemSettingsSchemaPendingError
from packages.domain.services.withdraw_order_refresh_service import (
    WithdrawOrderRefreshValidationError,
    queue_withdraw_order_refreshes,
)
from packages.domain.services.withdraw_order_service import (
    WithdrawOrderCacheSchemaPendingError,
    WithdrawOrderValidationError,
    query_withdraw_channel_summary,
    query_withdraw_operator_summary,
    query_withdraw_orders,
)
from packages.domain.services.withdraw_scoring_import_service import (
    WithdrawScoringCacheSchemaPendingError,
    WithdrawScoringImportError,
    import_scoring_reviewed_cases_export,
)

router = APIRouter(prefix="/withdraw-orders", tags=["withdraw-orders"])


async def _read_scoring_workbook(upload: UploadFile) -> bytes:
    """Read a scoring export into bounded memory without retaining the file."""

    chunks: list[bytes] = []
    total = 0
    try:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_SCORING_REVIEWED_CASES_EXPORT_BYTES:
                raise WithdrawScoringImportError("评分审核导出文件超过大小限制。")
            chunks.append(chunk)
    finally:
        await upload.close()
    return b"".join(chunks)


@router.post("/query", response_model=WithdrawOrderQueryResponse)
async def withdraw_order_query(
    payload: WithdrawOrderQueryRequest,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> WithdrawOrderQueryResponse:
    try:
        result = await query_withdraw_orders(session, request=payload)
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WithdrawOrderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (WithdrawOrderCacheSchemaPendingError, SystemSettingsSchemaPendingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return WithdrawOrderQueryResponse(
        items=result.items,
        total=result.total,
        remote_total=result.remote_total,
        page=payload.page,
        page_size=payload.page_size,
        fetched_pages=result.fetched_pages,
        complete=result.complete,
        source_id=result.source_id,
        source_display_name=result.source_display_name,
        business_timezone=result.business_timezone,
        currency=result.currency,
        effective_create_time_end=result.effective_create_time_end,
        fetched_at=result.fetched_at,
        local_updated_at=result.local_updated_at,
        last_refreshed_at=result.last_refreshed_at,
        refresh_status=result.refresh_status,
        status_dictionary=result.status_dictionary,
        channel_dictionary=result.channel_dictionary,
        summary=result.summary,
    )


@router.post("/channel-summary", response_model=WithdrawChannelSummaryResponse)
async def withdraw_channel_summary(
    payload: WithdrawChannelSummaryRequest,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> WithdrawChannelSummaryResponse:
    try:
        result = await query_withdraw_channel_summary(session, request=payload)
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WithdrawOrderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (WithdrawOrderCacheSchemaPendingError, SystemSettingsSchemaPendingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return WithdrawChannelSummaryResponse(
        items=result.items,
        total=result.total,
        page=payload.page,
        page_size=payload.page_size,
        source_id=result.source_id,
        source_display_name=result.source_display_name,
        business_timezone=result.business_timezone,
        currency=result.currency,
        effective_create_time_end=result.effective_create_time_end,
        fetched_at=result.fetched_at,
        local_updated_at=result.local_updated_at,
        channel_dictionary=result.channel_dictionary,
    )


@router.post("/operator-summary", response_model=WithdrawOperatorSummaryResponse)
async def withdraw_operator_summary(
    payload: WithdrawOperatorSummaryRequest,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> WithdrawOperatorSummaryResponse:
    """Return a paginated, local-only withdrawal aggregation by operator."""

    try:
        result = await query_withdraw_operator_summary(session, request=payload)
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WithdrawOrderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (WithdrawOrderCacheSchemaPendingError, SystemSettingsSchemaPendingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return WithdrawOperatorSummaryResponse(
        items=result.items,
        total=result.total,
        page=payload.page,
        page_size=payload.page_size,
        source_id=result.source_id,
        source_display_name=result.source_display_name,
        business_timezone=result.business_timezone,
        effective_create_time_end=result.effective_create_time_end,
        fetched_at=result.fetched_at,
        local_updated_at=result.local_updated_at,
        status_columns=result.status_columns,
        status_dictionary=result.status_dictionary,
        selected_order_total=result.selected_order_total,
    )


@router.post(
    "/scoring-review-summary",
    response_model=ScoringReviewOperatorSummaryResponse,
)
async def scoring_review_operator_summary(
    payload: ScoringReviewOperatorSummaryRequest,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> ScoringReviewOperatorSummaryResponse:
    """Aggregate local score supplements over the selected withdrawal source."""

    try:
        result = await query_scoring_review_operator_summary(
            session=session,
            source_id=payload.source_id,
            create_time_start=payload.create_time_start,
            create_time_end=payload.create_time_end,
        )
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WithdrawOrderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (WithdrawOrderCacheSchemaPendingError, SystemSettingsSchemaPendingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return ScoringReviewOperatorSummaryResponse(
        source_id=result.source_id,
        source_display_name=result.source_display_name,
        business_timezone=result.business_timezone,
        start_at=result.start_at,
        end_at=result.end_at,
        generated_at=result.generated_at,
        local_updated_at=result.local_updated_at,
        rows=result.rows,
        totals=result.totals,
    )


@router.post(
    "/scoring-review/import",
    response_model=WithdrawScoringImportResponse,
)
async def import_scoring_review_workbook(
    source_id: str = Form(..., alias="sourceId"),
    upload: UploadFile = File(...),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> WithdrawScoringImportResponse:
    """Supplement one source's cached withdrawal orders from a scoring XLSX.

    The request intentionally receives only an Excel workbook.  No raw workbook
    is written to local storage; its permitted fields are joined by
    ``案件号 -> 主键`` to pre-existing withdrawal snapshots in the same source.
    """

    normalized_source_id = source_id.strip()
    if not normalized_source_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="盘口不能为空。")
    filename = (upload.filename or "").strip()
    if not filename.lower().endswith(".xlsx"):
        await upload.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请上传评分审核导出的 .xlsx 文件。",
        )
    try:
        content = await _read_scoring_workbook(upload)
        result = await import_scoring_reviewed_cases_export(
            session,
            source_id=normalized_source_id,
            content=content,
            actor_user_id=auth.user.id,
        )
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ScoringReviewedCasesImportError, WithdrawScoringImportError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WithdrawScoringCacheSchemaPendingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return WithdrawScoringImportResponse(
        source_id=result.source_id,
        source_row_count=result.source_row_count,
        matched_count=result.matched_count,
        created_count=result.created_count,
        updated_count=result.updated_count,
        unmatched_count=result.unmatched_count,
        synced_at=result.synced_at,
    )


@router.post(
    "/refresh",
    response_model=WithdrawOrderRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_withdraw_order_refresh(
    payload: WithdrawOrderRefreshRequest = WithdrawOrderRefreshRequest(),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> WithdrawOrderRefreshResponse:
    """Queue a worker-owned read-only cache refresh without remote I/O in API."""

    try:
        result = await queue_withdraw_order_refreshes(
            session,
            source_id=payload.source_id,
            query_range=payload.query_range,
            actor_user_id=auth.user.id,
        )
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WithdrawOrderRefreshValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WithdrawOrderCacheSchemaPendingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return WithdrawOrderRefreshResponse(
        status="queued",
        source_ids=result.source_ids,
        requested_at=result.requested_at,
        query_range=result.query_range,
        message=(
            f"已提交 {len(result.source_ids)} 个盘口的后台同步任务，将按所选时间范围刷新。"
            if result.query_range
            else f"已提交 {len(result.source_ids)} 个盘口的后台同步任务。"
        ),
    )
