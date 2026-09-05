"""Add local remote-redemption orchestration state and attempt history.

The schema stores parameter snapshots, safe identifiers and state transitions
only. It does not add a remote client, credential copy, session store or
automatic executor. Production execution requires a separate approved schema
window and application release.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0031"
down_revision = "20260818_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erp_redemption_remote_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("remote_account_id", sa.String(length=36), nullable=False),
        sa.Column(
            "redemption_type",
            sa.String(length=30),
            nullable=False,
            server_default="SEVEN_DAY_DEPOSIT",
        ),
        sa.Column(
            "workflow_status",
            sa.String(length=40),
            nullable=False,
            server_default="AWAITING_CREATE_AUTHORIZATION",
        ),
        sa.Column("publish_environment", sa.String(length=20), nullable=False),
        sa.Column("flow_times", sa.Integer(), nullable=False),
        sa.Column("creation_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("activity_recharge", sa.Numeric(24, 8), nullable=True),
        sa.Column("activity_recharge_count", sa.Integer(), nullable=True),
        sa.Column("activity_id", sa.Integer(), nullable=True),
        sa.Column("key_number", sa.Integer(), nullable=False),
        sa.Column("single_user_limit", sa.Integer(), nullable=False),
        sa.Column("single_key_limit", sa.Integer(), nullable=False),
        sa.Column("require_bind_bank_card", sa.Boolean(), nullable=False),
        sa.Column("require_bind_phone", sa.Boolean(), nullable=False),
        sa.Column("check_uuid", sa.Boolean(), nullable=False),
        sa.Column("uuid_reward_limit", sa.Integer(), nullable=False),
        sa.Column("check_login_ip", sa.Boolean(), nullable=False),
        sa.Column("login_ip_reward_limit", sa.Integer(), nullable=False),
        sa.Column("check_register_ip", sa.Boolean(), nullable=False),
        sa.Column("register_ip_reward_limit", sa.Integer(), nullable=False),
        sa.Column("publish_mode", sa.String(length=20), nullable=True),
        sa.Column("scheduled_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fallback_to_scheduled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("publish_note", sa.Text(), nullable=True),
        sa.Column("remote_publish_task_id", sa.String(length=255), nullable=True),
        sa.Column("schedule_cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reserved_operation", sa.String(length=20), nullable=True),
        sa.Column("reservation_id", sa.String(length=36), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "publish_environment in ('test', 'prod')",
            name="ck_erp_redemption_remote_plan_environment",
        ),
        sa.CheckConstraint(
            "redemption_type in ('SEVEN_DAY_DEPOSIT', 'PREVIOUS_DAY_DEPOSIT')",
            name="ck_erp_redemption_remote_plan_type",
        ),
        sa.CheckConstraint(
            "creation_interval_seconds between 1 and 60",
            name="ck_erp_redemption_remote_plan_interval",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["erp_redemption_code_batches.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["remote_account_id"],
            ["remote_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id"),
        sa.UniqueConstraint("reservation_id"),
    )
    op.create_index(
        "ix_erp_redemption_remote_plans_remote_account_id",
        "erp_redemption_remote_plans",
        ["remote_account_id"],
    )
    op.create_index(
        "ix_erp_redemption_remote_plans_workflow_status",
        "erp_redemption_remote_plans",
        ["workflow_status"],
    )
    op.create_index(
        "ix_erp_redemption_remote_plans_scheduled_publish_at",
        "erp_redemption_remote_plans",
        ["scheduled_publish_at"],
    )
    op.create_index(
        "ix_erp_redemption_remote_plan_status_schedule",
        "erp_redemption_remote_plans",
        ["workflow_status", "scheduled_publish_at"],
    )

    with op.batch_alter_table("erp_redemption_code_issues") as batch:
        batch.add_column(
            sa.Column(
                "remote_workflow_status",
                sa.String(length=30),
                nullable=False,
                server_default="NOT_STARTED",
            )
        )
        batch.add_column(sa.Column("remote_configuration_id", sa.String(length=255)))
        batch.add_column(sa.Column("remote_group_key", sa.String(length=255)))
        batch.add_column(
            sa.Column(
                "remote_label_ids_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(sa.Column("remote_description", sa.String(length=500)))
        batch.add_column(sa.Column("remote_error_code", sa.String(length=80)))
        batch.add_column(sa.Column("remote_error_message", sa.String(length=500)))
        batch.add_column(sa.Column("remote_created_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("remote_downloaded_at", sa.DateTime(timezone=True)))
        batch.create_unique_constraint(
            "uq_erp_redemption_issue_remote_configuration",
            ["remote_configuration_id"],
        )
        batch.create_index(
            "ix_erp_redemption_issue_remote_workflow_status",
            ["remote_workflow_status"],
        )

    op.create_table(
        "erp_redemption_remote_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("issue_id", sa.String(length=36), nullable=True),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("trigger_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("reservation_id", sa.String(length=36), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remote_request_id", sa.String(length=120), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "result_metadata_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["erp_redemption_remote_plans.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["erp_redemption_code_issues.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["app_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_id",
            "operation",
            "attempt_number",
            name="uq_erp_redemption_remote_execution_attempt",
        ),
        sa.UniqueConstraint("reservation_id"),
    )
    op.create_index(
        "ix_erp_redemption_remote_executions_plan_id",
        "erp_redemption_remote_executions",
        ["plan_id"],
    )
    op.create_index(
        "ix_erp_redemption_remote_executions_issue_id",
        "erp_redemption_remote_executions",
        ["issue_id"],
    )
    op.create_index(
        "ix_erp_redemption_remote_executions_status",
        "erp_redemption_remote_executions",
        ["status"],
    )
    op.create_index(
        "ix_erp_redemption_remote_execution_plan_requested",
        "erp_redemption_remote_executions",
        ["plan_id", "requested_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_erp_redemption_remote_execution_plan_requested",
        table_name="erp_redemption_remote_executions",
    )
    op.drop_index(
        "ix_erp_redemption_remote_executions_status",
        table_name="erp_redemption_remote_executions",
    )
    op.drop_index(
        "ix_erp_redemption_remote_executions_issue_id",
        table_name="erp_redemption_remote_executions",
    )
    op.drop_index(
        "ix_erp_redemption_remote_executions_plan_id",
        table_name="erp_redemption_remote_executions",
    )
    op.drop_table("erp_redemption_remote_executions")

    with op.batch_alter_table("erp_redemption_code_issues") as batch:
        batch.drop_index("ix_erp_redemption_issue_remote_workflow_status")
        batch.drop_constraint(
            "uq_erp_redemption_issue_remote_configuration",
            type_="unique",
        )
        batch.drop_column("remote_downloaded_at")
        batch.drop_column("remote_created_at")
        batch.drop_column("remote_error_message")
        batch.drop_column("remote_error_code")
        batch.drop_column("remote_description")
        batch.drop_column("remote_label_ids_json")
        batch.drop_column("remote_group_key")
        batch.drop_column("remote_configuration_id")
        batch.drop_column("remote_workflow_status")

    op.drop_index(
        "ix_erp_redemption_remote_plan_status_schedule",
        table_name="erp_redemption_remote_plans",
    )
    op.drop_index(
        "ix_erp_redemption_remote_plans_scheduled_publish_at",
        table_name="erp_redemption_remote_plans",
    )
    op.drop_index(
        "ix_erp_redemption_remote_plans_workflow_status",
        table_name="erp_redemption_remote_plans",
    )
    op.drop_index(
        "ix_erp_redemption_remote_plans_remote_account_id",
        table_name="erp_redemption_remote_plans",
    )
    op.drop_table("erp_redemption_remote_plans")
