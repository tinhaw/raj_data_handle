"""separate ERP compatibility claim dates from remote valid time

Revision ID: 20260905_0040
Revises: 20260829_0039
Create Date: 2026-09-05

The offsets are immutable batch snapshots.  Existing and default behavior is
preserved: offset 0 through 0 means each remote configuration is valid only on
its own claim date.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0040"
down_revision: str | None = "20260829_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table(
        "erp_compat_redemption_code_batches"
    ) as batch_op:
        batch_op.add_column(sa.Column(
            "valid_from_day_offset",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ))
        batch_op.add_column(sa.Column(
            "valid_to_day_offset",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ))
        batch_op.create_check_constraint(
            "ck_erp_compat_redemption_valid_time_offsets",
            "valid_from_day_offset between 0 and 365 and "
            "valid_to_day_offset between valid_from_day_offset and 365",
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "erp_compat_redemption_code_batches"
    ) as batch_op:
        batch_op.drop_constraint(
            "ck_erp_compat_redemption_valid_time_offsets",
            type_="check",
        )
        batch_op.drop_column("valid_to_day_offset")
        batch_op.drop_column("valid_from_day_offset")
