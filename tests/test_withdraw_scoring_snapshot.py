from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import (
    Base,
    SourceConfig,
    SystemRetentionSetting,
    WithdrawOrderSnapshot,
    WithdrawScoringSnapshot,
)
from packages.domain.services.retention_cleanup_service import cleanup_expired_data
from packages.storage.local import LocalFileStorage


async def _database() -> tuple[object, async_sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _source() -> SourceConfig:
    return SourceConfig(
        source_id="rajwin",
        display_name="RajWin",
        enabled=True,
    )


def _withdraw_order(*, synced_at: datetime) -> WithdrawOrderSnapshot:
    return WithdrawOrderSnapshot(
        source_id="rajwin",
        remote_order_id="case-1",
        uid="10001",
        status="paid",
        synced_at=synced_at,
    )


def _scoring_snapshot(*, synced_at: datetime) -> WithdrawScoringSnapshot:
    return WithdrawScoringSnapshot(
        source_id="rajwin",
        withdraw_order_id="case-1",
        global_hard_condition="已通过",
        scenario_review="未命中",
        score_review="-35",
        decision_stage="评分审核",
        final_review_suggestion="出款",
        operation_result="出款成功",
        review_summary="用户渠道：Wheel +5",
        current_status="已提交代付 (1)",
        synced_at=synced_at,
    )


@pytest.mark.asyncio
async def test_scoring_snapshot_requires_master_withdrawal_and_excludes_master_fields() -> None:
    engine, factory = await _database()
    now = datetime(2026, 8, 1, tzinfo=UTC)
    async with factory() as session:
        session.add_all(
            [_source(), _withdraw_order(synced_at=now), _scoring_snapshot(synced_at=now)]
        )
        await session.commit()

        master = await session.scalar(
            select(WithdrawOrderSnapshot).where(WithdrawOrderSnapshot.remote_order_id == "case-1")
        )
        assert master is not None
        await session.delete(master)
        await session.commit()
        assert await session.scalar(select(WithdrawScoringSnapshot)) is None

        session.add(
            WithdrawScoringSnapshot(
                source_id="rajwin",
                withdraw_order_id="score-only-case",
                score_review="15",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    columns = WithdrawScoringSnapshot.__table__.columns
    assert "uid" not in columns
    assert "amount" not in columns
    assert "channel" not in columns
    await engine.dispose()


@pytest.mark.asyncio
async def test_retention_removes_expired_scoring_supplement_without_removing_master(
    tmp_path: Path,
) -> None:
    engine, factory = await _database()
    now = datetime(2026, 8, 1, tzinfo=UTC)
    async with factory() as session:
        session.add_all(
            [
                _source(),
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                ),
                _withdraw_order(synced_at=now),
                _scoring_snapshot(synced_at=now - timedelta(days=31)),
            ]
        )
        await session.commit()

        result = await cleanup_expired_data(
            session,
            storage=LocalFileStorage(tmp_path / "storage", max_bytes=1024),
            now=now,
        )
        assert result["deletedWithdrawScoringSnapshots"] == 1
        assert await session.scalar(select(WithdrawScoringSnapshot)) is None
        assert await session.scalar(select(WithdrawOrderSnapshot)) is not None

    await engine.dispose()
