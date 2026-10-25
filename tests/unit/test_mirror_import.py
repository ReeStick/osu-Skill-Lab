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
