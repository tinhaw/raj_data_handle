"""add per-source v1 initial-review API configuration

Revision ID: 20260817_0027
Revises: 20260817_0026
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0027"
down_revision: str | None = "20260817_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_configs",
        sa.Column("initial_review_v1_api_base_url", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "source_configs",
        sa.Column("encrypted_initial_review_v1_api_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "source_configs",
        sa.Column(
            "initial_review_v1_api_key_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "source_configs",
        sa.Column(
            "initial_review_v1_api_key_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("source_configs", "initial_review_v1_api_key_updated_at")
    op.drop_column("source_configs", "initial_review_v1_api_key_version")
    op.drop_column("source_configs", "encrypted_initial_review_v1_api_key")
    op.drop_column("source_configs", "initial_review_v1_api_base_url")
