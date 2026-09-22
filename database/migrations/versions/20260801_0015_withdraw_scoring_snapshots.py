"""add supplemental score-review snapshots for cached withdrawal orders

Revision ID: 20260801_0015
Revises: 20260731_0014
Create Date: 2026-08-01

Score-review rows are deliberately constrained to an existing withdrawal
snapshot.  A scoring workbook can therefore enrich a cached withdrawal order,
but cannot create an order that is absent from the authoritative withdrawal
Excel export.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0015"
down_revision: str | None = "20260731_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "withdraw_scoring_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("withdraw_order_id", sa.String(length=120), nullable=False),
        sa.Column("global_hard_condition", sa.String(length=120), nullable=True),
        sa.Column("scenario_review", sa.String(length=120), nullable=True),
        sa.Column("score_review", sa.String(length=80), nullable=True),
        sa.Column("decision_stage", sa.String(length=120), nullable=True),
        sa.Column("final_review_suggestion", sa.String(length=120), nullable=True),
        sa.Column("operation_result", sa.String(length=120), nullable=True),
        sa.Column("review_summary", sa.Text(), nullable=True),
        sa.Column("current_status", sa.String(length=120), nullable=True),
        sa.Column("review_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_duration", sa.String(length=80), nullable=True),
        sa.Column("queue_duration", sa.String(length=80), nullable=True),
        sa.Column("entered_queue_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exited_queue_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id", "withdraw_order_id"],
            [
                "withdraw_order_snapshots.source_id",
                "withdraw_order_snapshots.remote_order_id",
            ],
            name="fk_withdraw_scoring_snapshot_withdraw_order",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "withdraw_order_id",
            name="uq_withdraw_scoring_snapshot_source_withdraw_order_id",
        ),
    )
    op.create_index(
        "ix_withdraw_scoring_snapshots_synced_at",
        "withdraw_scoring_snapshots",
        ["synced_at"],
    )
    op.create_index(
        "ix_withdraw_scoring_snapshot_source_review_completed_at",
        "withdraw_scoring_snapshots",
        ["source_id", "review_completed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_withdraw_scoring_snapshot_source_review_completed_at",
        table_name="withdraw_scoring_snapshots",
    )
    op.drop_index(
        "ix_withdraw_scoring_snapshots_synced_at",
        table_name="withdraw_scoring_snapshots",
    )
    op.drop_table("withdraw_scoring_snapshots")
