"""Local ERP daily-ledger import APIs; these never call remote systems."""

from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_file_storage, require_erp_permission
from packages.common.database import get_db_session
from packages.domain.models import ErpImportJob
from packages.domain.schemas.erp_import import (
    ErpImportCommitRequest,
    ErpImportCommitResponse,
    ErpImportJobResponse,
    ErpImportPreviewResponse,
    ErpImportRowResponse,
    ErpPastePreviewRequest,
)
from packages.domain.services.auth_service import AuthContext
from packages.domain.services.erp_access_service import (
    ERP_PERMISSION_IMPORT,
    ErpScopePermissionError,
    assert_erp_operator_scope,
    resolve_erp_operator_scope,
)
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
from packages.domain.services.erp_operator_service import get_erp_operator_line
from packages.storage import LocalFileStorage

router = APIRouter(prefix="/erp/imports", tags=["erp-imports"])


def _api_error(exc: ErpImportError) -> HTTPException:
    if isinstance(exc, ErpImportNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ErpImportConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


async def _assert_line_scope(session: AsyncSession, *, user_id: int, line_id: str) -> None:
    line = await get_erp_operator_line(session, line_id=line_id)
    await assert_erp_operator_scope(session, user_id=user_id, operator_id=line.operator_id)


async def _assert_job_scope(
    session: AsyncSession, *, user_id: int, job_id: str
) -> ErpImportPreviewResponse:
    preview = await get_erp_import_job(session, job_id=job_id)
    for line_id in {row.operator_line_id for row in preview.rows if row.operator_line_id}:
        await _assert_line_scope(session, user_id=user_id, line_id=line_id)
    return preview


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


def _workbook_response(workbook: Workbook, filename: str) -> Response:
    buffer = BytesIO()
    workbook.save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/template")
async def get_import_template(
    _: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_IMPORT)),
) -> Response:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "日结导入模板"
    sheet.append(
        [
            "业务日期",
            "期初结余",
            "转U",
            "消耗",
            "欺诈损失",
            "欺诈扣减来源",
            "汇损费率",
            "汇损基数",
            "汇损模式",
            "汇损金额",
            "服务费率",
            "服务费基数",
            "服务费模式",
            "服务费金额",
            "回流",
            "退款",
            "其他扣减",
            "其他原因",
            "备注",
        ]
    )
    sheet.append(
        [
            "2026-08-18",
            0,
            0,
            0,
            0,
            "转U",
            0,
            "转U",
            "自动",
            None,
            0,
            "转U",
            "自动",
            None,
            0,
            0,
            0,
            None,
            None,
        ]
    )
    sheet.freeze_panes = "A2"
    return _workbook_response(workbook, "erp-daily-balance-template.xlsx")


@router.get("", response_model=list[ErpImportJobResponse])
async def get_import_jobs(
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_IMPORT)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ErpImportJobResponse]:
    return await list_erp_import_jobs(
        session,
        operator_ids=await resolve_erp_operator_scope(session, user_id=auth.user.id),
    )


@router.post("/paste/preview", response_model=ErpImportPreviewResponse)
async def post_paste_preview(
    payload: ErpPastePreviewRequest,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_IMPORT)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpImportPreviewResponse:
    try:
        await _assert_line_scope(session, user_id=auth.user.id, line_id=payload.operator_line_id)
        return await preview_erp_paste_import(
            session,
            text=payload.text,
            operator_line_id=payload.operator_line_id,
            conflict_strategy=payload.conflict_strategy,
            business_year=payload.business_year,
            actor_user_id=auth.user.id,
        )
    except ErpScopePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ErpImportError as exc:
        raise _api_error(exc) from exc


@router.post("/excel/preview", response_model=ErpImportPreviewResponse)
async def post_excel_preview(
    file: UploadFile = File(...),
    operator_line_id: str = Form(...),
    conflict_strategy: str = Form("SKIP_EXISTING"),
    business_year: int | None = Form(None),
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_IMPORT)),
    session: AsyncSession = Depends(get_db_session),
    storage: LocalFileStorage = Depends(get_file_storage),
) -> ErpImportPreviewResponse:
    try:
        await _assert_line_scope(session, user_id=auth.user.id, line_id=operator_line_id)
        stored = await storage.store_upload(file)
        return await preview_erp_excel_import(
            session,
            content=await _read_upload(file),
            original_filename=file.filename or "ledger-import.xlsx",
            operator_line_id=operator_line_id,
            conflict_strategy=conflict_strategy,
            business_year=business_year,
            actor_user_id=auth.user.id,
            source_storage_key=stored.storage_key,
            source_size_bytes=stored.byte_size,
        )
    except ErpScopePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ErpImportError as exc:
        raise _api_error(exc) from exc


@router.get("/{job_id}", response_model=ErpImportPreviewResponse)
async def get_import_job(
    job_id: str,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_IMPORT)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpImportPreviewResponse:
    try:
        return await _assert_job_scope(session, user_id=auth.user.id, job_id=job_id)
    except ErpScopePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ErpImportError as exc:
        raise _api_error(exc) from exc


@router.get("/{job_id}/rows", response_model=list[ErpImportRowResponse])
async def get_import_job_rows(
    job_id: str,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_IMPORT)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ErpImportRowResponse]:
    try:
        return (await _assert_job_scope(session, user_id=auth.user.id, job_id=job_id)).rows
    except ErpScopePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ErpImportError as exc:
        raise _api_error(exc) from exc


@router.get("/{job_id}/source")
async def download_import_source(
    job_id: str,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_IMPORT)),
    session: AsyncSession = Depends(get_db_session),
    storage: LocalFileStorage = Depends(get_file_storage),
) -> FileResponse:
    try:
        await _assert_job_scope(session, user_id=auth.user.id, job_id=job_id)
        job = await session.get(ErpImportJob, job_id)
        if job is None or not job.source_storage_key:
            raise ErpImportNotFoundError("该导入批次没有可下载的源文件。")
        return FileResponse(
            storage.resolve_path(job.source_storage_key),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=job.original_filename or f"erp-import-{job_id}.xlsx",
        )
    except ErpScopePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ErpImportError as exc:
        raise _api_error(exc) from exc


@router.get("/{job_id}/error-report")
async def download_import_error_report(
    job_id: str,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_IMPORT)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    try:
        preview = await _assert_job_scope(session, user_id=auth.user.id, job_id=job_id)
    except ErpScopePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ErpImportError as exc:
        raise _api_error(exc) from exc
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "导入错误"
    sheet.append(["工作表", "行号", "业务日期", "级别", "错误代码", "错误说明", "预期动作"])
    for row in preview.rows:
        if row.severity == "OK":
            continue
        sheet.append(
            [
                row.source_sheet,
                row.source_row,
                row.business_date,
                row.severity,
                row.error_code,
                row.error_message,
                row.action,
            ]
        )
    return _workbook_response(workbook, f"erp-import-errors-{job_id}.xlsx")


@router.post("/{job_id}/commit", response_model=ErpImportCommitResponse)
async def post_import_commit(
    job_id: str,
    payload: ErpImportCommitRequest | None = None,
    auth: AuthContext = Depends(require_erp_permission(ERP_PERMISSION_IMPORT)),
    session: AsyncSession = Depends(get_db_session),
) -> ErpImportCommitResponse:
    try:
        await _assert_job_scope(session, user_id=auth.user.id, job_id=job_id)
        return await commit_erp_import_job(
            session,
            job_id=job_id,
            conflict_strategy=payload.conflict_strategy if payload else None,
            actor_user_id=auth.user.id,
        )
    except ErpScopePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ErpImportError as exc:
        raise _api_error(exc) from exc
