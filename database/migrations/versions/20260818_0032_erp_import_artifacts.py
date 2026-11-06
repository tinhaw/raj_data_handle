"""Store ERP import source-artifact metadata.

Revision ID: 20260818_0032
Revises: 20260818_0031
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0032"
down_revision = "20260818_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "erp_import_jobs", sa.Column("source_storage_key", sa.String(length=500), nullable=True)
    )
    op.add_column(
        "erp_import_jobs", sa.Column("source_size_bytes", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("erp_import_jobs", "source_size_bytes")
    op.drop_column("erp_import_jobs", "source_storage_key")
