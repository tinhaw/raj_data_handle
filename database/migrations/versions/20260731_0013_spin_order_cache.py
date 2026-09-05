"""add locally cached turntable orders and source-channel dictionaries

Revision ID: 20260731_0013
Revises: 20260731_0012
Create Date: 2026-07-31

The turntable order cache stores only the reporting fields approved for this
read-only analysis system.  UID-to-channel resolution is kept in a separate,
minimal cache so no full user profile is copied into the RDS database.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0013"
down_revision: str | None = "20260731_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SPIN_ORDER_STATUSES = (
    ("0", "待审核"),
    ("1", "审核通过"),
    ("101", "自动审核通过"),
    ("2", "已拒绝"),
    ("3", "已挂起"),
)


def _seed_spin_order_statuses() -> None:
    connection = op.get_bind()
    sources = sa.table("source_configs", sa.column("source_id", sa.String(length=64)))
    entries = sa.table(
        "data_dictionary_entries",
        sa.column("source_id", sa.String(length=64)),
        sa.column("dictionary_type", sa.String(length=80)),
        sa.column("entry_code", sa.String(length=80)),
        sa.column("entry_label", sa.String(length=255)),
        sa.column("active", sa.Boolean()),
        sa.column("first_seen_at", sa.DateTime(timezone=True)),
        sa.column("last_seen_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    source_ids = list(connection.scalars(sa.select(sources.c.source_id)))
    existing = set(
        connection.execute(
            sa.select(entries.c.source_id, entries.c.entry_code).where(
                entries.c.dictionary_type == "spin_order_status"
            )
        ).all()
    )
    observed_at = datetime.now(UTC)
    labels = dict(SPIN_ORDER_STATUSES)
    for source_id, code in existing:
        label = labels.get(code)
        if label is None:
            continue
        connection.execute(
            sa.update(entries)
            .where(
                entries.c.source_id == source_id,
                entries.c.dictionary_type == "spin_order_status",
                entries.c.entry_code == code,
            )
            .values(
                entry_label=label,
                active=True,
                last_seen_at=observed_at,
                updated_at=observed_at,
            )
        )
    rows = [
        {
            "source_id": source_id,
            "dictionary_type": "spin_order_status",
            "entry_code": code,
            "entry_label": label,
            "active": True,
            "first_seen_at": observed_at,
            "last_seen_at": observed_at,
            "updated_at": observed_at,
        }
        for source_id in source_ids
        for code, label in SPIN_ORDER_STATUSES
        if (source_id, code) not in existing
    ]
    if rows:
        op.bulk_insert(entries, rows)


def upgrade() -> None:
    op.create_table(
        "spin_order_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("remote_order_id", sa.String(length=120), nullable=False),
        sa.Column("uid", sa.String(length=64), nullable=False),
        sa.Column("vip_level", sa.String(length=40), nullable=True),
        sa.Column("agent_total_count", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.String(length=64), nullable=True),
        sa.Column("spin_config_id", sa.String(length=40), nullable=False),
        sa.Column("round_number", sa.String(length=40), nullable=True),
        sa.Column("invite_count", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("status_label", sa.String(length=120), nullable=True),
        sa.Column("create_time", sa.String(length=32), nullable=True),
        sa.Column("create_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audit_time", sa.String(length=32), nullable=True),
        sa.Column("audit_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("channel_id", sa.String(length=120), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["source_configs.source_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "remote_order_id",
            name="uq_spin_order_snapshot_source_remote_id",
        ),
    )
    for name, columns in (
        ("ix_spin_order_snapshots_source_id", ["source_id"]),
        ("ix_spin_order_snapshots_synced_at", ["synced_at"]),
        ("ix_spin_order_snapshot_source_create_time", ["source_id", "create_time_utc"]),
        ("ix_spin_order_snapshot_source_status", ["source_id", "status"]),
        ("ix_spin_order_snapshot_source_uid", ["source_id", "uid"]),
        ("ix_spin_order_snapshot_source_config", ["source_id", "spin_config_id"]),
        ("ix_spin_order_snapshot_source_channel", ["source_id", "channel_id"]),
    ):
        op.create_index(name, "spin_order_snapshots", columns)

    op.create_table(
        "user_channel_caches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("uid", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=120), nullable=True),
        sa.Column("resolution_status", sa.String(length=20), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["source_configs.source_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "uid", name="uq_user_channel_cache_source_uid"),
    )
    for name, columns in (
        ("ix_user_channel_caches_source_id", ["source_id"]),
        ("ix_user_channel_cache_source_status", ["source_id", "resolution_status"]),
    ):
        op.create_index(name, "user_channel_caches", columns)

    op.create_table(
        "spin_order_refresh_states",
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
        sa.Column("last_resolved_uid_count", sa.Integer(), nullable=False),
        sa.Column("last_unresolved_uid_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["source_configs.source_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id"),
    )
    op.create_index(
        "ix_spin_order_refresh_states_status",
        "spin_order_refresh_states",
        ["status"],
    )
    _seed_spin_order_statuses()


def downgrade() -> None:
    entries = sa.table(
        "data_dictionary_entries",
        sa.column("dictionary_type", sa.String(length=80)),
        sa.column("entry_code", sa.String(length=80)),
    )
    op.execute(
        sa.delete(entries).where(
            entries.c.dictionary_type == "spin_order_status",
            entries.c.entry_code.in_([code for code, _label in SPIN_ORDER_STATUSES]),
        )
    )
    op.drop_index("ix_spin_order_refresh_states_status", table_name="spin_order_refresh_states")
    op.drop_table("spin_order_refresh_states")
    for name in (
        "ix_user_channel_cache_source_status",
        "ix_user_channel_caches_source_id",
    ):
        op.drop_index(name, table_name="user_channel_caches")
    op.drop_table("user_channel_caches")
    for name in (
        "ix_spin_order_snapshot_source_channel",
        "ix_spin_order_snapshot_source_config",
        "ix_spin_order_snapshot_source_uid",
        "ix_spin_order_snapshot_source_status",
        "ix_spin_order_snapshot_source_create_time",
        "ix_spin_order_snapshots_synced_at",
        "ix_spin_order_snapshots_source_id",
    ):
        op.drop_index(name, table_name="spin_order_snapshots")
    op.drop_table("spin_order_snapshots")
