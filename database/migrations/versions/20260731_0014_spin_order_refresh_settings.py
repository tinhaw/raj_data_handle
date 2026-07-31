"""add configurable turntable-order refresh settings

Revision ID: 20260731_0014
Revises: 20260731_0013
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0014"
down_revision: str | None = "20260731_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("system_retention_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "spin_order_refresh_interval_hours",
                sa.Integer(),
                nullable=False,
                server_default="2",
            )
        )
        batch_op.add_column(
            sa.Column(
                "spin_order_refresh_page_size",
                sa.Integer(),
                nullable=False,
                server_default="100",
            )
        )
        batch_op.add_column(
            sa.Column(
                "spin_order_query_range",
                sa.String(length=48),
                nullable=False,
                server_default="previous_business_day_to_completed_slot",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("system_retention_settings") as batch_op:
        batch_op.drop_column("spin_order_query_range")
        batch_op.drop_column("spin_order_refresh_page_size")
        batch_op.drop_column("spin_order_refresh_interval_hours")
