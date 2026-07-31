from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class AppUser(Base):
    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    username_normalized: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent_hash: Mapped[str | None] = mapped_column(String(64))


class SecurityAuditLog(Base):
    __tablename__ = "security_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(120))
    result: Mapped[str] = mapped_column(String(30), nullable=False, default="success")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


class SystemRetentionSetting(Base):
    __tablename__ = "system_retention_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    uploaded_file_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    result_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    remote_cache_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    withdraw_order_refresh_interval_hours: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    withdraw_order_refresh_page_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
    )
    withdraw_order_query_range: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="today",
    )
    withdraw_order_export_date_mode: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="previous_day",
    )
    withdraw_order_export_specific_date: Mapped[date | None] = mapped_column(Date)
    charge_order_refresh_interval_hours: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    charge_order_refresh_page_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
    )
    charge_order_query_range: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="today",
    )
    charge_order_export_date_mode: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="previous_day",
    )
    charge_order_export_specific_date: Mapped[date | None] = mapped_column(Date)
    spin_order_refresh_interval_hours: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2,
    )
    spin_order_refresh_page_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
    )
    spin_order_query_range: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        default="previous_business_day_to_completed_slot",
    )
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class SystemSessionSetting(Base):
    __tablename__ = "system_session_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    session_ttl_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class WithdrawOrderSnapshot(Base):
    """Approved withdrawal-order fields cached from one read-only source.

    The table intentionally has no raw remote payload column.  It is safe for
    the monitoring page to query without exposing account, IP, bank, or other
    unrelated remote fields.
    """

    __tablename__ = "withdraw_order_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "remote_order_id",
            name="uq_withdraw_order_snapshot_source_remote_id",
        ),
        Index(
            "ix_withdraw_order_snapshot_source_create_time",
            "source_id",
            "create_time_utc",
        ),
        Index(
            "ix_withdraw_order_snapshot_source_status",
            "source_id",
            "status",
        ),
        Index(
            "ix_withdraw_order_snapshot_source_uid",
            "source_id",
            "uid",
        ),
        Index(
            "ix_withdraw_order_snapshot_source_pay_channel",
            "source_id",
            "pay_channel",
        ),
        Index(
            "ix_withdraw_order_snapshot_source_order_num",
            "source_id",
            "order_num",
        ),
        Index(
            "ix_withdraw_order_snapshot_source_out_trade_no",
            "source_id",
            "out_trade_no",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_configs.source_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    remote_order_id: Mapped[str] = mapped_column(String(120), nullable=False)
    uid: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    order_num: Mapped[str | None] = mapped_column(String(160))
    out_trade_no: Mapped[str | None] = mapped_column(String(160))
    pay_channel_name: Mapped[str | None] = mapped_column(String(160))
    pay_channel: Mapped[str | None] = mapped_column(String(120))
    amount: Mapped[str | None] = mapped_column(String(64))
    fee: Mapped[str | None] = mapped_column(String(64))
    real_amount: Mapped[str | None] = mapped_column(String(64))
    create_time: Mapped[str | None] = mapped_column(String(32))
    create_time_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    update_time: Mapped[str | None] = mapped_column(String(32))
    submit_time: Mapped[str | None] = mapped_column(String(32))
    audit_admin: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    status_label: Mapped[str | None] = mapped_column(String(120))
    is_first: Mapped[str | None] = mapped_column(String(40))
    channel: Mapped[str | None] = mapped_column(String(120))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


class WithdrawOrderRefreshState(Base):
    """Source-scoped background refresh state and durable manual request marker."""

    __tablename__ = "withdraw_order_refresh_states"

    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_configs.source_id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle", index=True)
    manual_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_query_range: Mapped[str | None] = mapped_column(String(32))
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_window_start_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_window_end_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_remote_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_cached_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_fetched_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_export_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ChargeOrderSnapshot(Base):
    """Approved fields from the read-only remote recharge-order response.

    The snapshot deliberately omits account, IP, nickname, attachment and raw
    callback fields.  They are unnecessary for local monitoring and should not
    be copied into the analysis database.
    """

    __tablename__ = "charge_order_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "remote_order_id",
            name="uq_charge_order_snapshot_source_remote_id",
        ),
        Index("ix_charge_order_snapshot_source_create_time", "source_id", "create_time_utc"),
        Index("ix_charge_order_snapshot_source_status", "source_id", "status"),
        Index("ix_charge_order_snapshot_source_uid", "source_id", "uid"),
        Index("ix_charge_order_snapshot_source_channel", "source_id", "pay_method"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_configs.source_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    remote_order_id: Mapped[str] = mapped_column(String(120), nullable=False)
    uid: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    order_num: Mapped[str | None] = mapped_column(String(160))
    charge_product_id: Mapped[str | None] = mapped_column(String(120))
    product_name: Mapped[str | None] = mapped_column(String(160))
    out_trade_no: Mapped[str | None] = mapped_column(String(160))
    pay_method: Mapped[str | None] = mapped_column(String(120))
    pay_channel_name: Mapped[str | None] = mapped_column(String(160))
    pay_type: Mapped[str | None] = mapped_column(String(120))
    amount: Mapped[str | None] = mapped_column(String(64))
    balance: Mapped[str | None] = mapped_column(String(64))
    extra: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    create_time: Mapped[str | None] = mapped_column(String(32))
    create_time_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pay_time: Mapped[str | None] = mapped_column(String(32))
    update_time: Mapped[str | None] = mapped_column(String(32))
    first_pay: Mapped[str | None] = mapped_column(String(40))
    notified: Mapped[str | None] = mapped_column(String(40))
    charge_type: Mapped[str | None] = mapped_column(String(80))
    channel: Mapped[str | None] = mapped_column(String(120))
    fill_order_id: Mapped[str | None] = mapped_column(String(120))
    fill_order_num: Mapped[str | None] = mapped_column(String(160))
    fill_order_admin: Mapped[str | None] = mapped_column(String(160))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


class ChargeOrderRefreshState(Base):
    """Durable source-scoped scheduling state for recharge-order refreshes."""

    __tablename__ = "charge_order_refresh_states"

    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_configs.source_id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle", index=True)
    manual_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_query_range: Mapped[str | None] = mapped_column(String(32))
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_window_start_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_window_end_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_remote_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_cached_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_fetched_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_error: Mapped[str | None] = mapped_column(String(500))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class SpinOrderSnapshot(Base):
    """Read-only local projection of one remote turntable application."""

    __tablename__ = "spin_order_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "remote_order_id",
            name="uq_spin_order_snapshot_source_remote_id",
        ),
        Index("ix_spin_order_snapshot_source_create_time", "source_id", "create_time_utc"),
        Index("ix_spin_order_snapshot_source_status", "source_id", "status"),
        Index("ix_spin_order_snapshot_source_uid", "source_id", "uid"),
        Index("ix_spin_order_snapshot_source_config", "source_id", "spin_config_id"),
        Index("ix_spin_order_snapshot_source_channel", "source_id", "channel_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_configs.source_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    remote_order_id: Mapped[str] = mapped_column(String(120), nullable=False)
    uid: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    vip_level: Mapped[str | None] = mapped_column(String(40))
    agent_total_count: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[str | None] = mapped_column(String(64))
    spin_config_id: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    round_number: Mapped[str | None] = mapped_column(String(40))
    invite_count: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    status_label: Mapped[str | None] = mapped_column(String(120))
    create_time: Mapped[str | None] = mapped_column(String(32))
    create_time_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audit_time: Mapped[str | None] = mapped_column(String(32))
    audit_time_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel_id: Mapped[str | None] = mapped_column(String(120))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


class UserChannelCache(Base):
    """Minimal source-scoped UID-to-channel cache; no user profile data is stored."""

    __tablename__ = "user_channel_caches"
    __table_args__ = (
        UniqueConstraint("source_id", "uid", name="uq_user_channel_cache_source_uid"),
        Index("ix_user_channel_cache_source_status", "source_id", "resolution_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_configs.source_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uid: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_id: Mapped[str | None] = mapped_column(String(120))
    resolution_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class SpinOrderRefreshState(Base):
    """Source-scoped state for two-hour spin-order list refreshes."""

    __tablename__ = "spin_order_refresh_states"

    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_configs.source_id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle", index=True)
    manual_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_query_range: Mapped[str | None] = mapped_column(String(32))
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_window_start_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_window_end_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_remote_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_cached_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_fetched_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_resolved_uid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_unresolved_uid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class SourceConfig(Base):
    __tablename__ = "source_configs"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    business_timezone: Mapped[str] = mapped_column(
        String(80), nullable=False, default="Asia/Kolkata"
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    encrypted_credentials: Mapped[str | None] = mapped_column(Text)
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credential_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_status: Mapped[str | None] = mapped_column(String(30))
    last_test_request_id: Mapped[str | None] = mapped_column(String(64))

    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class PaymentPlatform(Base):
    __tablename__ = "payment_platforms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class PaymentTemplateVersion(Base):
    __tablename__ = "payment_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "platform_id",
            "business_type",
            "version",
            name="uq_payment_template_business_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("payment_platforms.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    business_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    sheet_name_pattern: Mapped[str | None] = mapped_column(String(200))
    header_signature_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    column_mapping_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    success_status_values_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    match_rules_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    published_by: Mapped[int | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentChannelBinding(Base):
    __tablename__ = "payment_channel_bindings"
    __table_args__ = (
        UniqueConstraint(
            "platform_id",
            "source_id",
            "business_type",
            "remote_channel_code",
            name="uq_payment_channel_binding",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("payment_platforms.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_configs.source_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    business_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    remote_channel_code: Mapped[str] = mapped_column(String(80), nullable=False)
    remote_channel_label: Mapped[str] = mapped_column(String(160), nullable=False)
    merchant_discriminator: Mapped[str | None] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class DataDictionaryEntry(Base):
    __tablename__ = "data_dictionary_entries"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "dictionary_type",
            "entry_code",
            name="uq_data_dictionary_source_type_code",
        ),
        Index(
            "ix_data_dictionary_type_active",
            "dictionary_type",
            "active",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_configs.source_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dictionary_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entry_code: Mapped[str] = mapped_column(String(80), nullable=False)
    entry_label: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class StoredFileObject(Base):
    __tablename__ = "stored_file_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReconciliationBatch(Base):
    __tablename__ = "reconciliation_batches"
    __table_args__ = (
        UniqueConstraint("comparison_series_id", "run_version", name="uq_batch_series_version"),
        Index("ix_batch_identity_status", "comparison_identity_key", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    comparison_series_id: Mapped[str] = mapped_column(String(36), nullable=False, default=new_uuid)
    comparison_identity_key: Mapped[str | None] = mapped_column(String(64), index=True)
    run_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rerun_of_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("reconciliation_batches.id", ondelete="SET NULL")
    )

    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_configs.source_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_business_timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    source_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    business_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="awaiting_confirmation", index=True
    )
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uploaded_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    progress_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    execution_requested_by: Mapped[int] = mapped_column(
        ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    error_category: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL")
    )
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class StoredFileReference(Base):
    __tablename__ = "stored_file_references"
    __table_args__ = (
        UniqueConstraint("batch_id", "file_object_id", name="uq_batch_file_reference"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    file_object_id: Mapped[str] = mapped_column(
        ForeignKey("stored_file_objects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class BatchActivityLog(Base):
    __tablename__ = "batch_activity_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(40))
    to_status: Mapped[str | None] = mapped_column(String(40))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


class OrderReconciliationResult(Base):
    __tablename__ = "order_reconciliation_results"
    __table_args__ = (
        UniqueConstraint("batch_id", "order_group_id", name="uq_batch_order_group_result"),
        Index("ix_reconciliation_result_status", "batch_id", "result_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_batches.id", ondelete="CASCADE"), nullable=False
    )
    order_group_id: Mapped[str] = mapped_column(String(64), nullable=False)
    result_status: Mapped[str] = mapped_column(String(50), nullable=False)
    payment_status_raw: Mapped[str | None] = mapped_column(String(120))
    payment_status_group: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    merchant_order_no: Mapped[str | None] = mapped_column(String(160))
    platform_order_no: Mapped[str | None] = mapped_column(String(160))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class UserNotification(Base):
    __tablename__ = "user_notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "batch_id",
            "run_version",
            "event_type",
            name="uq_notification_batch_event",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_batches.id", ondelete="CASCADE"), nullable=False
    )
    run_version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
