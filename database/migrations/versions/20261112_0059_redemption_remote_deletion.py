"""Retain intentional remote deletion facts without removing identity or inventory."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_0059"
down_revision = "20261112_0058"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '60s'")
    op.add_column(
        "erp_compat_redemption_code_issues", sa.Column("remote_deletion_state", sa.String(20))
    )
    op.create_table(
        "erp_compat_redemption_deletions",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column(
            "owner_issue_id",
            sa.BigInteger(),
            sa.ForeignKey("erp_compat_redemption_code_issues.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "requested_issue_id",
            sa.BigInteger(),
            sa.ForeignKey("erp_compat_redemption_code_issues.id"),
            nullable=False,
        ),
        sa.Column("configuration_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("remote_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("remote_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "status IN ('CHECKED','DELETING','UNKNOWN','DELETED')",
            name="ck_redemption_deletion_status",
        ),
    )
    op.create_table(
        "erp_compat_redemption_task_deletions",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("erp_compat_redemption_code_tasks.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("scope_json", sa.Text(), nullable=False),
        sa.Column("items_json", sa.Text(), nullable=False),
        sa.Column("busy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "status IN ('CHECKING','CHECKED','RUNNING','PAUSED','FINISHED','STOPPED')",
            name="ck_redemption_task_deletion_status",
        ),
    )
    op.create_index(
        "ix_redemption_task_deletion_task",
        "erp_compat_redemption_task_deletions",
        ["task_id", "id"],
    )


def downgrade():
    raise RuntimeError(
        "Intentional deletion records and stock must be retained; use a compatible forward fix"
    )
