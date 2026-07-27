from __future__ import annotations

from datetime import datetime
from typing import Any

from packages.common.schemas import ApiSchema


class NotificationResponse(ApiSchema):
    id: str
    event_type: str
    batch_id: str
    run_version: int
    title: str
    summary_json: dict[str, Any]
    created_at: datetime
    delivered_at: datetime | None
    read_at: datetime | None
