"""add durable batch jobs and shared mirror budget

Revision ID: 0005_batch_jobs
Revises: 0004_sources
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_batch_jobs"
down_revision: str | Sequence[str] | None = "0004_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("configuration_sha256", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider = 'hinamizawa'", name=op.f("ck_analysis_batches_known_provider")
        ),
        sa.CheckConstraint(
            "octet_length(configuration_sha256) = 32",
            name=op.f("ck_analysis_batches_config_hash_length"),
        ),
        sa.CheckConstraint(
            "octet_length(request_sha256) = 32",
            name=op.f("ck_analysis_batches_request_hash_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_batches")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_analysis_batches_idempotency_key")),
    )
    op.create_table(
        "provider_budgets",
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("next_request_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider = 'hinamizawa'", name=op.f("ck_provider_budgets_known_provider")
        ),
        sa.PrimaryKeyConstraint("provider", name=op.f("pk_provider_budgets")),
    )
    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("beatmap_id", sa.BigInteger(), nullable=False),
        sa.Column("expected_sha256", sa.LargeBinary(), nullable=True),
        sa.Column("observed_sha256", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "delivery_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("analysis_id", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=256), nullable=True),
        sa.CheckConstraint(
            "(status = 'running') = (lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "AND ((lease_token IS NULL) = (lease_until IS NULL))",
            name=op.f("ck_analysis_jobs_lease_state"),
        ),
        sa.CheckConstraint(
            "(status = 'succeeded') = (analysis_id IS NOT NULL)",
            name=op.f("ck_analysis_jobs_result_state"),
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','retry_wait','succeeded','failed','cancelled')",
            name=op.f("ck_analysis_jobs_known_status"),
        ),
        sa.CheckConstraint(
            "attempts BETWEEN 0 AND 5", name=op.f("ck_analysis_jobs_bounded_attempts")
        ),
        sa.CheckConstraint(
            "beatmap_id > 0 AND position BETWEEN 0 AND 99", name=op.f("ck_analysis_jobs_valid_item")
        ),
        sa.CheckConstraint(
            "expected_sha256 IS NULL OR octet_length(expected_sha256) = 32",
            name=op.f("ck_analysis_jobs_pin_length"),
        ),
        sa.CheckConstraint(
            "observed_sha256 IS NULL OR octet_length(observed_sha256) = 32",
            name=op.f("ck_analysis_jobs_observed_length"),
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analysis_results.id"],
            name=op.f("fk_analysis_jobs_analysis_id_analysis_results"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["analysis_batches.id"],
            name=op.f("fk_analysis_jobs_batch_id_analysis_batches"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_jobs")),
        sa.UniqueConstraint("batch_id", "beatmap_id", name="uq_analysis_jobs_batch_map"),
        sa.UniqueConstraint("batch_id", "position", name="uq_analysis_jobs_batch_position"),
    )
    op.create_index(
        "ix_analysis_jobs_delivery",
        "analysis_jobs",
        ["status", "run_after", "delivery_after"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_jobs_delivery", table_name="analysis_jobs")
    op.drop_table("analysis_jobs")
    op.drop_table("provider_budgets")
    op.drop_table("analysis_batches")
