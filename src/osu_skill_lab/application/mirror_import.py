import asyncio
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from osu_skill_lab.application.contracts import SaveAnalysisOutcome
from osu_skill_lab.application.service import AnalysisService
from osu_skill_lab.application.sources import MirrorError, SourceReceipt
from osu_skill_lab.infrastructure.hinamizawa import HinamizawaClient


@dataclass(frozen=True, slots=True)
class CachedImport:
    result_id: int
    md5: str
    sha256: str
    expires_at: float


@dataclass(slots=True)
class ImportGate:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class MirrorImportService:
    def __init__(
        self,
        api: HinamizawaClient,
        analyses: AnalysisService,
        *,
        official_cache_ttl: int = 3600,
        max_in_flight: int = 2,
        max_concurrent: int = 1,
    ) -> None:
        if not 1 <= max_concurrent <= max_in_flight <= 32:
            raise ValueError("Expected 1 <= max_concurrent <= max_in_flight <= 32")
        self.api, self.analyses = api, analyses
        self.official_cache_ttl = official_cache_ttl
        self._slots = asyncio.Semaphore(max_concurrent)
        self._gates: dict[int, ImportGate] = {}
        self._tokens: asyncio.Queue[None] = asyncio.Queue(maxsize=max_in_flight)
        for _ in range(max_in_flight):
            self._tokens.put_nowait(None)
        self._cache: OrderedDict[int, CachedImport] = OrderedDict()

    async def import_id(
        self,
        beatmap_id: int,
        *,
        expected_sha256: str | None = None,
        before_analysis: Callable[[SourceReceipt], Awaitable[None]] | None = None,
    ) -> SaveAnalysisOutcome:
        try:
            self._tokens.get_nowait()
        except asyncio.QueueEmpty:
            raise MirrorError(
                "mirror_busy", "Mirror import capacity is full", retryable=True, retry_after=1
            ) from None
        gate = self._gates.setdefault(beatmap_id, ImportGate())
        gate.users += 1
        try:
            async with gate.lock, self._slots:
                resolved = await self.api.resolve_ids([beatmap_id])
                if resolved.issues:
                    issue = resolved.issues[0]
                    if issue.kind == "missing":
                        raise MirrorError("mirror_not_found", "Mirror beatmap not found")
                    raise MirrorError(
                        "mirror_unresolved",
                        "Mirror could not resolve this beatmap",
                        retryable=True,
                        retry_after=60,
                    )
                metadata = resolved.items[0]
                if metadata.ruleset != 0:
                    raise MirrorError(
                        "mirror_unsupported_ruleset", "Only osu!standard is supported"
                    )
                if metadata.md5 is None:
                    raise MirrorError(
                        "mirror_checksum_unavailable", "Mirror metadata has no checksum"
                    )
                official_md5 = await self.analyses.recent_official_md5(
                    beatmap_id,
                    datetime.now(UTC) - timedelta(seconds=self.official_cache_ttl),
                )
                if official_md5 is not None and official_md5 != metadata.md5:
                    raise MirrorError(
                        "mirror_checksum_mismatch",
                        "Mirror metadata differs from a recent official checksum observation",
                    )
                cached = self._cache.get(beatmap_id)
                if (
                    cached is not None
                    and cached.expires_at > time.monotonic()
                    and cached.md5 == metadata.md5
                ):
                    if expected_sha256 is not None and cached.sha256 != expected_sha256:
                        raise MirrorError(
                            "mirror_checksum_mismatch",
                            "Cached source differs from requested revision",
                        )
                    record = await self.analyses.get_analysis(cached.result_id)
                    if record is not None:
                        if beatmap_id in self._cache:
                            self._cache.move_to_end(beatmap_id)
                        return SaveAnalysisOutcome(record, False)
                downloaded = await self.api.download(metadata, expected_sha256=expected_sha256)
                if before_analysis is not None:
                    await before_analysis(downloaded.receipt)

                async def chunks() -> AsyncIterator[bytes]:
                    yield downloaded.data

                outcome = await self.analyses.analyze_stream(chunks(), source=downloaded.receipt)
                self._cache[beatmap_id] = CachedImport(
                    outcome.record.id,
                    downloaded.receipt.source_md5.hex(),
                    downloaded.receipt.source_sha256.hex(),
                    time.monotonic() + self.api.cache_ttl,
                )
                self._cache.move_to_end(beatmap_id)
                while len(self._cache) > 256:
                    self._cache.popitem(last=False)
                return outcome
        finally:
            gate.users -= 1
            if gate.users == 0:
                del self._gates[beatmap_id]
            self._tokens.put_nowait(None)
