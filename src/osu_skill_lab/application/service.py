import asyncio
import logging
from collections.abc import AsyncIterable
from concurrent.futures import Executor
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime

from asyncpg import PostgresError
from sqlalchemy.exc import SQLAlchemyError

from osu_skill_lab.analysis.models import ParserLimits
from osu_skill_lab.application.contracts import AnalysisPage, AnalysisRecord, SaveAnalysisOutcome
from osu_skill_lab.application.preparation import (
    PreparationFailure,
    PreparedAnalysis,
    prepare_analysis,
)
from osu_skill_lab.application.sources import SourceReceipt
from osu_skill_lab.infrastructure import analysis_repository, source_repository
from osu_skill_lab.infrastructure.database import Database

logger = logging.getLogger(__name__)


class AnalysisInputError(ValueError):
    def __init__(
        self, code: str, message: str, section: str | None = None, line_number: int | None = None
    ) -> None:
        super().__init__(message)
        self.code, self.message = code, message
        self.section, self.line_number = section, line_number


class AnalysisBusyError(RuntimeError):
    pass


class AnalysisUnavailableError(RuntimeError):
    pass


class AnalysisProcessUnavailableError(AnalysisUnavailableError):
    pass


class AnalysisService:
    def __init__(self, database: Database, executor: Executor, *, max_in_flight: int = 2) -> None:
        if max_in_flight < 1:
            raise ValueError("max_in_flight must be positive")
        self.database = database
        self.executor = executor
        self._tokens: asyncio.Queue[None] = asyncio.Queue(maxsize=max_in_flight)
        for _ in range(max_in_flight):
            self._tokens.put_nowait(None)

    async def analyze_stream(
        self,
        chunks: AsyncIterable[bytes],
        *,
        source: SourceReceipt | None = None,
    ) -> SaveAnalysisOutcome:
        try:
            self._tokens.get_nowait()
        except asyncio.QueueEmpty:
            raise AnalysisBusyError("Analysis capacity is full") from None
        data = bytearray()
        release_on_exit = True
        try:
            maximum = ParserLimits().max_file_bytes
            async for chunk in chunks:
                if len(data) + len(chunk) > maximum:
                    raise AnalysisInputError("file_too_large", "Input exceeds max_file_bytes")
                data.extend(chunk)
            loop = asyncio.get_running_loop()
            try:
                # No files are written. Only compact metadata/results return from the CPU process.
                future = loop.run_in_executor(self.executor, prepare_analysis, bytes(data))
                try:
                    prepared = await asyncio.shield(future)
                except asyncio.CancelledError:
                    # Cancellation cannot stop a running CPU process. Keep its slot reserved.
                    release_on_exit = False

                    def finished(
                        task: asyncio.Future[PreparedAnalysis | PreparationFailure],
                    ) -> None:
                        if not task.cancelled():
                            # Consume a failed detached task without logging input.
                            task.exception()
                        self._tokens.put_nowait(None)

                    future.add_done_callback(finished)
                    raise
            except (BrokenProcessPool, RuntimeError) as exc:
                logger.warning("Analysis process unavailable (%s)", type(exc).__name__)
                raise AnalysisProcessUnavailableError("Analysis process unavailable") from None
            finally:
                data.clear()
            if isinstance(prepared, PreparationFailure):
                raise AnalysisInputError(
                    prepared.code, prepared.message, prepared.section, prepared.line_number
                )
            if source is not None and (
                prepared.source_sha256 != source.source_sha256
                or prepared.source_md5 != source.source_md5
                or prepared.metadata.beatmap_id not in {None, source.requested_beatmap_id}
                or prepared.metadata.beatmap_set_id not in {None, source.metadata_beatmap_set_id}
            ):
                raise AnalysisInputError(
                    "source_identity_mismatch", "Downloaded input identity does not match"
                )
            try:
                async with self.database.session() as session, session.begin():
                    outcome = await analysis_repository.save_analysis(session, prepared)
                    if source is None:
                        return outcome
                    await source_repository.save_source(
                        session, outcome.record.beatmap.input_id, source
                    )
                    record = await analysis_repository.get_analysis(session, outcome.record.id)
                    if record is None:
                        raise RuntimeError("Saved source analysis is not visible")
                    return SaveAnalysisOutcome(record, outcome.created)
            except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
                logger.warning("Analysis persistence unavailable (%s)", type(exc).__name__)
                raise AnalysisUnavailableError("Analysis persistence unavailable") from None
        finally:
            data.clear()
            if release_on_exit:
                self._tokens.put_nowait(None)

    async def get_analysis(self, analysis_id: int) -> AnalysisRecord | None:
        try:
            async with self.database.session() as session:
                return await analysis_repository.get_analysis(session, analysis_id)
        except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
            logger.warning("Analysis persistence unavailable (%s)", type(exc).__name__)
            raise AnalysisUnavailableError("Analysis persistence unavailable") from None

    async def recent_official_md5(self, beatmap_id: int, since: datetime) -> str | None:
        try:
            async with self.database.session() as session:
                return await source_repository.recent_official_md5(session, beatmap_id, since)
        except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
            logger.warning("Analysis persistence unavailable (%s)", type(exc).__name__)
            raise AnalysisUnavailableError("Analysis persistence unavailable") from None

    async def list_analyses(
        self, *, limit: int, after_id: int, claimed_beatmap_id: int | None = None
    ) -> AnalysisPage:
        if not 1 <= limit <= 100 or after_id < 0:
            raise ValueError("Invalid pagination")
        try:
            async with self.database.session() as session:
                return await analysis_repository.list_analyses(
                    session, limit=limit, after_id=after_id, claimed_beatmap_id=claimed_beatmap_id
                )
        except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
            logger.warning("Analysis persistence unavailable (%s)", type(exc).__name__)
            raise AnalysisUnavailableError("Analysis persistence unavailable") from None
