"""repair payment channel binding primary-key sequence

Revision ID: 20260728_0003
Revises: 20260728_0002
Create Date: 2026-07-28

The initial migration seeded ``payment_channel_bindings`` with explicit IDs.
PostgreSQL does not advance an auto-increment sequence for those inserts, so a
later binding created during source connection testing can reuse an existing
primary key.  Align the sequence with the rows already present.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260728_0003"
down_revision: str | None = "20260728_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('payment_channel_bindings', 'id'),
            COALESCE((SELECT MAX(id) FROM payment_channel_bindings), 1),
            true
        )
        """
    )


def downgrade() -> None:
    # A sequence may safely remain ahead of the current maximum.  Moving it
    # backwards during downgrade risks reusing an ID allocated after upgrade.
    pass
