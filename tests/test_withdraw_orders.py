from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.common.settings import Settings
from packages.domain.models import (
    Base,
    DataDictionaryEntry,
    SourceConfig,
    SystemRetentionSetting,
    WithdrawOrderRefreshState,
    WithdrawOrderSnapshot,
)
from packages.domain.schemas.withdraw_order import (
    WithdrawOperatorSummaryRequest,
    WithdrawOrderQueryRequest,
)
from packages.domain.services.remote_withdraw_service import (
    RajAdminWithdrawClient,
    normalize_withdraw_order,
)
from packages.domain.services.withdraw_order_service import (
    query_withdraw_operator_summary,
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


@pytest.mark.parametrize(
    "payload",
    [
        {"create_time_start": "2026-07-30 10:00:00"},
        {"create_time_end": "2026-07-30 10:00:00"},
        {
            "create_time_start": "2026-07-30 10:00:00",
            "create_time_end": "2026-07-30 09:59:59",
        },
        {
            "create_time_start": "2026-07-30T10:00:00",
            "create_time_end": "2026-07-30 11:00:00",
        },
    ],
)
def test_withdraw_query_time_range_requires_a_complete_ordered_wall_time_pair(
    payload: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        WithdrawOrderQueryRequest(source_id="rajwin", **payload)


def test_withdraw_operator_summary_request_normalizes_selected_statuses() -> None:
    request = WithdrawOperatorSummaryRequest(
        source_id="rajwin",
        statuses=[" 3 ", "0", "3"],
    )

    assert request.statuses == ["3", "0"]
    assert WithdrawOperatorSummaryRequest(source_id="rajwin", statuses=[]).statuses is None
    with pytest.raises(ValidationError):
        WithdrawOperatorSummaryRequest(
            source_id="rajwin",
            create_time_start="2026-07-30 10:00:00",
        )
    with pytest.raises(ValidationError):
        WithdrawOperatorSummaryRequest(source_id="rajwin", statuses=[""])
    with pytest.raises(ValidationError):
        WithdrawOperatorSummaryRequest(
            source_id="rajwin",
            statuses=[str(index) for index in range(21)],
        )


@pytest.mark.asyncio
async def test_withdraw_query_time_range_only_filters_local_cache_in_source_timezone() -> None:
    settings = Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
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
                # At 06:00 UTC, the configured last-two-hours cache spans
                # 09:30:00 through 11:30:00 in the source's Asia/Kolkata time.
                SystemRetentionSetting(
                    id=1,
                    uploaded_file_retention_days=3,
                    result_retention_days=30,
                    remote_cache_retention_days=30,
                    withdraw_order_refresh_interval_hours=1,
                    withdraw_order_query_range="last_2_hours",
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="outside-cache-window",
                    uid="100",
                    amount="10.00",
                    real_amount="10.00",
                    create_time="2026-07-30 09:00:00",
                    create_time_utc=datetime(2026, 7, 30, 3, 30, tzinfo=UTC),
                    status="0",
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="included-start",
                    uid="101",
                    amount="20.00",
                    real_amount="19.00",
                    create_time="2026-07-30 10:00:00",
                    create_time_utc=datetime(2026, 7, 30, 4, 30, tzinfo=UTC),
                    status="0",
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="included-end",
                    uid="102",
                    amount="30.00",
                    real_amount="29.00",
                    create_time="2026-07-30 11:00:00",
                    create_time_utc=datetime(2026, 7, 30, 5, 30, tzinfo=UTC),
                    status="3",
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="outside-page-range",
                    uid="103",
                    amount="40.00",
                    real_amount="39.00",
                    create_time="2026-07-30 11:30:00",
                    create_time_utc=datetime(2026, 7, 30, 6, 0, tzinfo=UTC),
                    status="3",
                ),
            ]
        )
        await session.commit()

        result = await query_withdraw_orders(
            session,
            request=WithdrawOrderQueryRequest(
                source_id="rajwin",
                # This is 03:30–05:30 UTC, so the local query intersects it
                # with the configured cache's 04:00–06:00 UTC window.
                create_time_start="2026-07-30 09:00:00",
                create_time_end="2026-07-30 11:00:00",
            ),
            settings=settings,
            now=datetime(2026, 7, 30, 6, 0, tzinfo=UTC),
        )

    assert [item["id"] for item in result.items] == ["included-end", "included-start"]
    assert result.total == 2
    assert result.effective_create_time_end == "2026-07-30 11:00:00"
    assert result.summary["order_count"] == 2
    assert result.summary["amount"] == "50.00"
    assert result.summary["real_amount"] == "48.00"
    assert result.summary["status_distribution"] == [
        {"status": "0", "count": 1, "amount": "20.00", "real_amount": "19.00"},
        {"status": "3", "count": 1, "amount": "30.00", "real_amount": "29.00"},
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_withdraw_operator_summary_aggregates_local_cache_by_trimmed_operator() -> None:
    settings = Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    query_time = datetime(2026, 7, 30, 6, 0, tzinfo=UTC)
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
                    withdraw_order_refresh_interval_hours=1,
                    withdraw_order_query_range="last_2_hours",
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
                    entry_code="2",
                    entry_label="处理中",
                    active=True,
                ),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type="withdraw_status",
                    entry_code="3",
                    entry_label="已完成",
                    active=False,
                ),
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type="withdraw_status",
                    entry_code="4",
                    entry_label="待审查",
                    active=True,
                ),
                # A source-specific code with the same review-state label is
                # excluded too; the summary is not tied solely to 0 / 4.
                DataDictionaryEntry(
                    source_id="rajwin",
                    dictionary_type="withdraw_status",
                    entry_code="7",
                    entry_label="待审核",
                    active=True,
                ),
                # This row is outside the configured cache window and must
                # never reach the local aggregation.
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="outside-cache-window",
                    uid="100",
                    create_time="2026-07-30 09:00:00",
                    create_time_utc=datetime(2026, 7, 30, 3, 30, tzinfo=UTC),
                    audit_admin="Alice",
                    status="0",
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="alice-pending",
                    uid="101",
                    create_time="2026-07-30 10:00:00",
                    create_time_utc=datetime(2026, 7, 30, 4, 30, tzinfo=UTC),
                    audit_admin=" Alice ",
                    status="0",
                    synced_at=datetime(2026, 7, 30, 5, 0, tzinfo=UTC),
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="alice-complete",
                    uid="102",
                    create_time="2026-07-30 10:30:00",
                    create_time_utc=datetime(2026, 7, 30, 5, 0, tzinfo=UTC),
                    audit_admin="Alice",
                    status="3",
                    synced_at=datetime(2026, 7, 30, 5, 10, tzinfo=UTC),
                ),
                # Case differences remain separate groups; only whitespace is
                # normalized for the displayed operator name.
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="lowercase-alice",
                    uid="103",
                    create_time="2026-07-30 11:00:00",
                    create_time_utc=datetime(2026, 7, 30, 5, 30, tzinfo=UTC),
                    audit_admin="alice",
                    status="0",
                    synced_at=datetime(2026, 7, 30, 5, 20, tzinfo=UTC),
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="missing-null",
                    uid="104",
                    create_time="2026-07-30 10:45:00",
                    create_time_utc=datetime(2026, 7, 30, 5, 15, tzinfo=UTC),
                    audit_admin=None,
                    status="3",
                    synced_at=datetime(2026, 7, 30, 5, 25, tzinfo=UTC),
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="missing-blank",
                    uid="105",
                    create_time="2026-07-30 10:50:00",
                    create_time_utc=datetime(2026, 7, 30, 5, 20, tzinfo=UTC),
                    audit_admin="  ",
                    status="0",
                    synced_at=datetime(2026, 7, 30, 5, 30, tzinfo=UTC),
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="bob-processing",
                    uid="106",
                    create_time="2026-07-30 10:55:00",
                    create_time_utc=datetime(2026, 7, 30, 5, 25, tzinfo=UTC),
                    audit_admin=" Bob ",
                    status="2",
                    synced_at=datetime(2026, 7, 30, 5, 40, tzinfo=UTC),
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="bob-review-pending",
                    uid="108",
                    create_time="2026-07-30 10:57:00",
                    create_time_utc=datetime(2026, 7, 30, 5, 27, tzinfo=UTC),
                    audit_admin="Bob",
                    status="4",
                    synced_at=datetime(2026, 7, 30, 5, 42, tzinfo=UTC),
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="alice-source-specific-review",
                    uid="109",
                    create_time="2026-07-30 10:59:00",
                    create_time_utc=datetime(2026, 7, 30, 5, 29, tzinfo=UTC),
                    audit_admin="Alice",
                    status="7",
                    synced_at=datetime(2026, 7, 30, 5, 43, tzinfo=UTC),
                ),
                # This is inside the configured cache window but outside the
                # page-local time range below.
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="outside-page-range",
                    uid="107",
                    create_time="2026-07-30 11:30:00",
                    create_time_utc=datetime(2026, 7, 30, 6, 0, tzinfo=UTC),
                    audit_admin="Bob",
                    status="0",
                    synced_at=datetime(2026, 7, 30, 5, 55, tzinfo=UTC),
                ),
            ]
        )
        await session.commit()

        result = await query_withdraw_operator_summary(
            session,
            request=WithdrawOperatorSummaryRequest(
                source_id="rajwin",
                create_time_start="2026-07-30 10:00:00",
                create_time_end="2026-07-30 11:00:00",
            ),
            settings=settings,
            now=query_time,
        )
        second_page = await query_withdraw_operator_summary(
            session,
            request=WithdrawOperatorSummaryRequest(
                source_id="rajwin",
                create_time_start="2026-07-30 10:00:00",
                create_time_end="2026-07-30 11:00:00",
                page=2,
                page_size=2,
            ),
            settings=settings,
            now=query_time,
        )
        filtered = await query_withdraw_operator_summary(
            session,
            request=WithdrawOperatorSummaryRequest(
                source_id="rajwin",
                create_time_start="2026-07-30 10:00:00",
                create_time_end="2026-07-30 11:00:00",
                statuses=["3", "0", "3"],
                audit_admin="ali",
            ),
            settings=settings,
            now=query_time,
        )
        excluded_only = await query_withdraw_operator_summary(
            session,
            request=WithdrawOperatorSummaryRequest(
                source_id="rajwin",
                create_time_start="2026-07-30 10:00:00",
                create_time_end="2026-07-30 11:00:00",
                statuses=["0", "4"],
            ),
            settings=settings,
            now=query_time,
        )

    items_by_operator = {item["audit_admin"]: item for item in result.items}
    assert result.source_id == "rajwin"
    assert result.source_display_name == "RajWin"
    assert result.business_timezone == "Asia/Kolkata"
    assert result.effective_create_time_end == "2026-07-30 11:00:00"
    assert result.status_columns == ["2", "3"]
    assert [(entry["code"], entry["label"]) for entry in result.status_dictionary] == [
        ("2", "处理中"),
        ("3", "已完成"),
    ]
    assert result.total == 3
    assert result.selected_order_total == 3
    assert set(items_by_operator) == {"Alice", "Bob", "未填写操作人员"}
    assert items_by_operator["Alice"] == {
        "audit_admin": "Alice",
        "audit_admin_missing": False,
        "status_counts": [
            {"status": "2", "count": 0},
            {"status": "3", "count": 1},
        ],
        "selected_total": 1,
    }
    assert items_by_operator["未填写操作人员"] == {
        "audit_admin": "未填写操作人员",
        "audit_admin_missing": True,
        "status_counts": [
            {"status": "2", "count": 0},
            {"status": "3", "count": 1},
        ],
        "selected_total": 1,
    }
    assert items_by_operator["Bob"]["status_counts"] == [
        {"status": "2", "count": 1},
        {"status": "3", "count": 0},
    ]
    assert second_page.total == 3
    assert {item["audit_admin"] for item in second_page.items} == {"Bob"}
    assert filtered.status_columns == ["3"]
    assert filtered.selected_order_total == 1
    assert filtered.total == 1
    assert {item["audit_admin"] for item in filtered.items} == {"Alice"}
    assert filtered.items[0]["status_counts"] == [
        {"status": "3", "count": 1},
    ]
    assert excluded_only.status_columns == []
    assert excluded_only.selected_order_total == 0
    assert excluded_only.total == 0
    assert excluded_only.items == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_withdraw_query_survives_page_size_schema_fallback_session_rollback() -> None:
    """A pre-0007 database must still serve the local withdrawal cache.

    Loading the current retention ORM model against that schema fails because
    the page-size column is absent.  The settings compatibility path rolls the
    session back before loading a legacy projection, which expires the source
    already read by ``query_withdraw_orders``.  Keep this end-to-end shape so
    the query cannot regress into lazily reloading that source after rollback.
    """

    settings = Settings(
        secret_key="test-secret-key-that-is-longer-than-32-characters",
        database_url="sqlite+aiosqlite:///:memory:",
    )
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

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
                    withdraw_order_refresh_interval_hours=1,
                    withdraw_order_refresh_page_size=100,
                    withdraw_order_query_range="today",
                ),
                WithdrawOrderSnapshot(
                    source_id="rajwin",
                    remote_order_id="cached-before-page-size-migration",
                    uid="100",
                    amount="50.00",
                    real_amount="49.00",
                    create_time="2026-07-30 10:30:00",
                    create_time_utc=datetime(2026, 7, 30, 5, 0, tzinfo=UTC),
                    status="3",
                ),
            ]
        )
        await session.commit()

    # Reproduce production after migration 0006 but before 0007.  The ORM
    # still selects the newer column, forcing the compatibility fallback and
    # its session rollback.
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "ALTER TABLE system_retention_settings "
                "DROP COLUMN withdraw_order_refresh_page_size"
            )
        )

    async with factory() as session:
        result = await query_withdraw_orders(
            session,
            request=WithdrawOrderQueryRequest(source_id="rajwin"),
            settings=settings,
            now=datetime(2026, 7, 30, 6, 0, tzinfo=UTC),
        )

    assert result.source_display_name == "RajWin"
    assert result.business_timezone == "Asia/Kolkata"
    assert [item["id"] for item in result.items] == [
        "cached-before-page-size-migration"
    ]

    async with factory() as session:
        summary = await query_withdraw_operator_summary(
            session,
            request=WithdrawOperatorSummaryRequest(source_id="rajwin"),
            settings=settings,
            now=datetime(2026, 7, 30, 6, 0, tzinfo=UTC),
        )

    assert summary.source_display_name == "RajWin"
    assert summary.business_timezone == "Asia/Kolkata"
    assert summary.selected_order_total == 1
    assert summary.items == [
        {
            "audit_admin": "未填写操作人员",
            "audit_admin_missing": True,
            "status_counts": [{"status": "3", "count": 1}],
            "selected_total": 1,
        }
    ]
    await engine.dispose()


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
