#!/usr/bin/env python3
"""Print a validated Raj Data Handle target without reading RDS secrets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .deployment_config import (
        DEFAULT_DEPLOYMENT_ID,
        DeploymentConfigError,
        load_data_handle_deployment,
    )
except ImportError:  # Supports `python deploy/read_rajluck_deployment.py`.
    from deployment_config import (  # type: ignore[no-redef]
        DEFAULT_DEPLOYMENT_ID,
        DeploymentConfigError,
        load_data_handle_deployment,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Read the Raj Data Handle host target.")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--deployment-id", default=DEFAULT_DEPLOYMENT_ID)
    parser.add_argument("--format", choices=("json", "shell"), default="json")
    args = parser.parse_args()

    try:
        target = load_data_handle_deployment(args.config, args.deployment_id)
    except DeploymentConfigError as exc:
        parser.exit(2, f"read_data_handle_deployment: {exc}\n")

    if args.format == "json":
        print(json.dumps(target.public_summary(), ensure_ascii=False))
    else:
        # Values have already been constrained by deployment_config.py and are
        # consumed by push-rajluck.sh without evaluating arbitrary YAML text.
        print(f"DEPLOYMENT_ID={target.deployment_id}")
        print(f"DEPLOYMENT_HOST_NAME={target.host_name}")
        print(f"DEPLOYMENT_SSH_USER={target.ssh_user}")
        print(f"DEPLOYMENT_SSH_HOST={target.ssh_host}")
        print(f"DEPLOYMENT_SSH_PORT={target.ssh_port}")
        print(f"DEPLOYMENT_WEB_ACCESS_MODE={target.web_access_mode}")
        print(f"DEPLOYMENT_WEB_HOSTNAME={target.web_hostname or ''}")
        print(f"DEPLOYMENT_WEB_PORT={target.web_port}")
        print(f"DEPLOYMENT_RDS_HOST={target.rds_host}")
        print(f"DEPLOYMENT_RDS_PORT={target.rds_port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
