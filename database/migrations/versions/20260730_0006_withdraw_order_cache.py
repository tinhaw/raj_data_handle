"""add local withdrawal-order cache and refresh policy

Revision ID: 20260730_0006
Revises: 20260730_0005
Create Date: 2026-07-30

Remote withdrawal data is refreshed only by the worker and persisted as a
source-scoped, approved-field snapshot.  The monitoring API queries this cache
instead of the remote system.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0006"
down_revision: str | None = "20260730_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "system_retention_settings",
        sa.Column(
            "withdraw_order_query_range",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'today'"),
        ),
    )

    op.create_table(
        "withdraw_order_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("remote_order_id", sa.String(length=120), nullable=False),
        sa.Column("uid", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.String(length=64), nullable=True),
        sa.Column("real_amount", sa.String(length=64), nullable=True),
        sa.Column("create_time", sa.String(length=32), nullable=True),
        sa.Column("create_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("update_time", sa.String(length=32), nullable=True),
        sa.Column("submit_time", sa.String(length=32), nullable=True),
        sa.Column("audit_admin", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["source_configs.source_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "remote_order_id",
            name="uq_withdraw_order_snapshot_source_remote_id",
        ),
    )
    op.create_index(
        "ix_withdraw_order_snapshots_source_id",
        "withdraw_order_snapshots",
        ["source_id"],
    )
    op.create_index(
        "ix_withdraw_order_snapshots_synced_at",
        "withdraw_order_snapshots",
        ["synced_at"],
    )
    op.create_index(
        "ix_withdraw_order_snapshot_source_create_time",
        "withdraw_order_snapshots",
        ["source_id", "create_time_utc"],
    )
    op.create_index(
        "ix_withdraw_order_snapshot_source_status",
        "withdraw_order_snapshots",
        ["source_id", "status"],
    )
    op.create_index(
        "ix_withdraw_order_snapshot_source_uid",
        "withdraw_order_snapshots",
        ["source_id", "uid"],
    )

    op.create_table(
        "withdraw_order_refresh_states",
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("manual_request_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_window_start_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_window_end_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_remote_total", sa.Integer(), nullable=False),
        sa.Column("last_cached_total", sa.Integer(), nullable=False),
        sa.Column("last_fetched_pages", sa.Integer(), nullable=False),
        sa.Column("last_complete", sa.Boolean(), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["source_configs.source_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id"),
    )
    op.create_index(
        "ix_withdraw_order_refresh_states_status",
        "withdraw_order_refresh_states",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_withdraw_order_refresh_states_status",
        table_name="withdraw_order_refresh_states",
    )
    op.drop_table("withdraw_order_refresh_states")
    op.drop_index("ix_withdraw_order_snapshot_source_uid", table_name="withdraw_order_snapshots")
    op.drop_index("ix_withdraw_order_snapshot_source_status", table_name="withdraw_order_snapshots")
    op.drop_index(
        "ix_withdraw_order_snapshot_source_create_time",
        table_name="withdraw_order_snapshots",
    )
    op.drop_index("ix_withdraw_order_snapshots_synced_at", table_name="withdraw_order_snapshots")
    op.drop_index("ix_withdraw_order_snapshots_source_id", table_name="withdraw_order_snapshots")
    op.drop_table("withdraw_order_snapshots")
    op.drop_column("system_retention_settings", "withdraw_order_query_range")
