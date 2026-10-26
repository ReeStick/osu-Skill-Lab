"""Durable job state and delivery intent; no source files or object arrays."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from osu_skill_lab.infrastructure.database import Base


class AnalysisBatch(Base):
    __tablename__ = "analysis_batches"
    __table_args__ = (
        CheckConstraint("octet_length(request_sha256) = 32", name="request_hash_length"),
        CheckConstraint("octet_length(configuration_sha256) = 32", name="config_hash_length"),
        CheckConstraint("provider = 'hinamizawa'", name="known_provider"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid, unique=True)
    request_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    provider: Mapped[str] = mapped_column(String(32))
    algorithm_version: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(64))
    configuration_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        UniqueConstraint("batch_id", "beatmap_id", name="uq_analysis_jobs_batch_map"),
        UniqueConstraint("batch_id", "position", name="uq_analysis_jobs_batch_position"),
        CheckConstraint("beatmap_id > 0 AND position BETWEEN 0 AND 99", name="valid_item"),
        CheckConstraint("attempts BETWEEN 0 AND 5", name="bounded_attempts"),
        CheckConstraint(
            "status IN ('queued','running','retry_wait','succeeded','failed','cancelled')",
            name="known_status",
        ),
        CheckConstraint(
            "(status = 'running') = (lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "AND ((lease_token IS NULL) = (lease_until IS NULL))",
            name="lease_state",
        ),
        CheckConstraint("(status = 'succeeded') = (analysis_id IS NOT NULL)", name="result_state"),
        CheckConstraint(
            "expected_sha256 IS NULL OR octet_length(expected_sha256) = 32",
            name="pin_length",
        ),
        CheckConstraint(
            "observed_sha256 IS NULL OR octet_length(observed_sha256) = 32",
            name="observed_length",
        ),
        Index("ix_analysis_jobs_delivery", "status", "run_after", "delivery_after"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_batches.id", ondelete="RESTRICT"))
    position: Mapped[int] = mapped_column(Integer)
    beatmap_id: Mapped[int] = mapped_column(BigInteger)
    expected_sha256: Mapped[bytes | None] = mapped_column(LargeBinary)
    observed_sha256: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivery_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_results.id", ondelete="RESTRICT"),
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(256))


class ProviderBudget(Base):
    __tablename__ = "provider_budgets"
    __table_args__ = (CheckConstraint("provider = 'hinamizawa'", name="known_provider"),)

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    next_request_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    blocked_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
