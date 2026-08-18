from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
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
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    result: Mapped[str] = mapped_column(String(30), nullable=False, default="success")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


class TotpAccount(Base):
    """Standalone encrypted TOTP account, independent from remote data sources."""

    __tablename__ = "totp_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    secret_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    secret_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class SystemRetentionSetting(Base):
    __tablename__ = "system_retention_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    uploaded_file_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    result_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    remote_cache_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # Operational sync records are intentionally retained separately from the
    # cached source data.  They are small, append-only audit projections and
    # should remain available even after an older order snapshot is purged.
    sync_log_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
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
    withdraw_order_export_time: Mapped[time] = mapped_column(
        Time,
        nullable=False,
        default=time(0, 5, 1),
    )
    automatic_sync_retry_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    automatic_sync_retry_interval_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
    )
    remote_order_sync_timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=180,
    )
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
    charge_order_export_time: Mapped[time] = mapped_column(
        Time,
        nullable=False,
        default=time(0, 0, 1),
    )
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


class WithdrawScoringSnapshot(Base):
    """Supplemental scoring-review fields for an already cached withdrawal order.

    A row is keyed by the source and the score workbook's ``案件号``.  The
    composite foreign key intentionally points to the authoritative withdrawal
    snapshot's ``(source_id, remote_order_id)`` pair.  This makes score-only
    workbooks unable to introduce a withdrawal order into the analysis system:
    the importer can persist a score row only after the primary withdrawal row
    exists.

    The projection excludes the score workbook's UID, amount, channel, and
    withdrawal-time columns.  Those values remain exclusively owned by
    :class:`WithdrawOrderSnapshot` and must never be overwritten by a scoring
    export.
    """

    __tablename__ = "withdraw_scoring_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "withdraw_order_id",
            name="uq_withdraw_scoring_snapshot_source_withdraw_order_id",
        ),
        ForeignKeyConstraint(
            ["source_id", "withdraw_order_id"],
            [
                "withdraw_order_snapshots.source_id",
                "withdraw_order_snapshots.remote_order_id",
            ],
            name="fk_withdraw_scoring_snapshot_withdraw_order",
            ondelete="CASCADE",
        ),
        Index(
            "ix_withdraw_scoring_snapshot_source_review_completed_at",
            "source_id",
            "review_completed_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    withdraw_order_id: Mapped[str] = mapped_column(String(120), nullable=False)

    global_hard_condition: Mapped[str | None] = mapped_column(String(120))
    scenario_review: Mapped[str | None] = mapped_column(String(120))
    # The workbook may contain an integer score or a textual state such as
    # "未开始", so retain its display value without coercing it to a number.
    score_review: Mapped[str | None] = mapped_column(String(80))
    decision_stage: Mapped[str | None] = mapped_column(String(120))
    final_review_suggestion: Mapped[str | None] = mapped_column(String(120))
    operation_result: Mapped[str | None] = mapped_column(String(120))
    review_summary: Mapped[str | None] = mapped_column(Text)
    current_status: Mapped[str | None] = mapped_column(String(120))
    review_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_duration: Mapped[str | None] = mapped_column(String(80))
    queue_duration: Mapped[str | None] = mapped_column(String(80))
    entered_queue_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exited_queue_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    automatic_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_export_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    # A manual request is represented by a durable sync-run record.  Keeping
    # both pointers on the source-scoped state lets the worker update the exact
    # queued/claimed run instead of trying to infer it from timestamps.
    pending_sync_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_sync_runs.id", ondelete="SET NULL"),
        index=True,
    )
    active_sync_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_sync_runs.id", ondelete="SET NULL"),
        index=True,
    )
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
    automatic_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    pending_sync_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_sync_runs.id", ondelete="SET NULL"),
        index=True,
    )
    active_sync_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_sync_runs.id", ondelete="SET NULL"),
        index=True,
    )
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
    automatic_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_resolved_uid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_unresolved_uid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    pending_sync_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_sync_runs.id", ondelete="SET NULL"),
        index=True,
    )
    active_sync_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_sync_runs.id", ondelete="SET NULL"),
        index=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class SourceConfig(Base):
    __tablename__ = "source_configs"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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

    # The scoring-review service is a separate, read-only integration.  Its
    # API key must never be mixed with the Raj admin login credentials above:
    # it has a different authorization model and can point at a different
    # source-specific base URL.
    scoring_api_base_url: Mapped[str | None] = mapped_column(String(500))
    encrypted_scoring_api_key: Mapped[str | None] = mapped_column(Text)
    scoring_api_key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scoring_api_key_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scoring_api_last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scoring_api_last_test_status: Mapped[str | None] = mapped_column(String(30))
    scoring_api_last_test_request_id: Mapped[str | None] = mapped_column(String(64))

    # The v1 initial-review API follows the same write-only key rules as the
    # scoring-review API, but has a separate authorization scope and URL.
    initial_review_v1_api_base_url: Mapped[str | None] = mapped_column(String(500))
    encrypted_initial_review_v1_api_key: Mapped[str | None] = mapped_column(Text)
    initial_review_v1_api_key_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    initial_review_v1_api_key_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

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


class RemoteAccount(Base):
    """One remote login account belonging to a unified analysis/ERP market.

    ``SourceConfig`` remains the market/source master so existing analysis
    records keep their stable foreign keys. During the migration window an
    account can explicitly reference the source's historical credential record
    through ``LEGACY_SOURCE``; managed accounts have an account-specific scope.
    """

    __tablename__ = "remote_accounts"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "login_username",
            name="uq_remote_account_source_login_username",
        ),
        Index("ix_remote_account_source_enabled", "source_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_configs.source_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # The visible remote login name is not a password or a session token.
    # Legacy source records may not have it without decrypting old ciphertext.
    login_username: Mapped[str | None] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    credential_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="MANAGED")
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


class RemoteAccountCapability(Base):
    """An explicit capability grant for one shared remote account."""

    __tablename__ = "remote_account_capabilities"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("remote_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    capability: Mapped[str] = mapped_column(String(80), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class RemoteAccountTagSnapshot(Base):
    """Last locally stored remote tag directory, without any credentials."""

    __tablename__ = "remote_account_tag_snapshots"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("remote_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    tags_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="MANUAL")
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class RemoteAccountRewardTierPreset(Base):
    """Per-account reward tiers bound to the tag snapshot used when saved."""

    __tablename__ = "remote_account_reward_tier_presets"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("remote_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    tiers_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    tag_snapshot_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    saved_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ErpUserAccessProfile(Base):
    """The local ERP scope envelope for one application user."""

    __tablename__ = "erp_user_access_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True
    )
    all_operators: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ErpUserRoleGrant(Base):
    """An ERP role, intentionally separate from the global login role."""

    __tablename__ = "erp_user_role_grants"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(50), primary_key=True)
    granted_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ErpUserOperatorScope(Base):
    """An explicit delivery-company scope for a local ERP user."""

    __tablename__ = "erp_user_operator_scopes"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True
    )
    operator_id: Mapped[str] = mapped_column(
        ForeignKey("erp_operators.id", ondelete="RESTRICT"), primary_key=True
    )
    granted_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class DataSyncRun(Base):
    """One append-only execution record for a local data synchronization.

    The record deliberately stores only operational counters and safe status
    text.  Remote credentials, request/response payloads, raw workbooks and
    exception traces must never be copied here.  Source and actor snapshots
    keep historical records understandable after a source is renamed or an
    application user is removed.
    """

    __tablename__ = "data_sync_runs"
    __table_args__ = (
        Index("ix_data_sync_runs_source_requested", "source_id", "requested_at"),
        Index(
            "ix_data_sync_runs_business_status_requested",
            "business_type",
            "status",
            "requested_at",
        ),
        Index("ix_data_sync_runs_finished", "finished_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_configs.source_id", ondelete="SET NULL"),
        index=True,
    )
    source_display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    business_timezone: Mapped[str | None] = mapped_column(String(80))
    source_config_version: Mapped[int | None] = mapped_column(Integer)

    # The values are application-level enums so deployments can add a new
    # read-only source workflow without a destructive database enum change.
    business_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    operation_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="remote_sync")
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="automatic")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)

    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL"),
        index=True,
    )
    requested_by_display_name: Mapped[str | None] = mapped_column(String(120))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    window_start_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    query_range: Mapped[str | None] = mapped_column(String(64))
    page_size: Mapped[int | None] = mapped_column(Integer)

    remote_total: Mapped[int | None] = mapped_column(Integer)
    export_row_count: Mapped[int | None] = mapped_column(Integer)
    cached_total: Mapped[int | None] = mapped_column(Integer)
    fetched_pages: Mapped[int | None] = mapped_column(Integer)
    imported_count: Mapped[int | None] = mapped_column(Integer)
    created_count: Mapped[int | None] = mapped_column(Integer)
    updated_count: Mapped[int | None] = mapped_column(Integer)
    duplicate_count: Mapped[int | None] = mapped_column(Integer)
    matched_count: Mapped[int | None] = mapped_column(Integer)
    unmatched_count: Mapped[int | None] = mapped_column(Integer)
    resolved_uid_count: Mapped[int | None] = mapped_column(Integer)
    unresolved_uid_count: Mapped[int | None] = mapped_column(Integer)
    complete: Mapped[bool | None] = mapped_column(Boolean)

    # The raw score-review workbook is never stored.  Its optional file name
    # and size give the operator a useful, non-content trace of an import.
    input_filename: Mapped[str | None] = mapped_column(String(255))
    input_size_bytes: Mapped[int | None] = mapped_column(Integer)

    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class DataSyncRunEvent(Base):
    """Safe lifecycle event belonging to one :class:`DataSyncRun`."""

    __tablename__ = "data_sync_run_events"
    __table_args__ = (Index("ix_data_sync_run_events_run_occurred", "run_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("data_sync_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
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


class ErpOperator(Base):
    """A delivery company migrated from the ERP local business domain."""

    __tablename__ = "erp_operators"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    operator_type: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPANY")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", index=True)
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_value: Mapped[str | None] = mapped_column(String(200))
    remark: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ErpOperatorLine(Base):
    """A delivery line belonging to an :class:`ErpOperator`."""

    __tablename__ = "erp_operator_lines"
    __table_args__ = (
        UniqueConstraint("operator_id", "code", name="uq_erp_operator_line_code"),
        UniqueConstraint("operator_id", "name", name="uq_erp_operator_line_name"),
        Index("ix_erp_operator_line_operator_status", "operator_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    operator_id: Mapped[str] = mapped_column(
        ForeignKey("erp_operators.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    asset: Mapped[str] = mapped_column(String(10), nullable=False, default="USDT")
    network: Mapped[str | None] = mapped_column(String(120))
    wallet_address: Mapped[str | None] = mapped_column(String(500))
    start_date: Mapped[date | None] = mapped_column(Date)
    default_exchange_loss_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, default=Decimal("0.02")
    )
    default_exchange_loss_basis: Mapped[str] = mapped_column(
        String(30), nullable=False, default="TRANSFER"
    )
    default_service_fee_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, default=Decimal("0.02")
    )
    default_service_fee_basis: Mapped[str] = mapped_column(
        String(30), nullable=False, default="TRANSFER"
    )
    calculation_scale: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ErpDailyBalance(Base):
    """One local ERP daily ledger record for a delivery line and business date."""

    __tablename__ = "erp_daily_balances"
    __table_args__ = (
        UniqueConstraint(
            "operator_line_id",
            "business_date",
            name="uq_erp_daily_balance_line_date",
        ),
        Index("ix_erp_daily_balance_line_date", "operator_line_id", "business_date"),
        Index("ix_erp_daily_balance_date_status", "business_date", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    operator_line_id: Mapped[str] = mapped_column(
        ForeignKey("erp_operator_lines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(24, 8),
        nullable=False,
        default=Decimal("0"),
    )
    suggested_opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    opening_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="AUTO")
    opening_override_reason: Mapped[str | None] = mapped_column(String(500))
    transfer_amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 8),
        nullable=False,
        default=Decimal("0"),
    )
    fraud_loss_amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 8),
        nullable=False,
        default=Decimal("0"),
    )
    fraud_deduction_source: Mapped[str | None] = mapped_column(String(20))
    effective_transfer_amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 8), nullable=False, default=Decimal("0")
    )
    spend_amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 8),
        nullable=False,
        default=Decimal("0"),
    )
    exchange_loss_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, default=Decimal("0")
    )
    exchange_loss_basis: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="TRANSFER",
    )
    exchange_loss_auto_amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 8), nullable=False, default=Decimal("0")
    )
    exchange_loss_amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 8), nullable=False, default=Decimal("0")
    )
    exchange_loss_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="AUTO")
    exchange_loss_override_reason: Mapped[str | None] = mapped_column(String(500))
    service_fee_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, default=Decimal("0")
    )
    service_fee_basis: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="TRANSFER",
    )
    service_fee_auto_amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 8), nullable=False, default=Decimal("0")
    )
    service_fee_amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 8), nullable=False, default=Decimal("0")
    )
    service_fee_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="AUTO")
    service_fee_override_reason: Mapped[str | None] = mapped_column(String(500))
    reflux_amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 8),
        nullable=False,
        default=Decimal("0"),
    )
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 8),
        nullable=False,
        default=Decimal("0"),
    )
    other_deduction_amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 8), nullable=False, default=Decimal("0")
    )
    other_reason: Mapped[str | None] = mapped_column(String(500))
    closing_balance: Mapped[Decimal] = mapped_column(
        Numeric(24, 8),
        nullable=False,
        default=Decimal("0"),
    )
    calculation_scale: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", index=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")
    remark: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    @property
    def fraud_from_transfer(self) -> Decimal:
        if self.fraud_deduction_source == "TRANSFER":
            return self.fraud_loss_amount
        return Decimal("0")

    @property
    def fraud_from_balance(self) -> Decimal:
        if self.fraud_deduction_source == "BALANCE":
            return self.fraud_loss_amount
        return Decimal("0")


class ErpAccountingPeriodLock(Base):
    """A local monthly close lock for one ERP delivery line."""

    __tablename__ = "erp_accounting_period_locks"
    __table_args__ = (
        UniqueConstraint(
            "operator_line_id",
            "month_start",
            name="uq_erp_period_lock_line_month",
        ),
        Index("ix_erp_period_lock_month_status", "month_start", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    operator_line_id: Mapped[str] = mapped_column(
        ForeignKey("erp_operator_lines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    month_start: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="LOCKED")
    locked_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unlock_reason: Mapped[str | None] = mapped_column(String(500))
    unlocked_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ErpImportJob(Base):
    """A local ERP ledger import preview and its eventual commit result."""

    __tablename__ = "erp_import_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(500))
    file_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    source_storage_key: Mapped[str | None] = mapped_column(String(500))
    source_size_bytes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PREVIEW_READY")
    conflict_strategy: Mapped[str] = mapped_column(
        String(30), nullable=False, default="SKIP_EXISTING"
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    committed_by: Mapped[int | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL")
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ErpImportJobRow(Base):
    """One source row with an immutable normalized daily-balance snapshot."""

    __tablename__ = "erp_import_job_rows"
    __table_args__ = (
        Index("ix_erp_import_job_row_job_source", "import_job_id", "source_sheet", "source_row"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    import_job_id: Mapped[str] = mapped_column(
        ForeignKey("erp_import_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_sheet: Mapped[str | None] = mapped_column(String(200))
    source_row: Mapped[int | None] = mapped_column(Integer)
    source_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    normalized_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    operator_line_id: Mapped[str | None] = mapped_column(
        ForeignKey("erp_operator_lines.id", ondelete="SET NULL"), index=True
    )
    business_date: Mapped[date | None] = mapped_column(Date)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="OK")
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(1_000))
    action: Mapped[str | None] = mapped_column(String(30))
    target_daily_balance_id: Mapped[str | None] = mapped_column(
        ForeignKey("erp_daily_balances.id", ondelete="SET NULL")
    )
    preview_daily_balance_id: Mapped[str | None] = mapped_column(String(36))
    preview_row_version: Mapped[int | None] = mapped_column(Integer)


class ErpRedemptionCampaign(Base):
    """Local definition of a redemption-code campaign."""

    __tablename__ = "erp_redemption_campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    description: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ErpRedemptionCampaignTier(Base):
    """A deposit threshold and reward snapshot for a local campaign."""

    __tablename__ = "erp_redemption_campaign_tiers"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "min_deposit_amount",
            name="uq_erp_redemption_tier_deposit",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("erp_redemption_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(120))
    min_deposit_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    bonus_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    bonus_max_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ErpRedemptionTask(Base):
    """One local redemption task group spanning one or more market subtasks."""

    __tablename__ = "erp_redemption_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("erp_redemption_campaigns.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    task_name: Mapped[str] = mapped_column(String(200), nullable=False)
    claim_date_from: Mapped[date] = mapped_column(Date, nullable=False)
    claim_date_to: Mapped[date] = mapped_column(Date, nullable=False)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    export_group_key: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PLANNED")
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ErpRedemptionCodeBatch(Base):
    """A local task batch; it does not represent a remote publication."""

    __tablename__ = "erp_redemption_code_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("erp_redemption_campaigns.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("erp_redemption_tasks.id", ondelete="SET NULL"), index=True
    )
    remote_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("remote_accounts.id", ondelete="RESTRICT"), index=True
    )
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_configs.source_id", ondelete="RESTRICT"), index=True
    )
    execution_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    claim_date_from: Mapped[date] = mapped_column(Date, nullable=False)
    claim_date_to: Mapped[date] = mapped_column(Date, nullable=False)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_code_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PLANNED")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[int | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL")
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ErpRedemptionRemotePlan(Base):
    """Local snapshot and state machine for one future remote redemption workflow.

    The plan contains no password, TOTP value, bearer token, cookie or remote
    response payload. Credentials remain owned by the unified ``RemoteAccount``.
    """

    __tablename__ = "erp_redemption_remote_plans"
    __table_args__ = (
        Index(
            "ix_erp_redemption_remote_plan_status_schedule",
            "workflow_status",
            "scheduled_publish_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("erp_redemption_code_batches.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    remote_account_id: Mapped[str] = mapped_column(
        ForeignKey("remote_accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    redemption_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="SEVEN_DAY_DEPOSIT"
    )
    workflow_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="AWAITING_CREATE_AUTHORIZATION", index=True
    )

    publish_environment: Mapped[str] = mapped_column(String(20), nullable=False, default="test")
    flow_times: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    creation_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    activity_recharge: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    activity_recharge_count: Mapped[int | None] = mapped_column(Integer)
    activity_id: Mapped[int | None] = mapped_column(Integer)
    key_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    single_user_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    single_key_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)
    require_bind_bank_card: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    require_bind_phone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    check_uuid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    uuid_reward_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    check_login_ip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    login_ip_reward_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    check_register_ip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    register_ip_reward_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    publish_mode: Mapped[str | None] = mapped_column(String(20))
    scheduled_publish_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    fallback_to_scheduled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    publish_note: Mapped[str | None] = mapped_column(Text)
    remote_publish_task_id: Mapped[str | None] = mapped_column(String(255))
    schedule_cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    reserved_operation: Mapped[str | None] = mapped_column(String(20))
    reservation_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ErpRedemptionCodeIssue(Base):
    """A local redemption-code task and, when supplied, its imported code."""

    __tablename__ = "erp_redemption_code_issues"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "claim_date",
            "campaign_tier_id",
            name="uq_erp_redemption_issue",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("erp_redemption_campaigns.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    campaign_tier_id: Mapped[str] = mapped_column(
        ForeignKey("erp_redemption_campaign_tiers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("erp_redemption_code_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    claim_date: Mapped[date] = mapped_column(Date, nullable=False)
    deposit_window_start: Mapped[date] = mapped_column(Date, nullable=False)
    deposit_window_end: Mapped[date] = mapped_column(Date, nullable=False)
    tier_name: Mapped[str | None] = mapped_column(String(120))
    min_deposit_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    bonus_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    bonus_max_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    redemption_code: Mapped[str | None] = mapped_column(String(255), unique=True)
    local_reference: Mapped[str | None] = mapped_column(String(255))
    workflow_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING_LOCAL_CODE"
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remote_workflow_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="NOT_STARTED", index=True
    )
    remote_configuration_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    remote_group_key: Mapped[str | None] = mapped_column(String(255))
    remote_label_ids_json: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    remote_description: Mapped[str | None] = mapped_column(String(500))
    remote_error_code: Mapped[str | None] = mapped_column(String(80))
    remote_error_message: Mapped[str | None] = mapped_column(String(500))
    remote_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remote_downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ErpRedemptionRemoteExecution(Base):
    """A safe, append-only attempt record around a future adapter invocation."""

    __tablename__ = "erp_redemption_remote_executions"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "operation",
            "attempt_number",
            name="uq_erp_redemption_remote_execution_attempt",
        ),
        Index("ix_erp_redemption_remote_execution_plan_requested", "plan_id", "requested_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("erp_redemption_remote_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issue_id: Mapped[str | None] = mapped_column(
        ForeignKey("erp_redemption_code_issues.id", ondelete="SET NULL"), index=True
    )
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="RESERVED", index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reservation_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remote_request_id: Mapped[str | None] = mapped_column(String(120))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    result_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL")
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
