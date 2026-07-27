from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import (
    ReconciliationBatch,
    SecurityAuditLog,
    StoredFileObject,
    StoredFileReference,
)
from packages.storage.local import LocalFileStorage


async def cleanup_expired_data(
    session: AsyncSession,
    *,
    storage: LocalFileStorage,
    now: datetime | None = None,
) -> dict[str, int]:
    cleanup_time = now or datetime.now(UTC)
    expired_references = list(
        await session.scalars(
            select(StoredFileReference).where(StoredFileReference.expires_at <= cleanup_time)
        )
    )
    if expired_references:
        await session.execute(
            delete(StoredFileReference).where(
                StoredFileReference.id.in_([item.id for item in expired_references])
            )
        )

    expired_batch_ids = list(
        await session.scalars(
            select(ReconciliationBatch.id).where(
                ReconciliationBatch.result_expires_at <= cleanup_time
            )
        )
    )
    if expired_batch_ids:
        await session.execute(
            delete(ReconciliationBatch).where(ReconciliationBatch.id.in_(expired_batch_ids))
        )
    await session.flush()

    orphaned_files = list(
        await session.scalars(
            select(StoredFileObject).where(
                StoredFileObject.deleted_at.is_(None),
                ~exists().where(StoredFileReference.file_object_id == StoredFileObject.id),
            )
        )
    )
    deleted_files = 0
    for file_object in orphaned_files:
        await storage.delete(file_object.storage_key)
        file_object.deleted_at = cleanup_time
        deleted_files += 1

    counts = {
        "expiredFileReferences": len(expired_references),
        "deletedFileObjects": deleted_files,
        "deletedBatches": len(expired_batch_ids),
    }
    if any(counts.values()):
        session.add(
            SecurityAuditLog(
                action="retention.cleanup",
                result="success",
                metadata_json=counts,
            )
        )
    await session.commit()
    return counts
