"""Allow independent redemption tiers to share a deposit threshold.

Only uniqueness is relaxed; existing tier IDs, rewards and audience snapshots
are preserved. No remote requests or code generation are performed.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261101_0052"
down_revision = "20260911_0051"
branch_labels = None
depends_on = None

CONSTRAINTS = (
    ("erp_redemption_campaign_tiers", "uq_erp_redemption_tier_deposit"),
    ("erp_compat_redemption_campaign_tiers", "uq_erp_compat_redemption_tier_deposit"),
)


def upgrade() -> None:
    for table, constraint in CONSTRAINTS:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(constraint, type_="unique")


def downgrade() -> None:
    # Check BOTH tables before restoring either constraint. Never discard tiers
    # or change their thresholds to make historical data fit the old schema.
    for table, _ in CONSTRAINTS:
        duplicate = (
            op.get_bind()
            .execute(
                sa.text(
                    f"SELECT 1 FROM {table} GROUP BY campaign_id, min_deposit_amount "
                    "HAVING COUNT(*) > 1 LIMIT 1"
                )
            )
            .first()
        )
        if duplicate:
            raise RuntimeError(
                "Shared redemption thresholds exist; use a forward fix instead of downgrade."
            )
    for table, constraint in CONSTRAINTS:
        with op.batch_alter_table(table) as batch:
            batch.create_unique_constraint(constraint, ["campaign_id", "min_deposit_amount"])
