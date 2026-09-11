"""add per-source scoring-review API configuration

Revision ID: 20260801_0017
Revises: 20260801_0016
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0017"
down_revision: str | None = "20260801_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("source_configs", sa.Column("scoring_api_base_url", sa.String(length=500)))
    op.add_column("source_configs", sa.Column("encrypted_scoring_api_key", sa.Text()))
    op.add_column(
        "source_configs",
        sa.Column(
            "scoring_api_key_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "source_configs",
        sa.Column("scoring_api_key_updated_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "source_configs",
        sa.Column("scoring_api_last_tested_at", sa.DateTime(timezone=True)),
    )
    op.add_column("source_configs", sa.Column("scoring_api_last_test_status", sa.String(length=30)))
    op.add_column(
        "source_configs",
        sa.Column("scoring_api_last_test_request_id", sa.String(length=64)),
    )


def downgrade() -> None:
    op.drop_column("source_configs", "scoring_api_last_test_request_id")
    op.drop_column("source_configs", "scoring_api_last_test_status")
    op.drop_column("source_configs", "scoring_api_last_tested_at")
    op.drop_column("source_configs", "scoring_api_key_updated_at")
    op.drop_column("source_configs", "scoring_api_key_version")
    op.drop_column("source_configs", "encrypted_scoring_api_key")
    op.drop_column("source_configs", "scoring_api_base_url")
