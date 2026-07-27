from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import DataDictionaryEntry, SourceConfig
from packages.domain.schemas.data_dictionary import DataDictionaryEntryResponse

PAYMENT_CHANNEL_NAME_DICTIONARY = "payment_channel_name"


class DataDictionarySyncError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DictionarySyncResult:
    active_entries: int
    created_entries: int
    updated_entries: int
    deactivated_entries: int


async def sync_payment_channel_names(
    session: AsyncSession,
    *,
    source_id: str,
    channels: list[dict[str, str]],
) -> DictionarySyncResult:
    normalized: dict[str, str] = {}
    for channel in channels:
        code = str(channel.get("code") or "").strip()
        label = str(channel.get("label") or "").strip()
        if not code or not label:
            raise DataDictionarySyncError("支付渠道名称字典包含空 ID 或名称。")
        previous = normalized.get(code)
        if previous is not None and previous != label:
            raise DataDictionarySyncError("支付渠道名称字典中同一 ID 对应多个名称。")
        normalized[code] = label
    if not normalized:
        raise DataDictionarySyncError("支付渠道名称字典为空。")

    existing = list(
        await session.scalars(
            select(DataDictionaryEntry).where(
                DataDictionaryEntry.source_id == source_id,
                DataDictionaryEntry.dictionary_type == PAYMENT_CHANNEL_NAME_DICTIONARY,
            )
        )
    )
    existing_by_code = {entry.entry_code: entry for entry in existing}
    now = datetime.now(UTC)
    created = 0
    updated = 0
    deactivated = 0

    for code, label in normalized.items():
        entry = existing_by_code.pop(code, None)
        if entry is None:
            session.add(
                DataDictionaryEntry(
                    source_id=source_id,
                    dictionary_type=PAYMENT_CHANNEL_NAME_DICTIONARY,
                    entry_code=code,
                    entry_label=label,
                    active=True,
                    first_seen_at=now,
                    last_seen_at=now,
                    updated_at=now,
                )
            )
            created += 1
            continue
        changed = entry.entry_label != label or not entry.active
        entry.entry_label = label
        entry.active = True
        entry.last_seen_at = now
        entry.updated_at = now
        if changed:
            updated += 1

    for entry in existing_by_code.values():
        if entry.active:
            entry.active = False
            entry.updated_at = now
            deactivated += 1

    await session.flush()
    return DictionarySyncResult(
        active_entries=len(normalized),
        created_entries=created,
        updated_entries=updated,
        deactivated_entries=deactivated,
    )


async def list_payment_channel_names(
    session: AsyncSession,
    *,
    source_id: str | None = None,
    active: bool | None = None,
) -> list[DataDictionaryEntryResponse]:
    statement = (
        select(DataDictionaryEntry, SourceConfig)
        .join(SourceConfig, SourceConfig.source_id == DataDictionaryEntry.source_id)
        .where(
            DataDictionaryEntry.dictionary_type == PAYMENT_CHANNEL_NAME_DICTIONARY,
        )
        .order_by(
            SourceConfig.display_name,
            DataDictionaryEntry.entry_label,
            DataDictionaryEntry.entry_code,
        )
    )
    if source_id:
        statement = statement.where(DataDictionaryEntry.source_id == source_id)
    if active is not None:
        statement = statement.where(DataDictionaryEntry.active.is_(active))
    rows = (await session.execute(statement)).all()
    return [
        DataDictionaryEntryResponse(
            id=entry.id,
            source_id=entry.source_id,
            source_display_name=source.display_name,
            dictionary_type=entry.dictionary_type,
            entry_code=entry.entry_code,
            entry_label=entry.entry_label,
            active=entry.active,
            first_seen_at=entry.first_seen_at,
            last_seen_at=entry.last_seen_at,
            updated_at=entry.updated_at,
        )
        for entry, source in rows
    ]
