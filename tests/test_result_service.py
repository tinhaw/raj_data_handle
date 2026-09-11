from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import Base, OrderReconciliationResult
from packages.domain.services.result_service import all_results, export_csv


@pytest.mark.asyncio
async def test_all_results_can_export_only_confirmed_missing_rows() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    started_at = datetime(2026, 7, 28, tzinfo=UTC)

    def result(
        *,
        row_id: str,
        batch_id: str,
        order_group_id: str,
        result_status: str,
        platform_order_no: str,
        offset: int,
    ) -> OrderReconciliationResult:
        return OrderReconciliationResult(
            id=row_id,
            batch_id=batch_id,
            order_group_id=order_group_id,
            result_status=result_status,
            payment_status_raw="success",
            payment_status_group="success",
            platform_order_no=platform_order_no,
            payload_json={"currency": "INR"},
            is_final=True,
            created_at=started_at + timedelta(seconds=offset),
        )

    async with factory() as session:
        session.add_all(
            [
                result(
                    row_id="result-1",
                    batch_id="batch-1",
                    order_group_id="group-1",
                    result_status="confirmed_missing",
                    platform_order_no="platform-missing-1",
                    offset=1,
                ),
                result(
                    row_id="result-2",
                    batch_id="batch-1",
                    order_group_id="group-2",
                    result_status="matched",
                    platform_order_no="platform-matched",
                    offset=2,
                ),
                result(
                    row_id="result-3",
                    batch_id="batch-1",
                    order_group_id="group-3",
                    result_status="confirmed_missing",
                    platform_order_no="platform-missing-2",
                    offset=3,
                ),
                result(
                    row_id="result-4",
                    batch_id="batch-2",
                    order_group_id="group-4",
                    result_status="confirmed_missing",
                    platform_order_no="other-batch-missing",
                    offset=4,
                ),
            ]
        )
        await session.commit()

        rows = await all_results(
            session,
            "batch-1",
            result_status="confirmed_missing",
        )

    assert [row.platform_order_no for row in rows] == [
        "platform-missing-1",
        "platform-missing-2",
    ]
    exported = export_csv(rows).decode("utf-8-sig")
    assert "platform-missing-1" in exported
    assert "platform-missing-2" in exported
    assert "platform-matched" not in exported
    assert "other-batch-missing" not in exported
    await engine.dispose()
