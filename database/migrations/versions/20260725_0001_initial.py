"""initial application skeleton

Revision ID: 20260725_0001
Revises:
Create Date: 2026-07-25
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    now = datetime.now(UTC)
    op.create_table(
        "app_users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("username_normalized", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
        sa.UniqueConstraint("username_normalized"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_index("ix_auth_sessions_revoked_at", "auth_sessions", ["revoked_at"])
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    op.create_table(
        "security_audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=True),
        sa.Column("target_id", sa.String(length=120), nullable=True),
        sa.Column("result", sa.String(length=30), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_security_audit_logs_action", "security_audit_logs", ["action"])
    op.create_index("ix_security_audit_logs_created_at", "security_audit_logs", ["created_at"])
    op.create_index(
        "ix_security_audit_logs_actor_user_id",
        "security_audit_logs",
        ["actor_user_id"],
    )

    op.create_table(
        "system_retention_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uploaded_file_retention_days", sa.Integer(), nullable=False),
        sa.Column("result_retention_days", sa.Integer(), nullable=False),
        sa.Column("remote_cache_retention_days", sa.Integer(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        sa.table(
            "system_retention_settings",
            sa.column("id", sa.Integer()),
            sa.column("uploaded_file_retention_days", sa.Integer()),
            sa.column("result_retention_days", sa.Integer()),
            sa.column("remote_cache_retention_days", sa.Integer()),
            sa.column("config_version", sa.Integer()),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": 1,
                "uploaded_file_retention_days": 3,
                "result_retention_days": 30,
                "remote_cache_retention_days": 30,
                "config_version": 1,
                "updated_at": now,
            }
        ],
    )

    op.create_table(
        "source_configs",
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("business_timezone", sa.String(length=80), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("encrypted_credentials", sa.Text(), nullable=True),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("credential_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(length=30), nullable=True),
        sa.Column("last_test_request_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("source_id"),
    )
    op.bulk_insert(
        sa.table(
            "source_configs",
            sa.column("source_id", sa.String()),
            sa.column("display_name", sa.String()),
            sa.column("enabled", sa.Boolean()),
            sa.column("business_timezone", sa.String()),
            sa.column("currency", sa.String()),
            sa.column("config_version", sa.Integer()),
            sa.column("credential_version", sa.Integer()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "source_id": "rajwin",
                "display_name": "RajWin",
                "enabled": False,
                "business_timezone": "Asia/Kolkata",
                "currency": "INR",
                "config_version": 1,
                "credential_version": 0,
                "created_at": now,
                "updated_at": now,
            },
            {
                "source_id": "rajluck",
                "display_name": "RajLuck",
                "enabled": False,
                "business_timezone": "Asia/Kolkata",
                "currency": "INR",
                "config_version": 1,
                "credential_version": 0,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )

    op.create_table(
        "payment_platforms",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform_key", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform_key"),
    )
    op.bulk_insert(
        sa.table(
            "payment_platforms",
            sa.column("id", sa.Integer()),
            sa.column("platform_key", sa.String()),
            sa.column("display_name", sa.String()),
            sa.column("active", sa.Boolean()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": 1,
                "platform_key": "aelopay",
                "display_name": "aelopay",
                "active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": 2,
                "platform_key": "elepay",
                "display_name": "elePay",
                "active": True,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )

    op.create_table(
        "payment_template_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("business_type", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sheet_name_pattern", sa.String(length=200), nullable=True),
        sa.Column("header_signature_json", sa.JSON(), nullable=False),
        sa.Column("column_mapping_json", sa.JSON(), nullable=False),
        sa.Column("success_status_values_json", sa.JSON(), nullable=False),
        sa.Column("match_rules_json", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("published_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["platform_id"], ["payment_platforms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["published_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform_id",
            "business_type",
            "version",
            name="uq_payment_template_business_version",
        ),
    )
    op.create_index(
        "ix_payment_template_versions_business_type",
        "payment_template_versions",
        ["business_type"],
    )
    op.create_index(
        "ix_payment_template_versions_platform_id",
        "payment_template_versions",
        ["platform_id"],
    )
    op.bulk_insert(
        sa.table(
            "payment_template_versions",
            sa.column("id", sa.Integer()),
            sa.column("platform_id", sa.Integer()),
            sa.column("business_type", sa.String()),
            sa.column("version", sa.Integer()),
            sa.column("sheet_name_pattern", sa.String()),
            sa.column("header_signature_json", sa.JSON()),
            sa.column("column_mapping_json", sa.JSON()),
            sa.column("success_status_values_json", sa.JSON()),
            sa.column("match_rules_json", sa.JSON()),
            sa.column("active", sa.Boolean()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("published_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": 1,
                "platform_id": 1,
                "business_type": "payin",
                "version": 1,
                "sheet_name_pattern": "^payin_",
                "header_signature_json": [
                    "ID",
                    "商户ID",
                    "商户订单号",
                    "平台订单号",
                    "订单金额",
                    "费率",
                    "手续费",
                    "订单状态",
                    "订单时间",
                    "到账时间",
                    "到账金额",
                ],
                "column_mapping_json": {
                    "merchant_order_no": "商户订单号",
                    "platform_order_no": "平台订单号",
                    "amount": "订单金额",
                    "fee": "手续费",
                    "net_amount": "到账金额",
                    "payment_status": "订单状态",
                    "candidate_time_fields": ["订单时间", "到账时间"],
                },
                "success_status_values_json": ["成功"],
                "match_rules_json": [
                    {
                        "priority": 1,
                        "payment_canonical_field": "merchant_order_no",
                        "remote_canonical_field": "order_num",
                        "match_type": "exact",
                        "required": True,
                    },
                    {
                        "priority": 2,
                        "payment_canonical_field": "platform_order_no",
                        "remote_canonical_field": "out_trade_no",
                        "match_type": "exact",
                        "required": False,
                    },
                ],
                "active": True,
                "created_at": now,
                "published_at": now,
            },
            {
                "id": 2,
                "platform_id": 2,
                "business_type": "payout",
                "version": 1,
                "sheet_name_pattern": "^(need_send_orders|Sheet1)$",
                "header_signature_json": [
                    "系统订单号",
                    "商户订单号",
                    "创建时间(IST)",
                    "金额",
                    "实付金额",
                    "状态",
                    "回调状态",
                    "回调次数",
                    "失败原因",
                    "UTR",
                    "费率(%)",
                    "手续费",
                    "固定手续费",
                    "总手续费",
                    "隐藏",
                    "延迟成功",
                    "成功时间(IST)",
                    "备注",
                ],
                "column_mapping_json": {
                    "merchant_order_no": "商户订单号",
                    "platform_order_no": "系统订单号",
                    "amount": "金额",
                    "net_amount": "实付金额",
                    "fee": "总手续费",
                    "payment_status": "状态",
                    "candidate_time_fields": [
                        "创建时间(IST)",
                        "成功时间(IST)",
                    ],
                },
                "success_status_values_json": ["已成功"],
                "match_rules_json": [
                    {
                        "priority": 1,
                        "payment_canonical_field": "merchant_order_no",
                        "remote_canonical_field": "order_num",
                        "match_type": "exact",
                        "required": True,
                    },
                    {
                        "priority": 2,
                        "payment_canonical_field": "platform_order_no",
                        "remote_canonical_field": "out_trade_no",
                        "match_type": "exact",
                        "required": False,
                    },
                ],
                "active": True,
                "created_at": now,
                "published_at": now,
            },
        ],
    )

    op.create_table(
        "payment_channel_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("business_type", sa.String(length=20), nullable=False),
        sa.Column("remote_channel_code", sa.String(length=80), nullable=False),
        sa.Column("remote_channel_label", sa.String(length=160), nullable=False),
        sa.Column("merchant_discriminator", sa.String(length=160), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["platform_id"], ["payment_platforms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_id"], ["source_configs.source_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform_id",
            "source_id",
            "business_type",
            "remote_channel_code",
            name="uq_payment_channel_binding",
        ),
    )
    op.create_index(
        "ix_payment_channel_bindings_business_type",
        "payment_channel_bindings",
        ["business_type"],
    )
    op.create_index(
        "ix_payment_channel_bindings_platform_id",
        "payment_channel_bindings",
        ["platform_id"],
    )
    op.create_index(
        "ix_payment_channel_bindings_source_id",
        "payment_channel_bindings",
        ["source_id"],
    )
    op.bulk_insert(
        sa.table(
            "payment_channel_bindings",
            sa.column("id", sa.Integer()),
            sa.column("platform_id", sa.Integer()),
            sa.column("source_id", sa.String()),
            sa.column("business_type", sa.String()),
            sa.column("remote_channel_code", sa.String()),
            sa.column("remote_channel_label", sa.String()),
            sa.column("active", sa.Boolean()),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": 1,
                "platform_id": 1,
                "source_id": "rajwin",
                "business_type": "payin",
                "remote_channel_code": "948",
                "remote_channel_label": "aelopay(HX)",
                "active": True,
                "created_at": now,
            },
            {
                "id": 2,
                "platform_id": 2,
                "source_id": "rajwin",
                "business_type": "payin",
                "remote_channel_code": "659",
                "remote_channel_label": "elePay(HX)",
                "active": True,
                "created_at": now,
            },
            {
                "id": 3,
                "platform_id": 2,
                "source_id": "rajwin",
                "business_type": "payin",
                "remote_channel_code": "800",
                "remote_channel_label": "elePay(QR)",
                "active": True,
                "created_at": now,
            },
            {
                "id": 4,
                "platform_id": 2,
                "source_id": "rajwin",
                "business_type": "payin",
                "remote_channel_code": "991",
                "remote_channel_label": "elePay(YS)",
                "active": True,
                "created_at": now,
            },
        ],
    )

    op.create_table(
        "stored_file_objects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_sha256"),
        sa.UniqueConstraint("storage_key"),
    )

    op.create_table(
        "reconciliation_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("comparison_series_id", sa.String(length=36), nullable=False),
        sa.Column("comparison_identity_key", sa.String(length=64), nullable=True),
        sa.Column("run_version", sa.Integer(), nullable=False),
        sa.Column("rerun_of_batch_id", sa.String(length=36), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("source_display_name", sa.String(length=120), nullable=False),
        sa.Column("source_config_version", sa.Integer(), nullable=False),
        sa.Column("source_business_timezone", sa.String(length=80), nullable=False),
        sa.Column("source_currency", sa.String(length=3), nullable=False),
        sa.Column("business_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("is_final", sa.Boolean(), nullable=False),
        sa.Column("uploaded_file_name", sa.String(length=255), nullable=False),
        sa.Column("uploaded_file_sha256", sa.String(length=64), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("progress_json", sa.JSON(), nullable=False),
        sa.Column("execution_requested_by", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("error_category", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Integer(), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["cancelled_by"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["app_users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_requested_by"], ["app_users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["rerun_of_batch_id"], ["reconciliation_batches.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["source_configs.source_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "comparison_series_id",
            "run_version",
            name="uq_batch_series_version",
        ),
    )
    op.create_index(
        "ix_batch_identity_status",
        "reconciliation_batches",
        ["comparison_identity_key", "status"],
    )
    for column in (
        "business_type",
        "comparison_identity_key",
        "created_at",
        "created_by",
        "execution_requested_by",
        "source_id",
        "status",
        "uploaded_file_sha256",
    ):
        op.create_index(
            f"ix_reconciliation_batches_{column}",
            "reconciliation_batches",
            [column],
        )

    op.create_table(
        "stored_file_references",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("file_object_id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["reconciliation_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["file_object_id"], ["stored_file_objects.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "file_object_id", name="uq_batch_file_reference"),
    )
    op.create_index(
        "ix_stored_file_references_batch_id",
        "stored_file_references",
        ["batch_id"],
    )
    op.create_index(
        "ix_stored_file_references_expires_at",
        "stored_file_references",
        ["expires_at"],
    )
    op.create_index(
        "ix_stored_file_references_file_object_id",
        "stored_file_references",
        ["file_object_id"],
    )

    op.create_table(
        "batch_activity_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("from_status", sa.String(length=40), nullable=True),
        sa.Column("to_status", sa.String(length=40), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["batch_id"], ["reconciliation_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_batch_activity_logs_actor_user_id",
        "batch_activity_logs",
        ["actor_user_id"],
    )
    op.create_index("ix_batch_activity_logs_batch_id", "batch_activity_logs", ["batch_id"])
    op.create_index(
        "ix_batch_activity_logs_created_at",
        "batch_activity_logs",
        ["created_at"],
    )

    op.create_table(
        "order_reconciliation_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("order_group_id", sa.String(length=64), nullable=False),
        sa.Column("result_status", sa.String(length=50), nullable=False),
        sa.Column("payment_status_raw", sa.String(length=120), nullable=True),
        sa.Column("payment_status_group", sa.String(length=20), nullable=False),
        sa.Column("merchant_order_no", sa.String(length=160), nullable=True),
        sa.Column("platform_order_no", sa.String(length=160), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("is_final", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["reconciliation_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "order_group_id", name="uq_batch_order_group_result"),
    )
    op.create_index(
        "ix_reconciliation_result_status",
        "order_reconciliation_results",
        ["batch_id", "result_status"],
    )

    op.create_table(
        "user_notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("run_version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["reconciliation_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "batch_id",
            "run_version",
            "event_type",
            name="uq_notification_batch_event",
        ),
    )
    op.create_index("ix_user_notifications_created_at", "user_notifications", ["created_at"])
    op.create_index("ix_user_notifications_read_at", "user_notifications", ["read_at"])
    op.create_index("ix_user_notifications_user_id", "user_notifications", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_notifications")
    op.drop_table("order_reconciliation_results")
    op.drop_table("batch_activity_logs")
    op.drop_table("stored_file_references")
    op.drop_table("reconciliation_batches")
    op.drop_table("stored_file_objects")
    op.drop_table("payment_channel_bindings")
    op.drop_table("payment_template_versions")
    op.drop_table("payment_platforms")
    op.drop_table("source_configs")
    op.drop_table("system_retention_settings")
    op.drop_table("security_audit_logs")
    op.drop_table("auth_sessions")
    op.drop_table("app_users")
