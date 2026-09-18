"""add local ERP redemption campaign, batch and code records

Revision ID: 20260817_0026
Revises: 20260817_0025
Create Date: 2026-08-17

This migration definition is code-only and has not been executed.
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0026"
down_revision: str | None = "20260817_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "erp_redemption_campaigns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("lookback_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "erp_redemption_campaign_tiers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("min_deposit_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("bonus_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("bonus_max_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["campaign_id"], ["erp_redemption_campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "min_deposit_amount", name="uq_erp_redemption_tier_deposit"),
    )
    op.create_index(
        "ix_erp_redemption_campaign_tiers_campaign_id",
        "erp_redemption_campaign_tiers",
        ["campaign_id"],
    )
    op.create_table(
        "erp_redemption_code_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("claim_date_from", sa.Date(), nullable=False),
        sa.Column("claim_date_to", sa.Date(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False),
        sa.Column("expected_code_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PLANNED"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Integer(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["erp_redemption_campaigns.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["published_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_erp_redemption_code_batches_campaign_id", "erp_redemption_code_batches", ["campaign_id"])
    op.create_table(
        "erp_redemption_code_issues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("campaign_tier_id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("claim_date", sa.Date(), nullable=False),
        sa.Column("deposit_window_start", sa.Date(), nullable=False),
        sa.Column("deposit_window_end", sa.Date(), nullable=False),
        sa.Column("tier_name", sa.String(length=120), nullable=True),
        sa.Column("min_deposit_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("bonus_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("bonus_max_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("redemption_code", sa.String(length=255), nullable=True),
        sa.Column("local_reference", sa.String(length=255), nullable=True),
        sa.Column("workflow_status", sa.String(length=30), nullable=False, server_default="PENDING_LOCAL_CODE"),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["erp_redemption_campaigns.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["campaign_tier_id"], ["erp_redemption_campaign_tiers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["batch_id"], ["erp_redemption_code_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("redemption_code"),
        sa.UniqueConstraint("batch_id", "claim_date", "campaign_tier_id", name="uq_erp_redemption_issue"),
    )
    op.create_index("ix_erp_redemption_code_issues_campaign_id", "erp_redemption_code_issues", ["campaign_id"])
    op.create_index("ix_erp_redemption_code_issues_campaign_tier_id", "erp_redemption_code_issues", ["campaign_tier_id"])
    op.create_index("ix_erp_redemption_code_issues_batch_id", "erp_redemption_code_issues", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_erp_redemption_code_issues_batch_id", table_name="erp_redemption_code_issues")
    op.drop_index("ix_erp_redemption_code_issues_campaign_tier_id", table_name="erp_redemption_code_issues")
    op.drop_index("ix_erp_redemption_code_issues_campaign_id", table_name="erp_redemption_code_issues")
    op.drop_table("erp_redemption_code_issues")
    op.drop_index("ix_erp_redemption_code_batches_campaign_id", table_name="erp_redemption_code_batches")
    op.drop_table("erp_redemption_code_batches")
    op.drop_index("ix_erp_redemption_campaign_tiers_campaign_id", table_name="erp_redemption_campaign_tiers")
    op.drop_table("erp_redemption_campaign_tiers")
    op.drop_table("erp_redemption_campaigns")
