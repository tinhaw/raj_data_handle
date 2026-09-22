from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from packages.common.settings import get_settings


def test_0036_backfills_local_erp_core_with_numeric_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "erp-compatibility.db"
    monkeypatch.setenv(
        "RAJ_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "20260827_0035")
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO erp_operators
                    (id, code, name, operator_type, status, row_version,
                     created_at, updated_at)
                VALUES
                    ('operator-uuid', 'OP-ONLINE', 'Online Company', 'COMPANY',
                     'ACTIVE', 4, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO erp_operator_lines
                    (id, operator_id, code, name, asset, status, row_version,
                     created_at, updated_at)
                VALUES
                    ('line-uuid', 'operator-uuid', 'LINE-ONLINE', 'Online Line',
                     'USDT', 'ACTIVE', 5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO erp_daily_balances
                    (id, operator_line_id, business_date, row_version,
                     created_at, updated_at)
                VALUES
                    ('balance-uuid', 'line-uuid', '2026-08-27', 6,
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO erp_accounting_period_locks
                    (id, operator_line_id, month_start, status, row_version,
                     created_at, updated_at)
                VALUES
                    ('lock-uuid', 'line-uuid', '2026-08-01', 'LOCKED', 2,
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO erp_import_jobs
                    (id, source_type, status, conflict_strategy, total_rows,
                     valid_rows, warning_rows, error_rows, created_at, updated_at)
                VALUES
                    ('job-uuid', 'PASTE', 'PREVIEW_READY', 'SKIP_EXISTING',
                     1, 1, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO erp_import_job_rows
                    (id, import_job_id, source_json, operator_line_id,
                     business_date, severity, target_daily_balance_id,
                     preview_daily_balance_id, preview_row_version)
                VALUES
                    ('row-uuid', 'job-uuid', '{}', 'line-uuid', '2026-08-27',
                     'OK', 'balance-uuid', 'balance-uuid', 6)
                """
            )
            connection.commit()

        command.upgrade(config, "head")
        with sqlite3.connect(database_path) as connection:
            operator = connection.execute(
                "SELECT id, code, name, row_version FROM erp_compat_operators"
            ).fetchone()
            line = connection.execute(
                "SELECT id, operator_id, code FROM erp_compat_operator_accounts"
            ).fetchone()
            balance = connection.execute(
                """
                SELECT id, operator_account_id, calculation_rule_version,
                       rounding_mode, row_version
                FROM erp_compat_daily_balances
                """
            ).fetchone()
            import_row = connection.execute(
                """
                SELECT import_job_id, operator_name, operator_account_id,
                       target_daily_balance_id, preview_daily_balance_id
                FROM erp_compat_import_job_rows
                """
            ).fetchone()
            assert operator is not None
            assert line is not None
            assert balance is not None
            assert import_row is not None
            assert operator[0] > 9_000_000_000_000
            assert operator[1:] == ("OP-ONLINE", "Online Company", 4)
            assert line == (operator[0], operator[0], "LINE-ONLINE")
            assert balance == (
                operator[0],
                operator[0],
                "BALANCE_V1_GROSS_TRANSFER",
                "HALF_UP",
                6,
            )
            assert import_row == (
                operator[0],
                "Online Company",
                operator[0],
                operator[0],
                operator[0],
            )
    finally:
        get_settings.cache_clear()
