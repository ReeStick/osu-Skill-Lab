import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from osu_skill_lab.application.osu_metadata import OsuApiError
from osu_skill_lab.application.osu_verification import OsuVerificationService
from osu_skill_lab.application.service import AnalysisService
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.infrastructure.osu_api import OsuApiClient


def configured_service() -> tuple[OsuVerificationService, AsyncMock, AsyncMock]:
    database = MagicMock(spec=Database)
    database.session.side_effect = AssertionError("No DB writes expected")
    analyses = AsyncMock(spec=AnalysisService)
    record = MagicMock()
    record.beatmap.osu = None
    record.beatmap.md5 = "a" * 32
    analyses.get_analysis.return_value = record
    api = AsyncMock(spec=OsuApiClient)
    service = OsuVerificationService(
        cast(Database, database),
        cast(AnalysisService, analyses),
        cast(OsuApiClient, api),
        cache_ttl=3600,
    )
    return service, analyses, api


async def test_full_capacity_rejects_and_cancellation_releases_slots() -> None:
    service, _, api = configured_service()
    barrier = asyncio.Barrier(3)
    released = asyncio.Event()

    async def lookup(md5: str) -> None:
        await barrier.wait()
        await released.wait()
        raise OsuApiError("osu_not_found", "Not found")

    api.lookup_checksum.side_effect = lookup
    first = asyncio.create_task(service.verify(1))
    second = asyncio.create_task(service.verify(2))
    async with asyncio.timeout(2):
        await barrier.wait()
    with pytest.raises(OsuApiError) as error:
        await service.verify(3)
    assert error.value.code == "osu_busy"
    first.cancel()
    second.cancel()
    for task in (first, second):
        with pytest.raises(asyncio.CancelledError):
            await task
    api.lookup_checksum.side_effect = OsuApiError("osu_not_found", "Not found")
    with pytest.raises(OsuApiError) as retry:
        await service.verify(3)
    assert retry.value.code == "osu_not_found"


async def test_missing_analysis_never_accesses_osu() -> None:
    service, analyses, api = configured_service()
    analyses.get_analysis.return_value = None
    with pytest.raises(OsuApiError) as error:
        await service.verify(1)
    assert error.value.code == "analysis_not_found"
    api.lookup_checksum.assert_not_called()


@pytest.mark.parametrize("checksum", [None, "b" * 32])
async def test_checksum_mismatch_is_rejected_before_db_session(checksum: str | None) -> None:
    service, _, api = configured_service()
    metadata = MagicMock()
    metadata.md5 = checksum
    api.lookup_checksum.return_value = metadata
    with pytest.raises(OsuApiError) as error:
        await service.verify(1)
    assert error.value.code == (
        "osu_checksum_unavailable" if checksum is None else "osu_checksum_mismatch"
    )
