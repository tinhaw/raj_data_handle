"""Add local ERP redemption task groups and market-subtask references.

This revision is intentionally not executed against production by this code
change. It has no remote business effect and requires a separately authorised
production schema window.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0030"
down_revision = "20260818_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erp_redemption_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("task_name", sa.String(length=200), nullable=False),
        sa.Column("claim_date_from", sa.Date(), nullable=False),
        sa.Column("claim_date_to", sa.Date(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False),
        sa.Column("export_group_key", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["erp_redemption_campaigns.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("export_group_key"),
    )
    op.create_index("ix_erp_redemption_tasks_campaign_id", "erp_redemption_tasks", ["campaign_id"])
    with op.batch_alter_table("erp_redemption_code_batches") as batch:
        batch.add_column(sa.Column("task_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("remote_account_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("source_id", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column("execution_order", sa.Integer(), nullable=False, server_default="1")
        )
        batch.create_foreign_key(
            "fk_erp_redemption_batch_task",
            "erp_redemption_tasks",
            ["task_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_erp_redemption_batch_remote_account",
            "remote_accounts",
            ["remote_account_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_erp_redemption_batch_source",
            "source_configs",
            ["source_id"],
            ["source_id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_erp_redemption_batch_task_id", ["task_id"])
        batch.create_index("ix_erp_redemption_batch_remote_account_id", ["remote_account_id"])
        batch.create_index("ix_erp_redemption_batch_source_id", ["source_id"])


def downgrade() -> None:
    with op.batch_alter_table("erp_redemption_code_batches") as batch:
        batch.drop_index("ix_erp_redemption_batch_source_id")
        batch.drop_index("ix_erp_redemption_batch_remote_account_id")
        batch.drop_index("ix_erp_redemption_batch_task_id")
        batch.drop_constraint("fk_erp_redemption_batch_source", type_="foreignkey")
        batch.drop_constraint("fk_erp_redemption_batch_remote_account", type_="foreignkey")
        batch.drop_constraint("fk_erp_redemption_batch_task", type_="foreignkey")
        batch.drop_column("execution_order")
        batch.drop_column("source_id")
        batch.drop_column("remote_account_id")
        batch.drop_column("task_id")
    op.drop_index("ix_erp_redemption_tasks_campaign_id", table_name="erp_redemption_tasks")
    op.drop_table("erp_redemption_tasks")
