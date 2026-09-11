"""add online-compatible local ERP core tables

Revision ID: 20260827_0036
Revises: 20260827_0035
Create Date: 2026-08-27

The tables preserve the deployed Spring API's numeric IDs and field semantics
for operators, ledgers, period locks, imports and audits.  This revision is a
code artifact only: production execution requires a newly approved schema
window explicitly covering 0035 and 0036.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0036"
down_revision: str | None = "20260827_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECTION_ID_BASE = 9_000_000_000_000


def _legacy_id_type() -> sa.types.TypeEngine:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _backfill_mapping(entity_type: str, table_name: str, id_column: str = "id") -> None:
    op.execute(
        sa.text(
            "INSERT INTO erp_compatibility_id_maps "
            "(entity_type, legacy_id, canonical_id, created_at) "
            "SELECT :entity_type, "
            "(SELECT CASE "
            " WHEN COALESCE(MAX(existing.legacy_id), 0) < :projection_base "
            " THEN :projection_base ELSE MAX(existing.legacy_id) END "
            " FROM erp_compatibility_id_maps existing "
            " WHERE existing.entity_type = :entity_type) "
            f"+ ROW_NUMBER() OVER (ORDER BY {id_column}), "
            f"{id_column}, CURRENT_TIMESTAMP FROM {table_name} source "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM erp_compatibility_id_maps mapping "
            "WHERE mapping.entity_type = :entity_type "
            f"AND mapping.canonical_id = source.{id_column}"
            f") ORDER BY {id_column}"
        ).bindparams(
            entity_type=entity_type,
            projection_base=PROJECTION_ID_BASE,
        )
    )


def _create_operator_tables() -> None:
    op.create_table(
        "erp_compat_operators",
        sa.Column("id", _legacy_id_type(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("operator_type", sa.String(20), nullable=False, server_default="COMPANY"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("contact_name", sa.String(120)),
        sa.Column("contact_value", sa.String(200)),
        sa.Column("remark", sa.Text()),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("updated_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_erp_compat_operator_code"),
    )
    op.create_table(
        "erp_compat_operator_accounts",
        sa.Column("id", _legacy_id_type(), autoincrement=True, nullable=False),
        sa.Column("operator_id", _legacy_id_type(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("asset", sa.String(10), nullable=False, server_default="USDT"),
        sa.Column("network", sa.String(30)),
        sa.Column("wallet_address", sa.String(200)),
        sa.Column("start_date", sa.Date()),
        sa.Column(
            "default_exchange_loss_rate",
            sa.Numeric(12, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "default_exchange_loss_basis",
            sa.String(30),
            nullable=False,
            server_default="TRANSFER",
        ),
        sa.Column(
            "default_service_fee_rate",
            sa.Numeric(12, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "default_service_fee_basis",
            sa.String(30),
            nullable=False,
            server_default="TRANSFER",
        ),
        sa.Column("calculation_scale", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("asset in ('USDT', 'USDC')"),
        sa.CheckConstraint("calculation_scale between 0 and 8"),
        sa.CheckConstraint("default_exchange_loss_rate between 0 and 1"),
        sa.CheckConstraint("default_service_fee_rate between 0 and 1"),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["erp_compat_operators.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operator_id",
            "code",
            name="uq_erp_compat_operator_account_code",
        ),
        sa.UniqueConstraint(
            "operator_id",
            "name",
            name="uq_erp_compat_operator_account_name",
        ),
    )
    op.create_index(
        "ix_erp_compat_operator_account_operator_status",
        "erp_compat_operator_accounts",
        ["operator_id", "status"],
    )


def _create_balance_tables() -> None:
    op.create_table(
        "erp_compat_daily_balances",
        sa.Column("id", _legacy_id_type(), autoincrement=True, nullable=False),
        sa.Column("operator_account_id", _legacy_id_type(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("opening_balance", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("suggested_opening_balance", sa.Numeric(24, 8)),
        sa.Column("opening_mode", sa.String(20), nullable=False, server_default="AUTO"),
        sa.Column("opening_override_reason", sa.String(500)),
        sa.Column("transfer_amount", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("fraud_loss_amount", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("fraud_deduction_source", sa.String(20)),
        sa.Column(
            "effective_transfer_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column("spend_amount", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("exchange_loss_rate", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column(
            "exchange_loss_basis",
            sa.String(30),
            nullable=False,
            server_default="TRANSFER",
        ),
        sa.Column(
            "exchange_loss_auto_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column("exchange_loss_amount", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("exchange_loss_mode", sa.String(20), nullable=False, server_default="AUTO"),
        sa.Column("exchange_loss_override_reason", sa.String(500)),
        sa.Column("service_fee_rate", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column(
            "service_fee_basis",
            sa.String(30),
            nullable=False,
            server_default="TRANSFER",
        ),
        sa.Column(
            "service_fee_auto_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column("service_fee_amount", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("service_fee_mode", sa.String(20), nullable=False, server_default="AUTO"),
        sa.Column("service_fee_override_reason", sa.String(500)),
        sa.Column("reflux_amount", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("refund_amount", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column(
            "other_deduction_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column("other_reason", sa.String(500)),
        sa.Column("closing_balance", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column(
            "calculation_rule_version",
            sa.String(50),
            nullable=False,
            server_default="BALANCE_V1_GROSS_TRANSFER",
        ),
        sa.Column("rounding_mode", sa.String(30), nullable=False, server_default="HALF_UP"),
        sa.Column("calculation_scale", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("source_type", sa.String(20), nullable=False, server_default="MANUAL"),
        sa.Column("remark", sa.Text()),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("updated_by", sa.BigInteger()),
        sa.Column("confirmed_by", sa.BigInteger()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("transfer_amount >= 0 and fraud_loss_amount >= 0 and spend_amount >= 0"),
        sa.CheckConstraint("exchange_loss_amount >= 0 and service_fee_amount >= 0"),
        sa.CheckConstraint(
            "reflux_amount >= 0 and refund_amount >= 0 "
            "and other_deduction_amount >= 0"
        ),
        sa.CheckConstraint(
            "exchange_loss_rate between 0 and 1 "
            "and service_fee_rate between 0 and 1"
        ),
        sa.CheckConstraint("calculation_scale between 0 and 8"),
        sa.ForeignKeyConstraint(
            ["operator_account_id"],
            ["erp_compat_operator_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operator_account_id",
            "business_date",
            name="uq_erp_compat_daily_balance_account_date",
        ),
    )
    op.create_index(
        "ix_erp_compat_daily_balance_account_date",
        "erp_compat_daily_balances",
        ["operator_account_id", "business_date"],
    )
    op.create_index(
        "ix_erp_compat_daily_balance_date_status",
        "erp_compat_daily_balances",
        ["business_date", "status"],
    )
    op.create_table(
        "erp_compat_accounting_period_locks",
        sa.Column("id", _legacy_id_type(), autoincrement=True, nullable=False),
        sa.Column("operator_account_id", _legacy_id_type(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="LOCKED"),
        sa.Column("locked_by", sa.BigInteger()),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("unlock_reason", sa.String(500)),
        sa.Column("unlocked_by", sa.BigInteger()),
        sa.Column("unlocked_at", sa.DateTime(timezone=True)),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["operator_account_id"],
            ["erp_compat_operator_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operator_account_id",
            "period_month",
            name="uq_erp_compat_period_lock_account_month",
        ),
    )


def _create_import_and_audit_tables() -> None:
    op.create_table(
        "erp_compat_import_jobs",
        sa.Column("id", _legacy_id_type(), autoincrement=True, nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("original_filename", sa.String(500)),
        sa.Column("file_sha256", sa.String(64)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "conflict_strategy",
            sa.String(30),
            nullable=False,
            server_default="SKIP_EXISTING",
        ),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("committed_by", sa.BigInteger()),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_erp_compat_import_job_created",
        "erp_compat_import_jobs",
        ["created_by", "created_at"],
    )
    op.create_table(
        "erp_compat_import_job_rows",
        sa.Column("id", _legacy_id_type(), autoincrement=True, nullable=False),
        sa.Column("import_job_id", _legacy_id_type(), nullable=False),
        sa.Column("source_sheet", sa.String(200)),
        sa.Column("source_row", sa.Integer()),
        sa.Column("source_json", sa.Text()),
        sa.Column("normalized_json", sa.Text()),
        sa.Column("operator_name", sa.String(200)),
        sa.Column("operator_account_id", _legacy_id_type()),
        sa.Column("business_date", sa.Date()),
        sa.Column("severity", sa.String(20), nullable=False, server_default="OK"),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.String(1000)),
        sa.Column("action", sa.String(30)),
        sa.Column("target_daily_balance_id", _legacy_id_type()),
        sa.Column("preview_daily_balance_id", _legacy_id_type()),
        sa.Column("preview_row_version", sa.BigInteger()),
        sa.ForeignKeyConstraint(
            ["import_job_id"],
            ["erp_compat_import_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "erp_compat_audit_logs",
        sa.Column("id", _legacy_id_type(), autoincrement=True, nullable=False),
        sa.Column("actor_user_id", sa.BigInteger()),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(100)),
        sa.Column("operator_id", _legacy_id_type()),
        sa.Column("request_id", sa.String(100)),
        sa.Column("ip_address", sa.String(100)),
        sa.Column("reason", sa.String(500)),
        sa.Column("before_json", sa.Text()),
        sa.Column("after_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_erp_compat_audit_operator_created",
        "erp_compat_audit_logs",
        ["operator_id", "created_at"],
    )
    op.create_index(
        "ix_erp_compat_audit_entity",
        "erp_compat_audit_logs",
        ["entity_type", "entity_id", "created_at"],
    )


def _copy_existing_local_data() -> None:
    # Repeat the 0035 core backfill so a deliberately separated 0035→0036
    # rollout cannot strand rows created in the interval.
    _backfill_mapping("operator", "erp_operators")
    _backfill_mapping("operator_line", "erp_operator_lines")
    _backfill_mapping("daily_balance", "erp_daily_balances")
    _backfill_mapping("period_lock", "erp_accounting_period_locks")
    _backfill_mapping("import_job", "erp_import_jobs")
    _backfill_mapping("import_job_row", "erp_import_job_rows")

    op.execute(
        """
        INSERT INTO erp_compat_operators
            (id, code, name, operator_type, status, contact_name, contact_value,
             remark, created_by, updated_by, created_at, updated_at, row_version)
        SELECT mapping.legacy_id, source.code, source.name, source.operator_type,
               source.status, source.contact_name, source.contact_value, source.remark,
               source.created_by, source.updated_by, source.created_at, source.updated_at,
               source.row_version
        FROM erp_operators source
        JOIN erp_compatibility_id_maps mapping
          ON mapping.entity_type = 'operator' AND mapping.canonical_id = source.id
        """
    )
    op.execute(
        """
        INSERT INTO erp_compat_operator_accounts
            (id, operator_id, code, name, asset, network, wallet_address, start_date,
             default_exchange_loss_rate, default_exchange_loss_basis,
             default_service_fee_rate, default_service_fee_basis, calculation_scale,
             status, created_at, updated_at, row_version)
        SELECT line_map.legacy_id, operator_map.legacy_id, source.code, source.name,
               source.asset, source.network, source.wallet_address, source.start_date,
               source.default_exchange_loss_rate, source.default_exchange_loss_basis,
               source.default_service_fee_rate, source.default_service_fee_basis,
               source.calculation_scale, source.status, source.created_at,
               source.updated_at, source.row_version
        FROM erp_operator_lines source
        JOIN erp_compatibility_id_maps line_map
          ON line_map.entity_type = 'operator_line' AND line_map.canonical_id = source.id
        JOIN erp_compatibility_id_maps operator_map
          ON operator_map.entity_type = 'operator'
         AND operator_map.canonical_id = source.operator_id
        """
    )
    op.execute(
        """
        INSERT INTO erp_compat_daily_balances
            (id, operator_account_id, business_date, opening_balance,
             suggested_opening_balance, opening_mode, opening_override_reason,
             transfer_amount, fraud_loss_amount, fraud_deduction_source,
             effective_transfer_amount, spend_amount, exchange_loss_rate,
             exchange_loss_basis, exchange_loss_auto_amount, exchange_loss_amount,
             exchange_loss_mode, exchange_loss_override_reason, service_fee_rate,
             service_fee_basis, service_fee_auto_amount, service_fee_amount,
             service_fee_mode, service_fee_override_reason, reflux_amount,
             refund_amount, other_deduction_amount, other_reason, closing_balance,
             calculation_rule_version, rounding_mode, calculation_scale, status,
             source_type, remark, created_by, updated_by, confirmed_by, confirmed_at,
             created_at, updated_at, row_version)
        SELECT balance_map.legacy_id, line_map.legacy_id, source.business_date,
               source.opening_balance, source.suggested_opening_balance,
               source.opening_mode, source.opening_override_reason,
               source.transfer_amount, source.fraud_loss_amount,
               source.fraud_deduction_source, source.effective_transfer_amount,
               source.spend_amount, source.exchange_loss_rate,
               source.exchange_loss_basis, source.exchange_loss_auto_amount,
               source.exchange_loss_amount, source.exchange_loss_mode,
               source.exchange_loss_override_reason, source.service_fee_rate,
               source.service_fee_basis, source.service_fee_auto_amount,
               source.service_fee_amount, source.service_fee_mode,
               source.service_fee_override_reason, source.reflux_amount,
               source.refund_amount, source.other_deduction_amount,
               source.other_reason, source.closing_balance,
               'BALANCE_V1_GROSS_TRANSFER', 'HALF_UP', source.calculation_scale,
               source.status, source.source_type, source.remark, source.created_by,
               source.updated_by, source.confirmed_by, source.confirmed_at,
               source.created_at, source.updated_at, source.row_version
        FROM erp_daily_balances source
        JOIN erp_compatibility_id_maps balance_map
          ON balance_map.entity_type = 'daily_balance' AND balance_map.canonical_id = source.id
        JOIN erp_compatibility_id_maps line_map
          ON line_map.entity_type = 'operator_line'
         AND line_map.canonical_id = source.operator_line_id
        """
    )
    op.execute(
        """
        INSERT INTO erp_compat_accounting_period_locks
            (id, operator_account_id, period_month, status, locked_by, locked_at,
             unlock_reason, unlocked_by, unlocked_at, row_version)
        SELECT lock_map.legacy_id, line_map.legacy_id, source.month_start,
               source.status, source.locked_by, source.locked_at, source.unlock_reason,
               source.unlocked_by, source.unlocked_at, source.row_version
        FROM erp_accounting_period_locks source
        JOIN erp_compatibility_id_maps lock_map
          ON lock_map.entity_type = 'period_lock' AND lock_map.canonical_id = source.id
        JOIN erp_compatibility_id_maps line_map
          ON line_map.entity_type = 'operator_line'
         AND line_map.canonical_id = source.operator_line_id
        """
    )
    op.execute(
        """
        INSERT INTO erp_compat_import_jobs
            (id, source_type, original_filename, file_sha256, status,
             conflict_strategy, total_rows, valid_rows, warning_rows, error_rows,
             created_by, committed_by, committed_at, created_at, updated_at)
        SELECT job_map.legacy_id, source.source_type, source.original_filename,
               source.file_sha256, source.status, source.conflict_strategy,
               source.total_rows, source.valid_rows, source.warning_rows,
               source.error_rows, source.created_by, source.committed_by,
               source.committed_at, source.created_at, source.updated_at
        FROM erp_import_jobs source
        JOIN erp_compatibility_id_maps job_map
          ON job_map.entity_type = 'import_job' AND job_map.canonical_id = source.id
        """
    )
    op.execute(
        """
        INSERT INTO erp_compat_import_job_rows
            (id, import_job_id, source_sheet, source_row, source_json,
             normalized_json, operator_name, operator_account_id, business_date,
             severity, error_code, error_message, action,
             target_daily_balance_id, preview_daily_balance_id, preview_row_version)
        SELECT row_map.legacy_id, job_map.legacy_id, source.source_sheet,
               source.source_row, CAST(source.source_json AS TEXT),
               CAST(source.normalized_json AS TEXT), operator.name,
               line_map.legacy_id, source.business_date, source.severity,
               source.error_code, source.error_message, source.action,
               target_map.legacy_id, preview_map.legacy_id, source.preview_row_version
        FROM erp_import_job_rows source
        JOIN erp_compatibility_id_maps row_map
          ON row_map.entity_type = 'import_job_row' AND row_map.canonical_id = source.id
        JOIN erp_compatibility_id_maps job_map
          ON job_map.entity_type = 'import_job' AND job_map.canonical_id = source.import_job_id
        LEFT JOIN erp_compatibility_id_maps line_map
          ON line_map.entity_type = 'operator_line'
         AND line_map.canonical_id = source.operator_line_id
        LEFT JOIN erp_operator_lines line ON line.id = source.operator_line_id
        LEFT JOIN erp_operators operator ON operator.id = line.operator_id
        LEFT JOIN erp_compatibility_id_maps target_map
          ON target_map.entity_type = 'daily_balance'
         AND target_map.canonical_id = source.target_daily_balance_id
        LEFT JOIN erp_compatibility_id_maps preview_map
          ON preview_map.entity_type = 'daily_balance'
         AND preview_map.canonical_id = source.preview_daily_balance_id
        """
    )


def _synchronize_postgresql_sequences() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name in (
        "erp_compat_operators",
        "erp_compat_operator_accounts",
        "erp_compat_daily_balances",
        "erp_compat_accounting_period_locks",
        "erp_compat_import_jobs",
        "erp_compat_import_job_rows",
        "erp_compat_audit_logs",
    ):
        op.execute(
            sa.text(
                f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                f"COALESCE(MAX(id), 1), COUNT(*) > 0) FROM {table_name}"
            )
        )


def upgrade() -> None:
    _create_operator_tables()
    _create_balance_tables()
    _create_import_and_audit_tables()
    _copy_existing_local_data()
    _synchronize_postgresql_sequences()


def downgrade() -> None:
    op.drop_index("ix_erp_compat_audit_entity", table_name="erp_compat_audit_logs")
    op.drop_index(
        "ix_erp_compat_audit_operator_created",
        table_name="erp_compat_audit_logs",
    )
    op.drop_table("erp_compat_audit_logs")
    op.drop_table("erp_compat_import_job_rows")
    op.drop_index(
        "ix_erp_compat_import_job_created",
        table_name="erp_compat_import_jobs",
    )
    op.drop_table("erp_compat_import_jobs")
    op.drop_table("erp_compat_accounting_period_locks")
    op.drop_index(
        "ix_erp_compat_daily_balance_date_status",
        table_name="erp_compat_daily_balances",
    )
    op.drop_index(
        "ix_erp_compat_daily_balance_account_date",
        table_name="erp_compat_daily_balances",
    )
    op.drop_table("erp_compat_daily_balances")
    op.drop_index(
        "ix_erp_compat_operator_account_operator_status",
        table_name="erp_compat_operator_accounts",
    )
    op.drop_table("erp_compat_operator_accounts")
    op.drop_table("erp_compat_operators")
