from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import (
    ChargeOrderSnapshot,
    ReconciliationBatch,
    SecurityAuditLog,
    SpinOrderSnapshot,
    StoredFileObject,
    StoredFileReference,
    WithdrawOrderSnapshot,
)
from packages.domain.services.system_setting_service import get_retention_settings
from packages.storage.local import LocalFileStorage


def _is_missing_order_snapshot_table(error: OperationalError | ProgrammingError) -> bool:
    message = str(error).lower()
    return (
        "withdraw_order_snapshots" in message
        or "charge_order_snapshots" in message
        or "spin_order_snapshots" in message
    ) and (
        "does not exist" in message or "no such table" in message
    )


async def _cleanup_expired_withdraw_snapshots(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    """Remove old local-only withdrawal snapshots after the configured retention.

    This runs before the rest of the retention transaction so a pre-0006
    deployment can roll back just this optional step and still clean files and
    reconciliation data normally.
    """

    retention = await get_retention_settings(session)
    cutoff = now - timedelta(days=retention.remote_cache_retention_days)
    try:
        result = await session.execute(
            delete(WithdrawOrderSnapshot).where(WithdrawOrderSnapshot.synced_at < cutoff)
        )
        return int(result.rowcount or 0)
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_order_snapshot_table(exc):
            raise
        await session.rollback()
        return 0


async def _cleanup_expired_charge_snapshots(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    retention = await get_retention_settings(session)
    cutoff = now - timedelta(days=retention.remote_cache_retention_days)
    try:
        result = await session.execute(
            delete(ChargeOrderSnapshot).where(ChargeOrderSnapshot.synced_at < cutoff)
        )
        return int(result.rowcount or 0)
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_order_snapshot_table(exc):
            raise
        await session.rollback()
        return 0


async def _cleanup_expired_spin_snapshots(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    retention = await get_retention_settings(session)
    cutoff = now - timedelta(days=retention.remote_cache_retention_days)
    try:
        result = await session.execute(
            delete(SpinOrderSnapshot).where(SpinOrderSnapshot.synced_at < cutoff)
        )
        return int(result.rowcount or 0)
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_order_snapshot_table(exc):
            raise
        await session.rollback()
        return 0


async def cleanup_expired_data(
    session: AsyncSession,
    *,
    storage: LocalFileStorage,
    now: datetime | None = None,
) -> dict[str, int]:
    cleanup_time = now or datetime.now(UTC)
    deleted_withdraw_order_snapshots = await _cleanup_expired_withdraw_snapshots(
        session,
        now=cleanup_time,
    )
    deleted_charge_order_snapshots = await _cleanup_expired_charge_snapshots(
        session,
        now=cleanup_time,
    )
    deleted_spin_order_snapshots = await _cleanup_expired_spin_snapshots(
        session,
        now=cleanup_time,
    )
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
        "deletedWithdrawOrderSnapshots": deleted_withdraw_order_snapshots,
        "deletedChargeOrderSnapshots": deleted_charge_order_snapshots,
        "deletedSpinOrderSnapshots": deleted_spin_order_snapshots,
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
