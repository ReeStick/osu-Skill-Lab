import asyncio
import logging
from uuid import UUID

from sqlalchemy import select

from osu_skill_lab.application.mirror_import import MirrorImportService
from osu_skill_lab.application.preparation import pipeline_identity
from osu_skill_lab.application.service import (
    AnalysisBusyError,
    AnalysisInputError,
    AnalysisProcessUnavailableError,
    AnalysisUnavailableError,
)
from osu_skill_lab.application.sources import MirrorError, SourceReceipt
from osu_skill_lab.infrastructure import job_repository
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.infrastructure.job_models import AnalysisJob
from osu_skill_lab.infrastructure.job_repository import ClaimedJob
from osu_skill_lab.infrastructure.rabbitmq import RabbitBroker
from osu_skill_lab.workers.runtime import WorkerRestartRequired as WorkerRestartRequired
from osu_skill_lab.workers.runtime import consume_jobs

logger = logging.getLogger(__name__)


class LeaseLost(RuntimeError):
    pass


class ImportWorker:
    def __init__(self, database: Database, importer: MirrorImportService) -> None:
        self.database, self.importer = database, importer

    async def process(self, item_id: int) -> None:
        async with self.database.session() as session, session.begin():
            job = await job_repository.claim(session, item_id)
        if job is None:
            return
        work = asyncio.create_task(self._execute(job))
        heartbeat = asyncio.create_task(self._heartbeat(job))
        try:
            done, _ = await asyncio.wait({work, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
            if heartbeat in done:
                await heartbeat
                work.cancel()
            else:
                await work
        finally:
            work.cancel()
            heartbeat.cancel()
            await asyncio.gather(work, heartbeat, return_exceptions=True)

    async def _heartbeat(self, job: ClaimedJob) -> None:
        while True:
            await asyncio.sleep(15)
            async with self.database.session() as session, session.begin():
                if not await job_repository.heartbeat(session, job):
                    return

    async def _warm_metadata(self, batch_id: UUID) -> None:
        async with self.database.session() as session:
            ids = list(
                await session.scalars(
                    select(AnalysisJob.beatmap_id)
                    .where(
                        AnalysisJob.batch_id == batch_id,
                        AnalysisJob.status.in_({"queued", "running", "retry_wait"}),
                    )
                    .order_by(AnalysisJob.position)
                    .limit(100)
                )
            )
        if ids:
            await self.importer.api.resolve_ids(ids)

    async def _execute(self, job: ClaimedJob) -> None:
        try:
            if job.identity != pipeline_identity():
                await self._fail(
                    job, "pipeline_version_mismatch", "Job requires a different pipeline"
                )
                return
            await self._warm_metadata(job.batch_id)

            async def pin(receipt: SourceReceipt) -> None:
                async with self.database.session() as session, session.begin():
                    if not await job_repository.pin_source(session, job, receipt.source_sha256):
                        raise LeaseLost()

            result = await self.importer.import_id(
                job.beatmap_id,
                expected_sha256=job.expected_sha256,
                before_analysis=pin,
            )
            async with self.database.session() as session, session.begin():
                if await job_repository.pin_source(
                    session,
                    job,
                    bytes.fromhex(result.record.beatmap.sha256),
                ):
                    await job_repository.finish(session, job, analysis_id=result.record.id)
        except LeaseLost:
            return
        except MirrorError as exc:
            await self._fail(
                job,
                exc.code,
                exc.message,
                retry_after=(exc.retry_after or 60) if exc.retryable else None,
            )
        except AnalysisInputError as exc:
            await self._fail(job, exc.code, exc.message)
        except (AnalysisBusyError, AnalysisUnavailableError) as exc:
            await self._fail(
                job, "analysis_unavailable", "Analysis temporarily unavailable", retry_after=30
            )
            if isinstance(exc, AnalysisProcessUnavailableError):
                raise WorkerRestartRequired("Worker CPU process unavailable") from None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Job processing interrupted (%s)", type(exc).__name__)
            await self._fail(job, "worker_error", "Worker temporarily unavailable", retry_after=30)

    async def _fail(
        self,
        job: ClaimedJob,
        code: str,
        message: str,
        *,
        retry_after: int | None = None,
    ) -> None:
        async with self.database.session() as session, session.begin():
            await job_repository.finish(
                session,
                job,
                error_code=code,
                error_message=message,
                retry_after=retry_after,
            )

    async def serve(self, broker_url: str, *, concurrency: int = 1) -> None:
        if not 1 <= concurrency <= 32:
            raise ValueError("Worker concurrency must be between 1 and 32")
        while True:
            try:
                async with RabbitBroker(broker_url, prefetch_count=concurrency) as broker:
                    await consume_jobs(broker, self.process, concurrency=concurrency)
            except asyncio.CancelledError:
                raise
            except WorkerRestartRequired:
                raise
            except Exception as exc:
                logger.warning("Worker unavailable (%s)", type(exc).__name__)
                await asyncio.sleep(5)
