from pathlib import Path

import pytest

from deploy.deployment_config import DeploymentConfigError, load_data_handle_deployment


def write_target_config(
    path: Path,
    *,
    host_role: str = "data_analysis",
    ssh_authentication: str = "public_key",
    access_mode: str = "direct_http",
) -> None:
    path.write_text(
        f"""deployments:
  raj-data-handle:
    project:
      name: raj-data-handle
      type: data_analysis
    host:
      name: Raj Data Handle host
      role: {host_role}
      ecs_host: 203.0.113.10
      ssh_user: root
      ssh_port: 22
      ssh_authentication: {ssh_authentication}
      ssh_host_key_checking: strict
    web:
      access_mode: {access_mode}
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


def test_resolves_the_single_analysis_ecs_target(tmp_path: Path) -> None:
    config = tmp_path / "deployments.local.yml"
    write_target_config(config)

    target = load_data_handle_deployment(config)

    assert target.deployment_id == "raj-data-handle"
    assert target.ssh_user == "root"
    assert target.ssh_host == "203.0.113.10"
    assert target.ssh_port == 22
    assert target.web_access_mode == "direct_http"
    assert target.web_hostname is None
    assert target.web_port == 18080
    assert target.rds_host == "rds.example.test"
    assert target.rds_port == 5432


def test_rejects_a_non_analysis_target(tmp_path: Path) -> None:
    config = tmp_path / "deployments.local.yml"
    write_target_config(config, host_role="recheck")

    with pytest.raises(DeploymentConfigError, match="data_analysis"):
        load_data_handle_deployment(config)


def test_rejects_password_based_ssh_configuration(tmp_path: Path) -> None:
    config = tmp_path / "deployments.local.yml"
    write_target_config(config, ssh_authentication="password")

    with pytest.raises(DeploymentConfigError, match="public_key"):
        load_data_handle_deployment(config)


def test_accepts_cloudflare_reverse_proxy_with_a_hostname(tmp_path: Path) -> None:
    config = tmp_path / "deployments.local.yml"
    write_target_config(config, access_mode="cloudflare_reverse_proxy")
    content = config.read_text(encoding="utf-8").replace(
        "      port: 18080", "      hostname: analysis.example.test\n      port: 18080"
    )
    config.write_text(content, encoding="utf-8")

    target = load_data_handle_deployment(config)

    assert target.web_access_mode == "cloudflare_reverse_proxy"
    assert target.web_hostname == "analysis.example.test"
