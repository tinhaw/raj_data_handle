from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_production_compose_keeps_compatibility_runtime_on_shared_data_handle_boundary() -> None:
    compose = (ROOT / "deploy" / "compose.rajluck.yml").read_text(encoding="utf-8")

    assert "erp-compat:" in compose
    assert "SPRING_DATASOURCE_URL: ${ERP_COMPAT_DATABASE_URL:" in compose
    assert 'ERP_COMPATIBILITY_MODE_ENABLED: "true"' in compose
    assert 'ERP_COMPAT_STANDALONE_AUTH_ENABLED: "false"' in compose
    assert 'ERP_COMPAT_FLYWAY_ENABLED: "false"' in compose
    assert "ERP_COMPAT_DDL_AUTO: none" in compose
    assert 'ERP_COMPAT_REMOTE_OPERATIONS_ENABLED: "false"' in compose
    assert "http://api:8000/api/v1/erp/access/compatibility-session" in compose
    assert "http://api:8000/api/v1/erp/remote-accounts/compatibility-registry" in compose


def test_web_proxy_exposes_only_the_compatibility_api_mount() -> None:
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")

    assert "location /erp-api/" in nginx
    assert "proxy_pass http://erp-compat:8080/;" in nginx
