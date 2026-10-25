"""add checksum matched osu metadata

Revision ID: 0003_osu_metadata
Revises: 0002_compact_analysis
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_osu_metadata"
down_revision: str | Sequence[str] | None = "0002_compact_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "osu_beatmap_matches",
        sa.Column("input_id", sa.BigInteger(), nullable=False),
        sa.Column("beatmap_id", sa.BigInteger(), nullable=False),
        sa.Column("beatmap_set_id", sa.BigInteger(), nullable=False),
        sa.Column("source_md5", sa.LargeBinary(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("artist", sa.String(length=512), nullable=False),
        sa.Column("set_creator", sa.String(length=256), nullable=False),
        sa.Column("creator_id", sa.BigInteger(), nullable=False),
        sa.Column("difficulty_name", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("api_response_version", sa.String(length=16), nullable=False),
        sa.Column("metadata_schema_version", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "beatmap_id > 0 AND beatmap_set_id > 0 AND creator_id > 0",
            name=op.f("ck_osu_beatmap_matches_positive_ids"),
        ),
        sa.CheckConstraint(
            "octet_length(source_md5) = 16", name=op.f("ck_osu_beatmap_matches_md5_length")
        ),
        sa.ForeignKeyConstraint(
            ["input_id"],
            ["beatmap_inputs.id"],
            name=op.f("fk_osu_beatmap_matches_input_id_beatmap_inputs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("input_id", name=op.f("pk_osu_beatmap_matches")),
    )
    op.create_index(
        op.f("ix_osu_beatmap_matches_beatmap_id"),
        "osu_beatmap_matches",
        ["beatmap_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_osu_beatmap_matches_beatmap_id"), table_name="osu_beatmap_matches")
    op.drop_table("osu_beatmap_matches")
