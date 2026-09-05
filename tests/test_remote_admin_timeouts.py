from __future__ import annotations

import pytest

from packages.domain.services.remote_charge_service import (
    REMOTE_CONNECT_TIMEOUT_SECONDS,
    REMOTE_REQUEST_TIMEOUT_SECONDS,
    RajAdminChargeClient,
)
from packages.domain.services.remote_spin_service import RajAdminSpinClient
from packages.domain.services.remote_withdraw_service import RajAdminWithdrawClient


@pytest.mark.asyncio
async def test_remote_admin_clients_allow_slow_exports_but_bound_connections() -> None:
    clients = [
        RajAdminChargeClient(
            base_url="https://example.test",
            username="reader",
            password="password",
            totp_secret="JBSWY3DPEHPK3PXP",
        ),
        RajAdminWithdrawClient(
            base_url="https://example.test",
            username="reader",
            password="password",
            totp_secret="JBSWY3DPEHPK3PXP",
        ),
        RajAdminSpinClient(
            base_url="https://example.test",
            username="reader",
            password="password",
            totp_secret="JBSWY3DPEHPK3PXP",
        ),
    ]
    try:
        for client in clients:
            assert client._client.timeout.connect == REMOTE_CONNECT_TIMEOUT_SECONDS
            assert client._client.timeout.read == REMOTE_REQUEST_TIMEOUT_SECONDS
            assert client._client.timeout.write == REMOTE_REQUEST_TIMEOUT_SECONDS
            assert client._client.timeout.pool == REMOTE_REQUEST_TIMEOUT_SECONDS
    finally:
        for client in clients:
            await client.close()
