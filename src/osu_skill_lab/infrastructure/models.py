"""Compact immutable inputs and scalar results; never raw files or object arrays."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from osu_skill_lab.infrastructure.database import Base


class BeatmapInput(Base):
    __tablename__ = "beatmap_inputs"
    __table_args__ = (
        CheckConstraint("octet_length(source_sha256) = 32", name="sha256_length"),
        CheckConstraint("octet_length(source_md5) = 16", name="md5_length"),
        CheckConstraint("byte_size > 0", name="positive_size"),
        CheckConstraint("format_version > 0 AND ruleset = 0", name="supported_format_ruleset"),
        CheckConstraint(
            "claimed_beatmap_id IS NULL OR claimed_beatmap_id > 0", name="positive_map_id"
        ),
        CheckConstraint(
            "claimed_beatmap_set_id IS NULL OR claimed_beatmap_set_id > 0", name="positive_set_id"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_sha256: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    source_md5: Mapped[bytes] = mapped_column(LargeBinary, index=True)
    byte_size: Mapped[int] = mapped_column(Integer)
    format_version: Mapped[int] = mapped_column(SmallInteger)
    ruleset: Mapped[int] = mapped_column(SmallInteger)
    claimed_beatmap_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    claimed_beatmap_set_id: Mapped[int | None] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(512))
    artist: Mapped[str] = mapped_column(String(512))
    creator: Mapped[str] = mapped_column(String(256))
    difficulty_name: Mapped[str] = mapped_column(String(512))
    metadata_parser_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    __table_args__ = (
        UniqueConstraint(
            "input_id",
            "algorithm_version",
            "parser_version",
            "configuration_sha256",
            name="uq_analysis_results_identity",
        ),
        CheckConstraint("octet_length(configuration_sha256) = 32", name="config_hash_length"),
        CheckConstraint(
            "jsonb_typeof(configuration) = 'object' AND octet_length(configuration::text) <= 4096",
            name="bounded_configuration",
        ),
        CheckConstraint(
            "hit_object_count = circle_count + slider_count + spinner_count "
            "AND circle_count >= 0 AND slider_count >= 0 AND spinner_count >= 0",
            name="object_counts",
        ),
        CheckConstraint(
            "timing_point_count = red_timing_point_count + inherited_timing_point_count "
            "AND red_timing_point_count >= 1 AND inherited_timing_point_count >= 0",
            name="timing_counts",
        ),
        CheckConstraint(
            "head_object_count = circle_count + slider_count "
            "AND head_pair_count = greatest(head_object_count - 1, 0) "
            "AND zero_head_interval_count BETWEEN 0 AND head_pair_count",
            name="head_counts",
        ),
        CheckConstraint(
            "hp_drain_rate BETWEEN 0 AND 10 AND circle_size BETWEEN 0 AND 10 "
            "AND overall_difficulty BETWEEN 0 AND 10 AND approach_rate BETWEEN 0 AND 10 "
            "AND stack_leniency BETWEEN 0 AND 1 "
            "AND slider_multiplier > 0 AND slider_multiplier <= 1e12 "
            "AND slider_tick_rate > 0 AND slider_tick_rate <= 1e12",
            name="difficulty_ranges",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    input_id: Mapped[int] = mapped_column(ForeignKey("beatmap_inputs.id", ondelete="RESTRICT"))
    algorithm_version: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[dict[str, object]] = mapped_column(JSONB)
    configuration_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    hp_drain_rate: Mapped[float] = mapped_column(Float)
    circle_size: Mapped[float] = mapped_column(Float)
    overall_difficulty: Mapped[float] = mapped_column(Float)
    approach_rate: Mapped[float] = mapped_column(Float)
    slider_multiplier: Mapped[float] = mapped_column(Float)
    slider_tick_rate: Mapped[float] = mapped_column(Float)
    stack_leniency: Mapped[float] = mapped_column(Float)
    hit_object_count: Mapped[int] = mapped_column(Integer)
    circle_count: Mapped[int] = mapped_column(Integer)
    slider_count: Mapped[int] = mapped_column(Integer)
    spinner_count: Mapped[int] = mapped_column(Integer)
    timing_point_count: Mapped[int] = mapped_column(Integer)
    red_timing_point_count: Mapped[int] = mapped_column(Integer)
    inherited_timing_point_count: Mapped[int] = mapped_column(Integer)
    red_bpm_min: Mapped[float | None] = mapped_column(Float)
    red_bpm_max: Mapped[float | None] = mapped_column(Float)
    first_object_start_ms: Mapped[float | None] = mapped_column(Float)
    last_object_start_ms: Mapped[float | None] = mapped_column(Float)
    object_start_span_ms: Mapped[float | None] = mapped_column(Float)
    head_object_count: Mapped[int] = mapped_column(Integer)
    head_pair_count: Mapped[int] = mapped_column(Integer)
    head_interval_min_ms: Mapped[float | None] = mapped_column(Float)
    head_interval_max_ms: Mapped[float | None] = mapped_column(Float)
    head_interval_mean_ms: Mapped[float | None] = mapped_column(Float)
    head_interval_median_ms: Mapped[float | None] = mapped_column(Float)
    zero_head_interval_count: Mapped[int] = mapped_column(Integer)
    raw_head_distance_min_px: Mapped[float | None] = mapped_column(Float)
    raw_head_distance_max_px: Mapped[float | None] = mapped_column(Float)
    raw_head_distance_mean_px: Mapped[float | None] = mapped_column(Float)
