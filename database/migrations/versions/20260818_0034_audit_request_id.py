"""add request correlation id to audit logs

Revision ID: 20260818_0034
Revises: 20260818_0033
Create Date: 2026-08-18

This schema definition is intentionally not authorized for production
execution. Apply it only in an approved schema window with backup and rollback.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0034"
down_revision: str | None = "20260818_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "security_audit_logs",
        sa.Column("request_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_security_audit_logs_request_id",
        "security_audit_logs",
        ["request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_security_audit_logs_request_id", table_name="security_audit_logs")
    op.drop_column("security_audit_logs", "request_id")
