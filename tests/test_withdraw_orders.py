from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    DataDictionaryEntry,
    SourceConfig,
    SystemRetentionSetting,
    WithdrawOrderSnapshot,
)
from packages.domain.schemas.withdraw_order import (
    WithdrawChannelSummaryRequest,
    WithdrawOrderQueryRequest,
)
from packages.domain.services.remote_withdraw_service import (
    WITHDRAW_EXPORT_COLUMNS,
    parse_withdraw_order_export,
)
from packages.domain.services.withdraw_order_service import (
    query_withdraw_channel_summary,
    query_withdraw_orders,
)


def _settings() -> Settings:
    return Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )


def _workbook_bytes(rows: list[dict[str, object]]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append([*WITHDRAW_EXPORT_COLUMNS, "银行卡号", "手机号", "IFSC", "失败原因"])
    for row in rows:
        worksheet.append(
            [row.get(column) for column in WITHDRAW_EXPORT_COLUMNS]
            + [
                row.get("银行卡号"),
                row.get("手机号"),
                row.get("IFSC"),
                row.get("失败原因"),
            ]
        )
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _export_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "主键": "remote-1",
        "提现uid": "10001",
        "提现订单号": "withdraw-remote-1",
        "用户渠道": "affiliate-a",
        "三方支付订单号": "third-remote-1",
        "支付通道名称": "Channel A",
        "支付通道": "channel-a",
        "提现金额": "100.00",
        "提现手续费": "3.00",
        "到账金额": "97.00",
        "是否首提": "是",
        "状态": "代付成功",
        "创建时间": datetime(2026, 7, 30, 10, 0),
        "提交时间": datetime(2026, 7, 30, 10, 1),
        "修改时间": datetime(2026, 7, 30, 10, 2),
        "审核人": "Operator A",
        "银行卡号": "must-not-copy",
        "手机号": "must-not-copy",
        "IFSC": "must-not-copy",
        "失败原因": "must-not-copy",
    }
    row.update(overrides)
    return row


def test_withdraw_excel_parser_keeps_only_cache_whitelist() -> None:
    orders = parse_withdraw_order_export(_workbook_bytes([_export_row()]))

    assert orders == [
        {
            "remote_order_id": "remote-1",
            "uid": "10001",
            "order_num": "withdraw-remote-1",
            "channel": "affiliate-a",
            "out_trade_no": "third-remote-1",
            "pay_channel_name": "Channel A",
            "pay_channel": "channel-a",
            "amount": "100.00",
            "fee": "3.00",
            "real_amount": "97.00",
            "is_first": "是",
            "status": "3",
            "status_label": "代付成功",
            "create_time": "2026-07-30 10:00:00",
            "submit_time": "2026-07-30 10:01:00",
            "update_time": "2026-07-30 10:02:00",
            "audit_person": "Operator A",
        }
    ]
    for sensitive_key in ("银行卡号", "手机号", "IFSC", "失败原因"):
        assert sensitive_key not in orders[0]


def test_withdraw_excel_parser_keeps_unknown_label_for_source_dictionary_validation() -> None:
    orders = parse_withdraw_order_export(
        _workbook_bytes([_export_row(状态="远端新增状态")])
    )

    # The parser stays schema-focused.  The refresh service will reject this
    # row atomically if the selected source's status dictionary does not map
    # the label, preserving the old cache (covered in refresh tests).
    assert orders[0]["status"] == "远端新增状态"
    assert orders[0]["status_label"] == "远端新增状态"


async def _database() -> tuple[object, async_sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _snapshot(
    remote_order_id: str,
    *,
    pay_channel: str,
    pay_channel_name: str,
    status: str,
    status_label: str,
    amount: str,
    real_amount: str,
    fee: str,
    local_time: datetime,
    audit_admin: str = "Operator A",
) -> WithdrawOrderSnapshot:
    return WithdrawOrderSnapshot(
        source_id="rajwin",
        remote_order_id=remote_order_id,
        uid="10001",
        order_num=f"withdraw-{remote_order_id}",
        out_trade_no=f"third-{remote_order_id}",
        pay_channel=pay_channel,
        pay_channel_name=pay_channel_name,
        amount=amount,
        real_amount=real_amount,
        fee=fee,
        create_time=local_time.strftime("%Y-%m-%d %H:%M:%S"),
        create_time_utc=local_time.replace(tzinfo=UTC),
        # The test's local values are explicitly set below in the caller with
        # their matching UTC timestamp to keep the business-day assertion easy
        # to audit.
        submit_time=(local_time.replace(minute=local_time.minute + 1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        update_time=(local_time.replace(minute=local_time.minute + 2)).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        audit_admin=audit_admin,
        status=status,
        status_label=status_label,
        is_first="是",
        channel="affiliate-a",
    )


def _india_snapshot(
    remote_order_id: str,
    *,
    pay_channel: str,
    pay_channel_name: str,
    status: str,
    status_label: str,
    amount: str,
    real_amount: str,
    fee: str,
    local_time: datetime,
    audit_admin: str = "Operator A",
) -> WithdrawOrderSnapshot:
    snapshot = _snapshot(
        remote_order_id,
        pay_channel=pay_channel,
        pay_channel_name=pay_channel_name,
        status=status,
        status_label=status_label,
        amount=amount,
        real_amount=real_amount,
        fee=fee,
        local_time=local_time,
        audit_admin=audit_admin,
    )
    # Asia/Kolkata is UTC+05:30.  The service groups on this value, not the
    # string displayed by the remote workbook.
    snapshot.create_time_utc = local_time.replace(tzinfo=UTC) - timedelta(hours=5, minutes=30)
    return snapshot


@pytest.mark.asyncio
async def test_withdraw_detail_uses_cached_export_fields_and_filters() -> None:
    engine, factory = await _database()
    now = datetime(2026, 7, 31, 6, 0, tzinfo=UTC)
    async with factory() as session:
        session.add_all(
            [
                SourceConfig(
                    source_id="rajwin",
                    display_name="RajWin",
                    enabled=True,
                    business_timezone="Asia/Kolkata",
                    currency="INR",
                ),
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                ),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type="withdraw_status",
                    entry_code="success-code",
                    entry_label="代付成功",
                    active=True,
                ),
                _india_snapshot(
                    "detail",
                    pay_channel="channel-a",
                    pay_channel_name="Channel A",
                    status="success-code",
                    status_label="代付成功",
                    amount="100.00",
                    real_amount="97.00",
                    fee="3.00",
                    local_time=datetime(2026, 7, 30, 10, 0),
                ),
                _india_snapshot(
                    "other",
                    pay_channel="channel-b",
                    pay_channel_name="Channel B",
                    status="success-code",
                    status_label="代付成功",
                    amount="50.00",
                    real_amount="48.00",
                    fee="2.00",
                    local_time=datetime(2026, 7, 30, 11, 0),
                ),
            ]
        )
        await session.commit()
        result = await query_withdraw_orders(
            session,
            request=WithdrawOrderQueryRequest(
                source_id="rajwin",
                create_time_start="2026-07-30 00:00:00",
                create_time_end="2026-07-30 23:59:59",
                order_num="withdraw-detail",
                out_trade_no="third-detail",
                pay_channel="channel-a",
            ),
            settings=_settings(),
            now=now,
        )

    assert result.total == 1
    assert result.items == [
        {
            "id": "detail",
            "uid": "10001",
            "order_num": "withdraw-detail",
            "out_trade_no": "third-detail",
            "pay_channel_name": "Channel A",
            "pay_channel": "channel-a",
            "amount": "100.00",
            "real_amount": "97.00",
            "fee": "3.00",
            "create_time": "2026-07-30 10:00:00",
            "update_time": "2026-07-30 10:02:00",
            "submit_time": "2026-07-30 10:01:00",
            "audit_admin": "Operator A",
            "status": "success-code",
            "status_label": "代付成功",
            "is_first": "是",
            "channel": "affiliate-a",
        }
    ]
    assert result.channel_dictionary == [
        {"code": "channel-a", "label": "Channel A"},
        {"code": "channel-b", "label": "Channel B"},
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_channel_summary_uses_success_amount_fee_and_daily_denominators() -> None:
    engine, factory = await _database()
    now = datetime(2026, 8, 1, 6, 0, tzinfo=UTC)
    async with factory() as session:
        session.add_all(
            [
                SourceConfig(
                    source_id="rajwin",
                    display_name="RajWin",
                    enabled=True,
                    business_timezone="Asia/Kolkata",
                    currency="INR",
                ),
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                ),
                *[
                    DataDictionaryEntry(
                        source_id="rajwin",
                        dictionary_type="withdraw_status",
                        entry_code=code,
                        entry_label=label,
                        active=True,
                    )
                    for code, label in (
                        ("status-success", "代付成功"),
                        ("status-failed", "代付失败"),
                        ("status-submitted", "已提交代付"),
                        ("status-rejected", "审核拒绝"),
                    )
                ],
                _india_snapshot(
                    "a-success",
                    pay_channel="channel-a",
                    pay_channel_name="Channel A",
                    status="status-success",
                    status_label="代付成功",
                    amount="105.00",
                    real_amount="100.00",
                    fee="5.00",
                    local_time=datetime(2026, 7, 30, 10, 0),
                ),
                _india_snapshot(
                    "a-submitted",
                    pay_channel="channel-a",
                    pay_channel_name="Channel A",
                    status="status-submitted",
                    status_label="已提交代付",
                    amount="55.00",
                    real_amount="0.00",
                    fee="99.00",
                    local_time=datetime(2026, 7, 30, 11, 0),
                ),
                _india_snapshot(
                    "a-failed",
                    pay_channel="channel-a",
                    pay_channel_name="Channel A",
                    status="status-failed",
                    status_label="代付失败",
                    amount="65.00",
                    real_amount="0.00",
                    fee="12.00",
                    local_time=datetime(2026, 7, 30, 12, 0),
                ),
                _india_snapshot(
                    "b-success",
                    pay_channel="channel-b",
                    pay_channel_name="Channel B",
                    status="status-success",
                    status_label="代付成功",
                    amount="307.00",
                    real_amount="300.00",
                    fee="7.00",
                    local_time=datetime(2026, 7, 30, 13, 0),
                ),
                _india_snapshot(
                    "b-rejected",
                    pay_channel="channel-b",
                    pay_channel_name="Channel B",
                    status="status-rejected",
                    status_label="审核拒绝",
                    amount="88.00",
                    real_amount="0.00",
                    fee="88.00",
                    local_time=datetime(2026, 7, 30, 14, 0),
                ),
                _india_snapshot(
                    "c-submitted-only",
                    pay_channel="channel-c",
                    pay_channel_name="Channel C",
                    status="status-submitted",
                    status_label="已提交代付",
                    amount="20.00",
                    real_amount="0.00",
                    fee="20.00",
                    local_time=datetime(2026, 7, 31, 10, 0),
                ),
            ]
        )
        await session.commit()
        result = await query_withdraw_channel_summary(
            session,
            request=WithdrawChannelSummaryRequest(
                source_id="rajwin",
                create_time_start="2026-07-30 00:00:00",
                create_time_end="2026-07-31 23:59:59",
                page_size=100,
            ),
            settings=_settings(),
            now=now,
        )
        filtered = await query_withdraw_channel_summary(
            session,
            request=WithdrawChannelSummaryRequest(
                source_id="rajwin",
                create_time_start="2026-07-30 00:00:00",
                create_time_end="2026-07-31 23:59:59",
                pay_channel="channel-a",
                page_size=100,
            ),
            settings=_settings(),
            now=now,
        )

    rows = {(item["date"], item["pay_channel"]): item for item in result.items}
    assert rows[("2026-07-30", "channel-a")] == {
        "date": "2026-07-30",
        "pay_channel": "channel-a",
        "pay_channel_name": "Channel A",
        "order_count": 3,
        "successful_order_count": 1,
        "successful_amount": "100.00",
        "successful_fee": "5.00",
        "failed_order_count": 1,
        "submitted_order_count": 1,
        "rejected_order_count": 0,
        "successful_order_share": "50.00",
        "successful_amount_share": "25.00",
        "stuck_rate": "33.33",
        "success_rate": "33.33",
    }
    assert rows[("2026-07-30", "channel-b")] == {
        "date": "2026-07-30",
        "pay_channel": "channel-b",
        "pay_channel_name": "Channel B",
        "order_count": 2,
        "successful_order_count": 1,
        "successful_amount": "300.00",
        "successful_fee": "7.00",
        "failed_order_count": 0,
        "submitted_order_count": 0,
        "rejected_order_count": 1,
        "successful_order_share": "50.00",
        "successful_amount_share": "75.00",
        "stuck_rate": "0.00",
        "success_rate": "50.00",
    }
    assert rows[("2026-07-31", "channel-c")]["successful_order_share"] == "—"
    assert rows[("2026-07-31", "channel-c")]["successful_amount_share"] == "—"
    assert rows[("2026-07-31", "channel-c")]["stuck_rate"] == "100.00"
    # Filtering a channel does not narrow the day-level denominator used for
    # its success share.
    assert filtered.total == 1
    assert filtered.items[0]["successful_amount_share"] == "25.00"
    await engine.dispose()
