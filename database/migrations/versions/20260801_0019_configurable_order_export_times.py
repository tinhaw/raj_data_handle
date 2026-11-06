"""make daily charge and withdrawal export times configurable

Revision ID: 20260801_0019
Revises: 20260801_0018
Create Date: 2026-08-01

The defaults preserve the previous fixed worker behavior.  Both values are
global wall-clock times and are evaluated in each source's business timezone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0019"
down_revision: str | None = "20260801_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "system_retention_settings",
        sa.Column(
            "charge_order_export_time",
            sa.Time(),
            nullable=False,
            server_default=sa.text("'00:00:01'"),
        ),
    )
    op.add_column(
        "system_retention_settings",
        sa.Column(
            "withdraw_order_export_time",
            sa.Time(),
            nullable=False,
            server_default=sa.text("'00:05:01'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("system_retention_settings", "withdraw_order_export_time")
    op.drop_column("system_retention_settings", "charge_order_export_time")
