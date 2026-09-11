"""Resolve the online ERP directory into a concrete P5 migration mapping.

The input uses stable business keys (usernames, market codes and remote login
names) instead of database IDs.  The command reads only directory columns from
the source snapshot.  When explicitly applied to an isolated rehearsal or
production-cutover target, it may create disabled, credential-free unified
remote-account placeholders.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from deploy.rehearse_erp_snapshot import (
    ERP_ROLES,
    MIGRATION_NAMESPACE,
    PRODUCTION_CONFIRMATION,
    PROJECTION_ID_BASE,
    TARGET_MODE_ISOLATED,
    TARGET_MODE_PRODUCTION,
    TARGET_MODES,
    RehearsalError,
    RehearsalManifest,
    _enforce_source_read_only,
    _engine,
    _reflect,
    _require_tables,
    _source_version,
    _target_version,
    validate_target_urls,
)

CONFIRMATION = "P5-ISOLATED-DIRECTORY"


@dataclass(frozen=True, slots=True)
class UserDirectoryBinding:
    legacy_username: str
    target_username: str
    target_role_grants: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MarketDirectoryBinding:
    legacy_code: str
    target_source_id: str


@dataclass(frozen=True, slots=True)
class RemoteAccountDirectoryBinding:
    legacy_market_code: str
    legacy_username: str
    target_source_id: str
    target_login_username: str
    target_display_name: str
    create_disabled_placeholder: bool


@dataclass(frozen=True, slots=True)
class DirectorySpec:
    users: tuple[UserDirectoryBinding, ...]
    ignored_legacy_usernames: frozenset[str]
    markets: tuple[MarketDirectoryBinding, ...]
    remote_accounts: tuple[RemoteAccountDirectoryBinding, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> DirectorySpec:
        users = tuple(_parse_user(item) for item in _sequence(value.get("users"), "users"))
        ignored = frozenset(
            _key(item, "ignored_legacy_usernames")
            for item in _sequence(
                value.get("ignored_legacy_usernames", []),
                "ignored_legacy_usernames",
            )
        )
        markets = tuple(_parse_market(item) for item in _sequence(value.get("markets"), "markets"))
        accounts = tuple(
            _parse_remote_account(item)
            for item in _sequence(value.get("remote_accounts"), "remote_accounts")
        )
        _unique((item.legacy_username for item in users), "旧 ERP 用户名")
        _unique((item.target_username for item in users), "当前系统用户名")
        _unique((item.legacy_code for item in markets), "旧盘口代码")
        _unique((item.target_source_id for item in markets), "当前 SourceConfig")
        _unique(
            (f"{item.legacy_market_code}/{item.legacy_username}" for item in accounts),
            "旧远端账号",
        )
        _unique(
            (f"{item.target_source_id}/{item.target_login_username}" for item in accounts),
            "当前统一远端账号",
        )
        if ignored.intersection(item.legacy_username for item in users):
            raise RehearsalError("旧用户不能同时出现在映射和忽略清单中。")
        return cls(users, ignored, markets, accounts)


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise RehearsalError(f"{label} 必须是数组。")
    return value


def _item(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RehearsalError(f"{label} 的每一项必须是对象。")
    return value


def _text(value: Any, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise RehearsalError(f"{label} 不能为空。")
    return normalized


def _key(value: Any, label: str) -> str:
    return _text(value, label).casefold()


def _parse_user(value: Any) -> UserDirectoryBinding:
    item = _item(value, "users")
    roles = tuple(sorted(set(item.get("target_role_grants", []))))
    if set(roles) - ERP_ROLES:
        raise RehearsalError("users 包含当前系统不支持的 ERP 角色。")
    return UserDirectoryBinding(
        legacy_username=_key(item.get("legacy_username"), "legacy_username"),
        target_username=_key(item.get("target_username"), "target_username"),
        target_role_grants=roles,
    )


def _parse_market(value: Any) -> MarketDirectoryBinding:
    item = _item(value, "markets")
    return MarketDirectoryBinding(
        legacy_code=_key(item.get("legacy_code"), "legacy_code"),
        target_source_id=_text(item.get("target_source_id"), "target_source_id"),
    )


def _parse_remote_account(value: Any) -> RemoteAccountDirectoryBinding:
    item = _item(value, "remote_accounts")
    create_placeholder = item.get("create_disabled_placeholder", False)
    if not isinstance(create_placeholder, bool):
        raise RehearsalError("create_disabled_placeholder 必须是布尔值。")
    return RemoteAccountDirectoryBinding(
        legacy_market_code=_key(item.get("legacy_market_code"), "legacy_market_code"),
        legacy_username=_key(item.get("legacy_username"), "legacy_username"),
        target_source_id=_text(item.get("target_source_id"), "target_source_id"),
        target_login_username=_text(item.get("target_login_username"), "target_login_username"),
        target_display_name=_text(item.get("target_display_name"), "target_display_name"),
        create_disabled_placeholder=create_placeholder,
    )


def _unique(values: Sequence[str] | Any, label: str) -> None:
    normalized = list(values)
    if len(set(normalized)) != len(normalized):
        raise RehearsalError(f"{label}映射必须一对一且不能重复。")


def load_directory_spec(path: Path) -> DirectorySpec:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RehearsalError("无法读取 P5 目录映射规则。") from exc
    if not isinstance(payload, Mapping):
        raise RehearsalError("P5 目录映射规则顶层必须是对象。")
    return DirectorySpec.from_mapping(payload)


def _rows_by_key(
    connection: Connection,
    table: sa.Table,
    key_column: str,
    *,
    columns: tuple[str, ...],
    label: str,
) -> dict[str, dict[str, Any]]:
    selected = [table.c[column] for column in columns]
    result: dict[str, dict[str, Any]] = {}
    for raw in connection.execute(sa.select(*selected)).mappings():
        row = dict(raw)
        key = _key(row[key_column], label)
        if key in result:
            raise RehearsalError(f"{label}在快照中不唯一。")
        result[key] = row
    return result


def _placeholder_account_id(binding: RemoteAccountDirectoryBinding) -> str:
    identity = (
        f"online-erp:remote-account:{binding.legacy_market_code}:"
        f"{binding.legacy_username}:{binding.target_source_id}"
    )
    return str(uuid.uuid5(MIGRATION_NAMESPACE, identity))


def _next_compatibility_ids(
    target: Connection,
    maps: sa.Table,
    count: int,
) -> list[int]:
    maximum = target.scalar(
        sa.select(sa.func.max(maps.c.legacy_id)).where(maps.c.entity_type == "remote_account")
    )
    start = max(int(maximum or PROJECTION_ID_BASE), PROJECTION_ID_BASE) + 1
    return list(range(start, start + count))


def _resolve_users(
    source: Connection,
    target: Connection,
    source_meta: sa.MetaData,
    target_meta: sa.MetaData,
    spec: DirectorySpec,
) -> tuple[dict[str, Any], list[int]]:
    source_users = _rows_by_key(
        source,
        source_meta.tables["app_users"],
        "username",
        columns=("id", "username"),
        label="旧 ERP 用户名",
    )
    target_users = _rows_by_key(
        target,
        target_meta.tables["app_users"],
        "username",
        columns=("id", "username"),
        label="当前系统用户名",
    )
    covered = {item.legacy_username for item in spec.users} | set(spec.ignored_legacy_usernames)
    if covered != set(source_users):
        raise RehearsalError("目录规则必须逐一映射或忽略源快照中的每个旧 ERP 用户。")
    result: dict[str, Any] = {}
    for binding in spec.users:
        if binding.target_username not in target_users:
            raise RehearsalError("目录规则引用了不存在的当前系统用户。")
        legacy_id = int(source_users[binding.legacy_username]["id"])
        result[str(legacy_id)] = {
            "target_user_id": int(target_users[binding.target_username]["id"]),
            "target_role_grants": list(binding.target_role_grants),
        }
    ignored = sorted(int(source_users[key]["id"]) for key in spec.ignored_legacy_usernames)
    return result, ignored


def _resolve_markets(
    source: Connection,
    target: Connection,
    source_meta: sa.MetaData,
    target_meta: sa.MetaData,
    spec: DirectorySpec,
) -> tuple[dict[str, str], dict[int, str], dict[str, dict[str, Any]]]:
    market_rows = _rows_by_key(
        source,
        source_meta.tables["redemption_remote_markets"],
        "code",
        columns=("id", "code"),
        label="旧盘口代码",
    )
    source_configs = {
        str(row["source_id"]): dict(row)
        for row in target.execute(
            sa.select(target_meta.tables["source_configs"].c.source_id)
        ).mappings()
    }
    if {item.legacy_code for item in spec.markets} != set(market_rows):
        raise RehearsalError("目录规则必须覆盖源快照中的全部旧盘口。")
    by_legacy_id: dict[str, str] = {}
    target_by_legacy_id: dict[int, str] = {}
    for binding in spec.markets:
        if binding.target_source_id not in source_configs:
            raise RehearsalError("旧盘口目录映射引用了不存在的 SourceConfig。")
        legacy_id = int(market_rows[binding.legacy_code]["id"])
        by_legacy_id[str(legacy_id)] = binding.target_source_id
        target_by_legacy_id[legacy_id] = binding.target_source_id
    return by_legacy_id, target_by_legacy_id, market_rows


def _resolve_remote_accounts(
    source: Connection,
    target: Connection,
    source_meta: sa.MetaData,
    target_meta: sa.MetaData,
    spec: DirectorySpec,
    market_targets: Mapping[int, str],
    market_rows: Mapping[str, Mapping[str, Any]],
    *,
    apply: bool,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    connections = source_meta.tables["redemption_remote_connections"]
    legacy_market_codes = {int(row["id"]): code for code, row in market_rows.items()}
    source_accounts: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in source.execute(
        sa.select(connections.c.id, connections.c.market_id, connections.c.username)
    ).mappings():
        row = dict(raw)
        key = (legacy_market_codes[int(row["market_id"])], _key(row["username"], "旧远端账号"))
        if key in source_accounts:
            raise RehearsalError("旧远端账号业务键在快照中不唯一。")
        source_accounts[key] = row
    if {(item.legacy_market_code, item.legacy_username) for item in spec.remote_accounts} != set(
        source_accounts
    ):
        raise RehearsalError("目录规则必须覆盖源快照中的全部旧远端账号。")

    remote_accounts = target_meta.tables["remote_accounts"]
    existing_accounts: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in target.execute(
        sa.select(
            remote_accounts.c.id,
            remote_accounts.c.source_id,
            remote_accounts.c.login_username,
        ).where(remote_accounts.c.login_username.is_not(None))
    ).mappings():
        row = dict(raw)
        key = (str(row["source_id"]), _key(row["login_username"], "当前远端账号"))
        if key in existing_accounts:
            raise RehearsalError("当前统一远端账号业务键不唯一。")
        existing_accounts[key] = row

    maps = target_meta.tables["erp_compatibility_id_maps"]
    mapped_ids = {
        str(row["canonical_id"]): int(row["legacy_id"])
        for row in target.execute(
            sa.select(maps.c.canonical_id, maps.c.legacy_id).where(
                maps.c.entity_type == "remote_account"
            )
        ).mappings()
    }
    pending = [
        item
        for item in spec.remote_accounts
        if (item.target_source_id, item.target_login_username.casefold()) not in existing_accounts
    ]
    if any(not item.create_disabled_placeholder for item in pending):
        raise RehearsalError("目标统一账号不存在，且目录规则未允许创建禁用占位账号。")
    compatibility_ids = iter(_next_compatibility_ids(target, maps, len(pending)))
    planned: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    for binding in sorted(
        spec.remote_accounts,
        key=lambda item: (item.target_source_id, item.target_login_username.casefold()),
    ):
        source_row = source_accounts[(binding.legacy_market_code, binding.legacy_username)]
        legacy_market_id = int(source_row["market_id"])
        if market_targets[legacy_market_id] != binding.target_source_id:
            raise RehearsalError("旧远端账号的目标盘口与旧盘口映射不一致。")
        target_key = (binding.target_source_id, binding.target_login_username.casefold())
        account_row = existing_accounts.get(target_key)
        created = account_row is None
        if created:
            account_id = _placeholder_account_id(binding)
            if target.scalar(
                sa.select(sa.func.count())
                .select_from(remote_accounts)
                .where(remote_accounts.c.id == account_id)
            ):
                raise RehearsalError("禁用占位账号的确定性 ID 已被其他账号占用。")
            compatibility_id = next(compatibility_ids)
            if apply:
                target.execute(
                    sa.insert(remote_accounts),
                    {
                        "id": account_id,
                        "source_id": binding.target_source_id,
                        "login_username": binding.target_login_username,
                        "display_name": binding.target_display_name,
                        "enabled": False,
                        "credential_mode": "MANAGED",
                        "encrypted_credentials": None,
                        "credential_version": 0,
                        "credential_updated_at": None,
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_request_id": None,
                        "created_by": None,
                        "updated_by": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                target.execute(
                    sa.insert(maps),
                    {
                        "entity_type": "remote_account",
                        "legacy_id": compatibility_id,
                        "canonical_id": account_id,
                        "created_at": now,
                    },
                )
            mapped_ids[account_id] = compatibility_id
        else:
            account_id = str(account_row["id"])
            if account_id not in mapped_ids:
                raise RehearsalError("当前统一 RemoteAccount 缺少 0035 数字 ID 映射。")
            compatibility_id = mapped_ids[account_id]
        planned.append(
            {
                "legacy_connection_id": int(source_row["id"]),
                "account_id": account_id,
                "source_id": binding.target_source_id,
                "created_disabled_placeholder": created,
                "compatibility_id": compatibility_id,
                "credentials_copied": False,
                "capabilities_granted": False,
            }
        )
    return {str(item["legacy_connection_id"]): str(item["account_id"]) for item in planned}, planned


def prepare_directory_mapping(
    *,
    source_url: str,
    target_url: str,
    spec: DirectorySpec,
    apply: bool,
    confirmation: str | None = None,
    target_mode: str = TARGET_MODE_ISOLATED,
    production_confirmation: str | None = None,
) -> dict[str, Any]:
    source_parsed, target_parsed = validate_target_urls(
        source_url,
        target_url,
        target_mode=target_mode,
        production_confirmation=production_confirmation,
    )
    expected_confirmation = (
        CONFIRMATION if target_mode == TARGET_MODE_ISOLATED else PRODUCTION_CONFIRMATION
    )
    if apply and confirmation != expected_confirmation:
        raise RehearsalError(f"写入目标库目录必须显式确认 {expected_confirmation}。")
    source_engine = _engine(source_parsed)
    target_engine = _engine(target_parsed)
    try:
        target_context = target_engine.begin() if apply else target_engine.connect()
        with source_engine.connect() as source, target_context as target:
            _enforce_source_read_only(source)
            source_meta = _reflect(source)
            target_meta = _reflect(target)
            _require_tables(
                source_meta,
                {
                    "app_users",
                    "redemption_remote_markets",
                    "redemption_remote_connections",
                    "flyway_schema_history",
                },
                "源快照",
            )
            _require_tables(
                target_meta,
                {
                    "app_users",
                    "source_configs",
                    "remote_accounts",
                    "remote_account_capabilities",
                    "erp_compatibility_id_maps",
                    "alembic_version",
                },
                "目标演练库",
            )
            source_version = _source_version(source, source_meta)
            target_version = _target_version(target, target_meta)
            users, ignored = _resolve_users(source, target, source_meta, target_meta, spec)
            markets, market_targets, market_rows = _resolve_markets(
                source, target, source_meta, target_meta, spec
            )
            accounts, account_plan = _resolve_remote_accounts(
                source,
                target,
                source_meta,
                target_meta,
                spec,
                market_targets,
                market_rows,
                apply=apply,
            )
            manifest_payload = {
                "legacy_users": users,
                "ignored_legacy_user_ids": ignored,
                "legacy_markets": markets,
                "legacy_remote_accounts": accounts,
            }
            RehearsalManifest.from_mapping(manifest_payload)
            return {
                "mode": "apply" if apply else "preflight",
                "target_mode": target_mode,
                "passed": True,
                "source_schema": source_version,
                "target_schema": target_version,
                "mapping": manifest_payload,
                "directory": {
                    "mapped_users": len(users),
                    "ignored_users": len(ignored),
                    "markets": len(markets),
                    "remote_accounts": account_plan,
                },
                "safety": {
                    "placeholders_enabled": False,
                    "credentials_copied": False,
                    "capabilities_granted": False,
                    "remote_operations_executed": False,
                },
            }
    finally:
        source_engine.dispose()
        target_engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-mapping", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--source-url-env", default="ERP_P5_SOURCE_SNAPSHOT_URL")
    parser.add_argument("--target-url-env", default="ERP_P5_TARGET_REHEARSAL_URL")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--target-mode",
        choices=TARGET_MODES,
        default=TARGET_MODE_ISOLATED,
    )
    parser.add_argument("--confirm-isolated-directory")
    parser.add_argument("--confirm-production-directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source_url = os.environ.get(args.source_url_env, "")
        target_url = os.environ.get(args.target_url_env, "")
        if not source_url or not target_url:
            raise RehearsalError("源快照和目标演练库 URL 必须通过指定环境变量提供。")
        production_confirmation = (
            args.confirm_production_directory
            if args.target_mode == TARGET_MODE_PRODUCTION
            else None
        )
        confirmation = (
            args.confirm_isolated_directory
            if args.target_mode == TARGET_MODE_ISOLATED
            else args.confirm_production_directory
        )
        result = prepare_directory_mapping(
            source_url=source_url,
            target_url=target_url,
            spec=load_directory_spec(args.spec),
            apply=args.apply,
            confirmation=confirmation,
            target_mode=args.target_mode,
            production_confirmation=production_confirmation,
        )
        if args.output_mapping:
            args.output_mapping.parent.mkdir(parents=True, exist_ok=True)
            args.output_mapping.write_text(
                json.dumps(result["mapping"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    except RehearsalError as exc:
        print(f"P5 目录准备失败：{exc}", file=sys.stderr)
        return 2
    except Exception:
        print("P5 目录准备失败：数据库操作未完成；未输出敏感错误详情。", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
