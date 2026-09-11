"""Shared remote sessions and opt-in periodic login. No remote operations."""

import sqlalchemy as sa
from alembic import op

revision = "20260905_0044"
down_revision = "20260905_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("session_ciphertext", sa.Text()),
        sa.Column("session_identity", sa.String(64)),
        sa.Column("session_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "session_expiry_estimated", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("last_logged_in_at", sa.DateTime(timezone=True)),
        sa.Column("last_login_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("login_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("login_retry_after", sa.DateTime(timezone=True)),
        sa.Column("session_last_error", sa.String(500)),
        sa.Column("auto_relogin", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("relogin_interval_minutes", sa.Integer()),
        sa.Column("next_relogin_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("remote_accounts", column)
    with op.batch_alter_table("remote_accounts") as batch:
        batch.create_check_constraint(
            "ck_remote_account_relogin_interval",
            "relogin_interval_minutes IS NULL OR relogin_interval_minutes BETWEEN 15 AND 10080",
        )


def downgrade() -> None:
    with op.batch_alter_table("remote_accounts") as batch:
        batch.drop_constraint("ck_remote_account_relogin_interval", type_="check")
        for name in (
            "next_relogin_at",
            "relogin_interval_minutes",
            "auto_relogin",
            "session_last_error",
            "login_retry_after",
            "login_failure_count",
            "last_login_attempt_at",
            "last_logged_in_at",
            "session_expiry_estimated",
            "session_expires_at",
            "session_identity",
            "session_ciphertext",
        ):
            batch.drop_column(name)
