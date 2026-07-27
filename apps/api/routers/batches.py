from __future__ import annotations

import json
from collections import Counter
from datetime import UTC

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context, get_file_storage
from packages.common.database import get_db_session
from packages.domain.models import OrderReconciliationResult
from packages.domain.schemas.batch import (
    BatchCancelRequest,
    BatchChartsResponse,
    BatchCreateResponse,
    BatchListResponse,
    BatchResponse,
    BatchSummaryResponse,
    OperationalSummaryResponse,
    OrderResultListResponse,
    OrderResultResponse,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.batch_service import (
    BatchValidationError,
    cancel_batch,
    confirm_batch,
    create_batch_from_upload,
    get_batch,
    list_batches,
    rerun_batch,
    summarize_batch,
)
from packages.domain.services.batch_state import InvalidBatchTransition
from packages.domain.services.result_service import (
    all_results,
    export_csv,
    export_excel,
    list_results,
)
from packages.storage import LocalFileStorage
from packages.storage.local import UploadTooLargeError

router = APIRouter(prefix="/order-reconciliation", tags=["order-reconciliation"])


@router.get("/operational-summary", response_model=OperationalSummaryResponse)
async def operational_summary(
    source_id: str | None = None,
    business_type: str | None = None,
    batch_status: str | None = None,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> OperationalSummaryResponse:
    batches, _ = await list_batches(
        session,
        source_id=source_id,
        business_type=business_type,
        status=batch_status,
        limit=10_000,
    )
    statuses = Counter(item.status for item in batches)
    created = Counter(item.created_at.date().isoformat() for item in batches)
    failures = Counter(
        item.error_category or "unknown"
        for item in batches
        if item.status in {"failed", "comparison_incomplete"}
    )
    duration_buckets: Counter[str] = Counter()
    for item in batches:
        if not item.started_at or not item.completed_at:
            continue
        started = item.started_at
        completed = item.completed_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=UTC)
        seconds = (completed - started).total_seconds()
        bucket = (
            "<1m"
            if seconds < 60
            else "1-5m"
            if seconds < 300
            else "5-15m"
            if seconds < 900
            else ">=15m"
        )
        duration_buckets[bucket] += 1
    return OperationalSummaryResponse(
        execution_status_distribution=[
            {"status": key, "count": value} for key, value in sorted(statuses.items())
        ],
        execution_created_time_series=[
            {"date": key, "count": value} for key, value in sorted(created.items())
        ],
        execution_duration_buckets=[
            {"bucket": key, "count": value} for key, value in duration_buckets.items()
        ],
        failure_category_distribution=[
            {"category": key, "count": value} for key, value in sorted(failures.items())
        ],
    )


@router.post(
    "/batches",
    response_model=BatchCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_batch(
    source_id: str = Form(..., alias="sourceId"),
    business_type: str = Form(..., alias="businessType"),
    header_row: int = Form(1, alias="headerRow", ge=1, le=100),
    parameters_json: str = Form("{}", alias="parametersJson"),
    upload: UploadFile = File(...),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
    storage: LocalFileStorage = Depends(get_file_storage),
) -> BatchCreateResponse:
    try:
        parameters = json.loads(parameters_json)
        if not isinstance(parameters, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="parametersJson 必须是 JSON 对象。",
        ) from exc
    try:
        batch, duplicate = await create_batch_from_upload(
            session,
            storage=storage,
            upload=upload,
            source_id=source_id,
            business_type=business_type,
            header_row=header_row,
            parameters=parameters,
            actor_user_id=auth.user.id,
        )
    except (BatchValidationError, UploadTooLargeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BatchCreateResponse(
        batch=BatchResponse.model_validate(batch),
        duplicate_of_existing=duplicate,
    )


@router.get("/batches", response_model=BatchListResponse)
async def batches(
    source_id: str | None = None,
    business_type: str | None = None,
    batch_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> BatchListResponse:
    rows, total = await list_batches(
        session,
        source_id=source_id,
        business_type=business_type,
        status=batch_status,
        limit=min(max(limit, 1), 500),
        offset=max(offset, 0),
    )
    return BatchListResponse(
        items=[BatchResponse.model_validate(item) for item in rows],
        total=total,
    )


@router.get("/batches/{batch_id}", response_model=BatchResponse)
async def batch_detail(
    batch_id: str,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> BatchResponse:
    try:
        batch = await get_batch(session, batch_id)
    except BatchValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return BatchResponse.model_validate(batch)


@router.post("/batches/{batch_id}/rerun", response_model=BatchResponse)
async def rerun(
    batch_id: str,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> BatchResponse:
    try:
        batch = await rerun_batch(session, batch_id=batch_id, actor_user_id=auth.user.id)
    except BatchValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BatchResponse.model_validate(batch)


@router.post("/batches/{batch_id}/confirm", response_model=BatchResponse)
async def confirm(
    batch_id: str,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> BatchResponse:
    try:
        batch = await confirm_batch(
            session,
            batch_id=batch_id,
            actor_user_id=auth.user.id,
        )
    except (BatchValidationError, InvalidBatchTransition) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return BatchResponse.model_validate(batch)


@router.post("/batches/{batch_id}/cancel", response_model=BatchResponse)
async def cancel(
    batch_id: str,
    payload: BatchCancelRequest,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> BatchResponse:
    try:
        batch = await cancel_batch(
            session,
            batch_id=batch_id,
            actor_user_id=auth.user.id,
            reason=payload.reason,
        )
    except (BatchValidationError, InvalidBatchTransition) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return BatchResponse.model_validate(batch)


@router.get("/batches/{batch_id}/summary", response_model=BatchSummaryResponse)
async def batch_summary(
    batch_id: str,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> BatchSummaryResponse:
    try:
        batch = await get_batch(session, batch_id)
    except BatchValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return BatchSummaryResponse(
        batch_id=batch.id,
        run_version=batch.run_version,
        is_final=batch.is_final,
        counts=await summarize_batch(session, batch),
    )


@router.get("/batches/{batch_id}/results", response_model=OrderResultListResponse)
async def batch_results(
    batch_id: str,
    result_status: str | None = None,
    payment_status_group: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> OrderResultListResponse:
    try:
        await get_batch(session, batch_id)
    except BatchValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    rows, total = await list_results(
        session,
        batch_id=batch_id,
        result_status=result_status,
        payment_status_group=payment_status_group,
        limit=min(max(limit, 1), 500),
        offset=max(offset, 0),
    )
    return OrderResultListResponse(
        items=[OrderResultResponse.model_validate(row) for row in rows],
        total=total,
    )


@router.get("/batches/{batch_id}/export.csv")
async def download_csv(
    batch_id: str,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    try:
        batch = await get_batch(session, batch_id)
    except BatchValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not batch.is_final:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="批次尚无最终结果。")
    return Response(
        export_csv(await all_results(session, batch.id)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{batch.id}.csv"'},
    )


@router.get("/batches/{batch_id}/export.xlsx")
async def download_excel(
    batch_id: str,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    try:
        batch = await get_batch(session, batch_id)
    except BatchValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not batch.is_final:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="批次尚无最终结果。")
    return Response(
        export_excel(batch, await all_results(session, batch.id)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{batch.id}.xlsx"'},
    )


@router.get("/batches/{batch_id}/charts", response_model=BatchChartsResponse)
async def batch_charts(
    batch_id: str,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> BatchChartsResponse:
    try:
        batch = await get_batch(session, batch_id)
    except BatchValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    rows = list(
        await session.scalars(
            select(OrderReconciliationResult).where(OrderReconciliationResult.batch_id == batch.id)
        )
    )
    counts = Counter(row.result_status for row in rows)
    matrix = Counter((row.payment_status_group, row.result_status) for row in rows)
    time_series = Counter(
        str((row.payload_json or {}).get("paymentTime") or "")[:10]
        for row in rows
        if (row.payload_json or {}).get("paymentTime")
    )
    channels = Counter(
        str(
            ((row.payload_json or {}).get("remoteOrder") or {}).get("_remote_channel_label")
            or "未匹配远端"
        )
        for row in rows
    )
    return BatchChartsResponse(
        batch_id=batch.id,
        run_version=batch.run_version,
        is_final=batch.is_final,
        result_status_distribution=[
            {"status": key, "count": value} for key, value in sorted(counts.items())
        ],
        payment_status_result_matrix=[
            {"paymentStatus": key[0], "resultStatus": key[1], "count": value}
            for key, value in sorted(matrix.items())
        ],
        time_series=[{"date": key, "count": value} for key, value in sorted(time_series.items())],
        channel_comparison=[
            {"channel": key, "count": value} for key, value in sorted(channels.items())
        ],
    )
