"""switch recharge refresh to daily Excel exports

Revision ID: 20260731_0011
Revises: 20260730_0010
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0011"
down_revision: str | None = "20260730_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "system_retention_settings",
        sa.Column(
            "charge_order_export_date_mode",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'previous_day'"),
        ),
    )
    op.add_column(
        "system_retention_settings",
        sa.Column("charge_order_export_specific_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "charge_order_snapshots",
        sa.Column("charge_product_id", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "charge_order_snapshots",
        sa.Column("product_name", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "charge_order_snapshots",
        sa.Column("pay_type", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("charge_order_snapshots", "pay_type")
    op.drop_column("charge_order_snapshots", "product_name")
    op.drop_column("charge_order_snapshots", "charge_product_id")
    op.drop_column("system_retention_settings", "charge_order_export_specific_date")
    op.drop_column("system_retention_settings", "charge_order_export_date_mode")
