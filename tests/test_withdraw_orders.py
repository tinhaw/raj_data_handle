from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    DataDictionaryEntry,
    SourceConfig,
    WithdrawOrderRefreshState,
    WithdrawOrderSnapshot,
)
from packages.domain.schemas.withdraw_order import WithdrawOrderQueryRequest
from packages.domain.services.remote_withdraw_service import (
    RajAdminWithdrawClient,
    normalize_withdraw_order,
)
from packages.domain.services.withdraw_order_service import (
    query_withdraw_orders,
    summarize_withdraw_orders,
)


def test_withdraw_order_normalizer_keeps_only_approved_fields() -> None:
    normalized = normalize_withdraw_order(
        {
            "id": 2865914,
            "uid": 26258249,
            "amount": 500,
            "real_amount": "490.50",
            "status": 3,
            "audit_admin": "operator",
            "submit_time": "2026-07-30 02:10:00",
            "time": {
                "create_time": "2026-07-30 02:08:33",
                "update_time": "2026-07-30 02:09:00",
            },
            "info": {
                "bank_name": "private-name",
                "account": "1234567890",
                "mobile": "9000000000",
            },
            "ip": "192.0.2.10",
            "order_num": "not-approved-for-this-page",
        }
    )

    assert normalized == {
        "id": "2865914",
        "uid": "26258249",
        "amount": "500",
        "real_amount": "490.50",
        "create_time": "2026-07-30 02:08:33",
        "update_time": "2026-07-30 02:09:00",
        "submit_time": "2026-07-30 02:10:00",
        "audit_admin": "operator",
        "status": "3",
    }
    assert "info" not in normalized
    assert "ip" not in normalized
    assert "order_num" not in normalized


@pytest.mark.asyncio
async def test_withdraw_client_posts_filters_and_paginates_all_safe_rows() -> None:
    request_bodies: list[dict[str, object]] = []
    renewals = 0

    async def on_page_fetched() -> None:
        nonlocal renewals
        renewals += 1

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/system/login"):
            return httpx.Response(200, json={"data": {"token": "test-token"}})
        assert request.url.path.endswith("/api/operate/withdrawOrder/index")
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer test-token"
        body = json.loads(request.content)
        request_bodies.append(body)
        page = int(body["page"])
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {
                            "id": page,
                            "uid": 100 + page,
                            "amount": 100 * page,
                            "real_amount": 90 * page,
                            "status": page - 1,
                            "time": {
                                "create_time": f"2026-07-30 0{page}:00:00",
                                "update_time": "-",
                            },
                            "submit_time": "-",
                            "audit_admin": "",
                            "info": {"account": "must-not-leak"},
                            "ip": "192.0.2.1",
                        }
                    ],
                    "pageInfo": {
                        "total": 2,
                        "currentPage": page,
                        "totalPage": 2,
                    },
                }
            },
        )

    async with RajAdminWithdrawClient(
        base_url="https://admin.example.test",
        username="reader",
        password="password",
        totp_secret="JBSWY3DPEHPK3PXP",
        page_size=1,
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await client.fetch_all_withdraw_orders(
            create_start="2026-07-29T18:30:00.000Z",
            create_end="2026-07-30T18:29:59.000Z",
            uid="1001",
            status="3",
            on_page_fetched=on_page_fetched,
        )

    assert result.complete is True
    assert result.fetched_pages == 2
    assert result.remote_total == 2
    assert [item["id"] for item in result.orders] == ["1", "2"]
    assert all("info" not in item and "ip" not in item for item in result.orders)
    assert [body["page"] for body in request_bodies] == [1, 2]
    assert renewals == 2
    assert all(body["uid"] == "1001" and body["status"] == "3" for body in request_bodies)
    assert all(
        body["create_time"]
        == ["2026-07-29T18:30:00.000Z", "2026-07-30T18:29:59.000Z"]
        for body in request_bodies
    )


@pytest.mark.asyncio
async def test_withdraw_client_fetches_status_dictionary_through_read_allowlist() -> None:
    login_attempts = 0
    dictionary_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_attempts, dictionary_attempts
        if request.url.path.endswith("/api/system/login"):
            login_attempts += 1
            return httpx.Response(200, json={"data": {"token": f"test-token-{login_attempts}"}})

        assert request.url.path.endswith("/api/system/dataDict/list")
        assert request.method == "GET"
        assert dict(request.url.params) == {"code": "withdraw_status"}
        dictionary_attempts += 1
        if dictionary_attempts == 1:
            assert request.headers["authorization"] == "Bearer test-token-1"
            return httpx.Response(401, json={"message": "expired"})
        assert request.headers["authorization"] == "Bearer test-token-2"
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {"id": 88, "key": "-1", "title": "审核拒绝", "ignored": "not-stored"},
                    {"id": 89, "key": 0, "title": "待审核"},
                    {"id": 92, "key": "3", "title": "代付成功"},
                ],
            },
        )

    async with RajAdminWithdrawClient(
        base_url="https://admin.example.test",
        username="reader",
        password="password",
        totp_secret="JBSWY3DPEHPK3PXP",
        transport=httpx.MockTransport(handler),
    ) as client:
        statuses = await client.fetch_withdraw_statuses()

    assert statuses == [
        {"code": "-1", "label": "审核拒绝"},
        {"code": "0", "label": "待审核"},
        {"code": "3", "label": "代付成功"},
    ]
    assert login_attempts == 2
    assert dictionary_attempts == 2


def test_withdraw_summary_uses_same_filtered_rows_for_metrics_and_charts() -> None:
    summary = summarize_withdraw_orders(
        [
            {
                "amount": "100.00",
                "real_amount": "98.00",
                "status": "0",
                "create_time": "2026-07-30 09:10:00",
            },
            {
                "amount": "200.00",
                "real_amount": "195.00",
                "status": "3",
                "create_time": "2026-07-30 09:30:00",
            },
            {
                "amount": "50.00",
                "real_amount": "50.00",
                "status": "3",
                "create_time": "2026-07-30 10:00:00",
            },
        ],
        window_start=datetime(2026, 7, 30, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
    )

    assert summary["order_count"] == 3
    assert summary["amount"] == "350.00"
    assert summary["real_amount"] == "343.00"
    assert summary["average_amount"] == "116.67"
    assert summary["status_distribution"] == [
        {"status": "0", "count": 1, "amount": "100.00", "real_amount": "98.00"},
        {"status": "3", "count": 2, "amount": "250.00", "real_amount": "245.00"},
    ]
    assert summary["time_series"] == [
        {"bucket": "2026-07-30 09:00", "count": 2, "amount": "300.00", "real_amount": "293.00"},
        {"bucket": "2026-07-30 10:00", "count": 1, "amount": "50.00", "real_amount": "50.00"},
    ]


@pytest.mark.asyncio
async def test_withdraw_query_reads_only_source_scoped_local_cache_and_dictionary() -> None:
    settings = Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        rajwin = SourceConfig(
            source_id="rajwin",
            display_name="RajWin",
            enabled=True,
            business_timezone="Asia/Kolkata",
            currency="INR",
        )
        session.add_all(
            [
                rajwin,
                SourceConfig(
                    source_id="rajluck",
                    display_name="RajLuck",
                    business_timezone="Asia/Kolkata",
                    currency="INR",
                ),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type="withdraw_status",
                    entry_code="0",
                    entry_label="待审核",
                    active=True,
                ),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type="withdraw_status",
                    entry_code="3",
                    entry_label="出款完成",
                    active=False,
                ),
                DataDictionaryEntry(
                    source_id="rajluck",
                    dictionary_type="withdraw_status",
                    entry_code="0",
                    entry_label="RajLuck 专用文案",
                    active=True,
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="one",
                    uid="100",
                    amount="50.00",
                    real_amount="49.00",
                    create_time="2026-07-30 10:00:00",
                    create_time_utc=datetime(2026, 7, 30, 4, 30, tzinfo=UTC),
                    status="0",
                    synced_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="two",
                    uid="101",
                    amount="100.00",
                    real_amount="98.00",
                    create_time="2026-07-30 11:00:00",
                    create_time_utc=datetime(2026, 7, 30, 5, 30, tzinfo=UTC),
                    status="3",
                    synced_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
                ),
                # The page uses the current system refresh range, so this
                # retained older row must not appear when the preset is today.
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="older",
                    uid="999",
                    amount="999.00",
                    real_amount="999.00",
                    create_time="2026-07-29 10:00:00",
                    create_time_utc=datetime(2026, 7, 29, 4, 30, tzinfo=UTC),
                    status="9",
                    synced_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
                ),
                WithdrawOrderSnapshot(
                    source_id="rajluck",
                    remote_order_id="other-source",
                    uid="200",
                    amount="500.00",
                    real_amount="500.00",
                    create_time="2026-07-30 10:00:00",
                    create_time_utc=datetime(2026, 7, 30, 4, 30, tzinfo=UTC),
                    status="0",
                    synced_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
                ),
                WithdrawOrderRefreshState(
                    source_id="rajwin",
                    status="succeeded",
                    last_remote_total=17,
                    last_cached_total=2,
                    last_fetched_pages=1,
                    last_complete=True,
                    last_succeeded_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
                ),
            ]
        )
        await session.commit()

        result = await query_withdraw_orders(
            session,
            request=WithdrawOrderQueryRequest(
                source_id="rajwin",
            ),
            settings=settings,
            now=datetime(2026, 7, 30, 18, 0, tzinfo=UTC),
        )

    assert result.summary["status_distribution"] == [
        {"status": "0", "count": 1, "amount": "50.00", "real_amount": "49.00"},
        {"status": "3", "count": 1, "amount": "100.00", "real_amount": "98.00"},
    ]
    assert result.status_dictionary == [
        {"code": "0", "label": "待审核", "active": True},
        {"code": "3", "label": "出款完成", "active": False},
    ]
    assert result.remote_total == 17
    assert result.fetched_pages == 1
    assert result.complete is True
    assert [item["id"] for item in result.items] == ["two", "one"]
    await engine.dispose()
