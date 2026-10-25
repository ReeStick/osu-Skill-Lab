import asyncio
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import ParamSpec, TypeVar, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from osu_skill_lab.application.preparation import PreparationFailure
from osu_skill_lab.application.service import (
    AnalysisBusyError,
    AnalysisInputError,
    AnalysisService,
    AnalysisUnavailableError,
)
from osu_skill_lab.infrastructure.database import Database

P = ParamSpec("P")
T = TypeVar("T")
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "analytic-v14.osu"


class ControlledExecutor(Executor):
    def __init__(self) -> None:
        self.futures: list[Future[object]] = []
        self.submission_event = asyncio.Event()

    def submit(self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        future: Future[T] = Future()
        self.futures.append(cast(Future[object], future))
        self.submission_event.set()
        return future


async def chunks(data: bytes = b"input") -> AsyncIterator[bytes]:
    yield data


def no_database() -> Database:
    database = MagicMock(spec=Database)
    database.session.side_effect = AssertionError("Database must not be used for rejected input")
    return cast(Database, database)


async def submitted(executor: ControlledExecutor, count: int) -> None:
    async with asyncio.timeout(2):
        while len(executor.futures) < count:
            executor.submission_event.clear()
            await executor.submission_event.wait()


async def test_capacity_is_reserved_before_consuming_another_request_body() -> None:
    executor = ControlledExecutor()
    service = AnalysisService(no_database(), executor, max_in_flight=1)
    first = asyncio.create_task(service.analyze_stream(chunks()))
    await submitted(executor, 1)
    consumed = False

    async def second_body() -> AsyncIterator[bytes]:
        nonlocal consumed
        consumed = True
        yield b"second"

    with pytest.raises(AnalysisBusyError):
        await service.analyze_stream(second_body())
    assert not consumed
    executor.futures[0].set_result(PreparationFailure("invalid_header", "Invalid header"))
    with pytest.raises(AnalysisInputError):
        await first


async def test_cancelled_request_keeps_capacity_until_its_process_finishes() -> None:
    executor = ControlledExecutor()
    service = AnalysisService(no_database(), executor, max_in_flight=1)
    first = asyncio.create_task(service.analyze_stream(chunks()))
    await submitted(executor, 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not executor.futures[0].cancelled()
    with pytest.raises(AnalysisBusyError):
        await service.analyze_stream(chunks())
    executor.futures[0].set_result(PreparationFailure("invalid_header", "Invalid header"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    second = asyncio.create_task(service.analyze_stream(chunks()))
    await submitted(executor, 2)
    executor.futures[1].set_result(PreparationFailure("invalid_header", "Invalid header"))
    with pytest.raises(AnalysisInputError):
        await second


async def test_oversized_stream_does_not_submit_work_or_leak_capacity() -> None:
    executor = ControlledExecutor()
    service = AnalysisService(no_database(), executor, max_in_flight=1)

    async def oversized() -> AsyncIterator[bytes]:
        yield b"x" * (4 * 1024 * 1024)
        yield b"one byte too many"

    with pytest.raises(AnalysisInputError) as error:
        await service.analyze_stream(oversized())
    assert error.value.code == "file_too_large"
    assert executor.futures == []
    retry = asyncio.create_task(service.analyze_stream(chunks()))
    await submitted(executor, 1)
    executor.futures[0].set_result(PreparationFailure("invalid_header", "Invalid header"))
    with pytest.raises(AnalysisInputError):
        await retry


async def test_process_failure_returns_generic_unavailability_and_releases_capacity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    executor = ControlledExecutor()
    service = AnalysisService(no_database(), executor, max_in_flight=1)
    first = asyncio.create_task(service.analyze_stream(chunks()))
    await submitted(executor, 1)
    executor.futures[0].set_exception(BrokenProcessPool("private internals"))
    with pytest.raises(AnalysisUnavailableError) as error:
        await first
    assert "private internals" not in str(error.value) + caplog.text
    retry = asyncio.create_task(service.analyze_stream(chunks()))
    await submitted(executor, 2)
    executor.futures[1].set_result(PreparationFailure("invalid_header", "Invalid header"))
    with pytest.raises(AnalysisInputError):
        await retry


async def test_database_failure_does_not_expose_connection_details(
    caplog: pytest.LogCaptureFixture,
    source: bytes,
) -> None:
    database = MagicMock(spec=Database)
    context = MagicMock()
    context.__aenter__ = AsyncMock(side_effect=OSError("private connection password"))
    database.session.return_value = context
    with ThreadPoolExecutor(max_workers=1) as executor:
        service = AnalysisService(cast(Database, database), executor)
        with pytest.raises(AnalysisUnavailableError) as error:
            await service.analyze_stream(chunks(source))
    assert "private connection password" not in str(error.value) + caplog.text


@pytest.fixture
def source() -> bytes:
    return FIXTURE.read_bytes()
