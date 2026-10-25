"""add versioned download provenance

Revision ID: 0004_sources
Revises: 0003_osu_metadata
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_sources"
down_revision: str | Sequence[str] | None = "0003_osu_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "beatmap_sources",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("input_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("requested_beatmap_id", sa.BigInteger(), nullable=False),
        sa.Column("metadata_beatmap_set_id", sa.BigInteger(), nullable=False),
        sa.Column("metadata_md5", sa.LargeBinary(), nullable=False),
        sa.Column("adapter_version", sa.String(length=64), nullable=False),
        sa.Column("metadata_schema_version", sa.String(length=64), nullable=False),
        sa.Column("metadata_last_updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("file_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_source_layer", sa.String(length=64), nullable=True),
        sa.Column("file_source_layer", sa.String(length=64), nullable=True),
        sa.Column("metadata_freshness", sa.String(length=64), nullable=True),
        sa.Column("http_etag", sa.String(length=512), nullable=True),
        sa.CheckConstraint(
            "provider = 'hinamizawa'", name=op.f("ck_beatmap_sources_known_provider")
        ),
        sa.CheckConstraint(
            "octet_length(metadata_md5) = 16", name=op.f("ck_beatmap_sources_md5_length")
        ),
        sa.CheckConstraint(
            "requested_beatmap_id > 0 AND metadata_beatmap_set_id > 0",
            name=op.f("ck_beatmap_sources_positive_ids"),
        ),
        sa.ForeignKeyConstraint(
            ["input_id"],
            ["beatmap_inputs.id"],
            name=op.f("fk_beatmap_sources_input_id_beatmap_inputs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_beatmap_sources")),
        sa.UniqueConstraint(
            "input_id",
            "provider",
            "requested_beatmap_id",
            "adapter_version",
            "metadata_schema_version",
            name="uq_beatmap_sources_observation",
        ),
    )
    op.create_index(
        op.f("ix_beatmap_sources_requested_beatmap_id"),
        "beatmap_sources",
        ["requested_beatmap_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_beatmap_sources_requested_beatmap_id"), table_name="beatmap_sources")
    op.drop_table("beatmap_sources")
