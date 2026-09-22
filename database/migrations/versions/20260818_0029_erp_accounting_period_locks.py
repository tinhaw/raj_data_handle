"""add local ERP accounting period locks

Revision ID: 20260818_0029
Revises: 20260818_0028
Create Date: 2026-08-18

This schema definition is intentionally not authorized for production
execution. Apply it only after the target environment, backup, rollback plan
and execution window have been explicitly approved.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0029"
down_revision: str | None = "20260818_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "erp_accounting_period_locks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("operator_line_id", sa.String(length=36), nullable=False),
        sa.Column("month_start", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="LOCKED"),
        sa.Column("locked_by", sa.Integer(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlock_reason", sa.String(length=500), nullable=True),
        sa.Column("unlocked_by", sa.Integer(), nullable=True),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status in ('LOCKED', 'UNLOCKED')"),
        sa.ForeignKeyConstraint(
            ["operator_line_id"],
            ["erp_operator_lines.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["locked_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["unlocked_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operator_line_id",
            "month_start",
            name="uq_erp_period_lock_line_month",
        ),
    )
    op.create_index(
        "ix_erp_period_lock_month_status",
        "erp_accounting_period_locks",
        ["month_start", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_erp_period_lock_month_status", table_name="erp_accounting_period_locks")
    op.drop_table("erp_accounting_period_locks")
