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
from packages.domain.services.charge_order_refresh_service import (
    run_due_charge_order_refreshes,
)
from packages.domain.services.reconciliation_execution_service import (
    execute_reconciliation_batch,
)
from packages.domain.services.retention_cleanup_service import cleanup_expired_data
from packages.domain.services.withdraw_order_refresh_service import (
    run_due_withdraw_order_refreshes,
)
from packages.storage import LocalFileStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("raj-worker")

# The worker owns the remote read loop.  The short poll makes an administrator
# initiated refresh prompt without treating the interval itself as a client-side
# timer.  The refresh service claims source rows with a durable lease, so this
# remains safe if a second worker is ever introduced.
WITHDRAW_ORDER_REFRESH_POLL_SECONDS = 30


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


async def process_due_withdraw_order_refreshes() -> int:
    """Run one source-serial withdrawal refresh cycle and return its outcome count."""

    async with AsyncSessionLocal() as session:
        outcomes = await run_due_withdraw_order_refreshes(session)
    return len(outcomes)


async def process_due_charge_order_refreshes() -> int:
    async with AsyncSessionLocal() as session:
        outcomes = await run_due_charge_order_refreshes(session)
    return len(outcomes)


async def run_due_withdraw_order_refresh_cycle() -> None:
    """Run one protected refresh cycle without exposing remote failure details."""

    try:
        refreshed_sources = await process_due_withdraw_order_refreshes()
        if refreshed_sources:
            logger.info(
                "withdraw order refresh cycle processed source_count=%s",
                refreshed_sources,
            )
    except SQLAlchemyError:
        logger.warning("withdraw order refresh schema or database is not ready; retrying later")
    except Exception:
        # The service persists a safe, source-scoped failure state.  Do not
        # log exception text here: errors from remote clients must never
        # accidentally expose credentials, request payloads, or responses.
        logger.warning("withdraw order refresh cycle failed; retrying later")


async def run_due_charge_order_refresh_cycle() -> None:
    try:
        refreshed_sources = await process_due_charge_order_refreshes()
        if refreshed_sources:
            logger.info("charge order refresh cycle processed source_count=%s", refreshed_sources)
    except SQLAlchemyError:
        logger.warning("charge order refresh schema or database is not ready; retrying later")
    except Exception:
        logger.warning("charge order refresh cycle failed; retrying later")


async def run_withdraw_order_refresh_loop() -> None:
    """Keep cached withdrawal orders current without blocking reconciliation work."""

    while True:
        await run_due_withdraw_order_refresh_cycle()
        await asyncio.sleep(WITHDRAW_ORDER_REFRESH_POLL_SECONDS)


async def run_charge_order_refresh_loop() -> None:
    while True:
        await run_due_charge_order_refresh_cycle()
        await asyncio.sleep(WITHDRAW_ORDER_REFRESH_POLL_SECONDS)


async def run() -> None:
    settings = get_settings()
    storage = LocalFileStorage(settings.storage_root, settings.upload_max_bytes)
    logger.info("reconciliation worker started")
    next_cleanup_at = 0.0
    refresh_task = asyncio.create_task(
        run_withdraw_order_refresh_loop(),
        name="withdraw-order-refresh-loop",
    )
    charge_refresh_task = asyncio.create_task(
        run_charge_order_refresh_loop(),
        name="charge-order-refresh-loop",
    )
    try:
        while True:
            try:
                if asyncio.get_running_loop().time() >= next_cleanup_at:
                    async with AsyncSessionLocal() as session:
                        counts = await cleanup_expired_data(session, storage=storage)
                    if any(counts.values()):
                        logger.info(
                            "retention cleanup finished references=%s files=%s batches=%s "
                            "withdraw_order_snapshots=%s charge_order_snapshots=%s",
                            counts["expiredFileReferences"],
                            counts["deletedFileObjects"],
                            counts["deletedBatches"],
                            counts.get("deletedWithdrawOrderSnapshots", 0),
                            counts.get("deletedChargeOrderSnapshots", 0),
                        )
                    next_cleanup_at = asyncio.get_running_loop().time() + 1800
                processed = await process_next_batch(storage)
                if not processed:
                    await asyncio.sleep(2)
            except SQLAlchemyError:
                logger.warning("database schema or connection is not ready; retrying later")
                await asyncio.sleep(30)
    finally:
        refresh_task.cancel()
        charge_refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass
        try:
            await charge_refresh_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(run())
