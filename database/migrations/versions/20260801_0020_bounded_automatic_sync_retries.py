"""configure bounded automatic synchronization retries

Revision ID: 20260801_0020
Revises: 20260801_0019
Create Date: 2026-08-01

The retry limit counts retries after the first automatic attempt.  Per-source
failure counters make the limit durable across worker restarts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0020"
down_revision: str | None = "20260801_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "system_retention_settings",
        sa.Column(
            "automatic_sync_retry_limit",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
    )
    op.add_column(
        "system_retention_settings",
        sa.Column(
            "automatic_sync_retry_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5"),
        ),
    )
    for table_name in (
        "charge_order_refresh_states",
        "withdraw_order_refresh_states",
        "spin_order_refresh_states",
    ):
        op.add_column(
            table_name,
            sa.Column(
                "automatic_failure_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    for table_name in (
        "spin_order_refresh_states",
        "withdraw_order_refresh_states",
        "charge_order_refresh_states",
    ):
        op.drop_column(table_name, "automatic_failure_count")
    op.drop_column("system_retention_settings", "automatic_sync_retry_interval_minutes")
    op.drop_column("system_retention_settings", "automatic_sync_retry_limit")
