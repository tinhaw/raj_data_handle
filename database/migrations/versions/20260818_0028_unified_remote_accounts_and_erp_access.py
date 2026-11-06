"""add unified remote accounts and ERP access grants

Revision ID: 20260818_0028
Revises: 20260817_0027
Create Date: 2026-08-18

The revision is definition-only in the current work session. It must not run
until the production target, backup, rollback plan and execution window have
been separately approved.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0028"
down_revision: str | None = "20260817_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "remote_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("login_username", sa.String(length=200), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "credential_mode",
            sa.String(length=30),
            nullable=False,
            server_default="MANAGED",
        ),
        sa.Column("encrypted_credentials", sa.Text(), nullable=True),
        sa.Column("credential_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credential_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(length=30), nullable=True),
        sa.Column("last_test_request_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("credential_mode in ('MANAGED', 'LEGACY_SOURCE')"),
        sa.ForeignKeyConstraint(["source_id"], ["source_configs.source_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "login_username",
            name="uq_remote_account_source_login_username",
        ),
    )
    op.create_index(
        "ix_remote_account_source_enabled",
        "remote_accounts",
        ["source_id", "enabled"],
    )
    op.create_table(
        "remote_account_capabilities",
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("capability", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["remote_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("account_id", "capability"),
    )
    op.create_table(
        "erp_user_access_profiles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("all_operators", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "erp_user_role_grants",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("granted_by", sa.Integer(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id", "role"),
    )
    op.create_table(
        "erp_user_operator_scopes",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.String(length=36), nullable=False),
        sa.Column("granted_by", sa.Integer(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_id"], ["erp_operators.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["granted_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id", "operator_id"),
    )

    # Existing analysis credentials remain encrypted in SourceConfig during
    # this safe transition.  We create one non-secret legacy account reference
    # per market instead of decrypting, copying or re-encrypting any secret.
    connection = op.get_bind()
    source_ids = list(
        connection.execute(sa.text("select source_id from source_configs order by source_id"))
        .scalars()
    )
    if not source_ids:
        return
    now = datetime.now(UTC)
    remote_accounts = sa.table(
        "remote_accounts",
        sa.column("id", sa.String()),
        sa.column("source_id", sa.String()),
        sa.column("login_username", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("credential_mode", sa.String()),
        sa.column("credential_version", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    capabilities = sa.table(
        "remote_account_capabilities",
        sa.column("account_id", sa.String()),
        sa.column("capability", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    accounts: list[dict[str, object]] = []
    grants: list[dict[str, object]] = []
    for source_id in source_ids:
        account_id = str(uuid.uuid4())
        accounts.append(
            {
                "id": account_id,
                "source_id": source_id,
                "login_username": None,
                "display_name": "历史分析默认账号",
                "enabled": True,
                "credential_mode": "LEGACY_SOURCE",
                "credential_version": 0,
                "created_at": now,
                "updated_at": now,
            }
        )
        grants.append(
            {
                "account_id": account_id,
                "capability": "ANALYSIS_READ",
                "enabled": True,
                "updated_at": now,
            }
        )
    op.bulk_insert(remote_accounts, accounts)
    op.bulk_insert(capabilities, grants)


def downgrade() -> None:
    op.drop_table("erp_user_operator_scopes")
    op.drop_table("erp_user_role_grants")
    op.drop_table("erp_user_access_profiles")
    op.drop_table("remote_account_capabilities")
    op.drop_index("ix_remote_account_source_enabled", table_name="remote_accounts")
    op.drop_table("remote_accounts")
