"""make unified remote accounts complete and select one default per market

Revision ID: 20260828_0038
Revises: 20260827_0037
Create Date: 2026-08-28

The migration only changes local account metadata. It does not decrypt or copy
credentials and does not execute any remote operation.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0038"
down_revision: str | None = "20260827_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CAPABILITIES = (
    "ANALYSIS_READ",
    "ERP_REMOTE_CHECK",
    "ERP_TAG_READ",
    "ERP_TAG_SYNC",
    "ERP_REDEMPTION_CREATE",
    "ERP_REDEMPTION_PUBLISH",
    "ERP_REDEMPTION_CANCEL",
    "ERP_REDEMPTION_DOWNLOAD",
)


def upgrade() -> None:
    op.add_column(
        "remote_accounts",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    connection = op.get_bind()
    # Prefer the legacy analysis account so rollout is behavior preserving.
    # Markets without one use their oldest enabled account.
    connection.execute(
        sa.text(
            "UPDATE remote_accounts AS target SET is_default = true "
            "WHERE target.id = ("
            " SELECT candidate.id FROM remote_accounts AS candidate "
            " WHERE candidate.source_id = target.source_id AND candidate.enabled = true "
            " ORDER BY CASE WHEN candidate.credential_mode = 'LEGACY_SOURCE' THEN 0 ELSE 1 END, "
            " candidate.created_at, candidate.id LIMIT 1"
            ")"
        )
    )
    op.create_index(
        "uq_remote_account_source_default",
        "remote_accounts",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default = 1"),
    )

    # Unified accounts are complete accounts. Fine-grained capability rows
    # remain as a server-side safety gate, but administrators no longer manage
    # them one by one.
    for capability in CAPABILITIES:
        connection.execute(
            sa.text(
                "INSERT INTO remote_account_capabilities "
                "(account_id, capability, enabled, updated_at) "
                "SELECT account.id, :capability, true, CURRENT_TIMESTAMP "
                "FROM remote_accounts AS account "
                "WHERE NOT EXISTS ("
                " SELECT 1 FROM remote_account_capabilities AS existing "
                " WHERE existing.account_id = account.id "
                " AND existing.capability = :capability"
                ")"
            ).bindparams(capability=capability)
        )
        connection.execute(
            sa.text(
                "UPDATE remote_account_capabilities SET enabled = true "
                "WHERE capability = :capability"
            ).bindparams(capability=capability)
        )


def downgrade() -> None:
    op.drop_index("uq_remote_account_source_default", table_name="remote_accounts")
    op.drop_column("remote_accounts", "is_default")
