"""store Telegram monitor credentials encrypted at rest

Revision ID: 20260911_0050
Revises: 20260911_0049
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0050"
down_revision: str | None = "20260911_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("monitor_notification_destinations") as batch_op:
        batch_op.add_column(sa.Column("encrypted_credentials", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("credential_version", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.alter_column(
            "bot_token_secret_ref",
            existing_type=sa.String(length=200),
            nullable=True,
        )
        batch_op.alter_column(
            "chat_id_secret_ref",
            existing_type=sa.String(length=200),
            nullable=True,
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE monitor_notification_destinations "
            "SET bot_token_secret_ref = COALESCE(bot_token_secret_ref, "
            "'env://TELEGRAM_BOT_TOKEN_RESTORE_REQUIRED'), "
            "chat_id_secret_ref = COALESCE(chat_id_secret_ref, "
            "'env://TELEGRAM_CHAT_ID_RESTORE_REQUIRED')"
        )
    )
    with op.batch_alter_table("monitor_notification_destinations") as batch_op:
        batch_op.alter_column(
            "chat_id_secret_ref",
            existing_type=sa.String(length=200),
            nullable=False,
        )
        batch_op.alter_column(
            "bot_token_secret_ref",
            existing_type=sa.String(length=200),
            nullable=False,
        )
        batch_op.drop_column("credential_version")
        batch_op.drop_column("encrypted_credentials")
