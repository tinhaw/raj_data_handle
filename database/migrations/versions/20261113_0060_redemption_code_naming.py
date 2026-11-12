"""Persist special-code spelling per batch without changing historical codes."""

import sqlalchemy as sa
from alembic import op

revision = "20261113_0060"
down_revision = "20261112_0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text("SET LOCAL statement_timeout = '60s'"))
    op.add_column(
        "erp_compat_redemption_code_batches",
        sa.Column(
            "special_code_naming",
            sa.String(20),
            sa.CheckConstraint(
                "special_code_naming IN ('ORIGINAL', 'TEN_K')",
                name="ck_erp_compat_batch_code_naming",
            ),
            nullable=False,
            server_default=sa.text("'ORIGINAL'"),
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Code naming snapshots must be retained; use a compatible forward fix")
