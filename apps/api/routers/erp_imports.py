"""Local ERP daily-ledger import APIs; these never call remote systems."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_context, require_admin
from packages.common.database import get_db_session
from packages.domain.schemas.erp_import import (
    ErpImportCommitRequest,
    ErpImportCommitResponse,
    ErpImportJobResponse,
    ErpImportPreviewResponse,
    ErpPastePreviewRequest,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.erp_import_service import (
    MAX_IMPORT_BYTES,
    ErpImportConflictError,
    ErpImportError,
    ErpImportNotFoundError,
    commit_erp_import_job,
    get_erp_import_job,
    list_erp_import_jobs,
    preview_erp_excel_import,
    preview_erp_paste_import,
)

router = APIRouter(prefix="/erp/imports", tags=["erp-imports"])


def _api_error(exc: ErpImportError) -> HTTPException:
    if isinstance(exc, ErpImportNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ErpImportConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


async def _read_upload(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_IMPORT_BYTES:
                raise ErpImportError("Excel 文件超过 10 MB 限制。")
            chunks.append(chunk)
    finally:
        await upload.close()
    return b"".join(chunks)


@router.get("", response_model=list[ErpImportJobResponse])
async def get_import_jobs(
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[ErpImportJobResponse]:
    return await list_erp_import_jobs(session)


@router.post("/paste/preview", response_model=ErpImportPreviewResponse)
async def post_paste_preview(
    payload: ErpPastePreviewRequest,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpImportPreviewResponse:
    try:
        return await preview_erp_paste_import(
            session,
            text=payload.text,
            operator_line_id=payload.operator_line_id,
            conflict_strategy=payload.conflict_strategy,
            business_year=payload.business_year,
            actor_user_id=auth.user.id,
        )
    except ErpImportError as exc:
        raise _api_error(exc) from exc


@router.post("/excel/preview", response_model=ErpImportPreviewResponse)
async def post_excel_preview(
    file: UploadFile = File(...),
    operator_line_id: str = Form(...),
    conflict_strategy: str = Form("SKIP_EXISTING"),
    business_year: int | None = Form(None),
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpImportPreviewResponse:
    try:
        return await preview_erp_excel_import(
            session,
            content=await _read_upload(file),
            original_filename=file.filename or "ledger-import.xlsx",
            operator_line_id=operator_line_id,
            conflict_strategy=conflict_strategy,
            business_year=business_year,
            actor_user_id=auth.user.id,
        )
    except ErpImportError as exc:
        raise _api_error(exc) from exc


@router.get("/{job_id}", response_model=ErpImportPreviewResponse)
async def get_import_job(
    job_id: str,
    _: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db_session),
) -> ErpImportPreviewResponse:
    try:
        return await get_erp_import_job(session, job_id=job_id)
    except ErpImportError as exc:
        raise _api_error(exc) from exc


@router.post("/{job_id}/commit", response_model=ErpImportCommitResponse)
async def post_import_commit(
    job_id: str,
    payload: ErpImportCommitRequest | None = None,
    auth: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErpImportCommitResponse:
    try:
        return await commit_erp_import_job(
            session,
            job_id=job_id,
            conflict_strategy=payload.conflict_strategy if payload else None,
            actor_user_id=auth.user.id,
        )
    except ErpImportError as exc:
        raise _api_error(exc) from exc
