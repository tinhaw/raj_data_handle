from __future__ import annotations

import re
from pathlib import Path

import yaml

from apps.api.main import app
from packages.domain.schemas.erp_access import ErpCompatibilitySessionResponse

BASELINE_PATH = Path(__file__).parents[1] / "docs" / "erp-online-parity-baseline.yml"


def _baseline() -> dict[str, object]:
    return yaml.safe_load(BASELINE_PATH.read_text(encoding="utf-8"))


def test_online_erp_baseline_covers_every_cloud_page() -> None:
    document = _baseline()
    routes = {page["source_route"] for page in document["pages"]}
    assert routes == {
        "/dashboard",
        "/operators",
        "/balances",
        "/imports",
        "/redemption",
        "/reports",
        "/audit",
        "/users",
        "/settings",
        "/remote-connections",
    }
    target_routes = [page["target_route"] for page in document["pages"]]
    assert len(target_routes) == len(set(target_routes))
    compatibility_routes = [page["compatibility_route"] for page in document["pages"]]
    assert len(compatibility_routes) == len(set(compatibility_routes))
    assert all(
        page["compatibility_component"].endswith(("Page.vue", "View.vue"))
        for page in document["pages"]
    )


def test_online_erp_baseline_uses_cloud_first_compatibility_strategy() -> None:
    document = _baseline()
    assert document["baseline"]["authority"] == "cloud_first"
    assert document["baseline"]["source_build_matches_cloud_main_asset"] is True
    visual_baseline = Path(__file__).parents[1] / document["baseline"][
        "redemption_visual_baseline"
    ]
    assert visual_baseline.is_file()
    assert re.fullmatch(r"[0-9a-f]{40}", document["baseline"]["source_commit"])
    assert document["migration"] == {
        "strategy": "compatibility_module",
        "frontend_mount": "/erp",
        "backend_mount": "/erp-api/api/v1",
        "target_database": "data_handle",
        "shared_identity": True,
        "shared_remote_accounts": True,
        "production_cutover_executed": True,
        "remote_operations_execution_authorized": False,
    }


def test_online_erp_baseline_covers_every_sensitive_remote_operation() -> None:
    document = _baseline()
    operations = {item["operation"] for item in document["remote_operations"]}
    assert operations == {
        "connection_check",
        "tag_read",
        "tag_sync",
        "remote_create",
        "remote_publish",
        "remote_cancel",
        "remote_download",
    }
    assert all(item["required_capability"] for item in document["remote_operations"])
    assert all(item["parity"] != "equivalent" for item in document["remote_operations"])


def test_compatibility_internal_contracts_expose_confirmed_redemption_bridges() -> None:
    internal_routes = {
        route.path: route
        for route in app.routes
        if getattr(route, "path", None)
        in {
            "/api/v1/erp/access/compatibility-session",
            "/api/v1/erp/remote-accounts/compatibility-registry",
            "/api/v1/erp/remote-accounts/compatibility-redemption/create",
            "/api/v1/erp/remote-accounts/compatibility-redemption/publish",
        }
    }
    assert set(internal_routes) == {
        "/api/v1/erp/access/compatibility-session",
        "/api/v1/erp/remote-accounts/compatibility-registry",
        "/api/v1/erp/remote-accounts/compatibility-redemption/create",
        "/api/v1/erp/remote-accounts/compatibility-redemption/publish",
    }
    assert internal_routes["/api/v1/erp/access/compatibility-session"].methods == {"GET"}
    assert internal_routes["/api/v1/erp/remote-accounts/compatibility-registry"].methods == {"GET"}
    assert (
        internal_routes[
            "/api/v1/erp/remote-accounts/compatibility-redemption/create"
        ].methods
        == {"POST"}
    )
    assert (
        internal_routes[
            "/api/v1/erp/remote-accounts/compatibility-redemption/publish"
        ].methods
        == {"POST"}
    )
    assert all(route.include_in_schema is False for route in internal_routes.values())


def test_compatibility_identity_contract_never_contains_secrets() -> None:
    fields = set(ErpCompatibilitySessionResponse.model_fields)
    assert fields == {
        "user_id",
        "username",
        "display_name",
        "global_role",
        "expires_at",
        "role_grants",
        "all_operators",
        "operator_ids",
        "effective_permissions",
    }
    assert not fields & {"password", "token", "cookie", "totp_secret", "credentials"}
