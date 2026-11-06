from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import AppUser, Base
from packages.domain.schemas.erp_operator import (
    ErpDeliveryLineCreateRequest,
    ErpOperatorCreateRequest,
)
from packages.domain.services.erp_balance_service import list_erp_daily_balances
from packages.domain.services.erp_import_service import (
    commit_erp_import_job,
    preview_erp_excel_import,
    preview_erp_paste_import,
)
from packages.domain.services.erp_operator_service import (
    create_erp_operator,
    create_erp_operator_line,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _actor_id(session) -> int:
    actor = AppUser(
        username="erp-import-admin",
        username_normalized="erp-import-admin",
        password_hash="not-used-in-this-test",
        display_name="ERP Import Admin",
        role="admin",
    )
    session.add(actor)
    await session.commit()
    return actor.id


@pytest.mark.asyncio
async def test_paste_import_previews_then_commits_to_the_local_ledger() -> None:
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            actor_id = await _actor_id(session)
            operator = await create_erp_operator(
                session,
                request=ErpOperatorCreateRequest(name="Raj Media"),
                actor_user_id=actor_id,
            )
            line = await create_erp_operator_line(
                session,
                operator_id=operator.id,
                request=ErpDeliveryLineCreateRequest(name="USDT Line", asset="USDT"),
                actor_user_id=actor_id,
            )
            preview = await preview_erp_paste_import(
                session,
                text=(
                    "业务日期\t期初余额\t转U\t消耗\t汇损费率\t服务费率\n"
                    "2026-08-01\t100\t10\t2\t0\t0"
                ),
                operator_line_id=line.id,
                conflict_strategy="SKIP_EXISTING",
                business_year=2026,
                actor_user_id=actor_id,
            )
            assert preview.job.status == "PREVIEW_READY"
            assert preview.job.valid_rows == 1
            assert preview.rows[0].action == "CREATE"
            assert preview.rows[0].normalized is not None

            result = await commit_erp_import_job(
                session,
                job_id=preview.job.id,
                conflict_strategy=None,
                actor_user_id=actor_id,
            )
            assert result.job.status == "SUCCEEDED"
            assert (result.created, result.updated, result.skipped) == (1, 0, 0)

            ledger = await list_erp_daily_balances(
                session,
                operator_line_id=line.id,
                month="2026-08",
            )
            assert len(ledger.records) == 1
            assert ledger.records[0].business_date == date(2026, 8, 1)
            assert ledger.records[0].closing_balance == Decimal("108.00000000")
            assert ledger.records[0].source_type == "IMPORT"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_excel_import_exposes_source_artifact_metadata_without_storage_key() -> None:
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            actor_id = await _actor_id(session)
            operator = await create_erp_operator(
                session,
                request=ErpOperatorCreateRequest(name="Artifact Media"),
                actor_user_id=actor_id,
            )
            line = await create_erp_operator_line(
                session,
                operator_id=operator.id,
                request=ErpDeliveryLineCreateRequest(name="USDT", asset="USDT"),
                actor_user_id=actor_id,
            )
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["业务日期", "期初结余", "转U", "消耗"])
            sheet.append(["2026-08-18", 100, 20, 5])
            buffer = BytesIO()
            workbook.save(buffer)
            preview = await preview_erp_excel_import(
                session,
                content=buffer.getvalue(),
                original_filename="ledger.xlsx",
                operator_line_id=line.id,
                conflict_strategy="SKIP_EXISTING",
                business_year=2026,
                actor_user_id=actor_id,
                source_storage_key="ab/test-file",
                source_size_bytes=len(buffer.getvalue()),
            )
            assert preview.job.source_available
            assert preview.job.source_size_bytes == len(buffer.getvalue())
            assert "storage" not in preview.job.model_dump_json()
    finally:
        await engine.dispose()
