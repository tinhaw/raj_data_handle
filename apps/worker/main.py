from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from packages.common.database import AsyncSessionLocal
from packages.common.settings import get_settings
from packages.domain.models import ReconciliationBatch
from packages.domain.services.batch_service import transition_batch
from packages.domain.services.batch_state import TERMINAL_BATCH_STATUSES
from packages.domain.services.reconciliation_execution_service import (
    execute_reconciliation_batch,
)
from packages.domain.services.retention_cleanup_service import cleanup_expired_data
from packages.storage import LocalFileStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("raj-worker")


async def process_next_batch(storage: LocalFileStorage) -> bool:
    async with AsyncSessionLocal() as session:
        batch = await session.scalar(
            select(ReconciliationBatch)
            .where(ReconciliationBatch.status == "queued")
            .order_by(ReconciliationBatch.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if batch is None:
            return False
        try:
            await execute_reconciliation_batch(
                session,
                batch=batch,
                storage=storage,
            )
            logger.info("batch execution finished batch_id=%s status=%s", batch.id, batch.status)
        except Exception:
            await session.rollback()
            await session.refresh(batch)
            logger.error("unexpected batch execution failure batch_id=%s", batch.id)
            if batch.status not in TERMINAL_BATCH_STATUSES:
                batch.error_category = "internal_error"
                batch.error_message = "执行器发生内部错误，未发布确认遗漏结论。"
                try:
                    await transition_batch(
                        session,
                        batch=batch,
                        to_status="failed",
                        actor_user_id=None,
                    )
                except Exception:
                    await session.rollback()
                    logger.error("failed to persist terminal state batch_id=%s", batch.id)
        return True


async def run() -> None:
    settings = get_settings()
    storage = LocalFileStorage(settings.storage_root, settings.upload_max_bytes)
    logger.info("reconciliation worker started")
    next_cleanup_at = 0.0
    while True:
        try:
            if asyncio.get_running_loop().time() >= next_cleanup_at:
                async with AsyncSessionLocal() as session:
                    counts = await cleanup_expired_data(session, storage=storage)
                if any(counts.values()):
                    logger.info(
                        "retention cleanup finished references=%s files=%s batches=%s",
                        counts["expiredFileReferences"],
                        counts["deletedFileObjects"],
                        counts["deletedBatches"],
                    )
                next_cleanup_at = asyncio.get_running_loop().time() + 1800
            processed = await process_next_batch(storage)
            if not processed:
                await asyncio.sleep(2)
        except SQLAlchemyError:
            logger.warning("database schema or connection is not ready; retrying later")
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(run())
