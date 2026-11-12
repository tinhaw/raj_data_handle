"""Scope remote claim IDs by user without rewriting existing claim facts.

Revision ID: 20261106_0055
Revises: 20261105_0054
"""

import sqlalchemy as sa
from alembic import op

revision = "20261106_0055"
down_revision = "20261105_0054"
branch_labels = None
depends_on = None

TABLE = "erp_redemption_claim_records"
NEW_KEY = "pk_claim_record_identity"
OLD_KEY = f"{TABLE}_pkey"


def _replace_key(expected, columns, name):
    connection = op.get_bind()
    primary = sa.inspect(connection).get_pk_constraint(TABLE)
    if primary["constrained_columns"] != expected:
        raise RuntimeError("Unexpected claim record primary key; inspect before migrating.")
    if connection.dialect.name == "postgresql":
        # A busy reader/writer must cause a bounded failure, not an unbounded
        # production lock queue. Both DDL operations share Alembic's transaction.
        connection.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(sa.text("SET LOCAL statement_timeout = '30s'"))
        op.drop_constraint(primary["name"], TABLE, type_="primary")
        op.create_primary_key(name, TABLE, columns)
    else:
        convention = {"pk": "pk_%(table_name)s"}
        with op.batch_alter_table(TABLE, naming_convention=convention) as batch:
            batch.drop_constraint(primary["name"] or f"pk_{TABLE}", type_="primary")
            batch.create_primary_key(name, columns)


def upgrade():
    _replace_key(["group_id", "remote_id"], ["group_id", "remote_id", "uid"], NEW_KEY)


def downgrade():
    # Once different users with the same ID have been stored, restoring the old
    # key would destroy real claims. Restore a verified compatible snapshot or
    # fix forward; never delete duplicate rows to force a downgrade.
    duplicate = op.get_bind().execute(
        sa.text(
            f"SELECT 1 FROM {TABLE} GROUP BY group_id, remote_id "
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate:
        raise RuntimeError(
            "Claim IDs repeat across users; retain schema and facts, restore a verified "
            "compatible snapshot or fix forward."
        )
    _replace_key(["group_id", "remote_id", "uid"], ["group_id", "remote_id"], OLD_KEY)
