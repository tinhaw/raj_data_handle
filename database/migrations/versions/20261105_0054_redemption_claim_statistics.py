"""Local claim snapshots, leases and seven-choice scheduling; no remote operations.

Revision ID: 20261105_0054
Revises: 20261101_0053
"""

import sqlalchemy as sa
from alembic import op

revision = "20261105_0054"
down_revision = "20261101_0053"
branch_labels = None
depends_on = None


def timestamp(name):
    return sa.Column(name, sa.DateTime(timezone=True))


def upgrade():
    op.create_table(
        "erp_redemption_claim_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("issue_id", sa.BigInteger(), nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("account_projection_id", sa.BigInteger()),
        sa.Column("configuration_id", sa.String(255)),
        sa.Column("group_key", sa.String(255)),
        sa.Column("column_key", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        timestamp("last_succeeded_at"),
        sa.Column("last_error", sa.String(500)),
        sa.UniqueConstraint("source_id", "group_key", name="uq_claim_group_source_key"),
    )
    op.create_index("ix_claim_group_task", "erp_redemption_claim_groups", ["task_id", "issue_id"])
    op.create_table(
        "erp_redemption_claim_records",
        sa.Column(
            "group_id",
            sa.String(36),
            sa.ForeignKey("erp_redemption_claim_groups.id"),
            primary_key=True,
        ),
        sa.Column("remote_id", sa.String(100), primary_key=True),
        sa.Column("code", sa.String(255), nullable=False),
        sa.Column("uid", sa.String(100), nullable=False),
        sa.Column("receive_time", sa.String(40), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("gift_type", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_claim_record_day_code",
        "erp_redemption_claim_records",
        ["group_id", "claim_date", "code"],
    )
    op.create_table(
        "erp_redemption_claim_daily",
        sa.Column(
            "group_id",
            sa.String(36),
            sa.ForeignKey("erp_redemption_claim_groups.id"),
            primary_key=True,
        ),
        sa.Column("code", sa.String(255), primary_key=True),
        sa.Column("claim_date", sa.Date(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "erp_redemption_claim_schedules",
        sa.Column("task_id", sa.BigInteger(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        timestamp("next_run_at"),
        timestamp("last_finished_at"),
        timestamp("last_succeeded_at"),
        sa.Column("active_run_id", sa.String(36)),
        sa.CheckConstraint(
            "interval_minutes in (30,60,120,180,360,720,1440)", name="ck_claim_interval"
        ),
    )
    op.create_index(
        "ix_erp_redemption_claim_schedules_next_run_at",
        "erp_redemption_claim_schedules",
        ["next_run_at"],
    )
    op.create_table(
        "erp_redemption_claim_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        timestamp("started_at"),
        timestamp("finished_at"),
        sa.Column("lease_token", sa.String(36)),
        timestamp("lease_expires_at"),
        sa.Column("progress", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_claim_run_task_created", "erp_redemption_claim_runs", ["task_id", "created_at"]
    )
    op.create_table(
        "erp_redemption_claim_leases",
        sa.Column("source_id", sa.String(64), primary_key=True),
        sa.Column("token", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    tables = [
        "erp_redemption_claim_daily",
        "erp_redemption_claim_records",
        "erp_redemption_claim_groups",
        "erp_redemption_claim_runs",
        "erp_redemption_claim_schedules",
        "erp_redemption_claim_leases",
    ]
    for table in tables[:-1]:
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Claim history or settings exist; retain schema and fix forward.")
    for table in tables:
        op.drop_table(table)
