from io import BytesIO

import pytest
from fastapi import UploadFile
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import Base, PaymentPlatform, PaymentTemplateVersion
from packages.domain.services.payment_template_service import detect_payment_template

AELLOPAY_HEADERS = [
    "ID",
    "商户ID",
    "商户订单号",
    "平台订单号",
    "订单金额",
    "费率",
    "手续费",
    "订单状态",
    "订单时间",
    "到账时间",
    "到账金额",
]


def workbook_upload(headers: list[str]) -> UploadFile:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "payin_5047_test"
    worksheet.append(headers)
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    buffer.seek(0)
    return UploadFile(
        filename="aelopay.xlsx",
        file=buffer,
        headers={
            "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        },
    )


@pytest.mark.asyncio
async def test_known_aelopay_header_is_detected() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        platform = PaymentPlatform(
            platform_key="aelopay",
            display_name="aelopay",
            active=True,
        )
        session.add(platform)
        await session.flush()
        session.add(
            PaymentTemplateVersion(
                platform_id=platform.id,
                business_type="payin",
                version=1,
                sheet_name_pattern="^payin_",
                header_signature_json=AELLOPAY_HEADERS,
                column_mapping_json={"merchant_order_no": "商户订单号"},
                success_status_values_json=["成功"],
                match_rules_json=[],
                active=True,
            )
        )
        await session.commit()

        detection = await detect_payment_template(
            session,
            workbook_upload(AELLOPAY_HEADERS),
        )

    assert detection.status == "matched"
    assert detection.header_coverage == 1
    assert detection.template is not None
    assert detection.template.platform_key == "aelopay"
    assert detection.template.business_type == "payin"
    await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_header_does_not_silently_match() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        detection = await detect_payment_template(
            session,
            workbook_upload(["订单", "金额", "时间"]),
        )

    assert detection.status == "unknown"
    assert detection.template is None
    await engine.dispose()
