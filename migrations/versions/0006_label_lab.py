"""add label workbench decisions rules and model lineage

Revision ID: 0006_label_lab
Revises: 0005_batch_jobs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_label_lab"
down_revision: str | Sequence[str] | None = "0005_batch_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lab_tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("canonical_name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.String(length=2048), nullable=False),
        sa.Column("definition_sha256", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(definition_sha256) = 32", name=op.f("ck_lab_tags_definition_hash")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_tags")),
        sa.UniqueConstraint("canonical_name", name=op.f("uq_lab_tags_canonical_name")),
    )
    op.create_table(
        "lab_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("training_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("train_count", sa.Integer(), nullable=False),
        sa.Column("validation_count", sa.Integer(), nullable=False),
        sa.Column("excluded_same_set", sa.Integer(), nullable=False),
        sa.Column("latest_event_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(artifact_sha256) = 32 AND octet_length(training_sha256) = 32",
            name=op.f("ck_lab_models_hashes"),
        ),
        sa.CheckConstraint(
            "train_count >= 4 AND validation_count >= 0 AND excluded_same_set >= 0",
            name=op.f("ck_lab_models_counts"),
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["lab_tags.id"],
            name=op.f("fk_lab_models_tag_id_lab_tags"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_models")),
    )
    op.create_index(op.f("ix_lab_models_tag_id"), "lab_models", ["tag_id"], unique=False)
    op.create_table(
        "lab_label_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("input_id", sa.BigInteger(), nullable=False),
        sa.Column("analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("value", sa.String(length=16), nullable=False),
        sa.Column("partition", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "partition IN ('train','validation')", name=op.f("ck_lab_label_events_known_partition")
        ),
        sa.CheckConstraint(
            "value IN ('yes','no','unsure','unreviewed')",
            name=op.f("ck_lab_label_events_known_value"),
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analysis_results.id"],
            name=op.f("fk_lab_label_events_analysis_id_analysis_results"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["input_id"],
            ["beatmap_inputs.id"],
            name=op.f("fk_lab_label_events_input_id_beatmap_inputs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["lab_tags.id"],
            name=op.f("fk_lab_label_events_tag_id_lab_tags"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_label_events")),
    )
    op.create_index(
        "ix_lab_label_latest", "lab_label_events", ["tag_id", "input_id", "id"], unique=False
    )
    op.create_table(
        "lab_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=True),
        sa.Column("configuration_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("specification", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(specification) = 'object' AND octet_length(specification::text) <= 8192",
            name=op.f("ck_lab_rules_bounded_specification"),
        ),
        sa.CheckConstraint(
            "octet_length(configuration_sha256) = 32", name=op.f("ck_lab_rules_config_hash")
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["lab_models.id"],
            name=op.f("fk_lab_rules_model_id_lab_models"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["lab_tags.id"],
            name=op.f("fk_lab_rules_tag_id_lab_tags"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_rules")),
    )
    op.create_index(op.f("ix_lab_rules_tag_id"), "lab_rules", ["tag_id"], unique=False)
    op.create_table(
        "lab_model_examples",
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("label_event_id", sa.BigInteger(), nullable=False),
        sa.Column("partition", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "partition IN ('train','validation')",
            name=op.f("ck_lab_model_examples_known_partition"),
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analysis_results.id"],
            name=op.f("fk_lab_model_examples_analysis_id_analysis_results"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["label_event_id"],
            ["lab_label_events.id"],
            name=op.f("fk_lab_model_examples_label_event_id_lab_label_events"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["lab_models.id"],
            name=op.f("fk_lab_model_examples_model_id_lab_models"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("model_id", "analysis_id", name=op.f("pk_lab_model_examples")),
    )


def downgrade() -> None:
    op.drop_table("lab_model_examples")
    op.drop_index(op.f("ix_lab_rules_tag_id"), table_name="lab_rules")
    op.drop_table("lab_rules")
    op.drop_index("ix_lab_label_latest", table_name="lab_label_events")
    op.drop_table("lab_label_events")
    op.drop_index(op.f("ix_lab_models_tag_id"), table_name="lab_models")
    op.drop_table("lab_models")
    op.drop_table("lab_tags")
