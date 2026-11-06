"""Local claim snapshots for the existing numeric-ID ERP task namespace."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from packages.domain.models.entities import Base, new_uuid, utcnow


class RedemptionClaimGroup(Base):
    __tablename__ = "erp_redemption_claim_groups"
    __table_args__ = (
        UniqueConstraint("source_id", "group_key", name="uq_claim_group_source_key"),
        Index("ix_claim_group_task", "task_id", "issue_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    issue_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    batch_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    account_projection_id: Mapped[int | None] = mapped_column(BigInteger)
    configuration_id: Mapped[str | None] = mapped_column(String(255))
    group_key: Mapped[str | None] = mapped_column(String(255))
    column_key: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))


class RedemptionClaimRecord(Base):
    __tablename__ = "erp_redemption_claim_records"
    __table_args__ = (Index("ix_claim_record_day_code", "group_id", "claim_date", "code"),)
    group_id: Mapped[str] = mapped_column(
        ForeignKey("erp_redemption_claim_groups.id"), primary_key=True
    )
    remote_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    code: Mapped[str] = mapped_column(String(255), nullable=False)
    uid: Mapped[str] = mapped_column(String(100), nullable=False)
    receive_time: Mapped[str] = mapped_column(String(40), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claim_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    gift_type: Mapped[int] = mapped_column(Integer, nullable=False)


class RedemptionClaimDaily(Base):
    __tablename__ = "erp_redemption_claim_daily"
    group_id: Mapped[str] = mapped_column(
        ForeignKey("erp_redemption_claim_groups.id"), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(255), primary_key=True)
    claim_date: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False)


class RedemptionClaimSchedule(Base):
    __tablename__ = "erp_redemption_claim_schedules"
    __table_args__ = (
        CheckConstraint(
            "interval_minutes in (30,60,120,180,360,720,1440)", name="ck_claim_interval"
        ),
    )
    task_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actor_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_run_id: Mapped[str | None] = mapped_column(String(36))


class RedemptionClaimRun(Base):
    __tablename__ = "erp_redemption_claim_runs"
    __table_args__ = (Index("ix_claim_run_task_created", "task_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class RedemptionClaimLease(Base):
    __tablename__ = "erp_redemption_claim_leases"
    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token: Mapped[str] = mapped_column(String(36), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
