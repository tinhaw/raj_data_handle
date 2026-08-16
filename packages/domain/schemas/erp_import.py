"""Contracts for local ERP daily-ledger import previews and commits."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from packages.common.schemas import ApiSchema
from packages.domain.schemas.erp_balance import ErpDailyBalanceWriteRequest

ErpImportConflictStrategy = Literal["SKIP_EXISTING", "UPDATE_DRAFT", "REJECT_ON_CONFLICT"]
ErpImportStatus = Literal["PREVIEW_READY", "SUCCEEDED"]
ErpImportSeverity = Literal["OK", "WARNING", "ERROR"]


class ErpPastePreviewRequest(ApiSchema):
    text: str = Field(min_length=1, max_length=1_000_000)
    operator_line_id: str = Field(min_length=1, max_length=36)
    conflict_strategy: ErpImportConflictStrategy = "SKIP_EXISTING"
    business_year: int | None = Field(default=None, ge=2000, le=2200)


class ErpImportCommitRequest(ApiSchema):
    conflict_strategy: ErpImportConflictStrategy | None = None


class ErpImportJobResponse(ApiSchema):
    id: str
    source_type: str
    original_filename: str | None
    file_sha256: str | None
    status: ErpImportStatus
    conflict_strategy: ErpImportConflictStrategy
    total_rows: int
    valid_rows: int
    warning_rows: int
    error_rows: int
    created_at: datetime
    committed_at: datetime | None


class ErpImportRowResponse(ApiSchema):
    id: str
    source_sheet: str | None
    source_row: int | None
    source_json: dict[str, Any]
    operator_line_id: str | None
    business_date: date | None
    severity: ErpImportSeverity
    error_code: str | None
    error_message: str | None
    action: str | None
    target_daily_balance_id: str | None
    normalized: ErpDailyBalanceWriteRequest | None


class ErpImportPreviewResponse(ApiSchema):
    job: ErpImportJobResponse
    rows: list[ErpImportRowResponse]


class ErpImportCommitResponse(ApiSchema):
    job: ErpImportJobResponse
    created: int
    updated: int
    skipped: int
