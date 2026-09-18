"""add locally cached data dictionary entries

Revision ID: 20260728_0002
Revises: 20260725_0001
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0002"
down_revision: str | None = "20260725_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_dictionary_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("dictionary_type", sa.String(length=80), nullable=False),
        sa.Column("entry_code", sa.String(length=80), nullable=False),
        sa.Column("entry_label", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_configs.source_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "dictionary_type",
            "entry_code",
            name="uq_data_dictionary_source_type_code",
        ),
    )
    op.create_index(
        "ix_data_dictionary_entries_dictionary_type",
        "data_dictionary_entries",
        ["dictionary_type"],
    )
    op.create_index(
        "ix_data_dictionary_entries_source_id",
        "data_dictionary_entries",
        ["source_id"],
    )
    op.create_index(
        "ix_data_dictionary_type_active",
        "data_dictionary_entries",
        ["dictionary_type", "active"],
    )


def downgrade() -> None:
    op.drop_table("data_dictionary_entries")
