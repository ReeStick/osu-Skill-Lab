import asyncio
import hashlib
import os
from collections.abc import AsyncIterator
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from osu_skill_lab.application.batches import BatchRequest, BatchService
from osu_skill_lab.application.mirror_import import MirrorImportService
from osu_skill_lab.application.service import (
    AnalysisProcessUnavailableError,
    AnalysisService,
    AnalysisUnavailableError,
)
from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure import job_repository
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.infrastructure.hinamizawa import HinamizawaClient
from osu_skill_lab.infrastructure.job_models import AnalysisBatch, AnalysisJob
from osu_skill_lab.infrastructure.models import AnalysisResult, BeatmapInput, BeatmapSource
from osu_skill_lab.infrastructure.rabbitmq import JobMessage, RabbitBroker
from osu_skill_lab.workers.dispatcher import dispatch_once
from osu_skill_lab.workers.import_worker import ImportWorker, WorkerRestartRequired

pytestmark = pytest.mark.integration
SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "analytic-v14.osu"


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
def data() -> bytes:
    return (
        SOURCE.read_bytes()
        .replace(b"BeatmapID: 0", b"BeatmapID: 123")
        .replace(
            b"BeatmapSetID: -1",
            b"BeatmapSetID: 456",
        )
    )


@pytest.fixture
async def cpu() -> AsyncIterator[ProcessPoolExecutor]:
    executor = ProcessPoolExecutor(max_workers=1)
    try:
        yield executor
    finally:
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)


@pytest.fixture
def broker_url() -> str:
    url = os.getenv("OSU_LAB_TEST_RABBITMQ_URL")
    if not url:
        pytest.skip("Set OSU_LAB_TEST_RABBITMQ_URL to run real RabbitMQ delivery tests")
    return url


def request(*ids: int) -> BatchRequest:
    return BatchRequest.model_validate({"items": [{"beatmap_id": item} for item in ids]})


def metadata(ids: list[int], data: bytes) -> dict[str, object]:
    return {
        "success": True,
        "requested": {"ids": ids, "md5": []},
        "results": [
            {
                "id": 123,
                "beatmapset_id": 456,
                "mode": "osu",
                "checksum": hashlib.md5(data, usedforsecurity=False).hexdigest(),
                "last_updated": "2026-10-01T00:00:00Z",
                "hinai_source": "local_duckdb",
            }
        ]
        if 123 in ids
        else [],
        "missing": {"ids": [item for item in ids if item != 123], "md5": []},
        "unresolved": {"ids": [], "md5": [], "reason": None},
    }


async def no_delay(seconds: float) -> None:
    await asyncio.sleep(0)


def client(data: bytes, requests: list[str]) -> HinamizawaClient:
    def remote(req: httpx.Request) -> httpx.Response:
        requests.append(req.url.path)
        assert "Authorization" not in req.headers
        if req.url.path == "/v3/osu/beatmaps/batch":
            return httpx.Response(
                200, json=metadata([int(item) for item in req.url.params["ids"].split(",")], data)
            )
        return httpx.Response(200, content=data)

    return HinamizawaClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(remote)), sleep=no_delay
    )


async def test_confirm_then_transaction_failure_can_be_safely_republished(
    database: Database,
    broker_url: str,
) -> None:
    view = await BatchService(database).submit(request(123), uuid4())
    queue_name = "test." + uuid4().hex
    async with RabbitBroker(broker_url, queue_name=queue_name) as broker:
        try:

            async def send_then_fail(item_id: int) -> None:
                await broker.publish(item_id)
                raise RuntimeError("Failure after confirm, before DB commit")

            interrupted = AsyncMock(spec=RabbitBroker)
            interrupted.publish.side_effect = send_then_fail
            with pytest.raises(RuntimeError):
                await dispatch_once(database, cast(RabbitBroker, interrupted))
            assert await dispatch_once(database, broker) == 1
            first, duplicate = await broker.receive(), await broker.receive()
            assert first is not None and duplicate is not None
            assert first.body == duplicate.body
            async with database.session() as session, session.begin():
                job = await job_repository.claim(session, view.items[0].id)
            assert job is not None
            async with database.session() as session, session.begin():
                assert await job_repository.claim(session, view.items[0].id) is None
                assert await job_repository.finish(session, job, error_code="test_failure")
            await first.ack()
            await duplicate.ack()
        finally:
            await broker.queue.delete(if_unused=False, if_empty=False)


async def test_real_broker_partial_batch_duplicate_delivery_and_worker_restart(
    database: Database,
    cpu: ProcessPoolExecutor,
    data: bytes,
    broker_url: str,
) -> None:
    service = BatchService(database)
    view = await service.submit(request(123, 999), uuid4())
    queue_name = "test." + uuid4().hex
    requests: list[str] = []
    api = client(data, requests)
    worker = ImportWorker(database, MirrorImportService(api, AnalysisService(database, cpu)))
    try:
        # Confirmed publication followed by a consumer crash before ACK.
        async with RabbitBroker(broker_url, queue_name=queue_name) as broker:
            assert await dispatch_once(database, broker) == 2
            first = await broker.receive()
            assert first is not None
            envelope = JobMessage.model_validate_json(first.body)
            async with database.session() as session, session.begin():
                assert await job_repository.claim(session, envelope.item_id) is not None
            # No ACK: closing the connection simulates a dead worker.
        async with database.session() as session, session.begin():
            await session.execute(
                update(AnalysisJob)
                .where(AnalysisJob.id == envelope.item_id)
                .values(
                    lease_until=func.clock_timestamp() - timedelta(seconds=1),
                )
            )
        async with RabbitBroker(broker_url, queue_name=queue_name) as restarted:
            assert await dispatch_once(database, restarted) == 1
            redelivered = False
            for _ in range(3):
                message = await restarted.receive()
                assert message is not None
                redelivered |= message.redelivered is True
                await worker.process(JobMessage.model_validate_json(message.body).item_id)
                await message.ack()
            assert redelivered
            assert await restarted.receive() is None
            result = await service.get(view.id)
            assert result is not None and result.status == "completed_with_errors"
            assert result.counts["succeeded"] == result.counts["failed"] == 1
            assert result.items[0].attempts == 2
            assert result.items[0].analysis_id is not None
            assert result.items[0].observed_sha256 == hashlib.sha256(data).hexdigest()
            assert result.items[1].error_code == "mirror_not_found"
            await worker.process(view.items[0].id)
            assert requests == ["/v3/osu/beatmaps/batch", "/api/osu/123"]
            async with database.session() as session:
                for model in (BeatmapInput, AnalysisResult, BeatmapSource):
                    assert await session.scalar(select(func.count()).select_from(model)) == 1
            await restarted.queue.delete(if_unused=False, if_empty=False)
    finally:
        await api.close()
        async with RabbitBroker(broker_url, queue_name=queue_name) as cleanup:
            await cleanup.queue.delete(if_unused=False, if_empty=False)


@pytest.mark.parametrize("fault", ["429", "503", "timeout", "unresolved"])
async def test_retryable_mirror_failure_is_durable_without_result(
    database: Database,
    cpu: ProcessPoolExecutor,
    data: bytes,
    fault: str,
) -> None:
    view = await BatchService(database).submit(request(123), uuid4())

    def remote(req: httpx.Request) -> httpx.Response:
        if fault == "timeout":
            raise httpx.ReadTimeout("private response", request=req)
        if fault == "unresolved":
            body = metadata([], data)
            body["requested"] = {"ids": [123], "md5": []}
            body["unresolved"] = {"ids": [123], "md5": [], "reason": "upstream_pressure"}
            return httpx.Response(200, json=body)
        return httpx.Response(int(fault), headers={"Retry-After": "120"})

    api = HinamizawaClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(remote)), sleep=no_delay
    )
    try:
        await ImportWorker(
            database, MirrorImportService(api, AnalysisService(database, cpu))
        ).process(view.items[0].id)
        result = await BatchService(database).get(view.id)
        assert result is not None and result.items[0].status == "retry_wait"
        assert result.items[0].attempts == 1 and result.items[0].next_attempt_at is not None
        assert "private" not in result.model_dump_json()
        async with database.session() as session:
            assert await session.scalar(select(func.count()).select_from(BeatmapInput)) == 0
    finally:
        await api.close()


async def test_retry_after_cpu_failure_pins_previously_downloaded_revision(
    database: Database,
    cpu: ProcessPoolExecutor,
    data: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = BatchService(database)
    view = await service.submit(request(123), uuid4())
    api = client(data, [])
    analysis = AnalysisService(database, cpu)
    monkeypatch.setattr(
        analysis, "analyze_stream", AsyncMock(side_effect=AnalysisUnavailableError("Unavailable"))
    )
    try:
        await ImportWorker(database, MirrorImportService(api, analysis)).process(view.items[0].id)
    finally:
        await api.close()
    waiting = await service.get(view.id)
    assert waiting is not None and waiting.items[0].status == "retry_wait"
    assert waiting.items[0].observed_sha256 == hashlib.sha256(data).hexdigest()
    async with database.session() as session, session.begin():
        await session.execute(
            update(AnalysisJob)
            .where(AnalysisJob.id == view.items[0].id)
            .values(
                run_after=func.clock_timestamp() - timedelta(seconds=1),
            )
        )
    # New process/cache sees a new revision under the same map ID.
    newer = client(data + b"\n// new revision", [])
    try:
        await ImportWorker(
            database, MirrorImportService(newer, AnalysisService(database, cpu))
        ).process(view.items[0].id)
        result = await service.get(view.id)
        assert result is not None and result.items[0].status == "failed"
        assert result.items[0].error_code == "mirror_checksum_mismatch"
        async with database.session() as session:
            assert await session.scalar(select(func.count()).select_from(BeatmapInput)) == 0
    finally:
        await newer.close()


async def test_cancel_during_download_prevents_cpu_persistence(
    database: Database,
    cpu: ProcessPoolExecutor,
    data: bytes,
) -> None:
    service = BatchService(database)
    view = await service.submit(request(123), uuid4())
    downloading, release = asyncio.Event(), asyncio.Event()

    async def remote(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v3/osu/beatmaps/batch":
            return httpx.Response(200, json=metadata([123], data))
        downloading.set()
        await release.wait()
        return httpx.Response(200, content=data)

    api = HinamizawaClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(remote)), sleep=no_delay
    )
    task = asyncio.create_task(
        ImportWorker(database, MirrorImportService(api, AnalysisService(database, cpu))).process(
            view.items[0].id
        )
    )
    try:
        async with asyncio.timeout(5):
            await downloading.wait()
            await service.get(view.id, cancel=True)
            release.set()
            await task
        final = await service.get(view.id)
        assert final is not None and final.items[0].status == "cancelled"
        async with database.session() as session:
            assert await session.scalar(select(func.count()).select_from(BeatmapInput)) == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await api.close()


async def test_broken_cpu_pool_preserves_retry_and_requests_worker_restart(
    database: Database,
    cpu: ProcessPoolExecutor,
    data: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = await BatchService(database).submit(request(123), uuid4())
    api = client(data, [])
    analysis = AnalysisService(database, cpu)
    monkeypatch.setattr(
        analysis,
        "analyze_stream",
        AsyncMock(
            side_effect=AnalysisProcessUnavailableError("Process unavailable"),
        ),
    )
    try:
        worker = ImportWorker(database, MirrorImportService(api, analysis))
        with pytest.raises(WorkerRestartRequired):
            await worker.process(view.items[0].id)
        result = await BatchService(database).get(view.id)
        assert result is not None and result.items[0].status == "retry_wait"
        assert result.items[0].observed_sha256 == hashlib.sha256(data).hexdigest()
    finally:
        await api.close()


async def test_pipeline_upgrade_does_not_silently_change_accepted_job(
    database: Database,
    cpu: ProcessPoolExecutor,
    data: bytes,
) -> None:
    view = await BatchService(database).submit(request(123), uuid4())
    async with database.session() as session, session.begin():
        await session.execute(
            update(AnalysisBatch)
            .where(AnalysisBatch.id == view.id)
            .values(algorithm_version="old/0")
        )
    requests: list[str] = []
    api = client(data, requests)
    try:
        await ImportWorker(
            database, MirrorImportService(api, AnalysisService(database, cpu))
        ).process(view.items[0].id)
        result = await BatchService(database).get(view.id)
        assert result is not None and result.items[0].error_code == "pipeline_version_mismatch"
        assert result.status == "failed" and requests == []
    finally:
        await api.close()
