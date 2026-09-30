"""Separate daily and seven-day reward presets without changing existing tiers."""

import sqlalchemy as sa
from alembic import op

revision = "20260905_0042"
down_revision = "20260905_0041"
branch_labels = None
depends_on = None

TABLE = "remote_account_reward_tier_presets"


def upgrade() -> None:
    pk = sa.inspect(op.get_bind()).get_pk_constraint(TABLE)["name"] or f"pk_{TABLE}"
    with op.batch_alter_table(TABLE, naming_convention={"pk": "pk_%(table_name)s"}) as batch:
        batch.add_column(
            sa.Column(
                "redemption_type", sa.String(32), nullable=False, server_default="SEVEN_DAY_DEPOSIT"
            )
        )
        batch.drop_constraint(pk, type_="primary")
        batch.create_primary_key(f"pk_{TABLE}_type", ["account_id", "redemption_type"])


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(f"SELECT 1 FROM {TABLE} WHERE redemption_type <> 'SEVEN_DAY_DEPOSIT' LIMIT 1")
        )
        .first()
    ):
        raise RuntimeError("Daily presets exist; use a forward fix to preserve them.")
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(f"pk_{TABLE}_type", type_="primary")
        batch.drop_column("redemption_type")
        batch.create_primary_key(f"pk_{TABLE}", ["account_id"])
