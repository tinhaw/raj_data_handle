"""add append-only operational data-sync run logs

Revision ID: 20260801_0018
Revises: 20260801_0017
Create Date: 2026-08-01

The existing per-source refresh-state rows intentionally keep only the latest
state.  This migration adds a separate append-only history for remote order
syncs and score-review imports, plus pointers from the refresh states to their
pending and active run records.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0018"
down_revision: str | None = "20260801_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_refresh_run_pointers(table_name: str, *, prefix: str) -> None:
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(sa.Column("pending_sync_run_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("active_sync_run_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            f"fk_{prefix}_pending_sync_run",
            "data_sync_runs",
            ["pending_sync_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            f"fk_{prefix}_active_sync_run",
            "data_sync_runs",
            ["active_sync_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            f"ix_{table_name}_pending_sync_run_id",
            ["pending_sync_run_id"],
            unique=False,
        )
        batch_op.create_index(
            f"ix_{table_name}_active_sync_run_id",
            ["active_sync_run_id"],
            unique=False,
        )


def _drop_refresh_run_pointers(table_name: str, *, prefix: str) -> None:
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.drop_index(f"ix_{table_name}_active_sync_run_id")
        batch_op.drop_index(f"ix_{table_name}_pending_sync_run_id")
        batch_op.drop_constraint(f"fk_{prefix}_active_sync_run", type_="foreignkey")
        batch_op.drop_constraint(f"fk_{prefix}_pending_sync_run", type_="foreignkey")
        batch_op.drop_column("active_sync_run_id")
        batch_op.drop_column("pending_sync_run_id")


def upgrade() -> None:
    op.create_table(
        "data_sync_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("source_display_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("business_timezone", sa.String(length=80), nullable=True),
        sa.Column("source_config_version", sa.Integer(), nullable=True),
        sa.Column("business_type", sa.String(length=48), nullable=False),
        sa.Column(
            "operation_kind",
            sa.String(length=32),
            nullable=False,
            server_default="remote_sync",
        ),
        sa.Column("trigger_type", sa.String(length=32), nullable=False, server_default="automatic"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("requested_by_display_name", sa.String(length=120), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_start_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("query_range", sa.String(length=64), nullable=True),
        sa.Column("page_size", sa.Integer(), nullable=True),
        sa.Column("remote_total", sa.Integer(), nullable=True),
        sa.Column("export_row_count", sa.Integer(), nullable=True),
        sa.Column("cached_total", sa.Integer(), nullable=True),
        sa.Column("fetched_pages", sa.Integer(), nullable=True),
        sa.Column("imported_count", sa.Integer(), nullable=True),
        sa.Column("created_count", sa.Integer(), nullable=True),
        sa.Column("updated_count", sa.Integer(), nullable=True),
        sa.Column("duplicate_count", sa.Integer(), nullable=True),
        sa.Column("matched_count", sa.Integer(), nullable=True),
        sa.Column("unmatched_count", sa.Integer(), nullable=True),
        sa.Column("resolved_uid_count", sa.Integer(), nullable=True),
        sa.Column("unresolved_uid_count", sa.Integer(), nullable=True),
        sa.Column("complete", sa.Boolean(), nullable=True),
        sa.Column("input_filename", sa.String(length=255), nullable=True),
        sa.Column("input_size_bytes", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["app_users.id"],
            name="fk_data_sync_runs_requested_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_configs.source_id"],
            name="fk_data_sync_runs_source",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_sync_runs_source_id", "data_sync_runs", ["source_id"])
    op.create_index("ix_data_sync_runs_business_type", "data_sync_runs", ["business_type"])
    op.create_index("ix_data_sync_runs_status", "data_sync_runs", ["status"])
    op.create_index(
        "ix_data_sync_runs_requested_by_user_id",
        "data_sync_runs",
        ["requested_by_user_id"],
    )
    op.create_index("ix_data_sync_runs_requested_at", "data_sync_runs", ["requested_at"])
    op.create_index("ix_data_sync_runs_started_at", "data_sync_runs", ["started_at"])
    op.create_index(
        "ix_data_sync_runs_source_requested",
        "data_sync_runs",
        ["source_id", "requested_at"],
    )
    op.create_index(
        "ix_data_sync_runs_business_status_requested",
        "data_sync_runs",
        ["business_type", "status", "requested_at"],
    )
    op.create_index("ix_data_sync_runs_finished", "data_sync_runs", ["finished_at"])

    op.create_table(
        "data_sync_run_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["data_sync_runs.id"],
            name="fk_data_sync_run_events_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_sync_run_events_run_id", "data_sync_run_events", ["run_id"])
    op.create_index(
        "ix_data_sync_run_events_occurred_at",
        "data_sync_run_events",
        ["occurred_at"],
    )
    op.create_index(
        "ix_data_sync_run_events_run_occurred",
        "data_sync_run_events",
        ["run_id", "occurred_at"],
    )

    with op.batch_alter_table("system_retention_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "sync_log_retention_days",
                sa.Integer(),
                nullable=False,
                server_default="30",
            )
        )

    _add_refresh_run_pointers(
        "withdraw_order_refresh_states",
        prefix="withdraw_order_refresh_state",
    )
    _add_refresh_run_pointers(
        "charge_order_refresh_states",
        prefix="charge_order_refresh_state",
    )
    _add_refresh_run_pointers(
        "spin_order_refresh_states",
        prefix="spin_order_refresh_state",
    )


def downgrade() -> None:
    _drop_refresh_run_pointers(
        "spin_order_refresh_states",
        prefix="spin_order_refresh_state",
    )
    _drop_refresh_run_pointers(
        "charge_order_refresh_states",
        prefix="charge_order_refresh_state",
    )
    _drop_refresh_run_pointers(
        "withdraw_order_refresh_states",
        prefix="withdraw_order_refresh_state",
    )

    with op.batch_alter_table("system_retention_settings") as batch_op:
        batch_op.drop_column("sync_log_retention_days")

    op.drop_index("ix_data_sync_run_events_run_occurred", table_name="data_sync_run_events")
    op.drop_index("ix_data_sync_run_events_occurred_at", table_name="data_sync_run_events")
    op.drop_index("ix_data_sync_run_events_run_id", table_name="data_sync_run_events")
    op.drop_table("data_sync_run_events")

    op.drop_index("ix_data_sync_runs_finished", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_business_status_requested", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_source_requested", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_started_at", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_requested_at", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_requested_by_user_id", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_status", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_business_type", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_source_id", table_name="data_sync_runs")
    op.drop_table("data_sync_runs")
