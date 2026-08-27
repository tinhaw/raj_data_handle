"""add online-compatible ERP redemption tables

Revision ID: 20260827_0037
Revises: 20260827_0036
Create Date: 2026-08-27

The compatibility tables preserve the deployed ERP's Long-ID API and state
machine.  Remote market/account rows are intentionally not copied: a batch's
``remote_connection_id`` is the numeric crosswalk for the canonical unified
``RemoteAccount``.  Passwords, TOTP secrets and remote sessions remain solely
owned by the main application.

This revision is code-only. Production execution requires a separately
approved schema and cutover window that explicitly includes revision 0037.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0037"
down_revision: str | None = "20260827_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECTION_ID_BASE = 9_000_000_000_000


def _legacy_id_type() -> sa.types.TypeEngine:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _backfill_mapping(
    entity_type: str,
    table_name: str,
    id_column: str = "id",
) -> None:
    op.execute(
        sa.text(
            "INSERT INTO erp_compatibility_id_maps "
            "(entity_type, legacy_id, canonical_id, created_at) "
            "SELECT :entity_type, "
            "(SELECT CASE "
            " WHEN COALESCE(MAX(existing.legacy_id), 0) < :projection_base "
            " THEN :projection_base ELSE MAX(existing.legacy_id) END "
            " FROM erp_compatibility_id_maps existing "
            " WHERE existing.entity_type = :entity_type) "
            f"+ ROW_NUMBER() OVER (ORDER BY source.{id_column}), "
            f"source.{id_column}, CURRENT_TIMESTAMP FROM {table_name} source "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM erp_compatibility_id_maps mapping "
            "WHERE mapping.entity_type = :entity_type "
            f"AND mapping.canonical_id = source.{id_column}"
            f") ORDER BY source.{id_column}"
        ).bindparams(entity_type=entity_type, projection_base=PROJECTION_ID_BASE)
    )


def _backfill_orphan_batch_tasks() -> None:
    op.execute(
        sa.text(
            "INSERT INTO erp_compatibility_id_maps "
            "(entity_type, legacy_id, canonical_id, created_at) "
            "SELECT 'redemption_task', "
            "(SELECT CASE "
            " WHEN COALESCE(MAX(existing.legacy_id), 0) < :projection_base "
            " THEN :projection_base ELSE MAX(existing.legacy_id) END "
            " FROM erp_compatibility_id_maps existing "
            " WHERE existing.entity_type = 'redemption_task') "
            "+ ROW_NUMBER() OVER (ORDER BY source.id), "
            "'batch:' || source.id, CURRENT_TIMESTAMP "
            "FROM erp_redemption_code_batches source "
            "WHERE source.task_id IS NULL AND NOT EXISTS ("
            " SELECT 1 FROM erp_compatibility_id_maps mapping "
            " WHERE mapping.entity_type = 'redemption_task' "
            " AND mapping.canonical_id = 'batch:' || source.id"
            ") ORDER BY source.id"
        ).bindparams(projection_base=PROJECTION_ID_BASE)
    )


def _create_campaign_tables() -> None:
    op.create_table(
        "erp_compat_redemption_campaigns",
        sa.Column("id", _legacy_id_type(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("lookback_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("description", sa.Text()),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("updated_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("status in ('DRAFT', 'ACTIVE', 'ARCHIVED')"),
        sa.CheckConstraint("lookback_days between 1 and 60"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_erp_compat_redemption_campaign_code"),
    )
    op.create_table(
        "erp_compat_redemption_campaign_tiers",
        sa.Column("id", _legacy_id_type(), autoincrement=True, nullable=False),
        sa.Column("campaign_id", _legacy_id_type(), nullable=False),
        sa.Column("display_name", sa.String(120)),
        sa.Column("min_deposit_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("bonus_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("bonus_max_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("min_deposit_amount >= 0"),
        sa.CheckConstraint("bonus_amount >= 0"),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["erp_compat_redemption_campaigns.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "min_deposit_amount",
            name="uq_erp_compat_redemption_tier_deposit",
        ),
    )
    op.create_index(
        "ix_erp_compat_redemption_tier_campaign_sort",
        "erp_compat_redemption_campaign_tiers",
        ["campaign_id", "sort_order"],
    )


def _create_task_and_batch_tables() -> None:
    op.create_table(
        "erp_compat_redemption_code_tasks",
        sa.Column("id", _legacy_id_type(), autoincrement=True, nullable=False),
        sa.Column("grouping_key", sa.String(140), nullable=False),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "grouping_key", name="uq_erp_compat_redemption_task_grouping_key"
        ),
    )
    op.create_table(
        "erp_compat_redemption_code_batches",
        sa.Column("id", _legacy_id_type(), autoincrement=True, nullable=False),
        sa.Column("campaign_id", _legacy_id_type(), nullable=False),
        sa.Column("claim_date_from", sa.Date(), nullable=False),
        sa.Column("claim_date_to", sa.Date(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False),
        sa.Column(
            "redemption_type",
            sa.String(30),
            nullable=False,
            server_default="SEVEN_DAY_DEPOSIT",
        ),
        sa.Column("expected_code_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="CREATING"),
        # Numeric crosswalk to the canonical unified RemoteAccount. Deliberately
        # no foreign key to any legacy connection table.
        sa.Column("remote_connection_id", _legacy_id_type()),
        sa.Column("task_id", _legacy_id_type(), nullable=False),
        sa.Column("export_group_key", sa.String(100)),
        sa.Column("remote_publish_environment", sa.String(20)),
        sa.Column("remote_flow_times", sa.Integer()),
        sa.Column("remote_creation_interval_seconds", sa.Integer(), server_default="5"),
        sa.Column("remote_activity_recharge", sa.Numeric(20, 2)),
        sa.Column("remote_activity_recharge_count", sa.Integer()),
        sa.Column("remote_activity_id", sa.BigInteger()),
        sa.Column("remote_key_number", sa.Integer()),
        sa.Column("remote_single_user_limit", sa.Integer()),
        sa.Column("remote_single_key_limit", sa.Integer()),
        sa.Column("remote_require_bind_bank_card", sa.Boolean()),
        sa.Column("remote_require_bind_phone", sa.Boolean()),
        sa.Column("remote_check_uuid", sa.Boolean()),
        sa.Column("remote_uuid_reward_limit", sa.Integer()),
        sa.Column("remote_check_login_ip", sa.Boolean()),
        sa.Column("remote_login_ip_reward_limit", sa.Integer()),
        sa.Column("remote_check_register_ip", sa.Boolean()),
        sa.Column("remote_register_ip_reward_limit", sa.Integer()),
        sa.Column("remote_publish_task_id", sa.String(255)),
        sa.Column("remote_publish_error", sa.String(1000)),
        sa.Column("remote_publish_mode", sa.String(20)),
        sa.Column("remote_scheduled_publish_at", sa.DateTime()),
        sa.Column("remote_publish_note", sa.String(2000)),
        sa.Column("remote_publish_cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("published_by", sa.BigInteger()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("claim_date_to >= claim_date_from"),
        sa.CheckConstraint("lookback_days between 1 and 60"),
        sa.CheckConstraint("expected_code_count > 0"),
        sa.CheckConstraint(
            "status in ('CREATING', 'READY_TO_PUBLISH', 'PUBLISHED', 'COMPLETED')"
        ),
        sa.CheckConstraint(
            "redemption_type in ('SEVEN_DAY_DEPOSIT', 'PREVIOUS_DAY_DEPOSIT')"
        ),
        sa.CheckConstraint(
            "remote_creation_interval_seconds is null or "
            "remote_creation_interval_seconds between 1 and 60"
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["erp_compat_redemption_campaigns.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["erp_compat_redemption_code_tasks.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_erp_compat_redemption_batch_campaign_created",
        "erp_compat_redemption_code_batches",
        ["campaign_id", "created_at"],
    )
    op.create_index(
        "ix_erp_compat_redemption_batch_remote_connection",
        "erp_compat_redemption_code_batches",
        ["remote_connection_id", "created_at"],
    )
    op.create_index(
        "ix_erp_compat_redemption_batch_task",
        "erp_compat_redemption_code_batches",
        ["task_id"],
    )
    op.create_index(
        "ix_erp_compat_redemption_batch_export_group",
        "erp_compat_redemption_code_batches",
        ["export_group_key"],
    )


def _create_issue_table() -> None:
    op.create_table(
        "erp_compat_redemption_code_issues",
        sa.Column("id", _legacy_id_type(), autoincrement=True, nullable=False),
        sa.Column("campaign_id", _legacy_id_type(), nullable=False),
        sa.Column("campaign_tier_id", _legacy_id_type(), nullable=False),
        sa.Column("claim_date", sa.Date(), nullable=False),
        sa.Column("deposit_window_start", sa.Date(), nullable=False),
        sa.Column("deposit_window_end", sa.Date(), nullable=False),
        sa.Column("tier_name", sa.String(120)),
        sa.Column("min_deposit_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("bonus_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("bonus_max_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("batch_id", _legacy_id_type()),
        sa.Column(
            "workflow_status",
            sa.String(30),
            nullable=False,
            server_default="PENDING_CREATION",
        ),
        sa.Column("remote_configuration_id", sa.String(255)),
        sa.Column("remote_group_key", sa.String(255)),
        sa.Column("remote_label_ids_json", sa.Text()),
        sa.Column("redemption_code", sa.String(255)),
        sa.Column("remote_request_id", sa.String(80), nullable=False),
        sa.Column("remote_reference_id", sa.String(255)),
        sa.Column("state", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("remote_error", sa.String(1000)),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("state in ('PENDING', 'GENERATED', 'FAILED')"),
        sa.CheckConstraint("deposit_window_end >= deposit_window_start"),
        sa.CheckConstraint(
            "workflow_status in ('PENDING_CREATION', 'CREATING_REMOTE', 'CREATED', "
            "'PUBLISHED', 'CODE_IMPORTED', 'FAILED')"
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["erp_compat_redemption_campaigns.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["campaign_tier_id"],
            ["erp_compat_redemption_campaign_tiers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["erp_compat_redemption_code_batches.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "campaign_tier_id",
            "claim_date",
            name="uq_erp_compat_redemption_issue_campaign_tier_date",
        ),
        sa.UniqueConstraint(
            "remote_configuration_id",
            name="uq_erp_compat_redemption_issue_remote_configuration",
        ),
        sa.UniqueConstraint(
            "redemption_code", name="uq_erp_compat_redemption_issue_code"
        ),
        sa.UniqueConstraint(
            "remote_request_id", name="uq_erp_compat_redemption_issue_request"
        ),
    )
    op.create_index(
        "ix_erp_compat_redemption_issue_campaign_claim",
        "erp_compat_redemption_code_issues",
        ["campaign_id", "claim_date"],
    )
    op.create_index(
        "ix_erp_compat_redemption_issue_batch",
        "erp_compat_redemption_code_issues",
        ["batch_id", "claim_date", "campaign_tier_id"],
    )


def _copy_existing_local_data() -> None:
    # Repeat registry mappings so a deliberately separated 0035→0037 rollout
    # cannot strand a source/account created in the interval.
    _backfill_mapping("source", "source_configs", "source_id")
    _backfill_mapping("remote_account", "remote_accounts")
    for entity_type, table_name in (
        ("redemption_campaign", "erp_redemption_campaigns"),
        ("redemption_campaign_tier", "erp_redemption_campaign_tiers"),
        ("redemption_task", "erp_redemption_tasks"),
        ("redemption_batch", "erp_redemption_code_batches"),
        ("redemption_issue", "erp_redemption_code_issues"),
    ):
        _backfill_mapping(entity_type, table_name)
    _backfill_orphan_batch_tasks()

    op.execute(
        """
        INSERT INTO erp_compat_redemption_campaigns
            (id, code, name, status, lookback_days, description, created_by,
             updated_by, created_at, updated_at, row_version)
        SELECT mapping.legacy_id, source.code, source.name, source.status,
               source.lookback_days, source.description, source.created_by,
               source.updated_by, source.created_at, source.updated_at,
               source.row_version
        FROM erp_redemption_campaigns source
        JOIN erp_compatibility_id_maps mapping
          ON mapping.entity_type = 'redemption_campaign'
         AND mapping.canonical_id = source.id
        """
    )
    op.execute(
        """
        INSERT INTO erp_compat_redemption_campaign_tiers
            (id, campaign_id, display_name, min_deposit_amount, bonus_amount,
             bonus_max_amount, sort_order, created_at, updated_at, row_version)
        SELECT tier_map.legacy_id, campaign_map.legacy_id, source.display_name,
               source.min_deposit_amount, source.bonus_amount,
               source.bonus_max_amount, source.sort_order,
               campaign.created_at, campaign.updated_at, source.row_version
        FROM erp_redemption_campaign_tiers source
        JOIN erp_redemption_campaigns campaign ON campaign.id = source.campaign_id
        JOIN erp_compatibility_id_maps tier_map
          ON tier_map.entity_type = 'redemption_campaign_tier'
         AND tier_map.canonical_id = source.id
        JOIN erp_compatibility_id_maps campaign_map
          ON campaign_map.entity_type = 'redemption_campaign'
         AND campaign_map.canonical_id = source.campaign_id
        """
    )
    op.execute(
        """
        INSERT INTO erp_compat_redemption_code_tasks
            (id, grouping_key, created_by, created_at)
        SELECT mapping.legacy_id, 'group:' || source.export_group_key,
               source.created_by, source.created_at
        FROM erp_redemption_tasks source
        JOIN erp_compatibility_id_maps mapping
          ON mapping.entity_type = 'redemption_task'
         AND mapping.canonical_id = source.id
        """
    )
    op.execute(
        """
        INSERT INTO erp_compat_redemption_code_tasks
            (id, grouping_key, created_by, created_at)
        SELECT mapping.legacy_id, 'batch:' || source.id,
               source.created_by, source.created_at
        FROM erp_redemption_code_batches source
        JOIN erp_compatibility_id_maps mapping
          ON mapping.entity_type = 'redemption_task'
         AND mapping.canonical_id = 'batch:' || source.id
        WHERE source.task_id IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO erp_compat_redemption_code_batches
            (id, campaign_id, claim_date_from, claim_date_to, lookback_days,
             redemption_type, expected_code_count, status,
             remote_connection_id, task_id, export_group_key,
             remote_publish_environment, remote_flow_times,
             remote_creation_interval_seconds, remote_activity_recharge,
             remote_activity_recharge_count, remote_activity_id,
             remote_key_number, remote_single_user_limit,
             remote_single_key_limit, remote_require_bind_bank_card,
             remote_require_bind_phone, remote_check_uuid,
             remote_uuid_reward_limit, remote_check_login_ip,
             remote_login_ip_reward_limit, remote_check_register_ip,
             remote_register_ip_reward_limit, remote_publish_task_id,
             remote_publish_error, remote_publish_mode,
             remote_scheduled_publish_at, remote_publish_note,
             remote_publish_cancelled_at, published_by, published_at,
             created_by, created_at, updated_at, row_version)
        SELECT batch_map.legacy_id, campaign_map.legacy_id,
               source.claim_date_from, source.claim_date_to,
               source.lookback_days,
               COALESCE(plan.redemption_type, 'SEVEN_DAY_DEPOSIT'),
               source.expected_code_count,
               CASE
                 WHEN plan.workflow_status = 'COMPLETED' THEN 'COMPLETED'
                 WHEN plan.workflow_status IN ('PUBLISH_SCHEDULED', 'PUBLISHED')
                   THEN 'PUBLISHED'
                 WHEN plan.workflow_status IN
                   ('READY_TO_PUBLISH', 'AWAITING_PUBLISH_AUTHORIZATION',
                    'PUBLISH_FAILED', 'CANCEL_FAILED')
                   THEN 'READY_TO_PUBLISH'
                 WHEN source.status = 'PUBLISHED_LOCAL' THEN 'COMPLETED'
                 WHEN source.status = 'READY_LOCAL' THEN 'READY_TO_PUBLISH'
                 ELSE 'CREATING'
               END,
               account_map.legacy_id, task_map.legacy_id,
               task.export_group_key, plan.publish_environment,
               plan.flow_times, plan.creation_interval_seconds,
               plan.activity_recharge, plan.activity_recharge_count,
               plan.activity_id, plan.key_number, plan.single_user_limit,
               plan.single_key_limit, plan.require_bind_bank_card,
               plan.require_bind_phone, plan.check_uuid,
               plan.uuid_reward_limit, plan.check_login_ip,
               plan.login_ip_reward_limit, plan.check_register_ip,
               plan.register_ip_reward_limit, plan.remote_publish_task_id,
               plan.error_message, plan.publish_mode,
               plan.scheduled_publish_at, plan.publish_note,
               plan.schedule_cancelled_at, source.published_by,
               source.published_at, source.created_by, source.created_at,
               source.updated_at, source.row_version
        FROM erp_redemption_code_batches source
        JOIN erp_compatibility_id_maps batch_map
          ON batch_map.entity_type = 'redemption_batch'
         AND batch_map.canonical_id = source.id
        JOIN erp_compatibility_id_maps campaign_map
          ON campaign_map.entity_type = 'redemption_campaign'
         AND campaign_map.canonical_id = source.campaign_id
        JOIN erp_compatibility_id_maps task_map
          ON task_map.entity_type = 'redemption_task'
         AND task_map.canonical_id = CASE WHEN source.task_id IS NULL
               THEN 'batch:' || source.id ELSE source.task_id END
        LEFT JOIN erp_redemption_tasks task ON task.id = source.task_id
        LEFT JOIN erp_redemption_remote_plans plan ON plan.batch_id = source.id
        LEFT JOIN erp_compatibility_id_maps account_map
          ON account_map.entity_type = 'remote_account'
         AND account_map.canonical_id = source.remote_account_id
        """
    )
    op.execute(
        """
        INSERT INTO erp_compat_redemption_code_issues
            (id, campaign_id, campaign_tier_id, claim_date,
             deposit_window_start, deposit_window_end, tier_name,
             min_deposit_amount, bonus_amount, bonus_max_amount, batch_id,
             workflow_status, remote_configuration_id, remote_group_key,
             remote_label_ids_json, redemption_code, remote_request_id,
             remote_reference_id, state, remote_error, generated_at,
             created_by, created_at, updated_at, row_version)
        SELECT issue_map.legacy_id, campaign_map.legacy_id, tier_map.legacy_id,
               source.claim_date, source.deposit_window_start,
               source.deposit_window_end, source.tier_name,
               source.min_deposit_amount, source.bonus_amount,
               source.bonus_max_amount, batch_map.legacy_id,
               CASE
                 WHEN source.redemption_code IS NOT NULL THEN 'CODE_IMPORTED'
                 WHEN source.remote_workflow_status = 'PUBLISHED' THEN 'PUBLISHED'
                 WHEN source.remote_workflow_status = 'CREATED' THEN 'CREATED'
                 WHEN source.remote_workflow_status = 'RESERVED'
                   THEN 'CREATING_REMOTE'
                 WHEN source.remote_workflow_status = 'FAILED' THEN 'FAILED'
                 ELSE 'PENDING_CREATION'
               END,
               source.remote_configuration_id, source.remote_group_key,
               CAST(source.remote_label_ids_json AS TEXT),
               source.redemption_code, 'compat:' || source.id,
               source.local_reference,
               CASE WHEN source.redemption_code IS NOT NULL THEN 'GENERATED'
                    ELSE source.state END,
               source.remote_error_message, source.imported_at,
               source.created_by, source.created_at, source.updated_at,
               source.row_version
        FROM erp_redemption_code_issues source
        JOIN erp_compatibility_id_maps issue_map
          ON issue_map.entity_type = 'redemption_issue'
         AND issue_map.canonical_id = source.id
        JOIN erp_compatibility_id_maps campaign_map
          ON campaign_map.entity_type = 'redemption_campaign'
         AND campaign_map.canonical_id = source.campaign_id
        JOIN erp_compatibility_id_maps tier_map
          ON tier_map.entity_type = 'redemption_campaign_tier'
         AND tier_map.canonical_id = source.campaign_tier_id
        JOIN erp_compatibility_id_maps batch_map
          ON batch_map.entity_type = 'redemption_batch'
         AND batch_map.canonical_id = source.batch_id
        """
    )


def _synchronize_postgresql_sequences() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name in (
        "erp_compat_redemption_campaigns",
        "erp_compat_redemption_campaign_tiers",
        "erp_compat_redemption_code_tasks",
        "erp_compat_redemption_code_batches",
        "erp_compat_redemption_code_issues",
    ):
        op.execute(
            sa.text(
                f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                f"COALESCE(MAX(id), 1), COUNT(*) > 0) FROM {table_name}"
            )
        )


def upgrade() -> None:
    _create_campaign_tables()
    _create_task_and_batch_tables()
    _create_issue_table()
    _copy_existing_local_data()
    _synchronize_postgresql_sequences()


def downgrade() -> None:
    op.drop_index(
        "ix_erp_compat_redemption_issue_batch",
        table_name="erp_compat_redemption_code_issues",
    )
    op.drop_index(
        "ix_erp_compat_redemption_issue_campaign_claim",
        table_name="erp_compat_redemption_code_issues",
    )
    op.drop_table("erp_compat_redemption_code_issues")
    op.drop_index(
        "ix_erp_compat_redemption_batch_export_group",
        table_name="erp_compat_redemption_code_batches",
    )
    op.drop_index(
        "ix_erp_compat_redemption_batch_task",
        table_name="erp_compat_redemption_code_batches",
    )
    op.drop_index(
        "ix_erp_compat_redemption_batch_remote_connection",
        table_name="erp_compat_redemption_code_batches",
    )
    op.drop_index(
        "ix_erp_compat_redemption_batch_campaign_created",
        table_name="erp_compat_redemption_code_batches",
    )
    op.drop_table("erp_compat_redemption_code_batches")
    op.drop_table("erp_compat_redemption_code_tasks")
    op.drop_index(
        "ix_erp_compat_redemption_tier_campaign_sort",
        table_name="erp_compat_redemption_campaign_tiers",
    )
    op.drop_table("erp_compat_redemption_campaign_tiers")
    op.drop_table("erp_compat_redemption_campaigns")
