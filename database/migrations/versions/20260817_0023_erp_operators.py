"""add local ERP delivery companies and delivery lines

Revision ID: 20260817_0023
Revises: 20260807_0022
Create Date: 2026-08-17

This revision is intentionally definition-only in the current work session.
Do not execute it until backup, rollback plan and execution window have been
separately approved.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0023"
down_revision: str | None = "20260807_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "erp_operators",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("operator_type", sa.String(length=20), nullable=False, server_default="COMPANY"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("contact_name", sa.String(length=200), nullable=True),
        sa.Column("contact_value", sa.String(length=200), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("operator_type in ('COMPANY', 'STUDIO', 'INDIVIDUAL')"),
        sa.CheckConstraint("status in ('ACTIVE', 'INACTIVE')"),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_erp_operator_code"),
    )
    op.create_index("ix_erp_operator_status", "erp_operators", ["status"])
    op.create_index("ix_erp_operator_name", "erp_operators", ["name"])

    op.create_table(
        "erp_operator_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("operator_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("asset", sa.String(length=10), nullable=False, server_default="USDT"),
        sa.Column("network", sa.String(length=120), nullable=True),
        sa.Column("wallet_address", sa.String(length=500), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column(
            "default_exchange_loss_rate",
            sa.Numeric(12, 8),
            nullable=False,
            server_default="0.02",
        ),
        sa.Column(
            "default_exchange_loss_basis",
            sa.String(length=30),
            nullable=False,
            server_default="TRANSFER",
        ),
        sa.Column(
            "default_service_fee_rate",
            sa.Numeric(12, 8),
            nullable=False,
            server_default="0.02",
        ),
        sa.Column(
            "default_service_fee_basis",
            sa.String(length=30),
            nullable=False,
            server_default="TRANSFER",
        ),
        sa.Column("calculation_scale", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("asset in ('USDT', 'USDC')"),
        sa.CheckConstraint("default_exchange_loss_rate between 0 and 1"),
        sa.CheckConstraint("default_service_fee_rate between 0 and 1"),
        sa.CheckConstraint("calculation_scale between 0 and 8"),
        sa.CheckConstraint("status in ('ACTIVE', 'INACTIVE')"),
        sa.ForeignKeyConstraint(["operator_id"], ["erp_operators.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operator_id", "code", name="uq_erp_operator_line_code"),
        sa.UniqueConstraint("operator_id", "name", name="uq_erp_operator_line_name"),
    )
    op.create_index(
        "ix_erp_operator_line_operator_status",
        "erp_operator_lines",
        ["operator_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_erp_operator_line_operator_status", table_name="erp_operator_lines")
    op.drop_table("erp_operator_lines")
    op.drop_index("ix_erp_operator_name", table_name="erp_operators")
    op.drop_index("ix_erp_operator_status", table_name="erp_operators")
    op.drop_table("erp_operators")
