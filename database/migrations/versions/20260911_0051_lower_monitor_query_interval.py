"""allow remote-market query intervals as low as ten seconds

Revision ID: 20260911_0051
Revises: 20260911_0050
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0051"
down_revision: str | None = "20260911_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "remote_market_monitor_target_settings"
CONSTRAINT = "ck_monitor_target_interval"


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.drop_constraint(CONSTRAINT, type_="check")
        batch_op.create_check_constraint(
            CONSTRAINT,
            "check_interval_seconds between 10 and 3600",
        )


def downgrade() -> None:
    incompatible = op.get_bind().execute(
        sa.text(
            f"SELECT source_id FROM {TABLE} "
            "WHERE check_interval_seconds < 30 LIMIT 1"
        )
    ).first()
    if incompatible:
        raise RuntimeError(
            "Remote-market query intervals below 30 seconds exist; "
            "raise them before downgrading."
        )
    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.drop_constraint(CONSTRAINT, type_="check")
        batch_op.create_check_constraint(
            CONSTRAINT,
            "check_interval_seconds between 30 and 3600",
        )
