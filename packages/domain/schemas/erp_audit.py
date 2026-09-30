"""Append-only local ERP audit-log contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from packages.common.schemas import ApiSchema


class ErpAuditLogEntry(ApiSchema):
    id: str
    action: str
    actor_user_id: int | None
    actor_display_name: str | None
    target_type: str | None
    target_id: str | None
    request_id: str | None
    result: str
    metadata: dict[str, Any]
    created_at: datetime


class ErpAuditLogList(ApiSchema):
    items: list[ErpAuditLogEntry]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
