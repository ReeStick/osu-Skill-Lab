import asyncio
import hashlib
import os
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from concurrent.futures import ProcessPoolExecutor
from contextlib import AsyncExitStack
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from osu_skill_lab.application.batches import BatchRequest, BatchService
from osu_skill_lab.application.contracts import SaveAnalysisOutcome
from osu_skill_lab.application.mirror_import import MirrorImportService
from osu_skill_lab.application.service import AnalysisService
from osu_skill_lab.application.sources import SourceReceipt
from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.infrastructure.hinamizawa import HinamizawaClient
from osu_skill_lab.infrastructure.models import AnalysisResult
from osu_skill_lab.infrastructure.rabbitmq import JobMessage, RabbitBroker
from osu_skill_lab.workers.dispatcher import dispatch_once
from osu_skill_lab.workers.import_worker import ImportWorker
from osu_skill_lab.workers.runtime import consume_jobs

pytestmark = pytest.mark.integration
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "analytic-v14.osu"


@pytest.fixture
async def database(
    migrated_engine: AsyncEngine, database_settings: Settings
) -> AsyncIterator[Database]:
    db = Database(database_settings)
    db.session_factory.configure(bind=migrated_engine)
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
def broker_url() -> str:
    value = os.getenv("OSU_LAB_TEST_RABBITMQ_URL")
    if not value:
        pytest.skip("Set OSU_LAB_TEST_RABBITMQ_URL for real runtime consumer tests")
    return value


def data_for(identifier: int) -> bytes:
    return (
        FIXTURE.read_bytes()
        .replace(b"BeatmapID: 0", f"BeatmapID: {identifier}".encode())
        .replace(
            b"BeatmapSetID: -1",
            b"BeatmapSetID: 456",
        )
    )


def mirror(requests: list[str] | None = None) -> HinamizawaClient:
    def remote(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request.url.path)
        if request.url.path == "/v3/osu/beatmaps/batch":
            ids = [int(value) for value in request.url.params["ids"].split(",")]
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "requested": {"ids": ids, "md5": []},
                    "results": [
                        {
                            "id": item,
                            "beatmapset_id": 456,
                            "mode": "osu",
                            "checksum": hashlib.md5(
                                data_for(item), usedforsecurity=False
                            ).hexdigest(),
                            "last_updated": "2026-10-01T00:00:00Z",
                        }
                        for item in ids
                    ],
                    "missing": {"ids": [], "md5": []},
                    "unresolved": {"ids": [], "md5": [], "reason": None},
                },
            )
        return httpx.Response(200, content=data_for(int(request.url.path.rsplit("/", 1)[-1])))

    async def no_delay(seconds: float) -> None:
        await asyncio.sleep(0)

    return HinamizawaClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(remote)), sleep=no_delay
    )


async def test_workers_with_different_capacities_share_queue_and_persist_results(
    database: Database,
    broker_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = await BatchService(database).submit(
        BatchRequest.model_validate(
            {
                "items": [{"beatmap_id": item} for item in range(1, 7)],
            }
        ),
        uuid4(),
    )
    queue_name = "test." + uuid4().hex
    release, all_full, all_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    active = [0, 0]
    peaks = [0, 0]
    completed: list[int] = []
    executor = ProcessPoolExecutor(max_workers=3)
    tasks: list[asyncio.Task[None]] = []
    try:
        async with AsyncExitStack() as stack:
            publisher = await stack.enter_async_context(
                RabbitBroker(broker_url, queue_name=queue_name)
            )
            for index, capacity in enumerate((1, 2)):
                api = mirror()
                stack.push_async_callback(api.close)
                service = AnalysisService(database, executor, max_in_flight=capacity)
                original = service.analyze_stream

                # Delay at the CPU boundary to observe each consumer's admission limit.
                def wrapped(
                    slot: int,
                    method: Callable[..., Awaitable[SaveAnalysisOutcome]],
                ) -> Callable[..., Awaitable[SaveAnalysisOutcome]]:

                    async def analyze(
                        chunks: AsyncIterable[bytes], *, source: SourceReceipt | None = None
                    ) -> SaveAnalysisOutcome:
                        active[slot] += 1
                        peaks[slot] = max(peaks[slot], active[slot])
                        if active == [1, 2]:
                            all_full.set()
                        try:
                            await release.wait()
                            return await method(chunks, source=source)
                        finally:
                            active[slot] -= 1

                    return analyze

                monkeypatch.setattr(service, "analyze_stream", wrapped(index, original))
                importer = MirrorImportService(
                    api, service, max_in_flight=capacity, max_concurrent=capacity
                )
                worker = ImportWorker(database, importer)
                broker = await stack.enter_async_context(
                    RabbitBroker(
                        broker_url,
                        queue_name=queue_name,
                        prefetch_count=capacity,
                    )
                )

                async def process(item_id: int, runner: ImportWorker = worker) -> None:
                    await runner.process(item_id)
                    completed.append(item_id)
                    if len(completed) == 6:
                        all_done.set()

                tasks.append(
                    asyncio.create_task(consume_jobs(broker, process, concurrency=capacity))
                )
            try:
                async with asyncio.timeout(15):
                    # Wait for both actual broker consumers before publishing.
                    while True:
                        queue = await publisher.channel.declare_queue(queue_name, passive=True)
                        if queue.declaration_result.consumer_count == 2:
                            break
                        await asyncio.sleep(0.01)
                    assert await dispatch_once(database, publisher) == 6
                    await all_full.wait()
                    assert active == [1, 2] and peaks == [1, 2]
                    release.set()
                    await all_done.wait()
                assert len(set(completed)) == 6
                result = await BatchService(database).get(view.id)
                assert result is not None and result.status == "completed"
                assert all(
                    item.attempts == 1 and item.analysis_id is not None for item in result.items
                )
                async with database.session() as session:
                    assert (
                        await session.scalar(select(func.count()).select_from(AnalysisResult)) == 6
                    )
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await publisher.queue.delete(if_unused=False, if_empty=False)
    finally:
        release.set()
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)


async def test_parallel_importer_deduplicates_same_id_without_serializing_other_maps(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = ProcessPoolExecutor(max_workers=2)
    requests: list[str] = []
    api = mirror(requests)
    service = AnalysisService(database, executor, max_in_flight=2)
    original = service.analyze_stream
    both_started, release = asyncio.Event(), asyncio.Event()
    entries: list[int] = []

    async def analyze(
        chunks: AsyncIterable[bytes], *, source: SourceReceipt | None = None
    ) -> SaveAnalysisOutcome:
        assert source is not None
        entries.append(source.requested_beatmap_id)
        if len(entries) == 2:
            both_started.set()
        await release.wait()
        return await original(chunks, source=source)

    monkeypatch.setattr(service, "analyze_stream", analyze)
    importer = MirrorImportService(api, service, max_in_flight=3, max_concurrent=2)
    tasks = [asyncio.create_task(importer.import_id(item)) for item in (1, 1, 2)]
    try:
        async with asyncio.timeout(10):
            await both_started.wait()
            assert sorted(entries) == [1, 2]
            release.set()
            first, duplicate, other = await asyncio.gather(*tasks)
        assert first.record.id == duplicate.record.id != other.record.id
        assert first.created and not duplicate.created
        assert requests.count("/api/osu/1") == requests.count("/api/osu/2") == 1
        async with database.session() as session:
            assert await session.scalar(select(func.count()).select_from(AnalysisResult)) == 2
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await api.close()
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)


async def test_shutdown_requeues_every_unacked_runtime_slot(broker_url: str) -> None:
    queue_name = "test." + uuid4().hex
    started, stopped = asyncio.Event(), asyncio.Event()
    running = 0

    async def process(item_id: int) -> None:
        nonlocal running
        running += 1
        if running == 2:
            started.set()
        try:
            await stopped.wait()
        finally:
            running -= 1

    async with RabbitBroker(broker_url, queue_name=queue_name, prefetch_count=2) as broker:
        await broker.publish(1)
        await broker.publish(2)
        task = asyncio.create_task(consume_jobs(broker, process, concurrency=2))
        try:
            async with asyncio.timeout(5):
                await started.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert running == 0
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    async with RabbitBroker(broker_url, queue_name=queue_name) as replacement:
        try:
            received = [await replacement.receive(), await replacement.receive()]
            assert all(message is not None and message.redelivered for message in received)
            assert {
                JobMessage.model_validate_json(message.body).item_id
                for message in received
                if message
            } == {1, 2}
            for message in received:
                assert message is not None
                await message.ack()
        finally:
            await replacement.queue.delete(if_unused=False, if_empty=False)
