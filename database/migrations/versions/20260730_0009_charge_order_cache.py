"""add local recharge-order cache and refresh policy

Revision ID: 20260730_0009
Revises: 20260730_0008
Create Date: 2026-07-30

Recharge orders are copied from the remote read-only API by the worker only.
The web page reads the approved local snapshot fields and never fetches remote
orders on page load.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0009"
down_revision: str | None = "20260730_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "system_retention_settings",
        sa.Column(
            "charge_order_refresh_interval_hours",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "system_retention_settings",
        sa.Column(
            "charge_order_refresh_page_size",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
    )
    op.add_column(
        "system_retention_settings",
        sa.Column(
            "charge_order_query_range",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'today'"),
        ),
    )
    op.create_table(
        "charge_order_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("remote_order_id", sa.String(length=120), nullable=False),
        sa.Column("uid", sa.String(length=64), nullable=False),
        sa.Column("order_num", sa.String(length=160), nullable=True),
        sa.Column("out_trade_no", sa.String(length=160), nullable=True),
        sa.Column("pay_method", sa.String(length=120), nullable=True),
        sa.Column("pay_channel_name", sa.String(length=160), nullable=True),
        sa.Column("amount", sa.String(length=64), nullable=True),
        sa.Column("balance", sa.String(length=64), nullable=True),
        sa.Column("extra", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("create_time", sa.String(length=32), nullable=True),
        sa.Column("create_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pay_time", sa.String(length=32), nullable=True),
        sa.Column("update_time", sa.String(length=32), nullable=True),
        sa.Column("first_pay", sa.String(length=40), nullable=True),
        sa.Column("notified", sa.String(length=40), nullable=True),
        sa.Column("charge_type", sa.String(length=80), nullable=True),
        sa.Column("channel", sa.String(length=120), nullable=True),
        sa.Column("fill_order_id", sa.String(length=120), nullable=True),
        sa.Column("fill_order_num", sa.String(length=160), nullable=True),
        sa.Column("fill_order_admin", sa.String(length=160), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["source_configs.source_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "remote_order_id",
            name="uq_charge_order_snapshot_source_remote_id",
        ),
    )
    for name, columns in (
        ("ix_charge_order_snapshots_source_id", ["source_id"]),
        ("ix_charge_order_snapshots_synced_at", ["synced_at"]),
        ("ix_charge_order_snapshot_source_create_time", ["source_id", "create_time_utc"]),
        ("ix_charge_order_snapshot_source_status", ["source_id", "status"]),
        ("ix_charge_order_snapshot_source_uid", ["source_id", "uid"]),
        ("ix_charge_order_snapshot_source_channel", ["source_id", "pay_method"]),
    ):
        op.create_index(name, "charge_order_snapshots", columns)
    op.create_table(
        "charge_order_refresh_states",
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("manual_request_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manual_query_range", sa.String(length=32), nullable=True),
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
        "ix_charge_order_refresh_states_status",
        "charge_order_refresh_states",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_charge_order_refresh_states_status", table_name="charge_order_refresh_states")
    op.drop_table("charge_order_refresh_states")
    for name in (
        "ix_charge_order_snapshot_source_channel",
        "ix_charge_order_snapshot_source_uid",
        "ix_charge_order_snapshot_source_status",
        "ix_charge_order_snapshot_source_create_time",
        "ix_charge_order_snapshots_synced_at",
        "ix_charge_order_snapshots_source_id",
    ):
        op.drop_index(name, table_name="charge_order_snapshots")
    op.drop_table("charge_order_snapshots")
    op.drop_column("system_retention_settings", "charge_order_query_range")
    op.drop_column("system_retention_settings", "charge_order_refresh_page_size")
    op.drop_column("system_retention_settings", "charge_order_refresh_interval_hours")
