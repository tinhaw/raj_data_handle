"""Store all codes per compatibility redemption group.

Revision ID: 20260905_0041
Revises: 20260905_0040
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0041"
down_revision: str | None = "20260905_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "erp_compat_redemption_issue_codes",
        sa.Column("issue_id", sa.BigInteger(), nullable=False),
        sa.Column("code_index", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("issue_id", "code_index"),
        sa.ForeignKeyConstraint(
            ["issue_id"], ["erp_compat_redemption_code_issues.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("code", name="uq_erp_compat_redemption_issue_codes_code"),
    )
    op.execute(
        sa.text(
            "INSERT INTO erp_compat_redemption_issue_codes (issue_id, code_index, code) "
            "SELECT id, 0, redemption_code FROM erp_compat_redemption_code_issues "
            "WHERE redemption_code IS NOT NULL"
        )
    )
    with op.batch_alter_table("erp_compat_redemption_code_batches") as batch_op:
        batch_op.create_check_constraint(
            "ck_erp_compat_redemption_key_number",
            "remote_key_number IS NULL OR remote_key_number BETWEEN 1 AND 1000",
        )


def downgrade() -> None:
    # Never silently discard extra codes or allow old single-code clients to see multi-code batches.
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM erp_compat_redemption_code_batches WHERE remote_key_number > 1 "
                "UNION ALL SELECT 1 FROM erp_compat_redemption_issue_codes "
                "WHERE code_index > 0 LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("Multi-code batches exist; keep revision 0041 and use a forward fix.")
    with op.batch_alter_table("erp_compat_redemption_code_batches") as batch_op:
        batch_op.drop_constraint("ck_erp_compat_redemption_key_number", type_="check")
    op.drop_table("erp_compat_redemption_issue_codes")
