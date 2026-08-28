"""Import online ERP history from an immutable database snapshot.

The default target mode is an isolated rehearsal database.  Production
``data_handle`` access requires both an explicit production target mode and a
separate fixed confirmation token.  The command copies business history only;
legacy login passwords, sessions and remote-account credentials never leave
the source snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import URL, Connection, Engine, make_url

PROJECTION_ID_BASE = 9_000_000_000_000
CONFIRMATION = "P5-ISOLATED-REHEARSAL"
PRODUCTION_CONFIRMATION = "P5-PRODUCTION-CUTOVER"
TARGET_MODE_ISOLATED = "isolated-rehearsal"
TARGET_MODE_PRODUCTION = "production-cutover"
TARGET_MODES = (TARGET_MODE_ISOLATED, TARGET_MODE_PRODUCTION)
MIGRATION_NAMESPACE = uuid.UUID("a245b5c0-ddb4-4c56-82d3-c6778dd3bd95")

ERP_ROLES = frozenset(
    {
        "ERP_VIEWER",
        "ERP_LEDGER_OPERATOR",
        "ERP_FINANCE_ADMIN",
        "ERP_AUDITOR",
        "ERP_REDEMPTION_MANAGER",
        "ERP_SYSTEM_ADMIN",
    }
)


@dataclass(frozen=True, slots=True)
class TableRule:
    source: str
    target: str
    entity_type: str
    user_columns: tuple[str, ...] = ()
    remote_account_column: str | None = None


TABLE_RULES = (
    TableRule("operators", "erp_compat_operators", "operator", ("created_by", "updated_by")),
    TableRule("operator_accounts", "erp_compat_operator_accounts", "operator_line"),
    TableRule(
        "daily_balances",
        "erp_compat_daily_balances",
        "daily_balance",
        ("created_by", "updated_by", "confirmed_by"),
    ),
    TableRule(
        "accounting_period_locks",
        "erp_compat_accounting_period_locks",
        "period_lock",
        ("locked_by", "unlocked_by"),
    ),
    TableRule(
        "import_jobs",
        "erp_compat_import_jobs",
        "import_job",
        ("created_by", "committed_by"),
    ),
    TableRule("import_job_rows", "erp_compat_import_job_rows", "import_job_row"),
    TableRule("audit_logs", "erp_compat_audit_logs", "audit_log", ("actor_user_id",)),
    TableRule(
        "redemption_campaigns",
        "erp_compat_redemption_campaigns",
        "redemption_campaign",
        ("created_by", "updated_by"),
    ),
    TableRule(
        "redemption_campaign_tiers",
        "erp_compat_redemption_campaign_tiers",
        "redemption_campaign_tier",
    ),
    TableRule(
        "redemption_code_tasks",
        "erp_compat_redemption_code_tasks",
        "redemption_task",
        ("created_by",),
    ),
    TableRule(
        "redemption_code_batches",
        "erp_compat_redemption_code_batches",
        "redemption_batch",
        ("published_by", "created_by"),
        "remote_connection_id",
    ),
    TableRule(
        "redemption_code_issues",
        "erp_compat_redemption_code_issues",
        "redemption_issue",
        ("created_by",),
    ),
)

AMOUNT_COLUMNS: dict[str, tuple[str, ...]] = {
    "daily_balances": (
        "opening_balance",
        "transfer_amount",
        "fraud_loss_amount",
        "effective_transfer_amount",
        "spend_amount",
        "exchange_loss_amount",
        "service_fee_amount",
        "reflux_amount",
        "refund_amount",
        "other_deduction_amount",
        "closing_balance",
    ),
    "redemption_campaign_tiers": (
        "min_deposit_amount",
        "bonus_amount",
        "bonus_max_amount",
    ),
    "redemption_code_issues": (
        "min_deposit_amount",
        "bonus_amount",
        "bonus_max_amount",
    ),
}

SOURCE_TRANSFORMED_TABLES: dict[str, str] = {
    "app_users": "历史操作人按显式用户名目录映射到当前 app_users；密码不复制",
    "roles": "旧角色语义转换为当前 ERP 角色授权",
    "user_roles": "旧用户角色关系转换为当前 ERP 角色授权",
    "user_operator_scopes": "旧公司范围转换为当前 ERP 公司 UUID 范围",
    "redemption_remote_markets": "旧盘口映射到统一 SourceConfig",
    "redemption_remote_connections": "旧账号映射到统一 RemoteAccount；凭据和会话不复制",
    "redemption_reward_tier_presets": "档位和标签快照转换到统一账号本地快照",
}

SOURCE_EXCLUDED_TABLES: dict[str, str] = {
    "permissions": "权限定义由当前 ERP 授权模型提供",
    "role_permissions": "权限关系由当前 ERP 授权模型提供",
    "flyway_schema_history": "仅用于校验源结构版本，不迁移到 Alembic 历史",
}

EXPECTED_SOURCE_TABLES = frozenset(
    {rule.source for rule in TABLE_RULES}
    | set(SOURCE_TRANSFORMED_TABLES)
    | set(SOURCE_EXCLUDED_TABLES)
)


class RehearsalError(RuntimeError):
    """A safe, credential-free P5 preflight or verification failure."""


@dataclass(frozen=True, slots=True)
class UserBinding:
    target_user_id: int
    target_role_grants: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RehearsalManifest:
    users: dict[int, UserBinding]
    ignored_user_ids: frozenset[int]
    markets: dict[int, str]
    remote_accounts: dict[int, str]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RehearsalManifest:
        raw_users = value.get("legacy_users", {})
        users: dict[int, UserBinding] = {}
        if not isinstance(raw_users, Mapping):
            raise RehearsalError("legacy_users 必须是对象。")
        for legacy_id, item in raw_users.items():
            if not isinstance(item, Mapping):
                raise RehearsalError("legacy_users 的每个值必须包含目标用户和角色。")
            target_roles = tuple(sorted(set(item.get("target_role_grants", []))))
            unknown_roles = set(target_roles) - ERP_ROLES
            if unknown_roles:
                raise RehearsalError("legacy_users 包含当前系统不支持的 ERP 角色。")
            users[_positive_int(legacy_id, "旧用户 ID")] = UserBinding(
                target_user_id=_positive_int(item.get("target_user_id"), "目标用户 ID"),
                target_role_grants=target_roles,
            )
        ignored = frozenset(
            _positive_int(item, "忽略的旧用户 ID")
            for item in value.get("ignored_legacy_user_ids", [])
        )
        if ignored.intersection(users):
            raise RehearsalError("旧用户不能同时出现在映射和忽略清单中。")
        markets = _id_string_map(value.get("legacy_markets", {}), "旧盘口")
        accounts = _id_string_map(value.get("legacy_remote_accounts", {}), "旧远端账号")
        if len(set(accounts.values())) != len(accounts):
            raise RehearsalError("每个旧远端账号必须映射到不同的统一远端账号。")
        return cls(users, ignored, markets, accounts)


def _positive_int(value: Any, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RehearsalError(f"{label} 必须是正整数。") from exc
    if result < 1:
        raise RehearsalError(f"{label} 必须是正整数。")
    return result


def _id_string_map(value: Any, label: str) -> dict[int, str]:
    if not isinstance(value, Mapping):
        raise RehearsalError(f"{label}映射必须是对象。")
    result: dict[int, str] = {}
    for legacy_id, canonical_id in value.items():
        normalized = str(canonical_id).strip()
        if not normalized:
            raise RehearsalError(f"{label}映射不能包含空的当前 ID。")
        result[_positive_int(legacy_id, f"{label} ID")] = normalized
    return result


def load_manifest(path: Path) -> RehearsalManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RehearsalError("无法读取 P5 映射清单。") from exc
    if not isinstance(payload, Mapping):
        raise RehearsalError("P5 映射清单顶层必须是对象。")
    return RehearsalManifest.from_mapping(payload)


def _database_label(url: URL) -> str:
    if url.get_backend_name() == "sqlite":
        return Path(url.database or "").name.lower()
    return (url.database or "").lower()


def validate_target_urls(
    source_url: str,
    target_url: str,
    *,
    target_mode: str = TARGET_MODE_ISOLATED,
    production_confirmation: str | None = None,
) -> tuple[URL, URL]:
    try:
        source = make_url(source_url)
        target = make_url(target_url)
    except sa.exc.ArgumentError as exc:
        raise RehearsalError("数据库地址格式无效。") from exc
    if source.render_as_string(hide_password=True) == target.render_as_string(hide_password=True):
        raise RehearsalError("源快照与目标演练库不能相同。")
    source_label = _database_label(source)
    if not any(marker in source_label for marker in ("snapshot", "rehearsal")):
        raise RehearsalError("源数据库名必须明确包含 snapshot 或 rehearsal。")
    target_label = _database_label(target)
    if target_mode == TARGET_MODE_ISOLATED:
        if not any(marker in target_label for marker in ("snapshot", "rehearsal")):
            raise RehearsalError("目标数据库名必须明确包含 snapshot 或 rehearsal。")
        if target_label == "data_handle":
            raise RehearsalError("P5 演练工具禁止连接生产 data_handle 数据库。")
    elif target_mode == TARGET_MODE_PRODUCTION:
        if target_label != "data_handle":
            raise RehearsalError("生产切换模式只允许目标数据库 data_handle。")
        if production_confirmation != PRODUCTION_CONFIRMATION:
            raise RehearsalError(
                f"生产切换模式必须显式确认 {PRODUCTION_CONFIRMATION}。"
            )
    else:
        raise RehearsalError("P5 目标模式无效。")
    return source, target


def validate_isolated_urls(source_url: str, target_url: str) -> tuple[URL, URL]:
    """Backwards-compatible isolated-target validation entry point."""

    return validate_target_urls(source_url, target_url)


def _sync_url(url: URL) -> URL:
    driver = url.drivername
    if driver == "sqlite+aiosqlite":
        return url.set(drivername="sqlite")
    if driver == "postgresql+asyncpg":
        return url.set(drivername="postgresql+psycopg")
    return url


def _engine(url: URL) -> Engine:
    return sa.create_engine(_sync_url(url), future=True)


def _enforce_source_read_only(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text("SET TRANSACTION READ ONLY"))
    elif connection.dialect.name == "sqlite":
        connection.execute(sa.text("PRAGMA query_only = ON"))


def _reflect(connection: Connection) -> sa.MetaData:
    metadata = sa.MetaData()
    metadata.reflect(bind=connection)
    return metadata


def _require_tables(metadata: sa.MetaData, names: Iterable[str], label: str) -> None:
    missing = sorted(set(names) - set(metadata.tables))
    if missing:
        raise RehearsalError(f"{label}缺少 P5 所需表：{', '.join(missing)}")


def _scalar_ids(connection: Connection, table: sa.Table, column: str = "id") -> set[int]:
    return {int(value) for value in connection.scalars(sa.select(table.c[column]))}


def _rows(connection: Connection, table: sa.Table, *, chunk_size: int = 1000):
    result = connection.execute(
        sa.select(table).order_by(table.c.id).execution_options(yield_per=chunk_size)
    )
    for partition in result.mappings().partitions(chunk_size):
        yield [dict(row) for row in partition]


def _canonical_operator_id(legacy_id: int) -> str:
    return str(uuid.uuid5(MIGRATION_NAMESPACE, f"online-erp:operator:{legacy_id}"))


def _canonical_line_id(legacy_id: int) -> str:
    return str(uuid.uuid5(MIGRATION_NAMESPACE, f"online-erp:operator-line:{legacy_id}"))


def _synthetic_canonical_id(entity_type: str, legacy_id: int) -> str:
    return f"online-erp:{entity_type}:{legacy_id}"


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def _digest_rows(rows: Iterable[Mapping[str, Any]], columns: Iterable[str]) -> str:
    digest = hashlib.sha256()
    selected = tuple(columns)
    for row in rows:
        payload = {column: _normalize(row.get(column)) for column in selected}
        digest.update(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _mapped_user(manifest: RehearsalManifest, value: Any) -> int | None:
    if value is None:
        return None
    legacy_id = int(value)
    binding = manifest.users.get(legacy_id)
    if binding is None:
        raise RehearsalError("历史业务记录引用了未映射的旧 ERP 用户。")
    return binding.target_user_id


def _transformed_row(
    row: Mapping[str, Any],
    *,
    rule: TableRule,
    target_columns: set[str],
    manifest: RehearsalManifest,
    remote_numeric_ids: Mapping[int, int],
) -> dict[str, Any]:
    transformed = {key: value for key, value in row.items() if key in target_columns}
    for column in rule.user_columns:
        if column in transformed:
            transformed[column] = _mapped_user(manifest, transformed[column])
    if rule.remote_account_column and transformed.get(rule.remote_account_column) is not None:
        legacy_id = int(transformed[rule.remote_account_column])
        try:
            transformed[rule.remote_account_column] = remote_numeric_ids[legacy_id]
        except KeyError as exc:
            raise RehearsalError("兑换码批次引用了未映射的旧远端账号。") from exc
    return transformed


def _source_version(connection: Connection, metadata: sa.MetaData) -> str:
    table = metadata.tables["flyway_schema_history"]
    version = connection.scalar(
        sa.select(table.c.version)
        .where(table.c.success.is_(True))
        .order_by(sa.cast(table.c.installed_rank, sa.Integer).desc())
        .limit(1)
    )
    if version is None or int(str(version).split(".")[0]) < 19:
        raise RehearsalError("源快照不是已完成 V19 的当前线上 ERP 结构。")
    return str(version)


def _target_version(connection: Connection, metadata: sa.MetaData) -> str:
    version = connection.scalar(sa.select(metadata.tables["alembic_version"].c.version_num))
    if version != "20260828_0038":
        raise RehearsalError("目标演练库必须先升级到 Alembic 20260828_0038。")
    return str(version)


def _validate_user_bindings(
    source: Connection,
    target: Connection,
    source_meta: sa.MetaData,
    target_meta: sa.MetaData,
    manifest: RehearsalManifest,
) -> dict[int, dict[str, Any]]:
    users = source_meta.tables["app_users"]
    source_users = {
        int(row["id"]): dict(row) for row in source.execute(sa.select(users)).mappings()
    }
    accounted = set(manifest.users) | set(manifest.ignored_user_ids)
    if accounted != set(source_users):
        raise RehearsalError("映射清单必须逐一映射或忽略源快照中的每个旧 ERP 用户。")
    target_users = target_meta.tables["app_users"]
    available_target_ids = _scalar_ids(target, target_users)
    missing = {item.target_user_id for item in manifest.users.values()} - available_target_ids
    if missing:
        raise RehearsalError("映射清单引用了不存在的当前系统用户。")
    if len({item.target_user_id for item in manifest.users.values()}) != len(manifest.users):
        raise RehearsalError("多个旧 ERP 用户不能合并到同一个当前用户。")
    return source_users


def _validate_remote_bindings(
    source: Connection,
    target: Connection,
    source_meta: sa.MetaData,
    target_meta: sa.MetaData,
    manifest: RehearsalManifest,
) -> tuple[dict[int, int], dict[str, Any]]:
    markets = source_meta.tables["redemption_remote_markets"]
    connections = source_meta.tables["redemption_remote_connections"]
    market_rows = {
        int(row["id"]): dict(row) for row in source.execute(sa.select(markets)).mappings()
    }
    connection_rows = {
        int(row["id"]): dict(row) for row in source.execute(sa.select(connections)).mappings()
    }
    if set(manifest.markets) != set(market_rows):
        raise RehearsalError("映射清单必须覆盖源快照中的全部旧盘口。")
    if set(manifest.remote_accounts) != set(connection_rows):
        raise RehearsalError("映射清单必须覆盖源快照中的全部旧远端账号。")

    source_configs = target_meta.tables["source_configs"]
    remote_accounts = target_meta.tables["remote_accounts"]
    source_rows = {
        str(row["source_id"]): dict(row)
        for row in target.execute(sa.select(source_configs)).mappings()
    }
    account_rows = {
        str(row["id"]): dict(row) for row in target.execute(sa.select(remote_accounts)).mappings()
    }
    if set(manifest.markets.values()) - set(source_rows):
        raise RehearsalError("旧盘口映射引用了不存在的 SourceConfig。")
    if set(manifest.remote_accounts.values()) - set(account_rows):
        raise RehearsalError("旧账号映射引用了不存在的统一 RemoteAccount。")
    for legacy_id, row in connection_rows.items():
        market_id = int(row["market_id"])
        expected_source = manifest.markets.get(market_id)
        account_id = manifest.remote_accounts[legacy_id]
        if account_rows[account_id]["source_id"] != expected_source:
            raise RehearsalError("旧账号映射后的 RemoteAccount 不属于对应 SourceConfig。")

    maps = target_meta.tables["erp_compatibility_id_maps"]
    numeric_by_canonical = {
        str(row["canonical_id"]): int(row["legacy_id"])
        for row in target.execute(
            sa.select(maps).where(maps.c.entity_type == "remote_account")
        ).mappings()
        if row["legacy_id"] is not None
    }
    remote_numeric: dict[int, int] = {}
    for legacy_id, canonical_id in manifest.remote_accounts.items():
        if canonical_id not in numeric_by_canonical:
            raise RehearsalError("统一 RemoteAccount 缺少 0035 数字 ID 映射。")
        remote_numeric[legacy_id] = numeric_by_canonical[canonical_id]
    return remote_numeric, {
        "markets": len(market_rows),
        "remote_accounts": len(connection_rows),
        "credentials_copied": False,
        "sessions_copied": False,
    }


def _validate_schema_pair(
    source_meta: sa.MetaData,
    target_meta: sa.MetaData,
) -> None:
    for rule in TABLE_RULES:
        source_columns = set(source_meta.tables[rule.source].c.keys())
        target_columns = set(target_meta.tables[rule.target].c.keys())
        missing = target_columns - source_columns
        if missing:
            raise RehearsalError(
                f"源表 {rule.source} 缺少线上兼容字段：{', '.join(sorted(missing))}"
            )


def _validate_source_table_coverage(source_meta: sa.MetaData) -> dict[str, Any]:
    actual = set(source_meta.tables)
    missing = EXPECTED_SOURCE_TABLES - actual
    if missing:
        raise RehearsalError(
            f"源快照缺少当前 V19 覆盖清单中的表：{', '.join(sorted(missing))}"
        )
    unclassified = actual - EXPECTED_SOURCE_TABLES
    if unclassified:
        raise RehearsalError(
            "源快照包含未分类表，必须先决定复制、转换或排除："
            + ", ".join(sorted(unclassified))
        )
    return {
        "copied_business_tables": sorted(rule.source for rule in TABLE_RULES),
        "transformed_directory_tables": dict(sorted(SOURCE_TRANSFORMED_TABLES.items())),
        "excluded_tables": dict(sorted(SOURCE_EXCLUDED_TABLES.items())),
        "unclassified_tables": [],
    }


def _collect_inventory(
    source: Connection,
    target: Connection,
    source_meta: sa.MetaData,
    target_meta: sa.MetaData,
    manifest: RehearsalManifest,
) -> tuple[dict[str, Any], dict[str, set[int]]]:
    counts: dict[str, int] = {}
    ids: dict[str, set[int]] = {}
    amount_sums: dict[str, dict[str, str]] = {}
    referenced_users: set[int] = set()
    for rule in TABLE_RULES:
        source_table = source_meta.tables[rule.source]
        target_table = target_meta.tables[rule.target]
        source_ids = _scalar_ids(source, source_table)
        if any(item >= PROJECTION_ID_BASE for item in source_ids):
            raise RehearsalError("源快照包含目标保留区 ID，不能作为线上 ERP 历史导入。")
        counts[rule.source] = len(source_ids)
        ids[rule.source] = source_ids
        if source_ids:
            overlap = set(
                int(value)
                for value in target.scalars(
                    sa.select(target_table.c.id).where(target_table.c.id.in_(source_ids))
                )
            )
            if overlap:
                raise RehearsalError(f"目标演练库已包含 {rule.source} 的历史 ID。")
        for column in rule.user_columns:
            referenced_users.update(
                int(value)
                for value in source.scalars(
                    sa.select(source_table.c[column])
                    .where(source_table.c[column].is_not(None))
                    .distinct()
                )
            )
        if rule.source in AMOUNT_COLUMNS:
            sums: dict[str, str] = {}
            for column in AMOUNT_COLUMNS[rule.source]:
                value = source.scalar(
                    sa.select(sa.func.coalesce(sa.func.sum(source_table.c[column]), 0))
                )
                sums[column] = format(Decimal(str(value)), "f")
            amount_sums[rule.source] = sums
    if referenced_users - set(manifest.users):
        raise RehearsalError("历史记录的操作人不能被忽略，必须映射到当前 app_users。")
    audit_table = source_meta.tables["audit_logs"]
    audit_timeline = source.execute(
        sa.select(
            sa.func.count(),
            sa.func.min(audit_table.c.created_at),
            sa.func.max(audit_table.c.created_at),
        )
    ).one()
    batch_table = source_meta.tables["redemption_code_batches"]
    issue_table = source_meta.tables["redemption_code_issues"]
    remote_identifiers = {
        "batches_with_remote_account": int(
            source.scalar(
                sa.select(sa.func.count())
                .select_from(batch_table)
                .where(batch_table.c.remote_connection_id.is_not(None))
            )
            or 0
        ),
        "issues_with_remote_configuration": int(
            source.scalar(
                sa.select(sa.func.count())
                .select_from(issue_table)
                .where(issue_table.c.remote_configuration_id.is_not(None))
            )
            or 0
        ),
        "issues_with_remote_reference": int(
            source.scalar(
                sa.select(sa.func.count())
                .select_from(issue_table)
                .where(issue_table.c.remote_reference_id.is_not(None))
            )
            or 0
        ),
    }
    return {
        "counts": counts,
        "amount_sums": amount_sums,
        "referenced_user_count": len(referenced_users),
        "audit_timeline": {
            "count": int(audit_timeline[0]),
            "first_at": _normalize(audit_timeline[1]),
            "last_at": _normalize(audit_timeline[2]),
        },
        "remote_identifiers": remote_identifiers,
    }, ids


def _ensure_no_value_overlap(
    source: Connection,
    target: Connection,
    source_table: sa.Table,
    target_table: sa.Table,
    columns: tuple[str, ...],
    label: str,
) -> None:
    values = set(source.execute(sa.select(*(source_table.c[item] for item in columns))))
    if not values:
        return
    if len(columns) == 1:
        target_statement = sa.select(target_table.c[columns[0]]).where(
            target_table.c[columns[0]].in_([row[0] for row in values])
        )
    else:
        target_statement = sa.select(*(target_table.c[item] for item in columns)).where(
            sa.tuple_(*(target_table.c[item] for item in columns)).in_(values)
        )
    if target.execute(target_statement.limit(1)).first() is not None:
        raise RehearsalError(f"目标演练库已有冲突的{label}，必须先显式完成归属核对。")


def _validate_target_conflicts(
    source: Connection,
    target: Connection,
    source_meta: sa.MetaData,
    target_meta: sa.MetaData,
    manifest: RehearsalManifest,
    ids: Mapping[str, set[int]],
) -> None:
    unique_checks = (
        ("operators", "erp_compat_operators", ("code",), "投放公司代码"),
        (
            "redemption_campaigns",
            "erp_compat_redemption_campaigns",
            ("code",),
            "兑换活动代码",
        ),
        (
            "redemption_code_tasks",
            "erp_compat_redemption_code_tasks",
            ("grouping_key",),
            "兑换任务组标识",
        ),
        (
            "redemption_code_issues",
            "erp_compat_redemption_code_issues",
            ("remote_request_id",),
            "远端请求标识",
        ),
        (
            "redemption_code_issues",
            "erp_compat_redemption_code_issues",
            ("remote_configuration_id",),
            "远端配置标识",
        ),
        (
            "redemption_code_issues",
            "erp_compat_redemption_code_issues",
            ("redemption_code",),
            "兑换码",
        ),
    )
    for source_name, target_name, columns, label in unique_checks:
        _ensure_no_value_overlap(
            source,
            target,
            source_meta.tables[source_name],
            target_meta.tables[target_name],
            columns,
            label,
        )
    _ensure_no_value_overlap(
        source,
        target,
        source_meta.tables["operators"],
        target_meta.tables["erp_operators"],
        ("code",),
        "当前投放公司代码",
    )

    id_maps = target_meta.tables["erp_compatibility_id_maps"]
    for rule in TABLE_RULES:
        if rule.entity_type == "audit_log":
            continue
        legacy_ids = ids[rule.source]
        if not legacy_ids:
            continue
        if target.scalar(
            sa.select(sa.func.count())
            .select_from(id_maps)
            .where(
                id_maps.c.entity_type == rule.entity_type,
                id_maps.c.legacy_id.in_(legacy_ids),
            )
        ):
            raise RehearsalError("目标 0035 crosswalk 已占用待导入的线上 ERP ID。")

    mapped_target_ids = {binding.target_user_id for binding in manifest.users.values()}
    for table_name in (
        "erp_user_access_profiles",
        "erp_user_role_grants",
        "erp_user_operator_scopes",
    ):
        table = target_meta.tables[table_name]
        if mapped_target_ids and target.scalar(
            sa.select(sa.func.count())
            .select_from(table)
            .where(table.c.user_id.in_(mapped_target_ids))
        ):
            raise RehearsalError("目标用户已有 ERP 授权，演练不会静默覆盖。")

    preset_source = source_meta.tables["redemption_reward_tier_presets"]
    preset_account_ids = [
        manifest.remote_accounts[int(value)]
        for value in source.scalars(sa.select(preset_source.c.remote_connection_id))
    ]
    for table_name in (
        "remote_account_tag_snapshots",
        "remote_account_reward_tier_presets",
    ):
        table = target_meta.tables[table_name]
        if preset_account_ids and target.scalar(
            sa.select(sa.func.count())
            .select_from(table)
            .where(table.c.account_id.in_(preset_account_ids))
        ):
            raise RehearsalError("目标统一账号已有标签或兑换档位快照，演练不会覆盖。")


def _orphan_counts(
    source: Connection,
    metadata: sa.MetaData,
    checks: Mapping[str, tuple[str, str, str]],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for name, (child_name, child_key, parent_name) in checks.items():
        child = metadata.tables[child_name]
        parent = metadata.tables[parent_name]
        statement = (
            sa.select(sa.func.count())
            .select_from(child.outerjoin(parent, child.c[child_key] == parent.c.id))
            .where(child.c[child_key].is_not(None), parent.c.id.is_(None))
        )
        result[name] = int(source.scalar(statement) or 0)
    return result


def _validate_relations(source: Connection, metadata: sa.MetaData) -> dict[str, Any]:
    hard_checks = {
        "operator_accounts_without_operator": (
            "operator_accounts",
            "operator_id",
            "operators",
        ),
        "user_scopes_without_operator": (
            "user_operator_scopes",
            "operator_id",
            "operators",
        ),
        "balances_without_account": ("daily_balances", "operator_account_id", "operator_accounts"),
        "period_locks_without_account": (
            "accounting_period_locks",
            "operator_account_id",
            "operator_accounts",
        ),
        "import_rows_without_job": ("import_job_rows", "import_job_id", "import_jobs"),
        "tiers_without_campaign": (
            "redemption_campaign_tiers",
            "campaign_id",
            "redemption_campaigns",
        ),
        "batches_without_campaign": (
            "redemption_code_batches",
            "campaign_id",
            "redemption_campaigns",
        ),
        "batches_without_task": ("redemption_code_batches", "task_id", "redemption_code_tasks"),
        "batches_without_remote_account": (
            "redemption_code_batches",
            "remote_connection_id",
            "redemption_remote_connections",
        ),
        "issues_without_campaign": (
            "redemption_code_issues",
            "campaign_id",
            "redemption_campaigns",
        ),
        "issues_without_batch": ("redemption_code_issues", "batch_id", "redemption_code_batches"),
        "issues_without_tier": (
            "redemption_code_issues",
            "campaign_tier_id",
            "redemption_campaign_tiers",
        ),
        "presets_without_remote_account": (
            "redemption_reward_tier_presets",
            "remote_connection_id",
            "redemption_remote_connections",
        ),
    }
    # These fields deliberately have no source or compatibility-table foreign
    # keys.  They are immutable evidence pointers that remain useful after an
    # administrator explicitly purges a company and its ledgers.  Preserve
    # their numeric values and surface counts instead of treating them as live
    # aggregate relationships.
    historical_soft_checks = {
        "import_rows_without_account": (
            "import_job_rows",
            "operator_account_id",
            "operator_accounts",
        ),
        "import_rows_without_target_balance": (
            "import_job_rows",
            "target_daily_balance_id",
            "daily_balances",
        ),
        "import_rows_without_preview_balance": (
            "import_job_rows",
            "preview_daily_balance_id",
            "daily_balances",
        ),
        "audit_without_operator": ("audit_logs", "operator_id", "operators"),
    }
    hard_orphans = _orphan_counts(source, metadata, hard_checks)
    if any(hard_orphans.values()):
        raise RehearsalError("源快照存在孤立的业务关系，已停止演练。")
    return {
        "hard_orphans": hard_orphans,
        "historical_soft_references": _orphan_counts(
            source, metadata, historical_soft_checks
        ),
    }


def _prepare_files(
    source: Connection,
    source_meta: sa.MetaData,
    source_root: Path | None,
) -> list[dict[str, Any]]:
    jobs = source_meta.tables["import_jobs"]
    xlsx_jobs = list(
        source.execute(
            sa.select(jobs.c.id, jobs.c.file_sha256)
            .where(jobs.c.source_type.like("XLSX%"))
            .order_by(jobs.c.id)
        ).mappings()
    )
    if xlsx_jobs and source_root is None:
        raise RehearsalError("源快照包含 Excel 导入任务，必须提供只读文件快照目录。")
    files: list[dict[str, Any]] = []
    for row in xlsx_jobs:
        path = source_root / "imports" / f"import-{row['id']}.xlsx"  # type: ignore[operator]
        if not path.is_file():
            raise RehearsalError("Excel 导入任务缺少对应的源文件快照。")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if row["file_sha256"] and digest.lower() != str(row["file_sha256"]).lower():
            raise RehearsalError("Excel 导入源文件的 SHA-256 与数据库记录不一致。")
        files.append({"job_id": int(row["id"]), "source": path, "sha256": digest})
    return files


def _insert_id_maps(
    target: Connection,
    table: sa.Table,
    rule: TableRule,
    legacy_ids: set[int],
) -> None:
    rows = []
    for legacy_id in sorted(legacy_ids):
        if rule.entity_type == "operator":
            canonical_id = _canonical_operator_id(legacy_id)
        elif rule.entity_type == "operator_line":
            canonical_id = _canonical_line_id(legacy_id)
        elif rule.entity_type == "audit_log":
            continue
        else:
            canonical_id = _synthetic_canonical_id(rule.entity_type, legacy_id)
        rows.append(
            {
                "entity_type": rule.entity_type,
                "legacy_id": legacy_id,
                "canonical_id": canonical_id,
            }
        )
    if rows:
        target.execute(sa.insert(table), rows)


def _insert_canonical_operators(
    source: Connection,
    target: Connection,
    source_meta: sa.MetaData,
    target_meta: sa.MetaData,
    manifest: RehearsalManifest,
) -> None:
    source_operators = source_meta.tables["operators"]
    target_operators = target_meta.tables["erp_operators"]
    operator_rows = []
    for partition in _rows(source, source_operators):
        for row in partition:
            item = {
                key: value
                for key, value in row.items()
                if key in target_operators.c and key != "id"
            }
            item["id"] = _canonical_operator_id(int(row["id"]))
            for column in ("created_by", "updated_by"):
                item[column] = _mapped_user(manifest, item.get(column))
            operator_rows.append(item)
    if operator_rows:
        target.execute(sa.insert(target_operators), operator_rows)

    source_lines = source_meta.tables["operator_accounts"]
    target_lines = target_meta.tables["erp_operator_lines"]
    line_rows = []
    for partition in _rows(source, source_lines):
        for row in partition:
            item = {
                key: value
                for key, value in row.items()
                if key in target_lines.c and key not in {"id", "operator_id"}
            }
            item["id"] = _canonical_line_id(int(row["id"]))
            item["operator_id"] = _canonical_operator_id(int(row["operator_id"]))
            line_rows.append(item)
    if line_rows:
        target.execute(sa.insert(target_lines), line_rows)


def _legacy_user_roles(
    source: Connection,
    source_meta: sa.MetaData,
) -> dict[int, set[str]]:
    users_roles = source_meta.tables["user_roles"]
    roles = source_meta.tables["roles"]
    rows = source.execute(
        sa.select(users_roles.c.user_id, roles.c.code).join(
            roles, users_roles.c.role_id == roles.c.id
        )
    )
    result: dict[int, set[str]] = {}
    for user_id, code in rows:
        result.setdefault(int(user_id), set()).add(str(code))
    return result


def _insert_access(
    source: Connection,
    target: Connection,
    source_meta: sa.MetaData,
    target_meta: sa.MetaData,
    manifest: RehearsalManifest,
) -> dict[str, Any]:
    profile_table = target_meta.tables["erp_user_access_profiles"]
    grant_table = target_meta.tables["erp_user_role_grants"]
    scope_table = target_meta.tables["erp_user_operator_scopes"]
    mapped_target_ids = {binding.target_user_id for binding in manifest.users.values()}
    for table in (profile_table, grant_table, scope_table):
        existing = target.scalar(
            sa.select(sa.func.count())
            .select_from(table)
            .where(table.c.user_id.in_(mapped_target_ids))
        )
        if existing:
            raise RehearsalError("目标用户已有 ERP 授权，演练不会静默覆盖。")

    old_roles = _legacy_user_roles(source, source_meta)
    old_scopes = source_meta.tables["user_operator_scopes"]
    all_scope_users = set(
        int(value)
        for value in source.scalars(
            sa.select(old_scopes.c.user_id).where(old_scopes.c.all_operators.is_(True))
        )
    )
    explicit_scopes: dict[int, set[int]] = {}
    for user_id, operator_id in source.execute(
        sa.select(old_scopes.c.user_id, old_scopes.c.operator_id).where(
            old_scopes.c.operator_id.is_not(None)
        )
    ):
        explicit_scopes.setdefault(int(user_id), set()).add(int(operator_id))

    profiles = []
    grants = []
    scopes = []
    migrated_at = datetime.now(UTC)
    for legacy_id, binding in manifest.users.items():
        all_operators = legacy_id in all_scope_users or "SUPER_ADMIN" in old_roles.get(
            legacy_id, set()
        )
        profiles.append(
            {
                "user_id": binding.target_user_id,
                "all_operators": all_operators,
                "created_at": migrated_at,
                "updated_at": migrated_at,
            }
        )
        grants.extend(
            {
                "user_id": binding.target_user_id,
                "role": role,
                "granted_at": migrated_at,
            }
            for role in binding.target_role_grants
        )
        if not all_operators:
            scopes.extend(
                {
                    "user_id": binding.target_user_id,
                    "operator_id": _canonical_operator_id(operator_id),
                    "granted_at": migrated_at,
                }
                for operator_id in sorted(explicit_scopes.get(legacy_id, set()))
            )
    if profiles:
        target.execute(sa.insert(profile_table), profiles)
    if grants:
        target.execute(sa.insert(grant_table), grants)
    if scopes:
        target.execute(sa.insert(scope_table), scopes)
    return {
        "mapped_users": len(manifest.users),
        "ignored_users": len(manifest.ignored_user_ids),
        "role_grants": len(grants),
        "operator_scopes": len(scopes),
    }


def _insert_presets(
    source: Connection,
    target: Connection,
    source_meta: sa.MetaData,
    target_meta: sa.MetaData,
    manifest: RehearsalManifest,
) -> int:
    source_table = source_meta.tables["redemption_reward_tier_presets"]
    tag_table = target_meta.tables["remote_account_tag_snapshots"]
    preset_table = target_meta.tables["remote_account_reward_tier_presets"]
    rows = list(source.execute(sa.select(source_table)).mappings())
    account_ids = [manifest.remote_accounts[int(row["remote_connection_id"])] for row in rows]
    for table in (tag_table, preset_table):
        if account_ids and target.scalar(
            sa.select(sa.func.count()).select_from(table).where(table.c.account_id.in_(account_ids))
        ):
            raise RehearsalError("目标统一账号已有标签或兑换档位快照，演练不会覆盖。")
    tag_rows = []
    preset_rows = []
    for row in rows:
        account_id = manifest.remote_accounts[int(row["remote_connection_id"])]
        tags = json.loads(row["tag_snapshot_json"])
        tiers = json.loads(row["tiers_json"])
        saved_by = _mapped_user(manifest, row["saved_by"])
        tag_rows.append(
            {
                "account_id": account_id,
                "tags_json": tags,
                "source": "ERP_HISTORY_IMPORT",
                "stale": bool(row["stale"]),
                "synced_at": row["last_synced_at"],
                "updated_by": saved_by,
                "row_version": 1,
                "updated_at": row["saved_at"],
            }
        )
        preset_rows.append(
            {
                "account_id": account_id,
                "tiers_json": tiers,
                "tag_snapshot_json": tags,
                "saved_by": saved_by,
                "saved_at": row["saved_at"],
                "row_version": 1,
                "updated_at": row["saved_at"],
            }
        )
    if tag_rows:
        target.execute(sa.insert(tag_table), tag_rows)
        target.execute(sa.insert(preset_table), preset_rows)
    return len(rows)


def _copy_business_tables(
    source: Connection,
    target: Connection,
    source_meta: sa.MetaData,
    target_meta: sa.MetaData,
    manifest: RehearsalManifest,
    remote_numeric_ids: Mapping[int, int],
) -> dict[str, str]:
    digests: dict[str, str] = {}
    for rule in TABLE_RULES:
        source_table = source_meta.tables[rule.source]
        target_table = target_meta.tables[rule.target]
        target_columns = set(target_table.c.keys())
        hash_state = hashlib.sha256()
        for partition in _rows(source, source_table):
            transformed = [
                _transformed_row(
                    row,
                    rule=rule,
                    target_columns=target_columns,
                    manifest=manifest,
                    remote_numeric_ids=remote_numeric_ids,
                )
                for row in partition
            ]
            if transformed:
                target.execute(sa.insert(target_table), transformed)
            for row in transformed:
                payload = {column: _normalize(row.get(column)) for column in target_table.c.keys()}
                hash_state.update(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode())
                hash_state.update(b"\n")
        digests[rule.source] = hash_state.hexdigest()
    return digests


def _verify_target(
    target: Connection,
    target_meta: sa.MetaData,
    ids: Mapping[str, set[int]],
    expected_digests: Mapping[str, str],
    inventory: Mapping[str, Any],
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    digests: dict[str, str] = {}
    amount_sums: dict[str, dict[str, str]] = {}
    for rule in TABLE_RULES:
        table = target_meta.tables[rule.target]
        source_ids = ids[rule.source]
        statement = sa.select(table).where(table.c.id.in_(source_ids)).order_by(table.c.id)
        rows = [dict(row) for row in target.execute(statement).mappings()]
        counts[rule.source] = len(rows)
        digests[rule.source] = _digest_rows(rows, table.c.keys())
        if rule.source in AMOUNT_COLUMNS:
            amount_sums[rule.source] = {
                column: format(sum((Decimal(str(row[column])) for row in rows), Decimal()), "f")
                for column in AMOUNT_COLUMNS[rule.source]
            }
    if counts != inventory["counts"]:
        raise RehearsalError("目标表行数校验失败。")
    if digests != expected_digests:
        mismatched_tables = sorted(
            table_name
            for table_name in set(digests) | set(expected_digests)
            if digests.get(table_name) != expected_digests.get(table_name)
        )
        raise RehearsalError(
            "目标表逐行摘要校验失败：" + "、".join(mismatched_tables) + "。"
        )
    if amount_sums != inventory["amount_sums"]:
        raise RehearsalError("目标金额汇总校验失败。")
    audit_table = target_meta.tables["erp_compat_audit_logs"]
    audit_ids = ids["audit_logs"]
    audit_timeline_row = target.execute(
        sa.select(
            sa.func.count(),
            sa.func.min(audit_table.c.created_at),
            sa.func.max(audit_table.c.created_at),
        ).where(audit_table.c.id.in_(audit_ids))
    ).one()
    audit_timeline = {
        "count": int(audit_timeline_row[0]),
        "first_at": _normalize(audit_timeline_row[1]),
        "last_at": _normalize(audit_timeline_row[2]),
    }
    batch_table = target_meta.tables["erp_compat_redemption_code_batches"]
    issue_table = target_meta.tables["erp_compat_redemption_code_issues"]
    remote_identifiers = {
        "batches_with_remote_account": int(
            target.scalar(
                sa.select(sa.func.count())
                .select_from(batch_table)
                .where(
                    batch_table.c.id.in_(ids["redemption_code_batches"]),
                    batch_table.c.remote_connection_id.is_not(None),
                )
            )
            or 0
        ),
        "issues_with_remote_configuration": int(
            target.scalar(
                sa.select(sa.func.count())
                .select_from(issue_table)
                .where(
                    issue_table.c.id.in_(ids["redemption_code_issues"]),
                    issue_table.c.remote_configuration_id.is_not(None),
                )
            )
            or 0
        ),
        "issues_with_remote_reference": int(
            target.scalar(
                sa.select(sa.func.count())
                .select_from(issue_table)
                .where(
                    issue_table.c.id.in_(ids["redemption_code_issues"]),
                    issue_table.c.remote_reference_id.is_not(None),
                )
            )
            or 0
        ),
    }
    if audit_timeline != inventory["audit_timeline"]:
        raise RehearsalError("目标审计时间线校验失败。")
    if remote_identifiers != inventory["remote_identifiers"]:
        raise RehearsalError("目标远端标识覆盖率校验失败。")
    return {
        "counts": counts,
        "amount_sums": amount_sums,
        "row_digests": digests,
        "audit_timeline": audit_timeline,
        "remote_identifiers": remote_identifiers,
    }


def _copy_files(files: list[dict[str, Any]], target_root: Path | None) -> list[Path]:
    if files and target_root is None:
        raise RehearsalError("迁移 Excel 源文件时必须提供目标演练文件目录。")
    created: list[Path] = []
    try:
        for item in files:
            target = (
                target_root / "imports" / f"import-{item['job_id']}.xlsx"  # type: ignore[operator]
            )
            if target.exists():
                raise RehearsalError("目标演练目录已存在同名 ERP 导入文件。")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item["source"], target)
            created.append(target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
                raise RehearsalError("目标演练文件复制后校验失败。")
        return created
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def _synchronize_target_sequences(
    target: Connection,
    target_meta: sa.MetaData,
) -> dict[str, Any]:
    if target.dialect.name != "postgresql":
        return {"dialect": target.dialect.name, "synchronized": False, "tables": {}}
    report: dict[str, dict[str, int]] = {}
    for table_name in sorted(rule.target for rule in TABLE_RULES):
        table = target_meta.tables[table_name]
        sequence_name = target.scalar(
            sa.text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
            {"table_name": table_name},
        )
        if not sequence_name:
            raise RehearsalError("目标兼容表缺少 PostgreSQL identity sequence。")
        maximum = target.scalar(sa.select(sa.func.max(table.c.id)))
        if maximum is None:
            target.execute(
                sa.text("SELECT setval(CAST(:sequence_name AS regclass), 1, false)"),
                {"sequence_name": sequence_name},
            )
            report[table_name] = {"max_id": 0, "next_id": 1}
        else:
            maximum_id = int(maximum)
            target.execute(
                sa.text(
                    "SELECT setval(CAST(:sequence_name AS regclass), :maximum_id, true)"
                ),
                {"sequence_name": sequence_name, "maximum_id": maximum_id},
            )
            report[table_name] = {
                "max_id": maximum_id,
                "next_id": maximum_id + 1,
            }
    return {"dialect": "postgresql", "synchronized": True, "tables": report}


def rehearse_snapshot(
    *,
    source_url: str,
    target_url: str,
    manifest: RehearsalManifest,
    apply: bool,
    confirmation: str | None = None,
    target_mode: str = TARGET_MODE_ISOLATED,
    production_confirmation: str | None = None,
    source_files_root: Path | None = None,
    target_files_root: Path | None = None,
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
        raise RehearsalError(f"写入目标库必须显式确认 {expected_confirmation}。")
    source_engine = _engine(source_parsed)
    target_engine = _engine(target_parsed)
    try:
        with source_engine.connect() as source, target_engine.connect() as target:
            _enforce_source_read_only(source)
            source_meta = _reflect(source)
            target_meta = _reflect(target)
            source_required = set(EXPECTED_SOURCE_TABLES)
            target_required = {
                *(rule.target for rule in TABLE_RULES),
                "app_users",
                "erp_operators",
                "erp_operator_lines",
                "erp_user_access_profiles",
                "erp_user_role_grants",
                "erp_user_operator_scopes",
                "source_configs",
                "remote_accounts",
                "remote_account_tag_snapshots",
                "remote_account_reward_tier_presets",
                "erp_compatibility_id_maps",
                "alembic_version",
            }
            _require_tables(source_meta, source_required, "源快照")
            _require_tables(target_meta, target_required, "目标演练库")
            source_version = _source_version(source, source_meta)
            target_version = _target_version(target, target_meta)
            source_table_coverage = _validate_source_table_coverage(source_meta)
            _validate_schema_pair(source_meta, target_meta)
            source_users = _validate_user_bindings(
                source, target, source_meta, target_meta, manifest
            )
            remote_numeric_ids, remote_report = _validate_remote_bindings(
                source, target, source_meta, target_meta, manifest
            )
            inventory, ids = _collect_inventory(source, target, source_meta, target_meta, manifest)
            _validate_target_conflicts(
                source,
                target,
                source_meta,
                target_meta,
                manifest,
                ids,
            )
            relations = _validate_relations(source, source_meta)
            files = _prepare_files(source, source_meta, source_files_root)
            preflight = {
                "target_mode": target_mode,
                "source_schema": source_version,
                "target_schema": target_version,
                "source_table_coverage": source_table_coverage,
                "legacy_users": len(source_users),
                "inventory": inventory,
                "relations": relations,
                "remote_directory": remote_report,
                "files": {"count": len(files), "sha256_verified": len(files)},
                "excluded": [
                    "legacy user passwords and sessions",
                    "legacy remote passwords, TOTP secrets, tokens and sessions",
                ],
            }
            if not apply:
                return {"mode": "preflight", "passed": True, **preflight}

        created_files: list[Path] = []
        try:
            with source_engine.connect() as source, target_engine.begin() as target:
                _enforce_source_read_only(source)
                source_meta = _reflect(source)
                target_meta = _reflect(target)
                _insert_canonical_operators(source, target, source_meta, target_meta, manifest)
                id_maps = target_meta.tables["erp_compatibility_id_maps"]
                for rule in TABLE_RULES:
                    _insert_id_maps(target, id_maps, rule, ids[rule.source])
                access_report = _insert_access(source, target, source_meta, target_meta, manifest)
                preset_count = _insert_presets(source, target, source_meta, target_meta, manifest)
                expected_digests = _copy_business_tables(
                    source,
                    target,
                    source_meta,
                    target_meta,
                    manifest,
                    remote_numeric_ids,
                )
                verification = _verify_target(target, target_meta, ids, expected_digests, inventory)
                created_files = _copy_files(files, target_files_root)
                sequences = _synchronize_target_sequences(target, target_meta)
            return {
                "mode": "apply",
                "passed": True,
                **preflight,
                "access": access_report,
                "reward_tier_presets": preset_count,
                "verification": verification,
                "sequences": sequences,
            }
        except Exception:
            for path in created_files:
                path.unlink(missing_ok=True)
            raise
    finally:
        source_engine.dispose()
        target_engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-url-env",
        default="ERP_P5_SOURCE_SNAPSHOT_URL",
        help="保存只读旧 ERP 快照 URL 的环境变量名",
    )
    parser.add_argument(
        "--target-url-env",
        default="ERP_P5_TARGET_REHEARSAL_URL",
        help="保存隔离 data_handle 演练库 URL 的环境变量名",
    )
    parser.add_argument("--mapping", type=Path, required=True, help="身份与统一远端账号映射 JSON")
    parser.add_argument("--source-files-root", type=Path)
    parser.add_argument("--target-files-root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true", help="写入目标库；默认只做预检")
    parser.add_argument(
        "--target-mode",
        choices=TARGET_MODES,
        default=TARGET_MODE_ISOLATED,
        help="目标库安全模式；默认仅允许隔离演练库",
    )
    parser.add_argument("--confirm-isolated-rehearsal")
    parser.add_argument("--confirm-production-cutover")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source_url = os.environ.get(args.source_url_env, "")
        target_url = os.environ.get(args.target_url_env, "")
        if not source_url or not target_url:
            raise RehearsalError("源快照和目标演练库 URL 必须通过指定环境变量提供。")
        confirmation = (
            args.confirm_isolated_rehearsal
            if args.target_mode == TARGET_MODE_ISOLATED
            else args.confirm_production_cutover
        )
        result = rehearse_snapshot(
            source_url=source_url,
            target_url=target_url,
            manifest=load_manifest(args.mapping),
            apply=args.apply,
            confirmation=confirmation,
            target_mode=args.target_mode,
            production_confirmation=args.confirm_production_cutover,
            source_files_root=args.source_files_root,
            target_files_root=args.target_files_root,
        )
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    except RehearsalError as exc:
        print(f"P5 演练失败：{exc}", file=sys.stderr)
        return 2
    except Exception:
        # Database drivers may embed URLs or SQL parameters in exception text.
        # Keep the CLI failure deliberately generic; operators can inspect the
        # isolated environment's protected logs instead of leaking secrets to
        # a terminal transcript or CI artifact.
        print("P5 演练失败：数据库或文件操作未完成；未输出敏感错误详情。", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
