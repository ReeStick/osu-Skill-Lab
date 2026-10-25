import asyncio
import logging
from datetime import UTC, datetime

from asyncpg import PostgresError
from sqlalchemy.exc import SQLAlchemyError

from osu_skill_lab.application.contracts import AnalysisRecord
from osu_skill_lab.application.osu_metadata import OsuApiError
from osu_skill_lab.application.service import AnalysisService
from osu_skill_lab.infrastructure import analysis_repository, osu_repository
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.infrastructure.osu_api import OsuApiClient

logger = logging.getLogger(__name__)


class OsuVerificationService:
    def __init__(
        self, database: Database, analyses: AnalysisService, api: OsuApiClient, *, cache_ttl: int
    ) -> None:
        self.database, self.analyses, self.api = database, analyses, api
        self.cache_ttl = cache_ttl
        self._tokens: asyncio.Queue[None] = asyncio.Queue(maxsize=2)
        for _ in range(2):
            self._tokens.put_nowait(None)

    async def verify(self, analysis_id: int) -> AnalysisRecord:
        record = await self.analyses.get_analysis(analysis_id)
        if record is None:
            raise OsuApiError("analysis_not_found", "Analysis not found")
        metadata = record.beatmap.osu
        if metadata is not None and (
            0 <= (datetime.now(UTC) - metadata.fetched_at).total_seconds() < self.cache_ttl
        ):
            return record
        try:
            self._tokens.get_nowait()
        except asyncio.QueueEmpty:
            raise OsuApiError(
                "osu_busy", "osu! verification capacity is full", retry_after=1
            ) from None
        try:
            metadata = await self.api.lookup_checksum(record.beatmap.md5)
            if metadata.md5 is None:
                raise OsuApiError("osu_checksum_unavailable", "osu! did not provide a checksum")
            if metadata.md5 != record.beatmap.md5:
                raise OsuApiError("osu_checksum_mismatch", "osu! checksum does not match the input")
            try:
                async with self.database.session() as session, session.begin():
                    await osu_repository.save_match(session, record.beatmap.input_id, metadata)
                    updated = await analysis_repository.get_analysis(session, analysis_id)
                    if updated is None:
                        raise OsuApiError("analysis_not_found", "Analysis not found")
                    return updated
            except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
                logger.warning("osu! metadata persistence unavailable (%s)", type(exc).__name__)
                raise OsuApiError(
                    "osu_storage_unavailable", "Metadata storage unavailable"
                ) from None
        finally:
            self._tokens.put_nowait(None)
