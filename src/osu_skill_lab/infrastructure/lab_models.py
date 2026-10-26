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
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from osu_skill_lab.infrastructure.database import Base


class LabTag(Base):
    __tablename__ = "lab_tags"
    __table_args__ = (
        CheckConstraint("octet_length(definition_sha256) = 32", name="definition_hash"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    canonical_name: Mapped[str] = mapped_column(String(256), unique=True)
    description: Mapped[str] = mapped_column(String(2048))
    definition_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LabLabelEvent(Base):
    __tablename__ = "lab_label_events"
    __table_args__ = (
        CheckConstraint("value IN ('yes','no','unsure','unreviewed')", name="known_value"),
        CheckConstraint("partition IN ('train','validation')", name="known_partition"),
        Index("ix_lab_label_latest", "tag_id", "input_id", "id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tag_id: Mapped[UUID] = mapped_column(ForeignKey("lab_tags.id", ondelete="RESTRICT"))
    input_id: Mapped[int] = mapped_column(ForeignKey("beatmap_inputs.id", ondelete="RESTRICT"))
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis_results.id", ondelete="RESTRICT"))
    value: Mapped[str] = mapped_column(String(16))
    partition: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LabModel(Base):
    __tablename__ = "lab_models"
    __table_args__ = (
        CheckConstraint(
            "octet_length(artifact_sha256) = 32 AND octet_length(training_sha256) = 32",
            name="hashes",
        ),
        CheckConstraint(
            "train_count >= 4 AND validation_count >= 0 AND excluded_same_set >= 0", name="counts"
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tag_id: Mapped[UUID] = mapped_column(ForeignKey("lab_tags.id", ondelete="RESTRICT"), index=True)
    artifact_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    training_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    train_count: Mapped[int] = mapped_column(Integer)
    validation_count: Mapped[int] = mapped_column(Integer)
    excluded_same_set: Mapped[int] = mapped_column(Integer)
    latest_event_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LabModelExample(Base):
    __tablename__ = "lab_model_examples"
    __table_args__ = (
        CheckConstraint("partition IN ('train','validation')", name="known_partition"),
    )
    model_id: Mapped[UUID] = mapped_column(
        ForeignKey("lab_models.id", ondelete="RESTRICT"), primary_key=True
    )
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_results.id", ondelete="RESTRICT"), primary_key=True
    )
    label_event_id: Mapped[int] = mapped_column(
        ForeignKey("lab_label_events.id", ondelete="RESTRICT")
    )
    partition: Mapped[str] = mapped_column(String(16))


class LabRule(Base):
    __tablename__ = "lab_rules"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(specification) = 'object' AND octet_length(specification::text) <= 8192",
            name="bounded_specification",
        ),
        CheckConstraint("octet_length(configuration_sha256) = 32", name="config_hash"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tag_id: Mapped[UUID] = mapped_column(ForeignKey("lab_tags.id", ondelete="RESTRICT"), index=True)
    model_id: Mapped[UUID | None] = mapped_column(ForeignKey("lab_models.id", ondelete="RESTRICT"))
    configuration_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    specification: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
