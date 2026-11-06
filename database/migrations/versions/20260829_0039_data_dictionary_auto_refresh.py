"""add source-scoped data dictionary automatic refresh settings

Revision ID: 20260829_0039
Revises: 20260828_0038
Create Date: 2026-08-29

The migration only creates local scheduling metadata. Automatic refresh stays
disabled until an administrator explicitly enables a source and dictionary.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0039"
down_revision: str | None = "20260828_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_dictionary_refresh_configs",
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("dictionary_type", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="360"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "interval_minutes IN (15, 30, 60, 180, 360, 720, 1440)",
            name="ck_data_dictionary_refresh_interval",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_configs.source_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("source_id", "dictionary_type"),
    )
    op.create_index(
        "ix_data_dictionary_refresh_due",
        "data_dictionary_refresh_configs",
        ["enabled", "next_refresh_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_data_dictionary_refresh_due",
        table_name="data_dictionary_refresh_configs",
    )
    op.drop_table("data_dictionary_refresh_configs")
