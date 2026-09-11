"""add configurable withdrawal order refresh interval

Revision ID: 20260730_0005
Revises: 20260728_0004
Create Date: 2026-07-30

The interval is persisted with the other administrator-owned system settings.
Existing deployments receive the safe one-hour default during migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0005"
down_revision: str | None = "20260728_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "system_retention_settings",
        sa.Column(
            "withdraw_order_refresh_interval_hours",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    op.drop_column("system_retention_settings", "withdraw_order_refresh_interval_hours")
