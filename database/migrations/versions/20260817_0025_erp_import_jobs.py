"""add local ERP ledger import preview tables

Revision ID: 20260817_0025
Revises: 20260817_0024
Create Date: 2026-08-17

This revision is intentionally unexecuted.  Database migration requires a
separate approval for backup, rollback plan and execution window.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0025"
down_revision: str | None = "20260817_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "erp_import_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="PREVIEW_READY",
        ),
        sa.Column(
            "conflict_strategy",
            sa.String(length=30),
            nullable=False,
            server_default="SKIP_EXISTING",
        ),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("committed_by", sa.Integer(), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["committed_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_erp_import_jobs_file_sha256", "erp_import_jobs", ["file_sha256"])
    op.create_table(
        "erp_import_job_rows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("import_job_id", sa.String(length=36), nullable=False),
        sa.Column("source_sheet", sa.String(length=200), nullable=True),
        sa.Column("source_row", sa.Integer(), nullable=True),
        sa.Column("source_json", sa.JSON(), nullable=False),
        sa.Column("normalized_json", sa.JSON(), nullable=True),
        sa.Column("operator_line_id", sa.String(length=36), nullable=True),
        sa.Column("business_date", sa.Date(), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="OK"),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=True),
        sa.Column("target_daily_balance_id", sa.String(length=36), nullable=True),
        sa.Column("preview_daily_balance_id", sa.String(length=36), nullable=True),
        sa.Column("preview_row_version", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["import_job_id"],
            ["erp_import_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["operator_line_id"],
            ["erp_operator_lines.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_daily_balance_id"],
            ["erp_daily_balances.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_erp_import_job_rows_import_job_id",
        "erp_import_job_rows",
        ["import_job_id"],
    )
    op.create_index(
        "ix_erp_import_job_rows_operator_line_id",
        "erp_import_job_rows",
        ["operator_line_id"],
    )
    op.create_index(
        "ix_erp_import_job_row_job_source",
        "erp_import_job_rows",
        ["import_job_id", "source_sheet", "source_row"],
    )


def downgrade() -> None:
    op.drop_index("ix_erp_import_job_row_job_source", table_name="erp_import_job_rows")
    op.drop_index("ix_erp_import_job_rows_operator_line_id", table_name="erp_import_job_rows")
    op.drop_index("ix_erp_import_job_rows_import_job_id", table_name="erp_import_job_rows")
    op.drop_table("erp_import_job_rows")
    op.drop_index("ix_erp_import_jobs_file_sha256", table_name="erp_import_jobs")
    op.drop_table("erp_import_jobs")
