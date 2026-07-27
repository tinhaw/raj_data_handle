"""Read and validate the local Raj Data Handle deployment target.

The target stores the ECS endpoint plus the non-sensitive RDS endpoint and
database name. RDS credentials are intentionally supplied only by the ignored
local application secrets file.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from ipaddress import AddressValueError, IPv4Address
from pathlib import Path
from typing import Any

import yaml

DEFAULT_DEPLOYMENT_ID = "raj-data-handle"


class DeploymentConfigError(RuntimeError):
    """Raised when a local deployment target is absent or unsafe."""


@dataclass(frozen=True, slots=True)
class DataHandleDeploymentTarget:
    deployment_id: str
    host_name: str
    ssh_user: str
    ssh_host: str
    ssh_port: int
    web_access_mode: str
    web_hostname: str | None
    web_port: int
    rds_host: str
    rds_port: int

    def public_summary(self) -> dict[str, Any]:
        return asdict(self)


def _require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DeploymentConfigError(f"{label} must be a mapping")
    return value


def _require_string(
    value: object,
    label: str,
    *,
    pattern: str | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeploymentConfigError(f"{label} must be a non-empty string")
    normalized = value.strip()
    if pattern and re.fullmatch(pattern, normalized) is None:
        raise DeploymentConfigError(f"{label} contains unsupported characters")
    return normalized


def load_data_handle_deployment(
    path: Path,
    deployment_id: str = DEFAULT_DEPLOYMENT_ID,
) -> DataHandleDeploymentTarget:
    if not path.is_file():
        raise DeploymentConfigError(f"deployment configuration file does not exist: {path}")
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        raise DeploymentConfigError(f"deployment configuration is not valid YAML: {path}") from exc

    root = _require_mapping(document, "deployment configuration")
    deployments = _require_mapping(root.get("deployments"), "deployments")
    deployment = _require_mapping(
        deployments.get(deployment_id),
        f"deployments.{deployment_id}",
    )
    project = _require_mapping(deployment.get("project"), f"deployments.{deployment_id}.project")
    host = _require_mapping(deployment.get("host"), f"deployments.{deployment_id}.host")
    web = _require_mapping(deployment.get("web"), f"deployments.{deployment_id}.web")
    rds = _require_mapping(deployment.get("rds"), f"deployments.{deployment_id}.rds")
    runtime = _require_mapping(
        deployment.get("runtime"),
        f"deployments.{deployment_id}.runtime",
    )

    if project.get("name") != "raj-data-handle" or project.get("type") != "data_analysis":
        raise DeploymentConfigError(
            f"deployments.{deployment_id} must describe the raj-data-handle analysis project"
        )
    if host.get("role") != "data_analysis":
        raise DeploymentConfigError(f"deployments.{deployment_id}.host.role must be data_analysis")
    if host.get("ssh_authentication") != "public_key":
        raise DeploymentConfigError(
            f"deployments.{deployment_id}.host.ssh_authentication must be public_key"
        )
    if host.get("ssh_host_key_checking") != "strict":
        raise DeploymentConfigError(
            f"deployments.{deployment_id}.host.ssh_host_key_checking must be strict"
        )
    if runtime.get("node_id") != deployment_id:
        raise DeploymentConfigError(
            f"deployments.{deployment_id}.runtime.node_id must equal the deployment id"
        )
    access_mode = web.get("access_mode")
    if access_mode not in {"direct_http", "cloudflare_reverse_proxy"}:
        raise DeploymentConfigError(
            f"deployments.{deployment_id}.web.access_mode must be direct_http or "
            "cloudflare_reverse_proxy"
        )
    web_hostname: str | None = None
    if access_mode == "cloudflare_reverse_proxy":
        web_hostname = _require_string(
            web.get("hostname"),
            f"deployments.{deployment_id}.web.hostname",
            pattern=r"[A-Za-z0-9.-]+",
        ).lower()
        if (
            web_hostname.startswith(".")
            or web_hostname.endswith(".")
            or "." not in web_hostname
            or ".." in web_hostname
        ):
            raise DeploymentConfigError(
                f"deployments.{deployment_id}.web.hostname must be a DNS hostname"
            )
    if rds.get("connect_via") != "ecs" or rds.get("public_access") is not False:
        raise DeploymentConfigError("RDS must be marked ECS-only with public_access=false")
    if rds.get("host_scope") != "vpc":
        raise DeploymentConfigError("RDS host_scope must be vpc")
    if rds.get("database") != "data_handle":
        raise DeploymentConfigError("RDS database must be data_handle")

    raw_port = host.get("ssh_port")
    if not isinstance(raw_port, int) or not 1 <= raw_port <= 65535:
        raise DeploymentConfigError(f"deployments.{deployment_id}.host.ssh_port is invalid")
    raw_rds_port = rds.get("port")
    if not isinstance(raw_rds_port, int) or not 1 <= raw_rds_port <= 65535:
        raise DeploymentConfigError(f"deployments.{deployment_id}.rds.port is invalid")
    raw_web_port = web.get("port")
    if not isinstance(raw_web_port, int) or not 1 <= raw_web_port <= 65535:
        raise DeploymentConfigError(f"deployments.{deployment_id}.web.port is invalid")

    ssh_host = _require_string(
        host.get("ecs_host"),
        "host.ecs_host",
        pattern=r"[A-Za-z0-9.-]+",
    )
    try:
        IPv4Address(ssh_host)
    except AddressValueError as exc:
        raise DeploymentConfigError(
            f"deployments.{deployment_id}.host.ecs_host must be an IPv4 address for direct access"
        ) from exc

    return DataHandleDeploymentTarget(
        deployment_id=_require_string(
            deployment_id,
            "deployment id",
            pattern=r"[A-Za-z0-9_-]+",
        ),
        host_name=_require_string(host.get("name"), "host.name"),
        ssh_user=_require_string(
            host.get("ssh_user"),
            "host.ssh_user",
            pattern=r"[A-Za-z0-9_-]+",
        ),
        ssh_host=ssh_host,
        ssh_port=raw_port,
        web_access_mode=access_mode,
        web_hostname=web_hostname,
        web_port=raw_web_port,
        rds_host=_require_string(
            rds.get("host"),
            "rds.host",
            pattern=r"[A-Za-z0-9.-]+",
        ),
        rds_port=raw_rds_port,
    )
