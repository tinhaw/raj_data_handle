"""Pure validation helpers for the unified remote-account domain.

The current analysis ``SourceConfig`` is the migration starting point for a
single account registry shared by analysis and ERP.  This module intentionally
has no database or HTTP dependencies, so the identity and credential rules can
be tested before a separately approved schema migration exists.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from packages.common.settings import Settings

REMOTE_MARKET_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,59}$")


class RemoteAccountIdentityValidationError(ValueError):
    """Raised when a unified market or remote-account identity is invalid."""


def normalize_remote_market_code(value: str) -> str:
    """Normalize the stable, non-secret code of one unified remote market."""

    normalized = value.strip().upper()
    if not REMOTE_MARKET_CODE_PATTERN.fullmatch(normalized):
        raise RemoteAccountIdentityValidationError(
            "远端盘口编码必须为 2-60 位，且只能包含大写字母、数字、下划线和连字符。"
        )
    return normalized


def normalize_remote_market_base_url(value: str, settings: Settings) -> str:
    """Normalize a market root URL for the unified account registry.

    The source ERP accepts either a host root or a trailing ``/api`` path.  The
    canonical record always keeps the host root, because each capability owns
    its API paths. HTTP remains available only to local development.
    """

    parts = urlsplit(value.strip())
    if parts.username or parts.password or parts.query or parts.fragment:
        raise RemoteAccountIdentityValidationError(
            "远端 Base URL 不能包含凭据、查询参数或片段。"
        )
    is_local_dev = settings.environment == "development" and parts.hostname in {
        "localhost",
        "127.0.0.1",
    }
    if parts.scheme != "https" and not (is_local_dev and parts.scheme == "http"):
        raise RemoteAccountIdentityValidationError("远端 Base URL 必须使用 HTTPS。")
    if not parts.hostname:
        raise RemoteAccountIdentityValidationError("远端 Base URL 缺少有效主机名。")

    path = parts.path.rstrip("/")
    if path == "/api":
        path = ""
    elif path not in {"", "/"}:
        raise RemoteAccountIdentityValidationError(
            "远端 Base URL 只能是主机根路径或以 /api 结尾。"
        )
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


def normalize_remote_username(value: str) -> str:
    """Return a non-empty account name without interpreting it as a market ID."""

    normalized = value.strip()
    if not normalized:
        raise RemoteAccountIdentityValidationError("远端账号名不能为空。")
    return normalized


def remote_account_credential_scope(account_id: str) -> str:
    """Return AES-GCM associated data for one account in the shared registry.

    It differs from the legacy ``SourceConfig`` and standalone TOTP scopes. A
    separately approved migration must re-encrypt existing credentials into
    this scope rather than copy plaintext into a second credential store.
    """

    normalized = account_id.strip()
    if not normalized:
        raise RemoteAccountIdentityValidationError("远端账号标识不能为空。")
    return f"remote-account:{normalized}"
