"""Add unified-account tag snapshots and reward tier presets.

Revision ID: 20260818_0033
Revises: 20260818_0032
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0033"
down_revision = "20260818_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "remote_account_tag_snapshots",
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["remote_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("account_id"),
    )
    op.create_table(
        "remote_account_reward_tier_presets",
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("tiers_json", sa.JSON(), nullable=False),
        sa.Column("tag_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("saved_by", sa.Integer(), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["remote_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["saved_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("account_id"),
    )


def downgrade() -> None:
    op.drop_table("remote_account_reward_tier_presets")
    op.drop_table("remote_account_tag_snapshots")
