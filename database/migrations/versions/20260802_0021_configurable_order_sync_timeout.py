"""configure remote order synchronization timeout

Revision ID: 20260802_0021
Revises: 20260801_0020
Create Date: 2026-08-02

The global setting governs read and Excel-download timeouts for charge,
withdrawal, and turntable order synchronization. Connection establishment
remains separately bounded by the client.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0021"
down_revision: str | None = "20260801_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "system_retention_settings",
        sa.Column(
            "remote_order_sync_timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("180"),
        ),
    )


def downgrade() -> None:
    op.drop_column("system_retention_settings", "remote_order_sync_timeout_seconds")
