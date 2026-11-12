import json
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_redemption_reuse_check import remote_read
from test_remote_account_service import development_settings

from packages.domain.models import Base
from packages.domain.schemas.remote_account import (
    ErpCompatibilityRemoteDeleteRequest,
    RemoteAccountCapabilityUpdateRequest,
    RemoteAccountCreateRequest,
    RemoteAccountCredentialsWrite,
)
from packages.domain.schemas.source import SourceCreateRequest
from packages.domain.services.erp_compatibility_id_service import register_erp_compatibility_id
from packages.domain.services.erp_compatibility_redemption_delete_service import (
    operate_compatibility_deletion,
)
from packages.domain.services.erp_compatibility_redemption_remote_service import (
    ErpCompatibilityRemoteExecutionError,
)
from packages.domain.services.erp_redemption_remote_http_adapter import RajAdminGiftCodeAdapter
from packages.domain.services.remote_account_service import (
    create_remote_account,
    update_remote_account_capabilities,
)
from packages.domain.services.source_service import create_source


@pytest.mark.asyncio
@pytest.mark.parametrize("write_outcome", ["success", "forbidden"])
async def test_unified_account_delete_is_default_off_and_single_execution_record_cannot_replay(
    monkeypatch,
    write_outcome,
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
        await c.execute(
            text("""CREATE TABLE erp_compat_redemption_code_issues
                    (id integer primary key, remote_deletion_state text)""")
        )
        await c.execute(
            text("""CREATE TABLE erp_compat_redemption_deletions
            (id integer primary key, owner_issue_id integer, requested_issue_id integer,
             configuration_id text, status text, remote_attempted boolean,
             snapshot_json text,remote_json text)""")
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = development_settings()
    monkeypatch.setattr(
        RajAdminGiftCodeAdapter, "_login", AsyncMock(return_value="synthetic-session")
    )
    calls, deleted = [], False
    native_permission = False

    def handler(request):
        nonlocal deleted
        calls.append(request.method)
        if request.url.path == "/api/system/getInfo":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "code": 200,
                    "data": {
                        "codes": ["common:giftCodeConfig:realDelete"] if native_permission else []
                    },
                },
            )
        if request.method == "DELETE":
            if write_outcome == "forbidden":
                return httpx.Response(403)
            deleted = True
            assert json.loads(request.content) == {"ids": [3403]}
            data = {}
        elif request.url.path.endswith("/index"):
            data = {"items": [], "pageInfo": {"currentPage": 1, "total": 0, "totalPage": 1}}
        else:
            data = [] if deleted else {**remote_read(), "group_key": "fixture-group"}
        return httpx.Response(200, json={"success": True, "code": 200, "data": data})

    async with factory() as session:
        source = await create_source(
            session,
            request=SourceCreateRequest(
                source_id="rajwin",
                display_name="Fixture",
                base_url="https://fixture.example",
            ),
            actor_user_id=1,
            settings=settings,
        )
        source.enabled = True
        await session.commit()
        account = await create_remote_account(
            session,
            request=RemoteAccountCreateRequest(
                source_id="rajwin",
                login_username="fixture",
                enabled=True,
                display_name="Fixture",
                credentials=RemoteAccountCredentialsWrite(
                    password="synthetic-password", totp_secret="JBSWY3DPEHPK3PXP"
                ),
            ),
            actor_user_id=1,
            settings=settings,
        )
        legacy = await register_erp_compatibility_id(
            session, entity_type="remote_account", canonical_id=account.account.id
        )
        payload = ErpCompatibilityRemoteDeleteRequest(
            account_id=legacy, issue_id=1, remote_configuration_id="3403", execution_confirmed=True
        )
        args = dict(
            session=session,
            payload=payload,
            actor_user_id=1,
            settings=settings,
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ErpCompatibilityRemoteExecutionError, match="能力授权"):
            await operate_compatibility_deletion(**args, operation="permission")
        assert calls == []
        await update_remote_account_capabilities(
            session,
            account_id=account.account.id,
            request=RemoteAccountCapabilityUpdateRequest(
                capabilities={"ERP_REDEMPTION_DELETE": True}
            ),
            actor_user_id=1,
        )
        # Proven absence only authorizes a local tombstone; no native DELETE is needed.
        await session.execute(
            text(
                "INSERT INTO erp_compat_redemption_deletions "
                "VALUES(0,1,1,'3403','CHECKED',false,:snapshot,:remote)"
            ),
            {
                "snapshot": json.dumps({"accountId": legacy}),
                "remote": json.dumps({"state": "ABSENT"}),
            },
        )
        assert await operate_compatibility_deletion(**args, operation="permission") == {
            "allowed": True
        }
        assert calls == []
        await session.execute(text("DELETE FROM erp_compat_redemption_deletions WHERE id=0"))
        await session.commit()
        # The local capability does not grant the native remote permission for a live target.
        with pytest.raises(ErpCompatibilityRemoteExecutionError, match="真删除.*权限"):
            await operate_compatibility_deletion(**args, operation="permission")
        audit = await session.scalar(
            text(
                "SELECT metadata_json FROM security_audit_logs "
                "WHERE action='erp_compatibility_redemption.delete_permission' "
                "ORDER BY created_at DESC LIMIT 1"
            )
        )
        audit = json.loads(audit) if isinstance(audit, str) else audit
        assert audit["reason_code"] == "REMOTE_DELETE_PERMISSION_MISSING"
        assert audit["failure_phase"] == "PERMISSION"
        assert "message" not in audit and "token" not in audit
        assert "DELETE" not in calls
        native_permission = True
        assert await operate_compatibility_deletion(**args, operation="permission") == {
            "allowed": True
        }
        preview = await operate_compatibility_deletion(**args, operation="preview")
        payload.expected_fingerprint = preview["fingerprint"]
        # A bare confirmed executor request is insufficient without a reserved ERP journal.
        with pytest.raises(ErpCompatibilityRemoteExecutionError, match="一次性"):
            await operate_compatibility_deletion(**args, operation="execute")
        assert "DELETE" not in calls
        await session.execute(
            text("INSERT INTO erp_compat_redemption_code_issues VALUES(1,'DELETING')")
        )
        await session.execute(
            text("""INSERT INTO erp_compat_redemption_deletions VALUES
            (1,1,1,'3403','DELETING',false,:snapshot,:remote)"""),
            {"snapshot": json.dumps({"accountId": legacy}), "remote": json.dumps(preview)},
        )
        await session.commit()
        if write_outcome == "forbidden":
            with pytest.raises(
                ErpCompatibilityRemoteExecutionError, match="远端删除请求.*HTTP 403"
            ):
                await operate_compatibility_deletion(**args, operation="execute")
            audit = await session.scalar(
                text(
                    "SELECT metadata_json FROM security_audit_logs "
                    "WHERE action='erp_compatibility_redemption.delete_execute' "
                    "ORDER BY created_at DESC LIMIT 1"
                )
            )
            audit = json.loads(audit) if isinstance(audit, str) else audit
            assert audit["reason_code"] == "REMOTE_HTTP_ERROR"
            assert audit["failure_phase"] == "DELETE_REQUEST"
            assert audit["http_status"] == 403
        else:
            result = await operate_compatibility_deletion(**args, operation="execute")
            assert result["state"] == "ABSENT"
        assert calls.count("DELETE") == 1
        with pytest.raises(ErpCompatibilityRemoteExecutionError, match="一次性"):
            await operate_compatibility_deletion(**args, operation="execute")
        assert calls.count("DELETE") == 1
        assert await session.scalar(
            text("SELECT remote_attempted FROM erp_compat_redemption_deletions")
        )
    await engine.dispose()
