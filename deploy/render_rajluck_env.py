#!/usr/bin/env python3
"""Render the production runtime environment without logging secrets."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from urllib.parse import quote, urlsplit

try:
    from .deployment_config import (
        DEFAULT_DEPLOYMENT_ID,
        DeploymentConfigError,
        load_data_handle_deployment,
    )
except ImportError:  # Supports `python deploy/render_rajluck_env.py`.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from deployment_config import (  # type: ignore[no-redef]
        DEFAULT_DEPLOYMENT_ID,
        DeploymentConfigError,
        load_data_handle_deployment,
    )

EXPECTED_DATABASE = "data_handle"
REQUIRED_APP_KEYS = (
    "RAJ_RDS_USERNAME",
    "RAJ_RDS_PASSWORD",
    "RAJ_SECRET_KEY",
    "RAJ_CREDENTIAL_ENCRYPTION_KEY",
)
OPTIONAL_APP_KEYS = (
    "RAJ_UPLOAD_MAX_BYTES",
    "RAJ_UPLOADED_FILE_RETENTION_DAYS",
    "RAJ_RESULT_RETENTION_DAYS",
    "RAJ_REMOTE_CACHE_RETENTION_DAYS",
)


class RenderError(RuntimeError):
    pass


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise RenderError(f"application secrets file does not exist: {path}")

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in raw_line:
            raise RenderError(f"invalid secrets line at {path}:{line_number}")
        key, value = raw_line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise RenderError(f"empty secret key at {path}:{line_number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _normalize_rds_host(raw: str) -> tuple[str, int]:
    value = raw.strip()
    if not value:
        raise RenderError("RDS host is empty")
    if "://" in value:
        raise RenderError("RDS host entry must be a hostname, not a connection URL")
    if value.count(":") == 1:
        host, candidate_port = value.rsplit(":", 1)
        if candidate_port.isdigit():
            port = int(candidate_port)
            if not 1 <= port <= 65535:
                raise RenderError("RDS port is outside the valid range")
            return host, port
    return value, 5432


def require_secret(values: dict[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value or value.startswith("CHANGE_ME") or value.startswith("replace-with"):
        raise RenderError(f"{key} must be set to a real local secret")
    if "\n" in value or "\r" in value:
        raise RenderError(f"{key} must not contain a line break")
    return value


def ensure_compose_env_safe(key: str, value: str) -> str:
    if "\n" in value or "\r" in value:
        raise RenderError(f"{key} must not contain a line break")
    # Docker Compose accepts a single-quoted .env value literally. Escape the
    # one quote form Compose recognizes so passwords or CORS JSON stay intact.
    return "'" + value.replace("'", "\\'") + "'"


def validate_cors_origins(value: str, *, cookie_secure: bool, web_port: int) -> list[str]:
    try:
        cors_origins = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RenderError("RAJ_CORS_ORIGINS must be a JSON array") from exc
    if not isinstance(cors_origins, list) or not cors_origins:
        raise RenderError("RAJ_CORS_ORIGINS must contain at least one origin")

    schemes: set[str] = set()
    for origin in cors_origins:
        if not isinstance(origin, str):
            raise RenderError("each RAJ_CORS_ORIGINS entry must be a string")
        parsed = urlsplit(origin)
        try:
            port = parsed.port
        except ValueError as exc:
            raise RenderError("RAJ_CORS_ORIGINS contains an invalid port") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise RenderError(
                "RAJ_CORS_ORIGINS entries must be HTTP or HTTPS origins without paths"
            )
        schemes.add(parsed.scheme)
        if parsed.scheme == "http" and (port or 80) != web_port:
            raise RenderError("direct HTTP RAJ_CORS_ORIGINS ports must equal WEB_PORT")

    if len(schemes) != 1:
        raise RenderError("HTTP and HTTPS CORS origins cannot be mixed in production")
    scheme = schemes.pop()
    if cookie_secure != (scheme == "https"):
        expected = "true" if scheme == "https" else "false"
        raise RenderError(
            f"RAJ_SESSION_COOKIE_SECURE must be {expected} for {scheme.upper()} origins"
        )
    return cors_origins


def build_runtime_env(
    app_secrets: dict[str, str],
    *,
    rds_host: str,
    rds_port: int,
    rds_database: str,
    public_web_host: str,
    web_port: int,
    access_mode: str = "direct_http",
) -> dict[str, str]:
    for key in REQUIRED_APP_KEYS:
        require_secret(app_secrets, key)

    if len(app_secrets["RAJ_SECRET_KEY"].strip()) < 32:
        raise RenderError("RAJ_SECRET_KEY must contain at least 32 characters")
    try:
        encryption_key = base64.urlsafe_b64decode(
            app_secrets["RAJ_CREDENTIAL_ENCRYPTION_KEY"].strip().encode("ascii")
        )
    except (UnicodeEncodeError, ValueError) as exc:
        raise RenderError("RAJ_CREDENTIAL_ENCRYPTION_KEY must be URL-safe Base64") from exc
    if len(encryption_key) != 32:
        raise RenderError("RAJ_CREDENTIAL_ENCRYPTION_KEY must decode to exactly 32 bytes")
    if rds_database != EXPECTED_DATABASE:
        raise RenderError(f"RDS database must be {EXPECTED_DATABASE}")
    if not 1 <= rds_port <= 65535:
        raise RenderError("RDS port is outside the valid range")
    if not 1 <= web_port <= 65535:
        raise RenderError("web port is outside the valid range")
    host, _ = _normalize_rds_host(rds_host)
    username = require_secret(app_secrets, "RAJ_RDS_USERNAME")
    password = require_secret(app_secrets, "RAJ_RDS_PASSWORD")
    database_url = (
        "postgresql+asyncpg://"
        f"{quote(username, safe='')}:{quote(password, safe='')}@{host}:{rds_port}/{rds_database}"
    )
    erp_compat_database_url = f"jdbc:postgresql://{host}:{rds_port}/{rds_database}"
    if access_mode == "direct_http":
        cookie_secure_raw = "false"
        cors_origins = json.dumps(
            [f"http://{public_web_host}:{web_port}"],
            separators=(",", ":"),
        )
        web_bind_address = "0.0.0.0"
    elif access_mode == "cloudflare_reverse_proxy":
        cookie_secure_raw = "true"
        cors_origins = json.dumps([f"https://{public_web_host}"], separators=(",", ":"))
        web_bind_address = "127.0.0.1"
    else:
        raise RenderError("unsupported web access mode")
    values = {
        "RAJ_ENVIRONMENT": "production",
        "RAJ_DATABASE_URL": database_url,
        "ERP_COMPAT_DATABASE_URL": erp_compat_database_url,
        "ERP_COMPAT_DATABASE_USERNAME": username,
        "ERP_COMPAT_DATABASE_PASSWORD": password,
        "RAJ_REDIS_URL": "redis://redis:6379/0",
        "RAJ_SECRET_KEY": app_secrets["RAJ_SECRET_KEY"].strip(),
        "RAJ_CREDENTIAL_ENCRYPTION_KEY": app_secrets["RAJ_CREDENTIAL_ENCRYPTION_KEY"].strip(),
        "RAJ_SESSION_COOKIE_SECURE": cookie_secure_raw,
        "RAJ_CORS_ORIGINS": cors_origins,
        "RAJ_STORAGE_ROOT": "/app/runtime/uploads",
        "WEB_BIND_ADDRESS": web_bind_address,
        "WEB_PORT": str(web_port),
    }
    for key in OPTIONAL_APP_KEYS:
        value = app_secrets.get(key, "").strip()
        if value:
            values[key] = value

    validate_cors_origins(
        values["RAJ_CORS_ORIGINS"],
        cookie_secure=cookie_secure_raw == "true",
        web_port=web_port,
    )

    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Raj Data Handle production .env.")
    parser.add_argument("--deployment-config", required=True, type=Path)
    parser.add_argument("--deployment-id", default=DEFAULT_DEPLOYMENT_ID)
    parser.add_argument("--app-secrets-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    try:
        deployment = load_data_handle_deployment(
            args.deployment_config,
            args.deployment_id,
        )
        app_secrets = read_env_file(args.app_secrets_file)
        rendered = build_runtime_env(
            app_secrets,
            rds_host=deployment.rds_host,
            rds_port=deployment.rds_port,
            rds_database=EXPECTED_DATABASE,
            public_web_host=deployment.web_hostname or deployment.ssh_host,
            web_port=deployment.web_port,
            access_mode=deployment.web_access_mode,
        )
    except (DeploymentConfigError, RenderError) as exc:
        parser.exit(2, f"render_data_handle_env: {exc}\n")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "\n".join(f"{key}={ensure_compose_env_safe(key, value)}" for key, value in rendered.items())
        + "\n"
    )
    args.output.write_text(content, encoding="utf-8", newline="\n")
    args.output.chmod(0o600)

    if args.summary:
        print(
            json.dumps(
                {
                    "database": EXPECTED_DATABASE,
                    "external_rds": True,
                    "web_bind_address": rendered["WEB_BIND_ADDRESS"],
                    "web_port": rendered["WEB_PORT"],
                    "environment": rendered["RAJ_ENVIRONMENT"],
                    "deployment_id": deployment.deployment_id,
                    "deployment_host": deployment.host_name,
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
