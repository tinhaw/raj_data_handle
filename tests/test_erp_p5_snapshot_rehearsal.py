from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from deploy.prepare_erp_p5_directory_mapping import (
    CONFIRMATION as DIRECTORY_CONFIRMATION,
)
from deploy.prepare_erp_p5_directory_mapping import (
    DirectorySpec,
    prepare_directory_mapping,
)
from deploy.rehearse_erp_snapshot import (
    CONFIRMATION,
    PRODUCTION_CONFIRMATION,
    REQUIRED_TARGET_ALEMBIC_VERSION,
    TABLE_RULES,
    TARGET_MODE_PRODUCTION,
    RehearsalError,
    RehearsalManifest,
    _normalize,
    rehearse_snapshot,
    validate_isolated_urls,
    validate_target_urls,
)
from packages.common.settings import get_settings


def test_p5_digest_normalizes_timezone_aware_datetimes_to_utc() -> None:
    utc_value = datetime(2026, 8, 27, 12, 42, 56, 425791, tzinfo=UTC)
    hong_kong_value = datetime(
        2026,
        8,
        27,
        20,
        42,
        56,
        425791,
        tzinfo=timezone(timedelta(hours=8)),
    )

    assert _normalize(utc_value) == _normalize(hong_kong_value)


def _upgrade_target(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAJ_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    get_settings.cache_clear()
    # The archived P5 importer deliberately accepts only its pinned schema.
    command.upgrade(Config("alembic.ini"), REQUIRED_TARGET_ALEMBIC_VERSION)
    get_settings.cache_clear()


def _seed_target_identity(path: Path) -> None:
    now = datetime(2026, 8, 27, 8, 0, tzinfo=UTC).isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO app_users
                (id, username, username_normalized, password_hash, display_name,
                 role, is_active, password_changed_at, created_at, updated_at)
            VALUES (1, 'admin', 'admin', 'not-a-real-hash', 'Admin', 'admin', 1, ?, ?, ?)
            """,
            (now, now, now),
        )
        connection.execute(
            """
            INSERT INTO remote_accounts
                (id, source_id, login_username, display_name, enabled,
                 credential_mode, credential_version, created_at, updated_at)
            VALUES
                ('00000000-0000-0000-0000-000000000001', 'rajwin',
                 'remote-user', 'Remote User', 1, 'MANAGED', 0, ?, ?)
            """,
            (now, now),
        )
        next_remote_compat_id = connection.execute(
            """
            SELECT coalesce(max(legacy_id), 9000000000000) + 1
            FROM erp_compatibility_id_maps
            WHERE entity_type = 'remote_account'
            """
        ).fetchone()[0]
        connection.executemany(
            """
            INSERT INTO erp_compatibility_id_maps
                (entity_type, legacy_id, canonical_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    "remote_account",
                    next_remote_compat_id,
                    "00000000-0000-0000-0000-000000000001",
                    now,
                )
            ],
        )
        connection.commit()


def _copy_column(column: sa.Column) -> sa.Column:
    default = column.server_default.arg if column.server_default is not None else None
    return sa.Column(
        column.name,
        column.type.copy(),
        primary_key=column.primary_key,
        nullable=column.nullable,
        server_default=default,
    )


def _create_source_schema(source_path: Path, target_path: Path) -> None:
    source_engine = sa.create_engine(f"sqlite:///{source_path}")
    target_engine = sa.create_engine(f"sqlite:///{target_path}")
    target_meta = sa.MetaData()
    target_meta.reflect(bind=target_engine)
    source_meta = sa.MetaData()
    for rule in TABLE_RULES:
        sa.Table(
            rule.source,
            source_meta,
            *[_copy_column(column) for column in target_meta.tables[rule.target].columns],
        )
    sa.Table(
        "flyway_schema_history",
        source_meta,
        sa.Column("installed_rank", sa.Integer, primary_key=True),
        sa.Column("version", sa.String(50)),
        sa.Column("success", sa.Boolean, nullable=False),
    )
    sa.Table(
        "app_users",
        source_meta,
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
    )
    sa.Table(
        "roles",
        source_meta,
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
    )
    sa.Table(
        "permissions",
        source_meta,
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
    )
    sa.Table(
        "user_roles",
        source_meta,
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("role_id", sa.BigInteger, nullable=False),
    )
    sa.Table(
        "role_permissions",
        source_meta,
        sa.Column("role_id", sa.BigInteger, nullable=False),
        sa.Column("permission_id", sa.BigInteger, nullable=False),
    )
    sa.Table(
        "user_operator_scopes",
        source_meta,
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("operator_id", sa.BigInteger),
        sa.Column("all_operators", sa.Boolean, nullable=False),
    )
    sa.Table(
        "redemption_remote_markets",
        source_meta,
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
    )
    sa.Table(
        "redemption_remote_connections",
        source_meta,
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("market_id", sa.BigInteger, nullable=False),
        sa.Column("username", sa.String(120), nullable=False),
        sa.Column("password_ciphertext", sa.Text),
        sa.Column("totp_secret_ciphertext", sa.Text),
        sa.Column("access_token_ciphertext", sa.Text),
    )
    sa.Table(
        "redemption_reward_tier_presets",
        source_meta,
        sa.Column("remote_connection_id", sa.BigInteger, primary_key=True),
        sa.Column("tiers_json", sa.Text, nullable=False),
        sa.Column("tag_snapshot_json", sa.Text, nullable=False),
        sa.Column("stale", sa.Boolean, nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("saved_by", sa.BigInteger),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
    )
    source_meta.create_all(source_engine)
    source_engine.dispose()
    target_engine.dispose()


def _required_row(table: sa.Table, row_id: int) -> dict[str, object]:
    now = datetime(2026, 8, 27, 8, 30, tzinfo=UTC)
    result: dict[str, object] = {"id": row_id}
    for column in table.columns:
        if column.name == "id" or column.nullable or column.server_default is not None:
            continue
        if isinstance(column.type, sa.DateTime):
            result[column.name] = now
        elif isinstance(column.type, sa.Date):
            result[column.name] = date(2026, 8, 27)
        elif isinstance(column.type, sa.Boolean):
            result[column.name] = False
        elif isinstance(column.type, sa.Numeric):
            result[column.name] = Decimal("0")
        elif isinstance(column.type, sa.Integer):
            result[column.name] = 1
        else:
            result[column.name] = f"{column.name}-{row_id}"
    return result


def _seed_source(source_path: Path, files_root: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{source_path}")
    metadata = sa.MetaData()
    metadata.reflect(bind=engine)
    now = datetime(2026, 8, 27, 8, 30, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(metadata.tables["flyway_schema_history"]),
            {"installed_rank": 19, "version": "19", "success": True},
        )
        connection.execute(
            sa.insert(metadata.tables["app_users"]),
            {"id": 1, "username": "legacy-admin", "enabled": True},
        )
        connection.execute(
            sa.insert(metadata.tables["roles"]),
            {"id": 1, "code": "SUPER_ADMIN"},
        )
        connection.execute(
            sa.insert(metadata.tables["user_roles"]),
            {"user_id": 1, "role_id": 1},
        )
        connection.execute(
            sa.insert(metadata.tables["user_operator_scopes"]),
            {"id": 1, "user_id": 1, "operator_id": None, "all_operators": True},
        )
        connection.execute(
            sa.insert(metadata.tables["redemption_remote_markets"]),
            {
                "id": 1,
                "code": "RAJWIN",
                "name": "RajWin",
                "base_url": "https://snapshot.invalid",
                "enabled": True,
            },
        )
        connection.execute(
            sa.insert(metadata.tables["redemption_remote_connections"]),
            {
                "id": 1,
                "market_id": 1,
                "username": "legacy-remote",
                "password_ciphertext": "must-not-copy",
                "totp_secret_ciphertext": "must-not-copy",
                "access_token_ciphertext": "must-not-copy",
            },
        )

        operators = _required_row(metadata.tables["operators"], 1)
        operators.update(
            code="ONLINE-OP",
            name="线上投放公司",
            operator_type="COMPANY",
            status="ACTIVE",
            created_by=1,
            updated_by=1,
        )
        connection.execute(sa.insert(metadata.tables["operators"]), operators)

        account = _required_row(metadata.tables["operator_accounts"], 1)
        account.update(
            operator_id=1,
            code="ONLINE-LINE",
            name="线上投放线",
            asset="USDT",
            status="ACTIVE",
        )
        connection.execute(sa.insert(metadata.tables["operator_accounts"]), account)

        balance = _required_row(metadata.tables["daily_balances"], 1)
        balance.update(
            operator_account_id=1,
            business_date=date(2026, 8, 27),
            transfer_amount=Decimal("100.50"),
            effective_transfer_amount=Decimal("100.50"),
            spend_amount=Decimal("40.25"),
            closing_balance=Decimal("60.25"),
            created_by=1,
            updated_by=1,
        )
        connection.execute(sa.insert(metadata.tables["daily_balances"]), balance)

        period_lock = _required_row(metadata.tables["accounting_period_locks"], 1)
        period_lock.update(
            operator_account_id=1,
            period_month=date(2026, 8, 1),
            status="LOCKED",
            locked_by=1,
        )
        connection.execute(sa.insert(metadata.tables["accounting_period_locks"]), period_lock)

        source_file = files_root / "imports" / "import-1.xlsx"
        source_file.parent.mkdir(parents=True)
        source_file.write_bytes(b"synthetic-xlsx-snapshot")
        source_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
        import_job = _required_row(metadata.tables["import_jobs"], 1)
        import_job.update(
            source_type="XLSX_STANDARD",
            original_filename="online-ledger.xlsx",
            file_sha256=source_hash,
            status="SUCCEEDED",
            conflict_strategy="SKIP_EXISTING",
            total_rows=1,
            valid_rows=1,
            warning_rows=0,
            error_rows=0,
            created_by=1,
            committed_by=1,
        )
        connection.execute(sa.insert(metadata.tables["import_jobs"]), import_job)

        import_row = _required_row(metadata.tables["import_job_rows"], 1)
        import_row.update(
            import_job_id=1,
            operator_account_id=1,
            business_date=date(2026, 8, 27),
            severity="OK",
            target_daily_balance_id=1,
            preview_daily_balance_id=1,
            preview_row_version=0,
        )
        connection.execute(sa.insert(metadata.tables["import_job_rows"]), import_row)

        audit = _required_row(metadata.tables["audit_logs"], 1)
        audit.update(
            actor_user_id=1,
            action="BALANCE_CONFIRM",
            entity_type="DAILY_BALANCE",
            entity_id="1",
            operator_id=1,
        )
        connection.execute(sa.insert(metadata.tables["audit_logs"]), audit)

        campaign = _required_row(metadata.tables["redemption_campaigns"], 1)
        campaign.update(
            code="ONLINE-CAMPAIGN",
            name="线上活动",
            status="ACTIVE",
            lookback_days=7,
            created_by=1,
            updated_by=1,
        )
        connection.execute(sa.insert(metadata.tables["redemption_campaigns"]), campaign)

        tier = _required_row(metadata.tables["redemption_campaign_tiers"], 1)
        tier.update(
            campaign_id=1,
            min_deposit_amount=Decimal("100"),
            bonus_amount=Decimal("8"),
            bonus_max_amount=Decimal("12"),
            sort_order=1,
        )
        connection.execute(sa.insert(metadata.tables["redemption_campaign_tiers"]), tier)

        task = _required_row(metadata.tables["redemption_code_tasks"], 1)
        task.update(grouping_key="group:online", created_by=1)
        connection.execute(sa.insert(metadata.tables["redemption_code_tasks"]), task)

        batch = _required_row(metadata.tables["redemption_code_batches"], 1)
        batch.update(
            campaign_id=1,
            claim_date_from=date(2026, 8, 27),
            claim_date_to=date(2026, 8, 27),
            lookback_days=7,
            redemption_type="SEVEN_DAY_DEPOSIT",
            expected_code_count=1,
            status="COMPLETED",
            remote_connection_id=1,
            task_id=1,
            created_by=1,
            published_by=1,
        )
        connection.execute(sa.insert(metadata.tables["redemption_code_batches"]), batch)

        issue = _required_row(metadata.tables["redemption_code_issues"], 1)
        issue.update(
            campaign_id=1,
            campaign_tier_id=1,
            batch_id=1,
            claim_date=date(2026, 8, 27),
            deposit_window_start=date(2026, 8, 20),
            deposit_window_end=date(2026, 8, 26),
            min_deposit_amount=Decimal("100"),
            bonus_amount=Decimal("8"),
            bonus_max_amount=Decimal("12"),
            workflow_status="CODE_IMPORTED",
            state="GENERATED",
            remote_request_id="online-request-1",
            redemption_code="SAFE-CODE-1",
            created_by=1,
        )
        connection.execute(sa.insert(metadata.tables["redemption_code_issues"]), issue)

        connection.execute(
            sa.insert(metadata.tables["redemption_reward_tier_presets"]),
            {
                "remote_connection_id": 1,
                "tiers_json": '[{"bonusAmount":8,"labelIds":[901]}]',
                "tag_snapshot_json": '[{"id":901,"name":"VIP"}]',
                "stale": False,
                "last_synced_at": now,
                "saved_by": 1,
                "saved_at": now,
            },
        )
    engine.dispose()


def _target_identity(target_path: Path) -> tuple[int, str, str]:
    with sqlite3.connect(target_path) as connection:
        user_id = connection.execute("SELECT id FROM app_users ORDER BY id LIMIT 1").fetchone()[0]
        account_id, source_id = connection.execute(
            "SELECT id, source_id FROM remote_accounts ORDER BY id LIMIT 1"
        ).fetchone()
    return int(user_id), str(account_id), str(source_id)


def test_p5_rehearsal_imports_history_without_copying_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path = tmp_path / "data-handle.rehearsal.db"
    source_path = tmp_path / "erp.snapshot.db"
    source_files_root = tmp_path / "erp-storage.snapshot"
    target_files_root = tmp_path / "data-handle-storage.rehearsal"
    _upgrade_target(target_path, monkeypatch)
    _seed_target_identity(target_path)
    _create_source_schema(source_path, target_path)
    _seed_source(source_path, source_files_root)
    user_id, account_id, source_id = _target_identity(target_path)
    manifest = RehearsalManifest.from_mapping(
        {
            "legacy_users": {
                "1": {
                    "target_user_id": user_id,
                    "target_role_grants": ["ERP_SYSTEM_ADMIN"],
                }
            },
            "ignored_legacy_user_ids": [],
            "legacy_markets": {"1": source_id},
            "legacy_remote_accounts": {"1": account_id},
        }
    )

    preflight = rehearse_snapshot(
        source_url=f"sqlite:///{source_path}",
        target_url=f"sqlite:///{target_path}",
        manifest=manifest,
        apply=False,
        source_files_root=source_files_root,
    )
    assert preflight["mode"] == "preflight"
    assert preflight["inventory"]["counts"]["daily_balances"] == 1
    assert preflight["source_table_coverage"]["unclassified_tables"] == []
    assert len(preflight["source_table_coverage"]["copied_business_tables"]) == 12
    assert len(preflight["source_table_coverage"]["transformed_directory_tables"]) == 7
    assert len(preflight["source_table_coverage"]["excluded_tables"]) == 3

    result = rehearse_snapshot(
        source_url=f"sqlite:///{source_path}",
        target_url=f"sqlite:///{target_path}",
        manifest=manifest,
        apply=True,
        confirmation=CONFIRMATION,
        source_files_root=source_files_root,
        target_files_root=target_files_root,
    )
    assert result["passed"] is True
    assert result["verification"]["amount_sums"]["daily_balances"]["transfer_amount"] == (
        "100.50000000"
    )
    assert result["remote_directory"]["credentials_copied"] is False
    assert result["sequences"] == {
        "dialect": "sqlite",
        "synchronized": False,
        "tables": {},
    }
    assert (target_files_root / "imports" / "import-1.xlsx").read_bytes() == (
        b"synthetic-xlsx-snapshot"
    )

    with sqlite3.connect(target_path) as connection:
        assert (
            connection.execute("SELECT count(*) FROM erp_compat_operators WHERE id = 1").fetchone()[
                0
            ]
            == 1
        )
        remote_numeric_id = connection.execute(
            """
            SELECT legacy_id FROM erp_compatibility_id_maps
            WHERE entity_type = 'remote_account' AND canonical_id = ?
            """,
            (account_id,),
        ).fetchone()[0]
        assert (
            connection.execute(
                "SELECT remote_connection_id FROM erp_compat_redemption_code_batches WHERE id = 1"
            ).fetchone()[0]
            == remote_numeric_id
        )
        tags = connection.execute(
            "SELECT tags_json FROM remote_account_tag_snapshots WHERE account_id = ?",
            (account_id,),
        ).fetchone()[0]
        assert "VIP" in tags
        canonical_operator_id = connection.execute(
            """
            SELECT canonical_id FROM erp_compatibility_id_maps
            WHERE entity_type = 'operator' AND legacy_id = 1
            """
        ).fetchone()[0]
        assert (
            connection.execute(
                "SELECT count(*) FROM erp_operators WHERE id = ?", (canonical_operator_id,)
            ).fetchone()[0]
            == 1
        )

    with sqlite3.connect(source_path) as connection:
        secret_row = connection.execute(
            "SELECT password_ciphertext, totp_secret_ciphertext, access_token_ciphertext "
            "FROM redemption_remote_connections"
        ).fetchone()
    assert secret_row == ("must-not-copy", "must-not-copy", "must-not-copy")


def test_p5_rehearsal_has_hard_isolation_and_confirmation_gates(tmp_path: Path) -> None:
    with pytest.raises(RehearsalError, match="snapshot 或 rehearsal"):
        validate_isolated_urls(
            "postgresql+psycopg://user:secret@db/erp",
            "postgresql+psycopg://user:secret@db/data_handle",
        )
    manifest = RehearsalManifest.from_mapping(
        {
            "legacy_users": {},
            "legacy_markets": {},
            "legacy_remote_accounts": {},
        }
    )
    with pytest.raises(RehearsalError, match=CONFIRMATION):
        rehearse_snapshot(
            source_url=f"sqlite:///{tmp_path / 'source.snapshot.db'}",
            target_url=f"sqlite:///{tmp_path / 'target.rehearsal.db'}",
            manifest=manifest,
            apply=True,
            confirmation="wrong",
        )

    source_url = "postgresql+psycopg://user:secret@db/erp_snapshot"
    production_url = "postgresql+psycopg://user:secret@db/data_handle"
    with pytest.raises(RehearsalError, match="snapshot 或 rehearsal"):
        validate_target_urls(source_url, production_url)
    with pytest.raises(RehearsalError, match=PRODUCTION_CONFIRMATION):
        validate_target_urls(
            source_url,
            production_url,
            target_mode=TARGET_MODE_PRODUCTION,
            production_confirmation="wrong",
        )
    with pytest.raises(RehearsalError, match="只允许目标数据库 data_handle"):
        validate_target_urls(
            source_url,
            "postgresql+psycopg://user:secret@db/not-production",
            target_mode=TARGET_MODE_PRODUCTION,
            production_confirmation=PRODUCTION_CONFIRMATION,
        )
    source, target = validate_target_urls(
        source_url,
        production_url,
        target_mode=TARGET_MODE_PRODUCTION,
        production_confirmation=PRODUCTION_CONFIRMATION,
    )
    assert source.database == "erp_snapshot"
    assert target.database == "data_handle"


def test_p5_directory_mapping_creates_only_disabled_credential_free_placeholders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path = tmp_path / "directory-target.rehearsal.db"
    source_path = tmp_path / "directory-source.snapshot.db"
    source_files_root = tmp_path / "directory-files.snapshot"
    _upgrade_target(target_path, monkeypatch)
    _seed_target_identity(target_path)
    _create_source_schema(source_path, target_path)
    _seed_source(source_path, source_files_root)
    spec = DirectorySpec.from_mapping(
        {
            "users": [
                {
                    "legacy_username": "legacy-admin",
                    "target_username": "admin",
                    "target_role_grants": ["ERP_SYSTEM_ADMIN"],
                }
            ],
            "ignored_legacy_usernames": [],
            "markets": [
                {"legacy_code": "RAJWIN", "target_source_id": "rajwin"}
            ],
            "remote_accounts": [
                {
                    "legacy_market_code": "RAJWIN",
                    "legacy_username": "legacy-remote",
                    "target_source_id": "rajwin",
                    "target_login_username": "legacy-remote",
                    "target_display_name": "ERP · legacy-remote",
                    "create_disabled_placeholder": True,
                }
            ],
        }
    )

    preflight = prepare_directory_mapping(
        source_url=f"sqlite:///{source_path}",
        target_url=f"sqlite:///{target_path}",
        spec=spec,
        apply=False,
    )
    planned = preflight["directory"]["remote_accounts"][0]
    assert planned["created_disabled_placeholder"] is True
    assert preflight["safety"] == {
        "placeholders_enabled": False,
        "credentials_copied": False,
        "capabilities_granted": False,
        "remote_operations_executed": False,
    }
    with sqlite3.connect(target_path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM remote_accounts WHERE login_username = 'legacy-remote'"
        ).fetchone()[0] == 0

    with pytest.raises(RehearsalError, match=DIRECTORY_CONFIRMATION):
        prepare_directory_mapping(
            source_url=f"sqlite:///{source_path}",
            target_url=f"sqlite:///{target_path}",
            spec=spec,
            apply=True,
            confirmation="wrong",
        )

    applied = prepare_directory_mapping(
        source_url=f"sqlite:///{source_path}",
        target_url=f"sqlite:///{target_path}",
        spec=spec,
        apply=True,
        confirmation=DIRECTORY_CONFIRMATION,
    )
    account_id = applied["mapping"]["legacy_remote_accounts"]["1"]
    with sqlite3.connect(target_path) as connection:
        account = connection.execute(
            """
            SELECT enabled, credential_mode, encrypted_credentials, credential_version
            FROM remote_accounts WHERE id = ?
            """,
            (account_id,),
        ).fetchone()
        assert account == (0, "MANAGED", None, 0)
        assert connection.execute(
            "SELECT count(*) FROM remote_account_capabilities WHERE account_id = ?",
            (account_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            """
            SELECT count(*) FROM erp_compatibility_id_maps
            WHERE entity_type = 'remote_account' AND canonical_id = ?
            """,
            (account_id,),
        ).fetchone()[0] == 1

    resolved_manifest = RehearsalManifest.from_mapping(applied["mapping"])
    rehearsal_preflight = rehearse_snapshot(
        source_url=f"sqlite:///{source_path}",
        target_url=f"sqlite:///{target_path}",
        manifest=resolved_manifest,
        apply=False,
        source_files_root=source_files_root,
    )
    assert rehearsal_preflight["passed"] is True
    assert rehearsal_preflight["remote_directory"]["credentials_copied"] is False


def test_p5_preflight_rejects_unclassified_source_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path = tmp_path / "coverage-target.rehearsal.db"
    source_path = tmp_path / "coverage-source.snapshot.db"
    source_files_root = tmp_path / "coverage-files.snapshot"
    _upgrade_target(target_path, monkeypatch)
    _seed_target_identity(target_path)
    _create_source_schema(source_path, target_path)
    _seed_source(source_path, source_files_root)
    with sqlite3.connect(source_path) as connection:
        connection.execute("CREATE TABLE newly_added_business_data (id INTEGER PRIMARY KEY)")
        connection.commit()
    user_id, account_id, source_id = _target_identity(target_path)
    manifest = RehearsalManifest.from_mapping(
        {
            "legacy_users": {
                "1": {
                    "target_user_id": user_id,
                    "target_role_grants": ["ERP_SYSTEM_ADMIN"],
                }
            },
            "ignored_legacy_user_ids": [],
            "legacy_markets": {"1": source_id},
            "legacy_remote_accounts": {"1": account_id},
        }
    )

    with pytest.raises(RehearsalError, match="未分类表"):
        rehearse_snapshot(
            source_url=f"sqlite:///{source_path}",
            target_url=f"sqlite:///{target_path}",
            manifest=manifest,
            apply=False,
            source_files_root=source_files_root,
        )


def test_p5_preserves_historical_soft_references_but_rejects_hard_orphans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path = tmp_path / "relations-target.rehearsal.db"
    source_path = tmp_path / "relations-source.snapshot.db"
    source_files_root = tmp_path / "relations-files.snapshot"
    target_files_root = tmp_path / "relations-target-files.rehearsal"
    _upgrade_target(target_path, monkeypatch)
    _seed_target_identity(target_path)
    _create_source_schema(source_path, target_path)
    _seed_source(source_path, source_files_root)
    with sqlite3.connect(source_path) as connection:
        connection.execute(
            """
            UPDATE import_job_rows
            SET operator_account_id = 901,
                target_daily_balance_id = 902,
                preview_daily_balance_id = 903
            """
        )
        connection.execute("UPDATE audit_logs SET operator_id = 904")
        connection.commit()
    user_id, account_id, source_id = _target_identity(target_path)
    manifest = RehearsalManifest.from_mapping(
        {
            "legacy_users": {
                "1": {
                    "target_user_id": user_id,
                    "target_role_grants": ["ERP_SYSTEM_ADMIN"],
                }
            },
            "ignored_legacy_user_ids": [],
            "legacy_markets": {"1": source_id},
            "legacy_remote_accounts": {"1": account_id},
        }
    )

    preflight = rehearse_snapshot(
        source_url=f"sqlite:///{source_path}",
        target_url=f"sqlite:///{target_path}",
        manifest=manifest,
        apply=False,
        source_files_root=source_files_root,
    )
    assert not any(preflight["relations"]["hard_orphans"].values())
    assert preflight["relations"]["historical_soft_references"] == {
        "import_rows_without_account": 1,
        "import_rows_without_target_balance": 1,
        "import_rows_without_preview_balance": 1,
        "audit_without_operator": 1,
    }

    applied = rehearse_snapshot(
        source_url=f"sqlite:///{source_path}",
        target_url=f"sqlite:///{target_path}",
        manifest=manifest,
        apply=True,
        confirmation=CONFIRMATION,
        source_files_root=source_files_root,
        target_files_root=target_files_root,
    )
    assert applied["passed"] is True
    with sqlite3.connect(target_path) as connection:
        assert connection.execute(
            """
            SELECT operator_account_id, target_daily_balance_id, preview_daily_balance_id
            FROM erp_compat_import_job_rows WHERE id = 1
            """
        ).fetchone() == (901, 902, 903)
        assert connection.execute(
            "SELECT operator_id FROM erp_compat_audit_logs WHERE id = 1"
        ).fetchone()[0] == 904

    hard_orphan_target = tmp_path / "hard-orphan-target.rehearsal.db"
    hard_orphan_source = tmp_path / "hard-orphan-source.snapshot.db"
    hard_orphan_files = tmp_path / "hard-orphan-files.snapshot"
    _upgrade_target(hard_orphan_target, monkeypatch)
    _seed_target_identity(hard_orphan_target)
    _create_source_schema(hard_orphan_source, hard_orphan_target)
    _seed_source(hard_orphan_source, hard_orphan_files)
    with sqlite3.connect(hard_orphan_source) as connection:
        connection.execute("UPDATE redemption_code_batches SET task_id = 999")
        connection.commit()
    hard_user_id, hard_account_id, hard_source_id = _target_identity(hard_orphan_target)
    hard_manifest = RehearsalManifest.from_mapping(
        {
            "legacy_users": {
                "1": {
                    "target_user_id": hard_user_id,
                    "target_role_grants": ["ERP_SYSTEM_ADMIN"],
                }
            },
            "ignored_legacy_user_ids": [],
            "legacy_markets": {"1": hard_source_id},
            "legacy_remote_accounts": {"1": hard_account_id},
        }
    )
    with pytest.raises(RehearsalError, match="孤立的业务关系"):
        rehearse_snapshot(
            source_url=f"sqlite:///{hard_orphan_source}",
            target_url=f"sqlite:///{hard_orphan_target}",
            manifest=hard_manifest,
            apply=False,
            source_files_root=hard_orphan_files,
        )
