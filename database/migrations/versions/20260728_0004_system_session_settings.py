"""add configurable login session settings

Revision ID: 20260728_0004
Revises: 20260728_0003
Create Date: 2026-07-28

This creates an independent settings record for administrator-controlled
session duration.  It is deliberately separate from retention policy so the
authentication path can fall back safely while the application and schema are
rolled out in separate steps.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0004"
down_revision: str | None = "20260728_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    now = datetime.now(UTC)
    op.create_table(
        "system_session_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_ttl_days", sa.Integer(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        sa.table(
            "system_session_settings",
            sa.column("id", sa.Integer()),
            sa.column("session_ttl_days", sa.Integer()),
            sa.column("config_version", sa.Integer()),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": 1,
                "session_ttl_days": 30,
                "config_version": 1,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("system_session_settings")
