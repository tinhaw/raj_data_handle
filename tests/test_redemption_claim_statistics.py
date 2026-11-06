from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from openpyxl import load_workbook
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.dependencies import get_auth_context
from apps.api.routers.redemption_claims import router
from packages.common.database import get_db_session
from packages.common.settings import Settings
from packages.domain.models import (
    AppUser,
    Base,
    ErpCompatibilityIdMap,
    RedemptionClaimDaily,
    RedemptionClaimGroup,
    RedemptionClaimRecord,
    RedemptionClaimRun,
    RedemptionClaimSchedule,
    RemoteAccount,
    RemoteAccountCapability,
    SecurityAuditLog,
    SourceConfig,
)
from packages.domain.schemas.remote_account import (
    RemoteAccountCreateRequest,
    RemoteAccountCredentialsWrite,
)
from packages.domain.services import redemption_claim_service as service
from packages.domain.services.redemption_claim_reader import (
    ClaimReadError,
    fetch_claim_snapshot,
    parse_record,
)
from packages.domain.services.redemption_claim_worker import (
    binding_authorization,
    claim_next,
    owned_run,
    process_claim_sync,
    schedule_due,
)
from packages.domain.services.remote_account_service import create_remote_account


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/claims.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        for ddl in [
            "CREATE TABLE erp_compat_redemption_code_tasks (id INTEGER PRIMARY KEY, "
            "task_date DATE, daily_sequence INTEGER)",
            "CREATE TABLE erp_compat_redemption_campaigns (id INTEGER PRIMARY KEY, name TEXT)",
            "CREATE TABLE erp_compat_redemption_code_batches (id INTEGER PRIMARY KEY, "
            "task_id INTEGER, campaign_id INTEGER, remote_connection_id INTEGER, "
            "redemption_type TEXT, lookback_days INTEGER, valid_from_day_offset INTEGER, "
            "valid_to_day_offset INTEGER)",
            "CREATE TABLE erp_compat_redemption_code_issues (id INTEGER PRIMARY KEY, "
            "batch_id INTEGER, campaign_tier_id INTEGER, remote_market_id INTEGER, "
            "remote_configuration_id TEXT, remote_group_key TEXT, tier_name TEXT, "
            "claim_date DATE, min_deposit_amount NUMERIC, bonus_amount NUMERIC, "
            "bonus_max_amount NUMERIC, remote_label_ids_json TEXT, redemption_code TEXT)",
            "CREATE TABLE erp_compat_redemption_issue_codes (issue_id INTEGER, "
            "code_index INTEGER, code TEXT)",
        ]:
            await connection.execute(text(ddl))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        environment="development",
        secret_key="claim-tests-only-secret-key-32-characters",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/claims.db",
    )
    async with factory() as session:
        session.add(
            AppUser(
                id=1,
                username="claims-admin",
                username_normalized="claims-admin",
                display_name="Test",
                password_hash="unused-test-hash",
                role="admin",
            )
        )
        session.add(
            SourceConfig(
                source_id="rajwin",
                display_name="RajWin",
                enabled=True,
                base_url="https://example.test",
                business_timezone="Asia/Kolkata",
            )
        )
        await session.commit()
        account = await create_remote_account(
            session,
            request=RemoteAccountCreateRequest(
                source_id="rajwin",
                login_username="claim-test",
                display_name="claim-test",
                credentials=RemoteAccountCredentialsWrite(
                    password="test-only-password", totp_secret="JBSWY3DPEHPK3PXP"
                ),
            ),
            actor_user_id=1,
            settings=settings,
        )
        mapping = await session.scalar(
            select(ErpCompatibilityIdMap).where(
                ErpCompatibilityIdMap.entity_type == "remote_account",
                ErpCompatibilityIdMap.canonical_id == account.account.id,
            )
        )
        session.add(ErpCompatibilityIdMap(entity_type="source", legacy_id=7, canonical_id="rajwin"))
        capability = await session.get(
            RemoteAccountCapability, (account.account.id, "ERP_REDEMPTION_CLAIM_READ")
        )
        capability.enabled = True
        await session.execute(
            text("INSERT INTO erp_compat_redemption_code_tasks VALUES (1,'2026-11-01',1)")
        )
        await session.execute(text("INSERT INTO erp_compat_redemption_campaigns VALUES (1,'Test')"))
        await session.execute(
            text(
                "INSERT INTO erp_compat_redemption_code_batches "
                "VALUES (1,1,1,:account,'PREVIOUS_DAY_DEPOSIT',1,0,0)"
            ),
            {"account": mapping.legacy_id},
        )
        await session.execute(
            text(
                "INSERT INTO erp_compat_redemption_code_issues VALUES "
                "(1,1,1,7,'42','group-1','充值100','2026-11-01',100,5,11,'[901]','CODE0001')"
            )
        )
        await session.execute(
            text(
                "INSERT INTO erp_compat_redemption_issue_codes VALUES "
                "(1,0,'CODE0001'),(1,1,'CODE0002')"
            )
        )
        await session.commit()
    yield factory, settings
    await engine.dispose()


def record(number, *, key="CODE0001", when="2026-11-01 00:00:00"):
    return {
        "id": number,
        "group_key": "group-1",
        "key": key,
        "uid": 800000 + number,
        "receive_time": when,
        "amount": 5,
        "gift_type": 0,
    }


class FakeAdapter:
    def __init__(self, records, *, cap=100, duplicate=False):
        self.records, self.cap, self.duplicate = records, cap, duplicate
        self.requests = []

    def _assert_read_grant(self, *_):
        pass

    async def _request(self, method, path, *, params):
        self.requests.append((method, path, params))
        size = min(params["pageSize"], self.cap)
        page = params["page"]
        start = (page - 1) * size
        items = self.records[start : start + size]
        if self.duplicate and page > 1:
            items = self.records[: len(items)]
        return {
            "data": {
                "items": items,
                "pageInfo": {
                    "total": len(self.records),
                    "currentPage": page,
                    "totalPage": (len(self.records) + size - 1) // size,
                },
            }
        }, None


async def noop():
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize("size,cap", [(0, 100), (45, 100), (100, 100), (101, 100), (101, 10)])
async def test_complete_pagination_and_silent_caps(size, cap):
    adapter = FakeAdapter([record(i + 1) for i in range(size)], cap=cap)
    result = await fetch_claim_snapshot(adapter, None, "group-1", "Asia/Kolkata", noop)
    assert len(result.records) == size
    assert adapter.requests[0][2]["pageSize"] == 100
    assert all(
        call[0] == "GET" and call[1] == "/api/common/userGift/index" for call in adapter.requests
    )


@pytest.mark.asyncio
async def test_duplicate_paging_cannot_publish_partial_counts():
    with pytest.raises(ClaimReadError, match="去重|变化"):
        await fetch_claim_snapshot(
            FakeAdapter([record(i + 1) for i in range(101)], duplicate=True),
            None,
            "group-1",
            "Asia/Kolkata",
            noop,
        )


def test_actual_date_timezone_and_invalid_group():
    parsed = parse_record(record(1, when="2026-11-02 00:01:00"), "group-1", "Asia/Kolkata")
    assert parsed["claim_date"] == date(2026, 11, 2)
    assert parsed["received_at"] == datetime(2026, 11, 1, 18, 31, tzinfo=UTC)
    assert parsed["amount"] == Decimal(5)
    with pytest.raises(ClaimReadError):
        parse_record(record(1), "other-group", "Asia/Kolkata")


def test_daily_coverage_does_not_invent_zero_for_unsynced_days_or_wait_for_future_groups():
    now = datetime(2026, 11, 5, tzinfo=UTC)
    first = RedemptionClaimGroup(
        id="one",
        snapshot={"timezone": "Asia/Kolkata", "validFrom": "2026-11-01", "validTo": "2026-11-10"},
        last_succeeded_at=datetime(2026, 11, 3, tzinfo=UTC),
    )
    assert service.cell([first], date(2026, 11, 4), {}, now)["count"] is None
    future = RedemptionClaimGroup(
        id="two",
        snapshot={"timezone": "Asia/Kolkata", "validFrom": "2026-11-10", "validTo": "2026-11-10"},
    )
    result = service.cell([first, future], date(2026, 11, 2), {}, now)
    assert result["count"] == 0 and result["complete"]


def test_cell_configuration_ids_include_failed_and_pending_groups_without_inventing_ids():
    now = datetime(2026, 11, 5, tzinfo=UTC)

    def group(group_id, configuration_id, **kwargs):
        return RedemptionClaimGroup(
            id=group_id,
            configuration_id=configuration_id,
            snapshot={
                "timezone": "Asia/Kolkata",
                "validFrom": "2026-11-01",
                "validTo": "2026-11-01",
            },
            **kwargs,
        )

    groups = [
        group("known", "42", last_succeeded_at=now),
        group("failed", "43", last_succeeded_at=now, last_error="分页内容不一致"),
        group("pending", "44"),
        group("missing-id", None),
        group("same-configuration", "42"),
    ]
    counts = {("known", date(2026, 11, 1)): 3}
    result = service.cell(groups, date(2026, 11, 1), counts, now, include_configuration_ids=True)
    assert result["configurationIds"] == ["42", "43", "44"]
    assert result["count"] == 3 and not result["complete"]
    # Showing IDs must not alter count/coverage semantics or expose internal group IDs.
    original = service.cell(groups, date(2026, 11, 1), counts, now)
    assert {k: v for k, v in result.items() if k != "configurationIds"} == original


@pytest.mark.asyncio
async def test_summary_configuration_ids_follow_cell_scope_and_cross_date_claims(db):
    factory, _ = db
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO erp_compat_redemption_code_issues VALUES "
                "(2,1,1,7,'43','group-2','充值100','2026-11-02',100,5,11,'[901]','CODE0003'),"
                "(3,1,2,7,'99','group-3','其他档位','2026-11-01',500,5,11,'[902]','CODE0004')"
            )
        )
        await session.commit()
        initial = await service.summary(session, 1, date(2026, 11, 1), date(2026, 11, 2))
        key = next(c["key"] for c in initial["columns"] if c["tierName"] == "充值100")
        assert initial["rows"][0]["cells"][key]["configurationIds"] == ["42"]
        assert initial["rows"][1]["cells"][key]["configurationIds"] == ["43"]
        assert initial["rows"][1]["cells"][key]["count"] is None
        group = next(
            g for g in await service.materialize_groups(session, 1) if g.configuration_id == "42"
        )
        await service.publish_group(
            session,
            group,
            [parse_record(record(1, when="2026-11-02 01:00:00"), "group-1", "Asia/Kolkata")],
        )
        await session.commit()
        updated = await service.summary(session, 1, date(2026, 11, 2), date(2026, 11, 2))
        cell = updated["rows"][0]["cells"][key]
        assert cell["configurationIds"] == ["42", "43"]
        assert cell["count"] == 1 and not cell["complete"]
        assert "configurationIds" not in updated["rows"][0]["total"]


@pytest.mark.asyncio
async def test_summary_zero_unknown_drilldown_and_idempotent_publish(db):
    factory, _ = db
    async with factory() as session:
        before = await service.summary(session, 1, date(2026, 11, 1), date(2026, 11, 2))
        assert before["rows"][0]["total"]["count"] is None
        group = (await service.materialize_groups(session, 1))[0]
        records = [parse_record(record(i), "group-1", "Asia/Kolkata") for i in (1, 2)]
        await service.publish_group(session, group, records)
        await session.commit()
        await service.publish_group(session, group, records)
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(RedemptionClaimRecord)) == 2
        result = await service.summary(session, 1, date(2026, 11, 1), date(2026, 11, 2))
        assert [r["total"]["count"] for r in result["rows"]] == [2, 0]
        details = await service.code_details(
            session, 1, date(2026, 11, 1), group.column_key, result["queryVersion"]
        )
        assert [i["count"] for i in details["items"]] == [2, 0]
        with pytest.raises(service.ClaimError, match="数据已更新"):
            await service.code_details(session, 1, date(2026, 11, 1), group.column_key, "stale")
        with pytest.raises(service.ClaimError, match="减少"):
            await service.publish_group(session, group, records[:1])
        await session.rollback()


@pytest.mark.asyncio
async def test_settings_whitelist_coalescing_cancel_and_fixed_delay(db):
    factory, _ = db
    async with factory() as session:
        for interval in service.INTERVALS:
            old = await service.get_schedule(session, 1)
            await service.save_schedule(session, 1, 1, False, interval, old["rowVersion"])
        with pytest.raises(service.ClaimError):
            await service.save_schedule(session, 1, 1, False, 90, 7)
        with pytest.raises(service.ClaimError, match="已被修改"):
            await service.save_schedule(session, 1, 1, False, 30, 0)
        old = await service.get_schedule(session, 1)
        saved = await service.save_schedule(session, 1, 1, True, 120, old["rowVersion"])
        manual = await service.request_sync(session, 1, 1)
        assert saved["activeRun"]["id"] == manual["id"]
        await service.save_schedule(session, 1, 1, False, 120, saved["rowVersion"])
        run = await session.get(RedemptionClaimRun, manual["id"])
        assert run.status == "cancelled"


@pytest.mark.asyncio
async def test_worker_read_only_account_gate_and_schedule(db):
    factory, settings = db
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/api/system/login":
            return httpx.Response(200, json={"data": {"token": "test-claims-token"}})
        assert request.method == "GET" and request.url.path == "/api/common/userGift/index"
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [record(1), record(2)],
                    "pageInfo": {"currentPage": 1, "totalPage": 1, "total": 2},
                }
            },
        )

    async with factory() as session:
        await service.save_schedule(session, 1, 1, True, 60, 0)
    assert await process_claim_sync(
        factory, settings=settings, transport=httpx.MockTransport(handler)
    )
    async with factory() as session:
        setting = await session.get(RedemptionClaimSchedule, 1)
        assert service.utc(setting.next_run_at) - service.utc(
            setting.last_finished_at
        ) == timedelta(hours=1)
        assert await session.scalar(select(func.count()).select_from(RedemptionClaimRecord)) == 2
        assert await session.scalar(select(func.sum(RedemptionClaimDaily.count))) == 2
        capability = await session.scalar(
            select(RemoteAccountCapability).where(
                RemoteAccountCapability.capability == "ERP_REDEMPTION_CLAIM_READ"
            )
        )
        capability.enabled = False
        await session.commit()
        group = await session.scalar(select(RedemptionClaimGroup))
        with pytest.raises(service.ClaimError, match="读取能力"):
            await binding_authorization(session, group, 1)
    assert "/api/common/giftCodeConfig/save" not in requests


@pytest.mark.asyncio
async def test_expired_lease_recovery_and_stale_owner_cannot_commit(db):
    factory, _ = db
    async with factory() as session:
        await service.request_sync(session, 1, 1)
    first = await claim_next(factory)
    async with factory() as session:
        run = await session.get(RedemptionClaimRun, first[0])
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    second = await claim_next(factory)
    assert first[0] == second[0] and first[1] != second[1]
    async with factory() as session:
        with pytest.raises(service.ClaimError, match="租约"):
            await owned_run(session, first[0], first[1])


@pytest.mark.asyncio
async def test_due_scheduler_coalesces_missed_intervals(db):
    factory, _ = db
    async with factory() as session:
        await service.save_schedule(session, 1, 1, False, 30, 0)
        setting = await session.get(RedemptionClaimSchedule, 1)
        setting.enabled = True
        setting.next_run_at = datetime.now(UTC) - timedelta(days=2)
        await session.commit()
    await schedule_due(factory)
    await schedule_due(factory)
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(RedemptionClaimRun)) == 1


@pytest.mark.asyncio
async def test_http_reads_export_and_invalid_interval_are_local(db):
    factory, _ = db
    app = FastAPI()
    app.include_router(router)

    async def database():
        async with factory() as session:
            yield session

    async def auth():
        from types import SimpleNamespace

        return SimpleNamespace(user=SimpleNamespace(id=1))

    app.dependency_overrides[get_db_session] = database
    app.dependency_overrides[get_auth_context] = auth
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        base = "/erp/remote-accounts/compatibility-redemption/claims/tasks/1/claim-statistics"
        response = await client.get(base, params={"dateFrom": "2026-11-01", "dateTo": "2026-11-02"})
        assert response.status_code == 200
        assert len(response.json()["rows"]) == 2
        first_cell = next(iter(response.json()["rows"][0]["cells"].values()))
        assert first_cell["configurationIds"] == ["42"]
        bad = await client.put(
            base + "/sync-settings", json={"enabled": True, "intervalMinutes": 90, "rowVersion": 0}
        )
        assert bad.status_code == 422
        export = await client.get(
            base + "/export", params={"dateFrom": "2026-11-01", "dateTo": "2026-11-02"}
        )
        assert export.status_code == 200
        assert load_workbook(BytesIO(export.content)).sheetnames == [
            "档位每日汇总",
            "单码每日统计",
            "领取明细",
        ]
        exported = await client.get(
            base + "/export",
            params={
                "dateFrom": "2026-11-01",
                "dateTo": "2026-11-02",
                "layout": "template",
                "queryVersion": response.json()["queryVersion"],
                "sourceId": "rajwin",
            },
        )
        assert exported.status_code == 200
        matrix = load_workbook(BytesIO(exported.content))
        assert matrix.sheetnames == ["每日存款兑换码"]
        assert matrix.active["A1"].value == "win"
        assert matrix.active["B2"].value == "充值100"
        assert matrix.active["B3"].value == "待同步"
        stale = await client.get(
            base + "/export",
            params={
                "dateFrom": "2026-11-01",
                "dateTo": "2026-11-02",
                "layout": "template",
                "queryVersion": "stale",
            },
        )
        assert stale.status_code == 409


@pytest.mark.asyncio
async def test_failed_pagination_retains_previous_complete_snapshot(db):
    factory, settings = db
    async with factory() as session:
        group = (await service.materialize_groups(session, 1))[0]
        await service.publish_group(
            session, group, [parse_record(record(1), "group-1", "Asia/Kolkata")]
        )
        await session.commit()
        await service.request_sync(session, 1, 1)

    def broken(request):
        if request.url.path == "/api/system/login":
            return httpx.Response(200, json={"data": {"token": "test-token"}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [record(2)],
                    "pageInfo": {"currentPage": 1, "totalPage": 1, "total": 10},
                }
            },
        )

    await process_claim_sync(factory, settings=settings, transport=httpx.MockTransport(broken))
    async with factory() as session:
        result = await service.summary(session, 1, date(2026, 11, 1), date(2026, 11, 1))
        assert result["rows"][0]["total"]["count"] == 1
        assert not result["rows"][0]["total"]["complete"]
        assert result["schedule"]["lastRun"]["status"] == "failed"
        assert list(await session.scalars(select(RedemptionClaimRecord.remote_id))) == ["1"]


@pytest.mark.asyncio
async def test_new_local_zero_codes_are_visible_and_pending_identity_is_retired(db):
    factory, _ = db
    async with factory() as session:
        group = (await service.materialize_groups(session, 1))[0]
        await service.publish_group(session, group, [])
        await session.commit()
        initial = await service.summary(session, 1, date(2026, 11, 1), date(2026, 11, 1))
        await session.execute(
            text("INSERT INTO erp_compat_redemption_issue_codes VALUES (1,2,'CODE0003')")
        )
        await session.commit()
        changed = await service.summary(session, 1, date(2026, 11, 1), date(2026, 11, 1))
        assert changed["queryVersion"] != initial["queryVersion"]
        detail = await service.code_details(
            session, 1, date(2026, 11, 1), group.column_key, changed["queryVersion"]
        )
        assert len(detail["items"]) == 3
        assert all(row["count"] == 0 for row in detail["items"])
        with pytest.raises(service.ClaimError, match="结束日期"):
            await service.summary(session, 1, date(2026, 11, 2), date(2026, 11, 1))


@pytest.mark.asyncio
async def test_source_mismatch_and_local_permission_revocation_block_remote_reads(db):
    factory, settings = db
    called = []

    def forbidden_network(request):
        called.append(request)
        raise AssertionError("Unauthorized request must not reach transport")

    async with factory() as session:
        await service.request_sync(session, 1, 1)
        admin = await session.get(AppUser, 1)
        admin.is_active = False
        await session.commit()
    await process_claim_sync(
        factory, settings=settings, transport=httpx.MockTransport(forbidden_network)
    )
    assert not called
    async with factory() as session:
        admin = await session.get(AppUser, 1)
        admin.is_active = True
        await session.commit()
        group = (await service.materialize_groups(session, 1))[0]
        group.source_id = "rajluck"
        await session.commit()
        with pytest.raises(service.ClaimError, match="不匹配"):
            await binding_authorization(session, group, 1)


async def add_claim_backup(factory, settings, *, source_id="rajwin", enabled=True, grant=True):
    async with factory() as session:
        if source_id != "rajwin":
            session.add(
                SourceConfig(
                    source_id=source_id,
                    display_name=source_id,
                    enabled=True,
                    base_url="https://other.example.test",
                    business_timezone="Asia/Kolkata",
                )
            )
            await session.commit()
        view = await create_remote_account(
            session,
            request=RemoteAccountCreateRequest(
                source_id=source_id,
                login_username="claim-backup",
                display_name="Backup",
                enabled=enabled,
                is_default=False,
                credentials=RemoteAccountCredentialsWrite(
                    password="backup-test-password", totp_secret="JBSWY3DPEHPK3PXP"
                ),
            ),
            actor_user_id=1,
            settings=settings,
        )
        capability = await session.get(
            RemoteAccountCapability, (view.account.id, "ERP_REDEMPTION_CLAIM_READ")
        )
        capability.enabled = grant
        await session.commit()
        return view.account.id


def claim_response(items, *, page=1, total=None):
    total = len(items) if total is None else total
    return httpx.Response(
        200,
        json={
            "data": {
                "items": items,
                "pageInfo": {"currentPage": page, "total": total, "totalPage": (total + 99) // 100},
            }
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [403, 429, 503, "network", "login", "business"])
async def test_claim_request_failure_uses_granted_same_market_backup(db, failure):
    factory, settings = db
    backup_id = await add_claim_backup(factory, settings)
    logins, claims = [], []

    def handler(request):
        if request.url.path == "/api/system/login":
            import json

            username = json.loads(request.content)["username"]
            logins.append(username)
            if username == "claim-test" and failure == "login":
                return httpx.Response(401)
            return httpx.Response(200, json={"data": {"token": f"test-{username}"}})
        assert request.method == "GET" and request.url.path == "/api/common/userGift/index"
        account = request.headers["authorization"]
        claims.append(account)
        if account == "Bearer test-claim-test":
            if failure == "network":
                raise httpx.ConnectError("test-only connection failure", request=request)
            if failure == "business":
                return httpx.Response(200, json={"success": False, "code": 403})
            return httpx.Response(failure)
        assert account == "Bearer test-claim-backup"
        return claim_response([record(1), record(2)])

    async with factory() as session:
        await service.request_sync(session, 1, 1)
        original_binding = await session.scalar(
            text("select remote_connection_id from erp_compat_redemption_code_batches where id=1")
        )
    await process_claim_sync(factory, settings=settings, transport=httpx.MockTransport(handler))
    async with factory() as session:
        run = await session.scalar(select(RedemptionClaimRun))
        assert run.status == "succeeded"
        assert run.progress["backupGroups"] == 1
        assert run.progress["accountUsage"] == [
            {
                "sourceId": "rajwin",
                "accountId": backup_id,
                "accountName": "Backup",
                "backup": True,
                "groups": 1,
            }
        ]
        assert await session.scalar(select(func.count()).select_from(RedemptionClaimRecord)) == 2
        assert (
            await session.scalar(
                text(
                    "select remote_connection_id from erp_compat_redemption_code_batches where id=1"
                )
            )
            == original_binding
        )
        backup = await session.get(RemoteAccount, backup_id)
        assert not backup.is_default and backup.session_ciphertext
        assert logins == ["claim-test", "claim-backup"]
        if failure != "login":
            assert claims.count("Bearer test-claim-test") == 1
        audit = await session.scalar(
            select(SecurityAuditLog).where(
                SecurityAuditLog.action == "redemption_claims.read_account_fallback"
            )
        )
        assert audit is not None


@pytest.mark.asyncio
async def test_backup_restarts_page_one_without_mixing_accounts(db):
    factory, settings = db
    await add_claim_backup(factory, settings)
    calls = []

    def handler(request):
        if request.url.path == "/api/system/login":
            import json

            return httpx.Response(
                200, json={"data": {"token": f"test-{json.loads(request.content)['username']}"}}
            )
        account = request.headers["authorization"]
        page = int(request.url.params["page"])
        calls.append((account, page))
        if account == "Bearer test-claim-test":
            return (
                claim_response([record(i) for i in range(1, 101)], total=101)
                if page == 1
                else httpx.Response(503)
            )
        records = [record(i) for i in range(1001, 1102)]
        return claim_response(records[(page - 1) * 100 : page * 100], page=page, total=101)

    async with factory() as session:
        await service.request_sync(session, 1, 1)
    await process_claim_sync(factory, settings=settings, transport=httpx.MockTransport(handler))
    assert calls == [
        ("Bearer test-claim-test", 1),
        ("Bearer test-claim-test", 2),
        ("Bearer test-claim-backup", 1),
        ("Bearer test-claim-backup", 2),
        ("Bearer test-claim-backup", 1),
    ]
    async with factory() as session:
        ids = list(await session.scalars(select(RedemptionClaimRecord.remote_id)))
        assert len(ids) == 101 and all(int(value) >= 1001 for value in ids)


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["disabled", "ungranted", "other-market"])
async def test_ineligible_backup_never_receives_claim_request(db, unavailable):
    factory, settings = db
    await add_claim_backup(
        factory,
        settings,
        enabled=unavailable != "disabled",
        grant=unavailable != "ungranted",
        source_id="rajluck" if unavailable == "other-market" else "rajwin",
    )
    logins = []

    def handler(request):
        if request.url.path == "/api/system/login":
            import json

            logins.append(json.loads(request.content)["username"])
            return httpx.Response(200, json={"data": {"token": "test-primary"}})
        return httpx.Response(403)

    async with factory() as session:
        await service.request_sync(session, 1, 1)
    await process_claim_sync(factory, settings=settings, transport=httpx.MockTransport(handler))
    assert logins == ["claim-test"]
    async with factory() as session:
        assert (await session.scalar(select(RedemptionClaimRun))).status == "failed"
        assert await session.scalar(select(func.count()).select_from(RedemptionClaimRecord)) == 0


@pytest.mark.asyncio
async def test_claim_data_conflict_does_not_switch_accounts(db):
    factory, settings = db
    await add_claim_backup(factory, settings)
    logins = []

    def handler(request):
        if request.url.path == "/api/system/login":
            import json

            logins.append(json.loads(request.content)["username"])
            return httpx.Response(200, json={"data": {"token": "test-primary"}})
        return claim_response([record(1), {**record(1), "uid": 800002}])

    async with factory() as session:
        await service.request_sync(session, 1, 1)
    await process_claim_sync(factory, settings=settings, transport=httpx.MockTransport(handler))
    assert logins == ["claim-test"]
    async with factory() as session:
        run = await session.scalar(select(RedemptionClaimRun))
        assert run.status == "failed" and "内容不一致" in run.progress["errors"][0]["message"]
        assert await session.scalar(select(func.count()).select_from(RedemptionClaimRecord)) == 0


@pytest.mark.asyncio
async def test_permission_revocation_during_read_cannot_fail_over(db):
    factory, settings = db
    await add_claim_backup(factory, settings)
    logins, pages = [], []

    async def handler(request):
        if request.url.path == "/api/system/login":
            import json

            logins.append(json.loads(request.content)["username"])
            return httpx.Response(200, json={"data": {"token": "test-primary"}})
        pages.append(int(request.url.params["page"]))
        async with factory() as session:
            actor = await session.get(AppUser, 1)
            actor.is_active = False
            await session.commit()
        return claim_response([record(i) for i in range(1, 101)], total=101)

    async with factory() as session:
        await service.request_sync(session, 1, 1)
    await process_claim_sync(factory, settings=settings, transport=httpx.MockTransport(handler))
    assert pages == [1] and logins == ["claim-test"]
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(RedemptionClaimRecord)) == 0


@pytest.mark.asyncio
async def test_successful_backup_is_reused_within_run_and_default_is_unchanged(db):
    factory, settings = db
    backup_id = await add_claim_backup(factory, settings)
    primary_calls = []

    def handler(request):
        if request.url.path == "/api/system/login":
            import json

            return httpx.Response(
                200, json={"data": {"token": f"test-{json.loads(request.content)['username']}"}}
            )
        if request.headers["authorization"] == "Bearer test-claim-test":
            primary_calls.append(request.url.params["group_key"])
            return httpx.Response(403)
        return claim_response([{**record(1), "group_key": request.url.params["group_key"]}])

    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO erp_compat_redemption_code_issues VALUES "
                "(2,1,1,7,'43','group-2','充值100','2026-11-02',100,5,11,'[901]','CODE0003')"
            )
        )
        await session.commit()
        await service.request_sync(session, 1, 1)
    await process_claim_sync(factory, settings=settings, transport=httpx.MockTransport(handler))
    assert primary_calls == ["group-1"]
    async with factory() as session:
        run = await session.scalar(select(RedemptionClaimRun))
        assert run.status == "succeeded" and run.progress["backupGroups"] == 2
        assert run.progress["accountUsage"][0]["accountId"] == backup_id
        assert run.progress["accountUsage"][0]["groups"] == 2
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SecurityAuditLog)
                .where(SecurityAuditLog.action == "redemption_claims.read_account_fallback")
            )
            == 1
        )
        primary = await session.scalar(
            select(RemoteAccount).where(RemoteAccount.is_default.is_(True))
        )
        assert primary.login_username == "claim-test"


@pytest.mark.asyncio
async def test_all_accounts_failed_preserves_old_snapshot_and_reports_attempts(db):
    factory, settings = db
    backup_id = await add_claim_backup(factory, settings)
    async with factory() as session:
        group = (await service.materialize_groups(session, 1))[0]
        await service.publish_group(
            session, group, [parse_record(record(99), "group-1", "Asia/Kolkata")]
        )
        await session.commit()
        await service.request_sync(session, 1, 1)

    def handler(request):
        if request.url.path == "/api/system/login":
            return httpx.Response(200, json={"data": {"token": "test-rejected"}})
        return httpx.Response(403)

    await process_claim_sync(factory, settings=settings, transport=httpx.MockTransport(handler))
    async with factory() as session:
        run = await session.scalar(select(RedemptionClaimRun))
        assert run.status == "failed"
        assert len(run.progress["errors"][0]["accountIds"]) == 2
        assert backup_id in run.progress["errors"][0]["accountIds"]
        assert list(await session.scalars(select(RedemptionClaimRecord.remote_id))) == ["99"]


@pytest.mark.asyncio
async def test_binding_change_during_primary_failure_stops_before_backup(db):
    factory, settings = db
    await add_claim_backup(factory, settings)
    logins = []

    async def handler(request):
        if request.url.path == "/api/system/login":
            import json

            logins.append(json.loads(request.content)["username"])
            return httpx.Response(200, json={"data": {"token": "test-primary"}})
        async with factory() as session:
            source = await session.get(SourceConfig, "rajwin")
            source.config_version += 1
            await session.commit()
        return httpx.Response(503)

    async with factory() as session:
        await service.request_sync(session, 1, 1)
    await process_claim_sync(factory, settings=settings, transport=httpx.MockTransport(handler))
    assert logins == ["claim-test"]
    async with factory() as session:
        run = await session.scalar(select(RedemptionClaimRun))
        assert run.status == "failed" and "配置已变化" in run.progress["errors"][0]["message"]
        assert await session.scalar(select(func.count()).select_from(RedemptionClaimRecord)) == 0


@pytest.mark.asyncio
async def test_backup_permission_revoked_during_paging_stops_without_publication(db):
    factory, settings = db
    backup_id = await add_claim_backup(factory, settings)
    calls = []

    async def handler(request):
        if request.url.path == "/api/system/login":
            import json

            return httpx.Response(
                200, json={"data": {"token": f"test-{json.loads(request.content)['username']}"}}
            )
        account = request.headers["authorization"]
        calls.append((account, int(request.url.params["page"])))
        if account == "Bearer test-claim-test":
            return httpx.Response(403)
        async with factory() as session:
            capability = await session.get(
                RemoteAccountCapability, (backup_id, "ERP_REDEMPTION_CLAIM_READ")
            )
            capability.enabled = False
            await session.commit()
        return claim_response([record(i) for i in range(1, 101)], total=101)

    async with factory() as session:
        await service.request_sync(session, 1, 1)
    await process_claim_sync(factory, settings=settings, transport=httpx.MockTransport(handler))
    assert calls == [("Bearer test-claim-test", 1), ("Bearer test-claim-backup", 1)]
    async with factory() as session:
        run = await session.scalar(select(RedemptionClaimRun))
        assert run.status == "failed" and "授权已变化" in run.progress["errors"][0]["message"]
        assert await session.scalar(select(func.count()).select_from(RedemptionClaimRecord)) == 0
