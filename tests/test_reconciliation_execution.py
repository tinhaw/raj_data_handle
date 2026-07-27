from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.security import encrypt_credentials
from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    OrderReconciliationResult,
    ReconciliationBatch,
    SourceConfig,
    StoredFileObject,
    StoredFileReference,
)
from packages.domain.services.reconciliation_execution_service import (
    execute_reconciliation_batch,
)
from packages.domain.services.remote_charge_service import ExactSearchResult
from packages.storage import LocalFileStorage


class FakeChargeClient:
    def __init__(self, **_: Any) -> None:
        pass

    async def __aenter__(self) -> FakeChargeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def fetch_all_charge_orders(
        self,
        **_: Any,
    ) -> tuple[list[dict[str, Any]], int]:
        return (
            [
                {
                    "order_num": "merchant-remote-status",
                    "out_trade_no": "platform-remote-status",
                    "amount": "20.00",
                    "status": 0,
                    "create_time": "2026-07-01 13:00:00",
                    "pay_time": "2026-07-01 13:01:00",
                    "_remote_channel_code": "948",
                    "_remote_channel_label": "aelopay(HX)",
                }
            ],
            1,
        )

    async def exact_search(self, **_: Any) -> ExactSearchResult:
        return ExactSearchResult(orders=[], complete=True)


def _write_payment_file(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "payin_test"
    sheet.append(["商户单号（自定义）", "三方单号（自定义）", "订单金额", "订单状态", "订单时间"])
    sheet.append(["merchant-missing", "platform-missing", "10.00", "成功", "2026-07-01 12:00:00"])
    sheet.append(
        [
            "merchant-remote-status",
            "platform-remote-status",
            "20.00",
            "成功",
            "2026-07-01 13:00:00",
        ]
    )
    workbook.save(path)
    workbook.close()


@pytest.mark.asyncio
async def test_executor_persists_confirmed_missing_and_remote_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
        storage_root=tmp_path,
    )
    engine = create_async_engine(configured.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = LocalFileStorage(tmp_path, 10 * 1024 * 1024)
    storage_key = "aa/payment-file"
    payment_path = storage.resolve_path(storage_key)
    payment_path.parent.mkdir(parents=True)
    _write_payment_file(payment_path)

    monkeypatch.setattr(
        "packages.domain.services.reconciliation_execution_service.RajAdminChargeClient",
        FakeChargeClient,
    )
    async with factory() as session:
        source = SourceConfig(
            source_id="rajwin",
            display_name="RajWin",
            base_url="https://admin.example.test",
            enabled=True,
            business_timezone="Asia/Kolkata",
            currency="INR",
            config_version=2,
            credential_version=1,
        )
        source.encrypted_credentials = encrypt_credentials(
            {
                "username": "reader",
                "password": "password",
                "totp_secret": "JBSWY3DPEHPK3PXP",
            },
            source_id=source.source_id,
            credential_version=source.credential_version,
            settings=configured,
        )
        session.add(source)
        file_object = StoredFileObject(
            content_sha256="a" * 64,
            storage_key=storage_key,
            byte_size=payment_path.stat().st_size,
        )
        session.add(file_object)
        await session.flush()
        now = datetime.now(UTC)
        batch = ReconciliationBatch(
            source_id="rajwin",
            source_display_name="RajWin",
            source_config_version=2,
            source_business_timezone="Asia/Kolkata",
            source_currency="INR",
            business_type="payin",
            status="queued",
            uploaded_file_name="payments.xlsx",
            uploaded_file_sha256="a" * 64,
            parameters_json={
                "selectedChannels": [
                    {"code": "948", "label": "aelopay(HX)", "platformKey": "aelopay"}
                ],
                "paymentColumnMapping": {
                    "merchant_order_no": "商户单号（自定义）",
                    "platform_order_no": "三方单号（自定义）",
                },
                "comparisonWindow": {
                    "start": "2026-07-01 00:00:00",
                    "end": "2026-07-01 23:59:59",
                    "paymentTimeField": "订单时间",
                    "paymentTimezone": "Asia/Kolkata",
                    "remoteTimeField": "create_time",
                    "remoteBusinessTimezone": "Asia/Kolkata",
                    "bufferBeforeHours": 24,
                    "bufferAfterHours": 24,
                },
                "currency": "INR",
                "templateDetection": {
                    "status": "matched",
                    "sourceSheet": "payin_test",
                    "headerRow": 1,
                    "detectedHeaders": [
                        "商户单号（自定义）",
                        "三方单号（自定义）",
                        "订单金额",
                        "订单状态",
                        "订单时间",
                    ],
                    "template": {
                        "platformKey": "aelopay",
                        "businessType": "payin",
                        "columnMapping": {
                            "merchant_order_no": "商户订单号",
                            "platform_order_no": "平台订单号",
                            "amount": "订单金额",
                            "payment_status": "订单状态",
                            "candidate_time_fields": ["订单时间"],
                        },
                        "successStatusValues": ["成功"],
                    },
                },
            },
            progress_json={"stage": "queued"},
            execution_requested_by=1,
            created_by=1,
            result_expires_at=now + timedelta(days=30),
        )
        session.add(batch)
        await session.flush()
        session.add(
            StoredFileReference(
                file_object_id=file_object.id,
                batch_id=batch.id,
                expires_at=now + timedelta(days=3),
            )
        )
        await session.commit()

        await execute_reconciliation_batch(
            session,
            batch=batch,
            storage=storage,
            settings=configured,
        )
        rows = list(
            await session.scalars(
                select(OrderReconciliationResult).where(
                    OrderReconciliationResult.batch_id == batch.id
                )
            )
        )

    assert batch.status == "completed"
    assert batch.is_final is True
    assert {row.result_status for row in rows} == {
        "confirmed_missing",
        "remote_status_not_success",
    }
    assert all(row.is_final for row in rows)
    await engine.dispose()
