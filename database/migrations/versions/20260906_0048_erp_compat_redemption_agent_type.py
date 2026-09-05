"""Allow the agent redemption-code type in ERP compatibility batches."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0048"
down_revision: str | None = "20260905_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "erp_compat_redemption_code_batches"
CHECK = "ck_erp_compat_redemption_batch_redemption_type"
EXPRESSION = "redemption_type in ('SEVEN_DAY_DEPOSIT', 'PREVIOUS_DAY_DEPOSIT', 'AGENT')"


def _redemption_type_checks() -> list[str]:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return [
            constraint["name"]
            for constraint in sa.inspect(bind).get_check_constraints(TABLE)
            if constraint.get("name")
            and "redemption_type" in (constraint.get("sqltext") or "").lower()
        ]
    return list(
        bind.execute(
            sa.text(
                """
                SELECT checks.constraint_name
                FROM information_schema.check_constraints checks
                JOIN information_schema.table_constraints constraints
                  ON constraints.constraint_catalog = checks.constraint_catalog
                 AND constraints.constraint_schema = checks.constraint_schema
                 AND constraints.constraint_name = checks.constraint_name
                WHERE constraints.table_name = :table_name
                  AND constraints.constraint_type = 'CHECK'
                  AND lower(checks.check_clause) LIKE '%redemption_type%'
                """
            ),
            {"table_name": TABLE},
        ).scalars()
    )


def upgrade() -> None:
    existing = _redemption_type_checks()
    if op.get_bind().dialect.name == "sqlite":
        # Batch recreation deliberately omits any unnamed legacy CHECK
        # constraints, then restores this replacement explicitly.
        with op.batch_alter_table(
            TABLE,
            recreate="always",
            table_args=(sa.CheckConstraint(EXPRESSION, name=CHECK),),
        ) as batch:
            for name in existing:
                batch.drop_constraint(name, type_="check")
        return
    with op.batch_alter_table(TABLE) as batch:
        for name in existing:
            batch.drop_constraint(name, type_="check")
        batch.create_check_constraint(CHECK, EXPRESSION)


def downgrade() -> None:
    if op.get_bind().execute(
        sa.text(f"SELECT 1 FROM {TABLE} WHERE redemption_type = 'AGENT' LIMIT 1")
    ).first():
        raise RuntimeError("Agent redemption batches exist; use a forward fix to preserve them.")
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(
            CHECK,
            "redemption_type in ('SEVEN_DAY_DEPOSIT', 'PREVIOUS_DAY_DEPOSIT')",
        )
