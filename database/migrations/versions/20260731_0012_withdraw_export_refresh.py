"""switch withdrawal refresh to daily Excel exports

Revision ID: 20260731_0012
Revises: 20260731_0011
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0012"
down_revision: str | None = "20260731_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "system_retention_settings",
        sa.Column(
            "withdraw_order_export_date_mode",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'previous_day'"),
        ),
    )
    op.add_column(
        "system_retention_settings",
        sa.Column("withdraw_order_export_specific_date", sa.Date(), nullable=True),
    )

    op.add_column(
        "withdraw_order_snapshots",
        sa.Column("order_num", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "withdraw_order_snapshots",
        sa.Column("out_trade_no", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "withdraw_order_snapshots",
        sa.Column("pay_channel_name", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "withdraw_order_snapshots",
        sa.Column("pay_channel", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "withdraw_order_snapshots",
        sa.Column("fee", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "withdraw_order_snapshots",
        sa.Column("status_label", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "withdraw_order_snapshots",
        sa.Column("is_first", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "withdraw_order_snapshots",
        sa.Column("channel", sa.String(length=120), nullable=True),
    )
    op.create_index(
        "ix_withdraw_order_snapshot_source_pay_channel",
        "withdraw_order_snapshots",
        ["source_id", "pay_channel"],
    )
    op.create_index(
        "ix_withdraw_order_snapshot_source_order_num",
        "withdraw_order_snapshots",
        ["source_id", "order_num"],
    )
    op.create_index(
        "ix_withdraw_order_snapshot_source_out_trade_no",
        "withdraw_order_snapshots",
        ["source_id", "out_trade_no"],
    )

    op.add_column(
        "withdraw_order_refresh_states",
        sa.Column(
            "last_export_row_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "withdraw_order_refresh_states",
        sa.Column(
            "last_imported_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "withdraw_order_refresh_states",
        sa.Column(
            "last_duplicate_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("withdraw_order_refresh_states", "last_duplicate_count")
    op.drop_column("withdraw_order_refresh_states", "last_imported_count")
    op.drop_column("withdraw_order_refresh_states", "last_export_row_count")

    op.drop_index(
        "ix_withdraw_order_snapshot_source_out_trade_no",
        table_name="withdraw_order_snapshots",
    )
    op.drop_index(
        "ix_withdraw_order_snapshot_source_order_num",
        table_name="withdraw_order_snapshots",
    )
    op.drop_index(
        "ix_withdraw_order_snapshot_source_pay_channel",
        table_name="withdraw_order_snapshots",
    )
    op.drop_column("withdraw_order_snapshots", "channel")
    op.drop_column("withdraw_order_snapshots", "is_first")
    op.drop_column("withdraw_order_snapshots", "status_label")
    op.drop_column("withdraw_order_snapshots", "fee")
    op.drop_column("withdraw_order_snapshots", "pay_channel")
    op.drop_column("withdraw_order_snapshots", "pay_channel_name")
    op.drop_column("withdraw_order_snapshots", "out_trade_no")
    op.drop_column("withdraw_order_snapshots", "order_num")

    op.drop_column("system_retention_settings", "withdraw_order_export_specific_date")
    op.drop_column("system_retention_settings", "withdraw_order_export_date_mode")
