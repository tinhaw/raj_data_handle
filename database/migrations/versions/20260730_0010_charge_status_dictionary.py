"""seed the manually verified recharge-order status dictionary

Revision ID: 20260730_0010
Revises: 20260730_0009
Create Date: 2026-07-30
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0010"
down_revision: str | None = "20260730_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHARGE_STATUSES = (
    ("-1", "已失效"),
    ("0", "待支付"),
    ("1", "已支付"),
    ("2", "已退款"),
)


def upgrade() -> None:
    connection = op.get_bind()
    sources = sa.table(
        "source_configs",
        sa.column("source_id", sa.String(length=64)),
    )
    entries = sa.table(
        "data_dictionary_entries",
        sa.column("source_id", sa.String(length=64)),
        sa.column("dictionary_type", sa.String(length=80)),
        sa.column("entry_code", sa.String(length=80)),
        sa.column("entry_label", sa.String(length=255)),
        sa.column("active", sa.Boolean()),
        sa.column("first_seen_at", sa.DateTime(timezone=True)),
        sa.column("last_seen_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    source_ids = list(connection.scalars(sa.select(sources.c.source_id)))
    existing = set(
        connection.execute(
            sa.select(entries.c.source_id, entries.c.entry_code).where(
                entries.c.dictionary_type == "charge_status"
            )
        ).all()
    )
    inserted_at = datetime.now(UTC)
    for source_id, code in existing:
        label = dict(CHARGE_STATUSES).get(code)
        if label is None:
            continue
        connection.execute(
            sa.update(entries)
            .where(
                entries.c.source_id == source_id,
                entries.c.dictionary_type == "charge_status",
                entries.c.entry_code == code,
            )
            .values(
                entry_label=label,
                active=True,
                last_seen_at=inserted_at,
                updated_at=inserted_at,
            )
        )
    rows = [
        {
            "source_id": source_id,
            "dictionary_type": "charge_status",
            "entry_code": code,
            "entry_label": label,
            "active": True,
            "first_seen_at": inserted_at,
            "last_seen_at": inserted_at,
            "updated_at": inserted_at,
        }
        for source_id in source_ids
        for code, label in CHARGE_STATUSES
        if (source_id, code) not in existing
    ]
    if rows:
        op.bulk_insert(entries, rows)


def downgrade() -> None:
    entries = sa.table(
        "data_dictionary_entries",
        sa.column("dictionary_type", sa.String(length=80)),
        sa.column("entry_code", sa.String(length=80)),
    )
    op.execute(
        sa.delete(entries).where(
            entries.c.dictionary_type == "charge_status",
            entries.c.entry_code.in_([code for code, _label in CHARGE_STATUSES]),
        )
    )
