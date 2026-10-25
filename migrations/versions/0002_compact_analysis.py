"""add compact inputs and scalar analysis results

Revision ID: 0002_compact_analysis
Revises: 0001_foundation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_compact_analysis"
down_revision: str | Sequence[str] | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "beatmap_inputs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("source_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("source_md5", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("format_version", sa.SmallInteger(), nullable=False),
        sa.Column("ruleset", sa.SmallInteger(), nullable=False),
        sa.Column("claimed_beatmap_id", sa.BigInteger(), nullable=True),
        sa.Column("claimed_beatmap_set_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("artist", sa.String(length=512), nullable=False),
        sa.Column("creator", sa.String(length=256), nullable=False),
        sa.Column("difficulty_name", sa.String(length=512), nullable=False),
        sa.Column("metadata_parser_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("byte_size > 0", name=op.f("ck_beatmap_inputs_positive_size")),
        sa.CheckConstraint(
            "claimed_beatmap_id IS NULL OR claimed_beatmap_id > 0",
            name=op.f("ck_beatmap_inputs_positive_map_id"),
        ),
        sa.CheckConstraint(
            "claimed_beatmap_set_id IS NULL OR claimed_beatmap_set_id > 0",
            name=op.f("ck_beatmap_inputs_positive_set_id"),
        ),
        sa.CheckConstraint(
            "format_version > 0 AND ruleset = 0",
            name=op.f("ck_beatmap_inputs_supported_format_ruleset"),
        ),
        sa.CheckConstraint(
            "octet_length(source_md5) = 16", name=op.f("ck_beatmap_inputs_md5_length")
        ),
        sa.CheckConstraint(
            "octet_length(source_sha256) = 32", name=op.f("ck_beatmap_inputs_sha256_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_beatmap_inputs")),
        sa.UniqueConstraint("source_sha256", name=op.f("uq_beatmap_inputs_source_sha256")),
    )
    op.create_index(
        op.f("ix_beatmap_inputs_claimed_beatmap_id"),
        "beatmap_inputs",
        ["claimed_beatmap_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_beatmap_inputs_source_md5"), "beatmap_inputs", ["source_md5"], unique=False
    )
    op.create_table(
        "analysis_results",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("input_id", sa.BigInteger(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("configuration_sha256", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("hp_drain_rate", sa.Float(), nullable=False),
        sa.Column("circle_size", sa.Float(), nullable=False),
        sa.Column("overall_difficulty", sa.Float(), nullable=False),
        sa.Column("approach_rate", sa.Float(), nullable=False),
        sa.Column("slider_multiplier", sa.Float(), nullable=False),
        sa.Column("slider_tick_rate", sa.Float(), nullable=False),
        sa.Column("stack_leniency", sa.Float(), nullable=False),
        sa.Column("hit_object_count", sa.Integer(), nullable=False),
        sa.Column("circle_count", sa.Integer(), nullable=False),
        sa.Column("slider_count", sa.Integer(), nullable=False),
        sa.Column("spinner_count", sa.Integer(), nullable=False),
        sa.Column("timing_point_count", sa.Integer(), nullable=False),
        sa.Column("red_timing_point_count", sa.Integer(), nullable=False),
        sa.Column("inherited_timing_point_count", sa.Integer(), nullable=False),
        sa.Column("red_bpm_min", sa.Float(), nullable=True),
        sa.Column("red_bpm_max", sa.Float(), nullable=True),
        sa.Column("first_object_start_ms", sa.Float(), nullable=True),
        sa.Column("last_object_start_ms", sa.Float(), nullable=True),
        sa.Column("object_start_span_ms", sa.Float(), nullable=True),
        sa.Column("head_object_count", sa.Integer(), nullable=False),
        sa.Column("head_pair_count", sa.Integer(), nullable=False),
        sa.Column("head_interval_min_ms", sa.Float(), nullable=True),
        sa.Column("head_interval_max_ms", sa.Float(), nullable=True),
        sa.Column("head_interval_mean_ms", sa.Float(), nullable=True),
        sa.Column("head_interval_median_ms", sa.Float(), nullable=True),
        sa.Column("zero_head_interval_count", sa.Integer(), nullable=False),
        sa.Column("raw_head_distance_min_px", sa.Float(), nullable=True),
        sa.Column("raw_head_distance_max_px", sa.Float(), nullable=True),
        sa.Column("raw_head_distance_mean_px", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "jsonb_typeof(configuration) = 'object' AND octet_length(configuration::text) <= 4096",
            name=op.f("ck_analysis_results_bounded_configuration"),
        ),
        sa.CheckConstraint(
            "head_object_count = circle_count + slider_count "
            "AND head_pair_count = greatest(head_object_count - 1, 0) "
            "AND zero_head_interval_count BETWEEN 0 AND head_pair_count",
            name=op.f("ck_analysis_results_head_counts"),
        ),
        sa.CheckConstraint(
            "hit_object_count = circle_count + slider_count + spinner_count "
            "AND circle_count >= 0 AND slider_count >= 0 AND spinner_count >= 0",
            name=op.f("ck_analysis_results_object_counts"),
        ),
        sa.CheckConstraint(
            "hp_drain_rate BETWEEN 0 AND 10 AND circle_size BETWEEN 0 AND 10 "
            "AND overall_difficulty BETWEEN 0 AND 10 AND approach_rate BETWEEN 0 AND 10 "
            "AND stack_leniency BETWEEN 0 AND 1 "
            "AND slider_multiplier > 0 AND slider_multiplier <= 1e12 "
            "AND slider_tick_rate > 0 AND slider_tick_rate <= 1e12",
            name=op.f("ck_analysis_results_difficulty_ranges"),
        ),
        sa.CheckConstraint(
            "octet_length(configuration_sha256) = 32",
            name=op.f("ck_analysis_results_config_hash_length"),
        ),
        sa.CheckConstraint(
            "timing_point_count = red_timing_point_count + inherited_timing_point_count "
            "AND red_timing_point_count >= 1 AND inherited_timing_point_count >= 0",
            name=op.f("ck_analysis_results_timing_counts"),
        ),
        sa.ForeignKeyConstraint(
            ["input_id"],
            ["beatmap_inputs.id"],
            name=op.f("fk_analysis_results_input_id_beatmap_inputs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_results")),
        sa.UniqueConstraint(
            "input_id",
            "algorithm_version",
            "parser_version",
            "configuration_sha256",
            name="uq_analysis_results_identity",
        ),
    )


def downgrade() -> None:
    op.drop_table("analysis_results")
    op.drop_index(op.f("ix_beatmap_inputs_source_md5"), table_name="beatmap_inputs")
    op.drop_index(op.f("ix_beatmap_inputs_claimed_beatmap_id"), table_name="beatmap_inputs")
    op.drop_table("beatmap_inputs")
