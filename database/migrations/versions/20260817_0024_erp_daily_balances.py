"""add local ERP daily ledger records

Revision ID: 20260817_0024
Revises: 20260817_0023
Create Date: 2026-08-17

This revision is not authorized to run in the current work session. It remains
an unexecuted code artifact until backup, rollback and execution window are
separately approved.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0024"
down_revision: str | None = "20260817_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "erp_daily_balances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("operator_line_id", sa.String(length=36), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column(
            "opening_balance",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column("suggested_opening_balance", sa.Numeric(24, 8), nullable=True),
        sa.Column(
            "opening_mode",
            sa.String(length=20),
            nullable=False,
            server_default="AUTO",
        ),
        sa.Column("opening_override_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "transfer_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "fraud_loss_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column("fraud_deduction_source", sa.String(length=20), nullable=True),
        sa.Column(
            "effective_transfer_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "spend_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "exchange_loss_rate",
            sa.Numeric(12, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "exchange_loss_basis",
            sa.String(length=30),
            nullable=False,
            server_default="TRANSFER",
        ),
        sa.Column(
            "exchange_loss_auto_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "exchange_loss_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "exchange_loss_mode",
            sa.String(length=20),
            nullable=False,
            server_default="AUTO",
        ),
        sa.Column("exchange_loss_override_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "service_fee_rate",
            sa.Numeric(12, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "service_fee_basis",
            sa.String(length=30),
            nullable=False,
            server_default="TRANSFER",
        ),
        sa.Column(
            "service_fee_auto_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "service_fee_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "service_fee_mode",
            sa.String(length=20),
            nullable=False,
            server_default="AUTO",
        ),
        sa.Column("service_fee_override_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "reflux_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "refund_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "other_deduction_amount",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column("other_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "closing_balance",
            sa.Numeric(24, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "calculation_scale",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "source_type",
            sa.String(length=20),
            nullable=False,
            server_default="MANUAL",
        ),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("confirmed_by", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("opening_mode in ('AUTO', 'MANUAL')"),
        sa.CheckConstraint(
            "fraud_deduction_source in ('TRANSFER', 'BALANCE') "
            "or fraud_deduction_source is null"
        ),
        sa.CheckConstraint(
            "exchange_loss_basis in "
            "('TRANSFER', 'EFFECTIVE_TRANSFER', 'SPEND', 'MANUAL')"
        ),
        sa.CheckConstraint(
            "service_fee_basis in "
            "('TRANSFER', 'EFFECTIVE_TRANSFER', 'SPEND', 'MANUAL')"
        ),
        sa.CheckConstraint("exchange_loss_mode in ('AUTO', 'MANUAL')"),
        sa.CheckConstraint("service_fee_mode in ('AUTO', 'MANUAL')"),
        sa.CheckConstraint("status in ('DRAFT', 'CONFIRMED')"),
        sa.CheckConstraint("source_type in ('MANUAL', 'PASTE', 'IMPORT')"),
        sa.CheckConstraint("calculation_scale between 0 and 8"),
        sa.ForeignKeyConstraint(
            ["operator_line_id"],
            ["erp_operator_lines.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["confirmed_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operator_line_id",
            "business_date",
            name="uq_erp_daily_balance_line_date",
        ),
    )
    op.create_index(
        "ix_erp_daily_balance_line_date",
        "erp_daily_balances",
        ["operator_line_id", "business_date"],
    )
    op.create_index(
        "ix_erp_daily_balance_date_status",
        "erp_daily_balances",
        ["business_date", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_erp_daily_balance_date_status", table_name="erp_daily_balances")
    op.drop_index("ix_erp_daily_balance_line_date", table_name="erp_daily_balances")
    op.drop_table("erp_daily_balances")
