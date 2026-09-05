"""Persist business-day task numbers for compatibility redemption work.

Task IDs are internal database identifiers.  Operators instead use a stable
``YYYYMMDDNNNN`` value, where the date is Asia/Shanghai and ``NNNN`` is the
one-based sequence of tasks created on that business day.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0045"
down_revision: str | None = "20260905_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "erp_compat_redemption_code_tasks"
UNIQUE = "uq_erp_redemption_task_daily_sequence"
CHECK = "ck_erp_redemption_task_daily_sequence"
INDEX = "idx_erp_redemption_task_date_sequence"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("task_date", sa.Date(), nullable=True))
    op.add_column(TABLE, sa.Column("daily_sequence", sa.Integer(), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                f"""
                UPDATE {TABLE} target
                SET task_date = (target.created_at AT TIME ZONE 'Asia/Shanghai')::date,
                    daily_sequence = (
                        SELECT COUNT(*)
                        FROM {TABLE} earlier
                        WHERE (earlier.created_at AT TIME ZONE 'Asia/Shanghai')::date
                                = (target.created_at AT TIME ZONE 'Asia/Shanghai')::date
                          AND (
                              earlier.created_at < target.created_at
                              OR (
                                  earlier.created_at = target.created_at
                                  AND earlier.id <= target.id
                              )
                          )
                    )
                """
            )
        )
    else:
        op.execute(
            sa.text(
                f"""
                WITH numbered AS (
                    SELECT id,
                           date(created_at) AS task_date,
                           ROW_NUMBER() OVER (
                               PARTITION BY date(created_at) ORDER BY created_at, id
                           ) AS daily_sequence
                    FROM {TABLE}
                )
                UPDATE {TABLE}
                SET task_date = (
                        SELECT task_date FROM numbered WHERE numbered.id = {TABLE}.id
                    ),
                    daily_sequence = (
                        SELECT daily_sequence FROM numbered WHERE numbered.id = {TABLE}.id
                    )
                """
            )
        )
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("task_date", nullable=False)
        batch.alter_column("daily_sequence", nullable=False)
        batch.create_unique_constraint(UNIQUE, ["task_date", "daily_sequence"])
        batch.create_check_constraint(CHECK, "daily_sequence BETWEEN 1 AND 9999")
    op.create_index(INDEX, TABLE, ["task_date", sa.text("daily_sequence DESC")])


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.drop_constraint(UNIQUE, type_="unique")
        batch.drop_column("daily_sequence")
        batch.drop_column("task_date")
