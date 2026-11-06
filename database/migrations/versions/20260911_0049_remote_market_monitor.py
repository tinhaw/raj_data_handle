"""add durable remote-market monitoring and notification outbox tables

The migration is additive.  Existing source configuration, remote-account
credentials, and the legacy browser-only monitor remain usable until the
application switches to the new background monitor.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0049"
down_revision: str | None = "20260906_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps(table: str) -> list[sa.Column[object]]:
    del table
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "remote_market_monitor_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("monitor_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "delivery_mode", sa.String(length=20), nullable=False, server_default="record_only"
        ),
        sa.Column(
            "dashboard_refresh_interval_seconds", sa.Integer(), nullable=False, server_default="30"
        ),
        sa.Column(
            "default_check_interval_seconds", sa.Integer(), nullable=False, server_default="60"
        ),
        sa.Column(
            "source_request_timeout_seconds", sa.Integer(), nullable=False, server_default="15"
        ),
        sa.Column(
            "default_breach_consecutive_checks", sa.Integer(), nullable=False, server_default="2"
        ),
        sa.Column(
            "default_recovery_consecutive_checks", sa.Integer(), nullable=False, server_default="2"
        ),
        sa.Column(
            "source_failure_consecutive_checks", sa.Integer(), nullable=False, server_default="2"
        ),
        sa.Column(
            "default_reminder_interval_minutes", sa.Integer(), nullable=False, server_default="10"
        ),
        sa.Column(
            "source_reminder_interval_minutes", sa.Integer(), nullable=False, server_default="15"
        ),
        sa.Column("stale_after_multiplier", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("notification_max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("check_run_retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column(
            "notification_attempt_retention_days", sa.Integer(), nullable=False, server_default="90"
        ),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("app_users.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "delivery_mode in ('record_only', 'telegram')", name="ck_monitor_delivery_mode"
        ),
    )
    op.create_table(
        "monitor_notification_template_sets",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("templates_json", sa.JSON(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("app_users.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "monitor_notification_destinations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("display_name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="telegram"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("bot_token_secret_ref", sa.String(length=200), nullable=False),
        sa.Column("chat_id_secret_ref", sa.String(length=200), nullable=False),
        sa.Column(
            "template_set_id",
            sa.String(length=64),
            sa.ForeignKey("monitor_notification_template_sets.id", ondelete="RESTRICT"),
            nullable=False,
            server_default="default-zh",
        ),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("app_users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("app_users.id", ondelete="SET NULL")),
        *_timestamps("monitor_notification_destinations"),
        sa.CheckConstraint("channel = 'telegram'", name="ck_monitor_destination_channel"),
    )
    op.create_table(
        "remote_market_monitor_target_settings",
        sa.Column(
            "source_id",
            sa.String(length=64),
            sa.ForeignKey("source_configs.source_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("check_interval_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column(
            "query_window_mode",
            sa.String(length=48),
            nullable=False,
            server_default="business_today",
        ),
        sa.Column("previous_days", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_failure_consecutive_checks", sa.Integer()),
        sa.Column("source_reminder_interval_minutes", sa.Integer()),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("app_users.id", ondelete="SET NULL")),
        *_timestamps("remote_market_monitor_target_settings"),
        sa.CheckConstraint(
            "check_interval_seconds between 30 and 3600", name="ck_monitor_target_interval"
        ),
        sa.CheckConstraint(
            "query_window_mode in ('business_today', 'business_today_and_previous_days')",
            name="ck_monitor_target_window",
        ),
    )
    op.create_index(
        "ix_remote_market_monitor_target_settings_next_check_at",
        "remote_market_monitor_target_settings",
        ["next_check_at"],
    )
    op.create_table(
        "remote_market_monitor_metric_policies",
        sa.Column(
            "source_id",
            sa.String(length=64),
            sa.ForeignKey("source_configs.source_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("metric", sa.String(length=40), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("comparison", sa.String(length=8), nullable=False, server_default="gt"),
        sa.Column("threshold", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("recovery_threshold", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("breach_consecutive_checks", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("recovery_consecutive_checks", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("reminder_interval_minutes", sa.Integer()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("app_users.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "metric in ('pending_audit', 'pending_review')", name="ck_monitor_metric"
        ),
        sa.CheckConstraint("comparison in ('gt', 'gte')", name="ck_monitor_comparison"),
        sa.CheckConstraint(
            "threshold >= 0 and recovery_threshold >= 0", name="ck_monitor_thresholds"
        ),
        sa.CheckConstraint("recovery_threshold <= threshold", name="ck_monitor_recovery_threshold"),
    )
    op.create_table(
        "remote_market_monitor_target_destinations",
        sa.Column(
            "source_id",
            sa.String(length=64),
            sa.ForeignKey("source_configs.source_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "destination_id",
            sa.String(length=36),
            sa.ForeignKey("monitor_notification_destinations.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "remote_market_monitor_states",
        sa.Column(
            "source_id",
            sa.String(length=64),
            sa.ForeignKey("source_configs.source_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("lease_owner", sa.String(length=120)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_check_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_pending_audit_count", sa.Integer()),
        sa.Column("last_pending_review_count", sa.Integer()),
        sa.Column("source_health", sa.String(length=20), nullable=False, server_default="healthy"),
        sa.Column(
            "consecutive_source_failure_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_error_code", sa.String(length=64)),
        sa.Column("last_safe_error_message", sa.String(length=500)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_remote_market_monitor_states_lease_expires_at",
        "remote_market_monitor_states",
        ["lease_expires_at"],
    )
    op.create_table(
        "remote_market_monitor_check_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(length=64),
            sa.ForeignKey("source_configs.source_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("run_mode", sa.String(length=20), nullable=False, server_default="automatic"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pending_audit_count", sa.Integer()),
        sa.Column("pending_review_count", sa.Integer()),
        sa.Column("query_range_start", sa.DateTime(timezone=True)),
        sa.Column("query_range_end", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("safe_error_message", sa.String(length=500)),
    )
    op.create_index(
        "ix_remote_market_monitor_check_runs_source_id",
        "remote_market_monitor_check_runs",
        ["source_id"],
    )
    op.create_table(
        "remote_market_monitor_incidents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(length=64),
            sa.ForeignKey("source_configs.source_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(length=40), nullable=False),
        sa.Column("incident_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("opening_count", sa.Integer()),
        sa.Column("latest_count", sa.Integer()),
        sa.Column("peak_count", sa.Integer()),
        sa.Column("consecutive_hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_recovery_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(length=64)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_remote_market_monitor_incidents_source_id",
        "remote_market_monitor_incidents",
        ["source_id"],
    )
    op.create_index(
        "ix_remote_market_monitor_incidents_status", "remote_market_monitor_incidents", ["status"]
    )
    op.create_index(
        "uq_remote_market_monitor_open_incident",
        "remote_market_monitor_incidents",
        ["source_id", "metric", "incident_type"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
        sqlite_where=sa.text("status = 'open'"),
    )
    op.create_table(
        "monitor_notification_outbox",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "incident_id",
            sa.String(length=36),
            sa.ForeignKey("remote_market_monitor_incidents.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "destination_id",
            sa.String(length=36),
            sa.ForeignKey("monitor_notification_destinations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False, unique=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("lease_owner", sa.String(length=120)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(length=500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_monitor_notification_outbox_status", "monitor_notification_outbox", ["status"]
    )
    op.create_index(
        "ix_monitor_notification_outbox_available_at",
        "monitor_notification_outbox",
        ["available_at"],
    )
    op.create_index(
        "ix_monitor_notification_outbox_lease_expires_at",
        "monitor_notification_outbox",
        ["lease_expires_at"],
    )
    op.create_table(
        "monitor_notification_attempts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "outbox_id",
            sa.String(length=36),
            sa.ForeignKey("monitor_notification_outbox.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("telegram_message_id", sa.String(length=120)),
        sa.Column("safe_error_message", sa.String(length=500)),
    )
    op.create_index(
        "ix_monitor_notification_attempts_outbox_id", "monitor_notification_attempts", ["outbox_id"]
    )


def downgrade() -> None:
    # Deliberately block a destructive downgrade once monitoring has recorded
    # operational history.  A forward migration keeps the audit trail intact.
    for table in (
        "monitor_notification_attempts",
        "monitor_notification_outbox",
        "remote_market_monitor_incidents",
        "remote_market_monitor_check_runs",
    ):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("远端盘口监控已存在审计记录；请使用前向修复，不能降级删除历史。")
    op.drop_table("monitor_notification_attempts")
    op.drop_table("monitor_notification_outbox")
    op.drop_table("remote_market_monitor_incidents")
    op.drop_table("remote_market_monitor_check_runs")
    op.drop_table("remote_market_monitor_states")
    op.drop_table("remote_market_monitor_target_destinations")
    op.drop_table("remote_market_monitor_metric_policies")
    op.drop_table("remote_market_monitor_target_settings")
    op.drop_table("monitor_notification_destinations")
    op.drop_table("monitor_notification_template_sets")
    op.drop_table("remote_market_monitor_settings")
