"""add stable legacy ID crosswalk for the ERP compatibility module

Revision ID: 20260827_0035
Revises: 20260818_0034
Create Date: 2026-08-27

This schema definition is code-only in the current migration phase. It must
not be applied to production until a new schema window, backup and rollback
authorization explicitly includes revision 0035.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0035"
down_revision: str | None = "20260818_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECTION_ID_BASE = 9_000_000_000_000


def upgrade() -> None:
    legacy_id_type = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "erp_compatibility_id_maps",
        sa.Column("mapping_id", legacy_id_type, autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("legacy_id", sa.BigInteger(), nullable=True),
        sa.Column("canonical_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("mapping_id"),
        sa.UniqueConstraint(
            "entity_type",
            "canonical_id",
            name="uq_erp_compatibility_id_map_canonical",
        ),
    )
    op.create_index(
        "ix_erp_compatibility_id_map_entity_legacy",
        "erp_compatibility_id_maps",
        ["entity_type", "legacy_id"],
        unique=True,
    )

    for entity_type, table_name, id_column in (
        ("operator", "erp_operators", "id"),
        ("operator_line", "erp_operator_lines", "id"),
        ("source", "source_configs", "source_id"),
        ("remote_account", "remote_accounts", "id"),
    ):
        op.execute(
            sa.text(
                "INSERT INTO erp_compatibility_id_maps "
                "(entity_type, legacy_id, canonical_id, created_at) "
                f"SELECT :entity_type, :projection_base + "
                f"ROW_NUMBER() OVER (ORDER BY {id_column}), "
                f"{id_column}, CURRENT_TIMESTAMP "
                f"FROM {table_name} ORDER BY {id_column}"
            ).bindparams(
                entity_type=entity_type,
                projection_base=PROJECTION_ID_BASE,
            )
        )


def downgrade() -> None:
    op.drop_index(
        "ix_erp_compatibility_id_map_entity_legacy",
        table_name="erp_compatibility_id_maps",
    )
    op.drop_table("erp_compatibility_id_maps")
