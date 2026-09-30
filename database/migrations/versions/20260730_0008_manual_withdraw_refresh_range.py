"""store a one-off withdrawal refresh range

Revision ID: 20260730_0008
Revises: 20260730_0007
Create Date: 2026-07-30

Persist the operator-selected preset on the source refresh state so a queued
manual run keeps its requested window until the background worker claims it.
The nullable column leaves existing automatic refreshes unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0008"
down_revision: str | None = "20260730_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "withdraw_order_refresh_states",
        sa.Column("manual_query_range", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("withdraw_order_refresh_states", "manual_query_range")
