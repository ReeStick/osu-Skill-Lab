import asyncio
from typing import cast
from unittest.mock import AsyncMock

import pytest

from osu_skill_lab.application.mirror_import import MirrorImportService
from osu_skill_lab.application.service import AnalysisService
from osu_skill_lab.application.sources import MirrorError, MirrorIssue, MirrorResolution
from osu_skill_lab.infrastructure.hinamizawa import HinamizawaClient


def service_for() -> tuple[MirrorImportService, AsyncMock, AsyncMock]:
    api = AsyncMock(spec=HinamizawaClient)
    analyses = AsyncMock(spec=AnalysisService)
    service = MirrorImportService(cast(HinamizawaClient, api), cast(AnalysisService, analyses))
    return service, api, analyses


@pytest.mark.parametrize(("admitted", "running"), [(0, 1), (33, 1), (2, 0), (1, 2)])
def test_import_capacity_configuration_is_validated(admitted: int, running: int) -> None:
    api = AsyncMock(spec=HinamizawaClient)
    analyses = AsyncMock(spec=AnalysisService)
    with pytest.raises(ValueError):
        MirrorImportService(
            cast(HinamizawaClient, api),
            cast(AnalysisService, analyses),
            max_in_flight=admitted,
            max_concurrent=running,
        )


async def test_parallel_imports_release_slots_after_cancellation() -> None:
    api = AsyncMock(spec=HinamizawaClient)
    analyses = AsyncMock(spec=AnalysisService)
    service = MirrorImportService(
        cast(HinamizawaClient, api),
        cast(AnalysisService, analyses),
        max_in_flight=2,
        max_concurrent=2,
    )
    entered: set[int] = set()
    full = asyncio.Event()

    async def resolve(ids: list[int]) -> None:
        entered.add(ids[0])
        if len(entered) == 2:
            full.set()
        await asyncio.Event().wait()

    api.resolve_ids.side_effect = resolve
    tasks = [asyncio.create_task(service.import_id(item)) for item in (1, 2)]
    try:
        async with asyncio.timeout(2):
            await full.wait()
        with pytest.raises(MirrorError) as busy:
            await service.import_id(3)
        assert busy.value.code == "mirror_busy"
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    api.resolve_ids.side_effect = MirrorError("mirror_not_found", "Not found")
    for item in (1, 2, 3):
        with pytest.raises(MirrorError) as retry:
            await service.import_id(item)
        assert retry.value.code == "mirror_not_found"


@pytest.mark.parametrize("kind", ["missing", "unresolved"])
async def test_metadata_issue_keeps_absence_distinct_from_retry(kind: str) -> None:
    service, api, analyses = service_for()
    issue = MirrorIssue(123, "missing" if kind == "missing" else "unresolved", "upstream_cap")
    api.resolve_ids.return_value = MirrorResolution((), (issue,))
    with pytest.raises(MirrorError) as error:
        await service.import_id(123)
    assert error.value.code == ("mirror_not_found" if kind == "missing" else "mirror_unresolved")
    assert error.value.retryable is (kind == "unresolved")
    api.download.assert_not_called()
    analyses.analyze_stream.assert_not_called()


async def test_capacity_and_cancelled_waiters_do_not_leak_admission_slots() -> None:
    service, api, _ = service_for()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def resolve(ids: list[int]) -> None:
        entered.set()
        await release.wait()

    api.resolve_ids.side_effect = resolve
    first = asyncio.create_task(service.import_id(123))
    async with asyncio.timeout(2):
        await entered.wait()
    second = asyncio.create_task(service.import_id(124))
    await asyncio.sleep(0)
    with pytest.raises(MirrorError) as error:
        await service.import_id(125)
    assert error.value.code == "mirror_busy"
    first.cancel()
    second.cancel()
    for task in (first, second):
        with pytest.raises(asyncio.CancelledError):
            await task
    api.resolve_ids.side_effect = MirrorError("mirror_not_found", "Not found")
    with pytest.raises(MirrorError) as retry:
        await service.import_id(125)
    assert retry.value.code == "mirror_not_found"


async def test_transport_failure_does_not_start_an_analysis() -> None:
    service, api, analyses = service_for()
    api.resolve_ids.side_effect = MirrorError("mirror_timeout", "Timed out", retryable=True)
    with pytest.raises(MirrorError) as error:
        await service.import_id(123)
    assert error.value.code == "mirror_timeout"
    analyses.analyze_stream.assert_not_called()
