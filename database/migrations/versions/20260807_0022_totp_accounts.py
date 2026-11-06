"""add standalone encrypted TOTP accounts

Revision ID: 20260807_0022
Revises: 20260802_0021
Create Date: 2026-08-07

TOTP accounts are intentionally independent from Raj remote source credentials.
Only encrypted secrets are persisted; generated codes remain ephemeral.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0022"
down_revision: str | None = "20260802_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "totp_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("account_name", sa.String(length=200), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("secret_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("secret_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_users.id"],
            name="fk_totp_accounts_created_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_users.id"],
            name="fk_totp_accounts_updated_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_totp_accounts_display_order", "totp_accounts", ["display_order"])
    op.create_index("ix_totp_accounts_enabled", "totp_accounts", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_totp_accounts_enabled", table_name="totp_accounts")
    op.drop_index("ix_totp_accounts_display_order", table_name="totp_accounts")
    op.drop_table("totp_accounts")
