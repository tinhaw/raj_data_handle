from __future__ import annotations

from datetime import UTC, datetime

from apps.api.routers.remote_accounts import _compatibility_registry
from packages.domain.models import RemoteAccount, SourceConfig
from packages.domain.services.remote_account_service import RemoteAccountView


def test_compatibility_registry_preserves_ids_without_exposing_credentials() -> None:
    now = datetime(2026, 8, 27, tzinfo=UTC)
    source = SourceConfig(
        source_id="rajluck",
        display_name="RajLuck",
        display_order=2,
        base_url="https://remote.example.test",
        enabled=True,
        config_version=3,
        created_at=now,
        updated_at=now,
    )
    account = RemoteAccount(
        id="2dc71d35-4008-4de8-bfad-9f16c8076c55",
        source_id=source.source_id,
        login_username="sfhk1",
        display_name="sfhk1",
        enabled=True,
        credential_mode="MANAGED",
        encrypted_credentials="v1:must-never-leave-the-main-api",
        credential_version=4,
        created_at=now,
        updated_at=now,
    )
    registry = _compatibility_registry(
        [
            RemoteAccountView(
                account=account,
                source=source,
                capabilities={"ERP_REMOTE_CHECK": True},
            )
        ],
        sources=[source],
        source_ids={source.source_id: 17},
        account_ids={account.id: 23},
    )

    payload = registry.model_dump(mode="json", by_alias=True)
    assert payload["markets"] == [
        {
            "id": 17,
            "canonicalId": "rajluck",
            "code": "RAJLUCK",
            "name": "RajLuck",
            "baseUrl": "https://remote.example.test",
            "enabled": True,
            "rowVersion": 3,
            "createdAt": "2026-08-27T00:00:00Z",
            "updatedAt": "2026-08-27T00:00:00Z",
        }
    ]
    assert payload["connections"][0]["id"] == 23
    assert payload["connections"][0]["canonicalId"] == account.id
    assert payload["connections"][0]["marketId"] == 17
    assert payload["connections"][0]["canonicalMarketId"] == source.source_id
    assert payload["connections"][0]["hasPassword"] is True
    assert "must-never-leave" not in str(payload)
    assert not set(payload["connections"][0]) & {
        "password",
        "totpSecret",
        "encryptedCredentials",
        "accessToken",
    }
