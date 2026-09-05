"""Persist the administrator username that created each redemption task."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0046"
down_revision: str | None = "20260905_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASK_TABLE = "erp_compat_redemption_code_tasks"
USER_TABLE = "app_users"


def upgrade() -> None:
    op.add_column(TASK_TABLE, sa.Column("created_by_username", sa.String(length=80), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                f"""
                UPDATE {TASK_TABLE} task
                SET created_by_username = app_user.username
                FROM {USER_TABLE} app_user
                WHERE task.created_by = app_user.id
                  AND task.created_by_username IS NULL
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                UPDATE {TASK_TABLE}
                SET created_by_username = '用户 #' || created_by::text
                WHERE created_by_username IS NULL
                  AND created_by IS NOT NULL
                """
            )
        )
    else:
        op.execute(
            sa.text(
                f"""
                UPDATE {TASK_TABLE}
                SET created_by_username = (
                    SELECT username FROM {USER_TABLE} WHERE id = {TASK_TABLE}.created_by
                )
                WHERE created_by_username IS NULL
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                UPDATE {TASK_TABLE}
                SET created_by_username = '用户 #' || CAST(created_by AS TEXT)
                WHERE created_by_username IS NULL
                  AND created_by IS NOT NULL
                """
            )
        )


def downgrade() -> None:
    op.drop_column(TASK_TABLE, "created_by_username")
