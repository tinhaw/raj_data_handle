from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

RENDERER_PATH = Path(__file__).parents[1] / "deploy" / "render_rajluck_env.py"
SPEC = importlib.util.spec_from_file_location("render_rajluck_env", RENDERER_PATH)
assert SPEC and SPEC.loader
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


def write_deployment_config(path: Path) -> None:
    path.write_text(
        """deployments:
  raj-data-handle:
    project:
      name: raj-data-handle
      type: data_analysis
    host:
      name: Raj Data Handle host
      role: data_analysis
      ecs_host: 203.0.113.10
      ssh_user: root
      ssh_port: 22
      ssh_authentication: public_key
      ssh_host_key_checking: strict
    web:
      access_mode: direct_http
      port: 18080
    runtime:
      node_id: raj-data-handle
    rds:
      connection_type: aliyun_vpc_rds
      host: rds.example.test
      host_scope: vpc
      connect_via: ecs
      public_access: false
      port: 5432
      database: data_handle
""",
        encoding="utf-8",
    )


def test_renderer_reads_rds_credentials_from_local_env_and_url_encodes_password(
    tmp_path: Path,
) -> None:
    app_secrets = tmp_path / "app.env"
    app_secrets.write_text(
        "RAJ_RDS_USERNAME=data_handle_user\n"
        "RAJ_RDS_PASSWORD=p@ss word:'&\n"
        "RAJ_SECRET_KEY=0123456789abcdef0123456789abcdef\n"
        "RAJ_CREDENTIAL_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\n",
        encoding="utf-8",
    )

    values = renderer.build_runtime_env(
        renderer.read_env_file(app_secrets),
        rds_host="rds.example.test",
        rds_port=5433,
        rds_database="data_handle",
        public_web_host="203.0.113.10",
        web_port=18080,
    )

    assert values["RAJ_DATABASE_URL"] == (
        "postgresql+asyncpg://data_handle_user:p%40ss%20word%3A%27%26@"
        "rds.example.test:5433/data_handle"
    )
    quoted_url = renderer.ensure_compose_env_safe("RAJ_DATABASE_URL", values["RAJ_DATABASE_URL"])
    assert quoted_url.startswith("'")
    assert values["RAJ_CORS_ORIGINS"] == '["http://203.0.113.10:18080"]'


def test_renderer_rejects_non_data_handle_database() -> None:
    app_secrets = {
        "RAJ_RDS_USERNAME": "data_handle_user",
        "RAJ_RDS_PASSWORD": "secret",
        "RAJ_SECRET_KEY": "0123456789abcdef0123456789abcdef",
        "RAJ_CREDENTIAL_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    }

    with pytest.raises(renderer.RenderError, match="data_handle"):
        renderer.build_runtime_env(
            app_secrets,
            rds_host="rds.example.test",
            rds_port=5432,
            rds_database="review_recheck",
            public_web_host="203.0.113.10",
            web_port=18080,
        )


def test_renderer_uses_yaml_web_settings_for_direct_http() -> None:
    app_secrets = {
        "RAJ_RDS_USERNAME": "data_handle_user",
        "RAJ_RDS_PASSWORD": "secret",
        "RAJ_SECRET_KEY": "0123456789abcdef0123456789abcdef",
        "RAJ_CREDENTIAL_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    }

    values = renderer.build_runtime_env(
        app_secrets,
        rds_host="rds.example.test",
        rds_port=5432,
        rds_database="data_handle",
        public_web_host="203.0.113.10",
        web_port=19090,
    )
    assert values["WEB_BIND_ADDRESS"] == "0.0.0.0"
    assert values["WEB_PORT"] == "19090"
    assert values["RAJ_SESSION_COOKIE_SECURE"] == "false"
    assert values["RAJ_CORS_ORIGINS"] == '["http://203.0.113.10:19090"]'


def test_renderer_ignores_legacy_web_values_in_private_env() -> None:
    app_secrets = {
        "RAJ_RDS_USERNAME": "data_handle_user",
        "RAJ_RDS_PASSWORD": "secret",
        "RAJ_SECRET_KEY": "0123456789abcdef0123456789abcdef",
        "RAJ_CREDENTIAL_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "RAJ_SESSION_COOKIE_SECURE": "true",
        "RAJ_CORS_ORIGINS": '["https://analytics.example.test"]',
        "WEB_BIND_ADDRESS": "127.0.0.1",
        "WEB_PORT": "443",
    }

    values = renderer.build_runtime_env(
        app_secrets,
        rds_host="rds.example.test",
        rds_port=5432,
        rds_database="data_handle",
        public_web_host="203.0.113.10",
        web_port=18080,
    )
    assert values["WEB_BIND_ADDRESS"] == "0.0.0.0"
    assert values["WEB_PORT"] == "18080"
    assert values["RAJ_CORS_ORIGINS"] == '["http://203.0.113.10:18080"]'


def test_renderer_uses_https_and_loopback_for_cloudflare_reverse_proxy() -> None:
    app_secrets = {
        "RAJ_RDS_USERNAME": "data_handle_user",
        "RAJ_RDS_PASSWORD": "secret",
        "RAJ_SECRET_KEY": "0123456789abcdef0123456789abcdef",
        "RAJ_CREDENTIAL_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    }

    values = renderer.build_runtime_env(
        app_secrets,
        rds_host="rds.example.test",
        rds_port=5432,
        rds_database="data_handle",
        public_web_host="analysis.example.test",
        web_port=18080,
        access_mode="cloudflare_reverse_proxy",
    )

    assert values["WEB_BIND_ADDRESS"] == "127.0.0.1"
    assert values["WEB_PORT"] == "18080"
    assert values["RAJ_SESSION_COOKIE_SECURE"] == "true"
    assert values["RAJ_CORS_ORIGINS"] == '["https://analysis.example.test"]'


def test_renderer_main_writes_a_private_env_without_echoing_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    app_secrets = tmp_path / "app.env"
    app_secrets.write_text(
        "RAJ_RDS_USERNAME=data_handle_user\n"
        "RAJ_RDS_PASSWORD=do-not-log-me\n"
        "RAJ_SECRET_KEY=0123456789abcdef0123456789abcdef\n"
        "RAJ_CREDENTIAL_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\n",
        encoding="utf-8",
    )
    output_file = tmp_path / "runtime.env"
    deployment_config = tmp_path / "deployments.local.yml"
    write_deployment_config(deployment_config)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "render_rajluck_env.py",
            "--deployment-config",
            str(deployment_config),
            "--app-secrets-file",
            str(app_secrets),
            "--output",
            str(output_file),
            "--summary",
        ],
    )

    assert renderer.main() == 0

    assert output_file.stat().st_mode & 0o777 == 0o600
    assert "do-not-log-me" not in capsys.readouterr().out
