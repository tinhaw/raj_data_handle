from __future__ import annotations

from datetime import datetime

from packages.common.schemas import ApiSchema


class DataDictionaryEntryResponse(ApiSchema):
    id: int
    source_id: str
    source_display_name: str
    dictionary_type: str
    entry_code: str
    entry_label: str
    active: bool
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime
