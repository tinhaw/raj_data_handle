from __future__ import annotations

import json

import httpx
import pytest

from packages.domain.services.remote_charge_service import RemoteResponseError
from packages.domain.services.remote_withdraw_service import RajAdminWithdrawClient


@pytest.mark.asyncio
async def test_withdraw_summary_projects_only_the_requested_status_count() -> None:
    observed_bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/operate/withdrawOrder/summary"
        assert request.headers["authorization"] == "Bearer test-token"
        observed_bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"success": True, "code": 200, "data": {"order_num": 12}})

    client = RajAdminWithdrawClient(
        base_url="https://admin.example.test",
        username="reader",
        password="test-password",
        totp_secret="JBSWY3DPEHPK3PXP",
    )
    await client.close()
    client._token = "test-token"
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        count = await client.fetch_withdraw_status_summary(
            create_start="2026-09-08T00:00:00.000Z",
            create_end="2026-09-08T01:00:00.000Z",
            status="0",
        )
    finally:
        await client.close()

    assert count == 12
    assert observed_bodies == [
        {
            "page": 1,
            "pageSize": 10,
            "create_time": ["2026-09-08T00:00:00.000Z", "2026-09-08T01:00:00.000Z"],
            "uid": "",
            "channel": [],
            "pay_channel_name": "",
            "pay_channel": "",
            "order_num": "",
            "out_trade_no": "",
            "is_first": "",
            "update_time": [],
            "status": "0",
            "not_to_back_cash": "",
            "recent": 0,
        }
    ]


@pytest.mark.asyncio
async def test_withdraw_summary_rejects_non_pending_status_without_request() -> None:
    client = RajAdminWithdrawClient(
        base_url="https://admin.example.test",
        username="reader",
        password="test-password",
        totp_secret="JBSWY3DPEHPK3PXP",
    )
    try:
        with pytest.raises(RemoteResponseError, match="不受支持"):
            await client.fetch_withdraw_status_summary(
                create_start="2026-09-08T00:00:00.000Z",
                create_end="2026-09-08T01:00:00.000Z",
                status="3",
            )
    finally:
        await client.close()
