"""PostgreSQL is authoritative for acceptance, retries and fenced job ownership."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from osu_skill_lab.application.batches import (
    TERMINAL,
    BatchCapacityError,
    BatchConflict,
    BatchItemView,
    BatchRequest,
    BatchView,
)
from osu_skill_lab.application.preparation import pipeline_identity
from osu_skill_lab.infrastructure.job_models import AnalysisBatch, AnalysisJob

LEASE_SECONDS = 90
MAX_ATTEMPTS = 5
MAX_ACTIVE_JOBS = 1000


async def get_batch(session: AsyncSession, batch_id: UUID) -> BatchView | None:
    batch = await session.get(AnalysisBatch, batch_id)
    if batch is None:
        return None
    rows = list(
        await session.scalars(
            select(AnalysisJob)
            .where(AnalysisJob.batch_id == batch_id)
            .order_by(AnalysisJob.position)
        )
    )
    counts = {
        name: sum(row.status == name for row in rows)
        for name in (
            "queued",
            "running",
            "retry_wait",
            "succeeded",
            "failed",
            "cancelled",
        )
    }
    if any(row.status not in TERMINAL for row in rows):
        status = "running" if counts["running"] else "pending"
    elif counts["cancelled"]:
        status = "cancelled"
    elif counts["failed"]:
        status = "completed_with_errors" if counts["succeeded"] else "failed"
    else:
        status = "completed"
    return BatchView(
        id=batch.id,
        provider=batch.provider,
        status=status,
        created_at=batch.created_at,
        cancel_requested_at=batch.cancel_requested_at,
        algorithm_version=batch.algorithm_version,
        parser_version=batch.parser_version,
        configuration_sha256=batch.configuration_sha256.hex(),
        counts=counts,
        items=[
            BatchItemView(
                id=row.id,
                beatmap_id=row.beatmap_id,
                status=row.status,
                attempts=row.attempts,
                expected_sha256=row.expected_sha256.hex() if row.expected_sha256 else None,
                observed_sha256=row.observed_sha256.hex() if row.observed_sha256 else None,
                analysis_id=row.analysis_id,
                next_attempt_at=row.run_after if row.status == "retry_wait" else None,
                error_code=row.error_code,
                error_message=row.error_message,
            )
            for row in rows
        ],
    )


async def submit(session: AsyncSession, request: BatchRequest, key: UUID) -> BatchView:
    # Global admission serialization; also makes concurrent idempotency replays atomic.
    await session.execute(text("SELECT pg_advisory_xact_lock(73519241)"))
    existing = await session.scalar(
        select(AnalysisBatch).where(AnalysisBatch.idempotency_key == key)
    )
    fingerprint = request.fingerprint()
    if existing is not None:
        if existing.request_sha256 != fingerprint:
            raise BatchConflict("Idempotency key belongs to a different request")
        result = await get_batch(session, existing.id)
        assert result is not None
        return result
    active = await session.scalar(
        select(func.count()).select_from(AnalysisJob).where(AnalysisJob.status.not_in(TERMINAL))
    )
    if (active or 0) + len(request.items) > MAX_ACTIVE_JOBS:
        raise BatchCapacityError("Active batch item capacity is full")
    algorithm, parser, config = pipeline_identity()
    batch = AnalysisBatch(
        id=uuid4(),
        idempotency_key=key,
        request_sha256=fingerprint,
        provider=request.provider,
        algorithm_version=algorithm,
        parser_version=parser,
        configuration_sha256=config,
    )
    session.add(batch)
    await session.flush()
    session.add_all(
        [
            AnalysisJob(
                batch_id=batch.id,
                position=position,
                beatmap_id=item.beatmap_id,
                expected_sha256=bytes.fromhex(item.expected_sha256)
                if item.expected_sha256
                else None,
            )
            for position, item in enumerate(request.items)
        ]
    )
    await session.flush()
    result = await get_batch(session, batch.id)
    assert result is not None
    return result


async def cancel(session: AsyncSession, batch_id: UUID) -> None:
    # Serialize cancellation with claim (batch lock is always acquired first).
    batch = await session.scalar(
        select(AnalysisBatch).where(AnalysisBatch.id == batch_id).with_for_update()
    )
    if batch is None:
        return
    if batch.cancel_requested_at is None:
        batch.cancel_requested_at = await session.scalar(select(func.clock_timestamp()))
    await session.execute(
        update(AnalysisJob)
        .where(
            AnalysisJob.batch_id == batch_id,
            AnalysisJob.status.not_in(TERMINAL),
        )
        .values(status="cancelled", lease_token=None, lease_until=None)
    )


@dataclass(frozen=True)
class ClaimedJob:
    id: int
    batch_id: UUID
    beatmap_id: int
    token: UUID
    expected_sha256: str | None
    identity: tuple[str, str, bytes]


async def claim(session: AsyncSession, job_id: int) -> ClaimedJob | None:
    batch_id = await session.scalar(select(AnalysisJob.batch_id).where(AnalysisJob.id == job_id))
    if batch_id is None:
        return None
    batch = await session.scalar(
        select(AnalysisBatch).where(AnalysisBatch.id == batch_id).with_for_update()
    )
    assert batch is not None
    row = await session.scalar(
        select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
    )
    assert row is not None
    now = await session.scalar(select(func.clock_timestamp()))
    assert now is not None
    if (
        batch.cancel_requested_at
        or row.status not in {"queued", "retry_wait"}
        or row.run_after > now
    ):
        return None
    if row.attempts >= MAX_ATTEMPTS:
        return None
    row.status, row.lease_token, row.lease_until = (
        "running",
        uuid4(),
        now + timedelta(seconds=LEASE_SECONDS),
    )
    row.attempts += 1
    digest = row.observed_sha256 or row.expected_sha256
    return ClaimedJob(
        row.id,
        row.batch_id,
        row.beatmap_id,
        row.lease_token,
        digest.hex() if digest else None,
        (batch.algorithm_version, batch.parser_version, batch.configuration_sha256),
    )


async def heartbeat(session: AsyncSession, job: ClaimedJob) -> bool:
    result = await session.scalar(
        update(AnalysisJob)
        .where(
            AnalysisJob.id == job.id,
            AnalysisJob.status == "running",
            AnalysisJob.lease_token == job.token,
            AnalysisJob.lease_until > func.clock_timestamp(),
        )
        .values(lease_until=func.clock_timestamp() + timedelta(seconds=LEASE_SECONDS))
        .returning(AnalysisJob.id)
    )
    return result is not None


async def pin_source(session: AsyncSession, job: ClaimedJob, sha256: bytes) -> bool:
    result = await session.scalar(
        update(AnalysisJob)
        .where(
            AnalysisJob.id == job.id,
            AnalysisJob.status == "running",
            AnalysisJob.lease_token == job.token,
            AnalysisJob.lease_until > func.clock_timestamp(),
        )
        .values(observed_sha256=sha256)
        .returning(AnalysisJob.id)
    )
    return result is not None


async def finish(
    session: AsyncSession,
    job: ClaimedJob,
    *,
    analysis_id: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    retry_after: int | None = None,
) -> bool:
    row = await session.scalar(
        select(AnalysisJob)
        .where(
            AnalysisJob.id == job.id,
            AnalysisJob.status == "running",
            AnalysisJob.lease_token == job.token,
            AnalysisJob.lease_until > func.clock_timestamp(),
        )
        .with_for_update()
    )
    if row is None:
        return False
    row.lease_token, row.lease_until = None, None
    if analysis_id is not None:
        row.status, row.analysis_id = "succeeded", analysis_id
        row.error_code, row.error_message = None, None
    else:
        row.error_code, row.error_message = error_code, error_message
        if retry_after is not None and row.attempts < MAX_ATTEMPTS:
            row.status = "retry_wait"
            now = await session.scalar(select(func.clock_timestamp()))
            assert now is not None
            row.run_after = now + timedelta(seconds=max(retry_after, min(300, 2**row.attempts)))
            row.delivery_after = row.run_after
        else:
            row.status = "failed"
    return True


async def recover_expired(session: AsyncSession) -> None:
    rows = await session.scalars(
        select(AnalysisJob)
        .where(
            AnalysisJob.status == "running",
            AnalysisJob.lease_until <= func.clock_timestamp(),
        )
        .with_for_update(skip_locked=True)
        .limit(100)
    )
    now = await session.scalar(select(func.clock_timestamp()))
    assert now is not None
    for row in rows:
        row.status = "retry_wait" if row.attempts < MAX_ATTEMPTS else "failed"
        row.lease_token, row.lease_until = None, None
        row.run_after = row.delivery_after = now
        row.error_code, row.error_message = "worker_lease_expired", "Worker lease expired"
