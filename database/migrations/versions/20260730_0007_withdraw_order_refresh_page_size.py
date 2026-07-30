"""add configurable withdrawal order refresh page size

Revision ID: 20260730_0007
Revises: 20260730_0006
Create Date: 2026-07-30

Persist the remote withdrawal-order traversal page size with the other
administrator-owned refresh settings.  Existing rows receive the remote
management page's current 100-record default.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0007"
down_revision: str | None = "20260730_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "system_retention_settings",
        sa.Column(
            "withdraw_order_refresh_page_size",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
    )


def downgrade() -> None:
    op.drop_column("system_retention_settings", "withdraw_order_refresh_page_size")
