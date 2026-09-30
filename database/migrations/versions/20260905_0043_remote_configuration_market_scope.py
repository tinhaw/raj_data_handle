"""Scope remote configuration identities to their unified market, not globally.

No remote requests or task retries are performed. Market 0 preserves the old
manual/offline namespace; a mapped remote task must use its actual market.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260905_0043"
down_revision = "20260905_0042"
branch_labels = None
depends_on = None

TABLE = "erp_compat_redemption_code_issues"
OLD_UNIQUE = "uq_erp_compat_redemption_issue_remote_configuration"
NEW_UNIQUE = "uq_erp_compat_issue_market_configuration"
MARKET_JOIN = """
    LEFT JOIN erp_compat_redemption_code_batches batch ON batch.id = issue.batch_id
    LEFT JOIN erp_compatibility_id_maps account_map
      ON account_map.entity_type = 'remote_account'
     AND account_map.legacy_id = batch.remote_connection_id
    LEFT JOIN remote_accounts account ON account.id = account_map.canonical_id
    LEFT JOIN erp_compatibility_id_maps market_map
      ON market_map.entity_type = 'source'
     AND market_map.canonical_id = account.source_id
"""


def upgrade() -> None:
    connection = op.get_bind()
    # Fail before changing schema if a remote identity has lost its provenance.
    # Deleted historical accounts must be reconciled explicitly, never guessed.
    unresolved = connection.execute(
        sa.text(f"""
            SELECT issue.id FROM {TABLE} issue {MARKET_JOIN}
            WHERE batch.remote_connection_id IS NOT NULL
              AND (issue.remote_configuration_id IS NOT NULL
                   OR issue.remote_reference_id IS NOT NULL)
              AND (market_map.legacy_id IS NULL OR market_map.legacy_id <= 0)
            LIMIT 1
        """)
    ).first()
    if unresolved:
        raise RuntimeError(
            f"Remote market cannot be resolved for issue {unresolved[0]}; "
            "reconcile account/source provenance before migration."
        )
    op.add_column(
        TABLE, sa.Column("remote_market_id", sa.BigInteger(), nullable=False, server_default="0")
    )
    # Do not infer receipts from legacy reference IDs or error messages.
    op.add_column(TABLE, sa.Column("remote_create_receipt_id", sa.String(255), nullable=True))
    op.execute(
        sa.text(f"""
        UPDATE {TABLE} SET remote_market_id = COALESCE((
            SELECT market_map.legacy_id FROM {TABLE} issue {MARKET_JOIN}
            WHERE issue.id = {TABLE}.id
        ), 0)
    """)
    )
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(OLD_UNIQUE, type_="unique")
        batch.create_unique_constraint(NEW_UNIQUE, ["remote_market_id", "remote_configuration_id"])
        batch.create_check_constraint(
            "ck_erp_compat_issue_market_nonnegative", "remote_market_id >= 0"
        )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(f"""
        SELECT 1 FROM {TABLE} WHERE remote_create_receipt_id IS NOT NULL
        AND remote_configuration_id IS NULL LIMIT 1
    """)
        )
        .first()
    ):
        raise RuntimeError("Unregistered remote receipts exist; reconcile before downgrade.")
    # Never discard cross-market records to satisfy the old global constraint.
    if (
        op.get_bind()
        .execute(
            sa.text(f"""
        SELECT remote_configuration_id FROM {TABLE}
        WHERE remote_configuration_id IS NOT NULL
        GROUP BY remote_configuration_id HAVING COUNT(*) > 1 LIMIT 1
    """)
        )
        .first()
    ):
        raise RuntimeError(
            "Cross-market configuration IDs exist; use a forward fix, not downgrade."
        )
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(NEW_UNIQUE, type_="unique")
        batch.drop_constraint("ck_erp_compat_issue_market_nonnegative", type_="check")
        batch.drop_column("remote_market_id")
        batch.drop_column("remote_create_receipt_id")
        batch.create_unique_constraint(OLD_UNIQUE, ["remote_configuration_id"])
