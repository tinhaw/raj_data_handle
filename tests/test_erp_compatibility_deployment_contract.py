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
    assert "http://api:8000/api/v1/erp/access/compatibility-session" in compose
    assert "http://api:8000/api/v1/erp/remote-accounts/compatibility-registry" in compose
    assert "http://api:8000/api/v1/erp/remote-accounts/compatibility-redemption" in compose


def test_web_proxy_exposes_only_the_compatibility_api_mount() -> None:
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")

    assert "location /erp-api/" in nginx
    assert "proxy_pass http://erp-compat:8080/;" in nginx


def test_source_upload_excludes_erp_compatibility_build_artifacts() -> None:
    push_script = (ROOT / "deploy" / "push-rajluck.sh").read_text(encoding="utf-8")

    assert "--exclude='apps/erp-compat/web/node_modules'" in push_script
    assert "--exclude='apps/erp-compat/web/dist'" in push_script
    assert "--exclude='apps/erp-compat/server/target'" in push_script
    assert "--exclude='apps/erp-compat/server/var'" in push_script


def test_web_image_includes_erp_compatibility_source_tree() -> None:
    dockerfile = Path("deploy/web.Dockerfile").read_text(encoding="utf-8")

    assert "COPY apps/erp-compat/web /erp-compat/web" in dockerfile
    assert "ln -s /app/node_modules /node_modules" in dockerfile


def test_compatibility_page_waits_for_bridged_session_before_mounting() -> None:
    module = (ROOT / "apps/web/src/components/ErpCompatibilityModule.vue").read_text(
        encoding="utf-8"
    )

    assert "const sessionReady = ref(false)" in module
    assert "if (session && !session.ready) await session.restore()" in module
    assert "sessionReady.value = true" in module
    assert '<component v-if="sessionReady" :is="page" />' in module


def test_deployed_erp_paths_keep_working_after_entry_cutover() -> None:
    router = (ROOT / "apps/web/src/router/index.ts").read_text(encoding="utf-8")
    expected_redirects = {
        "/dashboard": "/workspace",
        "/operators": "/erp/operators",
        "/balances": "/erp/balances",
        "/imports": "/erp/imports",
        "/redemption": "/erp/redemption",
        "/reports": "/erp/reports",
        "/audit": "/erp/audit",
        "/remote-connections": "/erp/remote-connections",
        "/users": "/settings/users",
        "/settings": "/settings/system",
    }
    for source, target in expected_redirects.items():
        assert f"{{ path: '{source}', redirect: '{target}' }}" in router


def test_legacy_erp_entry_cutover_redirects_only_safe_reads() -> None:
    nginx = (ROOT / "deploy/nginx.erp-entry-cutover.conf").read_text(encoding="utf-8")

    assert "server_name erp.aiggtj.com;" in nginx
    assert "return 302 https://analysis.ailuckdg.com$request_uri;" in nginx
    assert "if ($request_method !~ ^(GET|HEAD)$)" in nginx
    assert "return 405;" in nginx
    assert "Cache-Control \"no-store\"" in nginx


def test_release_wrapper_reuses_one_strict_ssh_connection() -> None:
    push_script = (ROOT / "deploy" / "push-rajluck.sh").read_text(encoding="utf-8")

    assert "ControlMaster=auto" in push_script
    assert "ControlPersist=60" in push_script
    assert 'ControlPath=$SSH_CONTROL_PATH' in push_script
    assert "StrictHostKeyChecking=yes" in push_script
    assert "PreferredAuthentications=publickey" in push_script
