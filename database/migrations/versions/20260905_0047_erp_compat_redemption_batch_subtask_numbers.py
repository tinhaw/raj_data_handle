"""Persist operator-facing three-digit child-task numbers for redemption batches."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0047"
down_revision: str | None = "20260905_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "erp_compat_redemption_code_batches"
TASK_TABLE = "erp_compat_redemption_code_tasks"
UNIQUE = "uq_erp_redemption_batch_subtask_daily_sequence"
CHECK = "ck_erp_redemption_batch_subtask_daily_sequence"
INDEX = "idx_erp_redemption_batch_subtask_date_sequence"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("subtask_date", sa.Date(), nullable=True))
    op.add_column(TABLE, sa.Column("subtask_daily_sequence", sa.Integer(), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                f"""
                UPDATE {TABLE} target
                SET subtask_date = COALESCE(
                    (SELECT task.task_date FROM {TASK_TABLE} task WHERE task.id = target.task_id),
                    (target.created_at AT TIME ZONE 'Asia/Shanghai')::date
                )
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                WITH numbered AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY subtask_date ORDER BY created_at, id
                           ) AS daily_sequence
                    FROM {TABLE}
                )
                UPDATE {TABLE} target
                SET subtask_daily_sequence = numbered.daily_sequence
                FROM numbered
                WHERE numbered.id = target.id
                """
            )
        )
    else:
        op.execute(
            sa.text(
                f"""
                UPDATE {TABLE}
                SET subtask_date = COALESCE(
                    (SELECT task_date FROM {TASK_TABLE} WHERE id = {TABLE}.task_id),
                    date(created_at)
                )
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                WITH numbered AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY subtask_date ORDER BY created_at, id
                           ) AS daily_sequence
                    FROM {TABLE}
                )
                UPDATE {TABLE}
                SET subtask_daily_sequence = (
                    SELECT daily_sequence FROM numbered WHERE numbered.id = {TABLE}.id
                )
                """
            )
        )
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("subtask_date", nullable=False)
        batch.alter_column("subtask_daily_sequence", nullable=False)
        batch.create_unique_constraint(UNIQUE, ["subtask_date", "subtask_daily_sequence"])
        batch.create_check_constraint(CHECK, "subtask_daily_sequence BETWEEN 1 AND 999")
    op.create_index(INDEX, TABLE, ["subtask_date", sa.text("subtask_daily_sequence DESC")])


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.drop_constraint(UNIQUE, type_="unique")
        batch.drop_column("subtask_daily_sequence")
        batch.drop_column("subtask_date")
