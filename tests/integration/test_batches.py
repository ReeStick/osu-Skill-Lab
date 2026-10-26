import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from osu_skill_lab.application.batches import (
    BatchCapacityError,
    BatchConflict,
    BatchRequest,
    BatchService,
)
from osu_skill_lab.application.sources import MirrorError
from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure import job_repository
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.infrastructure.job_models import AnalysisBatch, AnalysisJob, ProviderBudget
from osu_skill_lab.infrastructure.provider_budget import PostgresMirrorBudget
from osu_skill_lab.main import create_app
from osu_skill_lab.workers.dispatcher import dispatch_once

pytestmark = pytest.mark.integration


@pytest.fixture
def database(migrated_engine: AsyncEngine, database_settings: Settings) -> Database:
    db = Database(database_settings)
    db.session_factory.configure(bind=migrated_engine)
    return db


def request(*ids: int) -> BatchRequest:
    return BatchRequest.model_validate({"items": [{"beatmap_id": item} for item in ids]})


async def test_http_accept_get_replay_conflict_cancel_no_network(
    migrated_engine: AsyncEngine,
    database_settings: Settings,
) -> None:
    app = create_app(database_settings)
    async with app.router.lifespan_context(app):
        app.state.database.session_factory.configure(bind=migrated_engine)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"Idempotency-Key": str(uuid4())}
            first = await client.post(
                "/analysis-batches", json=request(1, 2, 1).model_dump(), headers=headers
            )
            assert first.status_code == 202, first.text
            view = first.json()
            assert len(view["items"]) == 2 and view["status"] == "pending"
            assert all(item["attempts"] == 0 for item in view["items"])
            location = first.headers["Location"]
            assert (await client.get(location)).json() == view
            replay = await client.post(
                "/analysis-batches", json=request(1, 2).model_dump(), headers=headers
            )
            assert replay.status_code == 202 and replay.json() == view
            conflict = await client.post(
                "/analysis-batches", json=request(3).model_dump(), headers=headers
            )
            assert conflict.status_code == 409
            cancelled = await client.post(location + "/cancel")
            assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
            assert cancelled.json()["counts"]["cancelled"] == 2
            assert (await client.post(location + "/cancel")).json() == cancelled.json()
            assert (await client.get(f"/analysis-batches/{uuid4()}")).status_code == 404


async def test_concurrent_idempotency_and_conflicting_replay(database: Database) -> None:
    service = BatchService(database)
    key = uuid4()
    first, second = await asyncio.gather(
        service.submit(request(1), key), service.submit(request(1), key)
    )
    assert first == second
    with pytest.raises(BatchConflict):
        await service.submit(request(2), key)
    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(AnalysisJob)) == 1


async def test_admission_cap_is_shared_and_atomic(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(job_repository, "MAX_ACTIVE_JOBS", 2)
    service = BatchService(database)
    await service.submit(request(1), uuid4())
    results = await asyncio.gather(
        service.submit(request(2), uuid4()),
        service.submit(request(3), uuid4()),
        return_exceptions=True,
    )
    assert sum(isinstance(item, BatchCapacityError) for item in results) == 1
    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(AnalysisBatch)) == 2


async def test_lease_crash_recovery_duplicate_fencing_and_pin(database: Database) -> None:
    view = await BatchService(database).submit(request(1), uuid4())
    item_id = view.items[0].id
    async with database.session() as session, session.begin():
        original = await job_repository.claim(session, item_id)
    assert original is not None
    async with database.session() as session, session.begin():
        assert await job_repository.claim(session, item_id) is None
        assert await job_repository.pin_source(session, original, b"x" * 32)
        await session.execute(
            update(AnalysisJob)
            .where(AnalysisJob.id == item_id)
            .values(
                lease_until=func.clock_timestamp() - timedelta(seconds=1),
            )
        )
    async with database.session() as session, session.begin():
        await job_repository.recover_expired(session)
    async with database.session() as session, session.begin():
        replacement = await job_repository.claim(session, item_id)
    assert replacement is not None and replacement.token != original.token
    assert replacement.expected_sha256 == (b"x" * 32).hex()
    async with database.session() as session, session.begin():
        assert not await job_repository.heartbeat(session, original)
        assert not await job_repository.finish(session, original, error_code="stale")
        assert await job_repository.heartbeat(session, replacement)
        assert await job_repository.finish(
            session, replacement, error_code="invalid_file", error_message="Invalid"
        )
    final = await BatchService(database).get(view.id)
    assert final is not None and final.status == "failed" and final.items[0].attempts == 2


async def test_retry_backoff_exhaustion_and_cancel_fences_running(database: Database) -> None:
    service = BatchService(database)
    view = await service.submit(request(1, 2), uuid4())
    for attempt in range(5):
        async with database.session() as session, session.begin():
            job = await job_repository.claim(session, view.items[0].id)
            assert job is not None
            assert await job_repository.finish(
                session, job, error_code="mirror_timeout", retry_after=60
            )
        final = await service.get(view.id)
        assert final is not None
        item = final.items[0]
        assert item.attempts == attempt + 1
        assert item.status == ("retry_wait" if attempt < 4 else "failed")
        if attempt < 4:
            async with database.session() as session, session.begin():
                assert await job_repository.claim(session, item.id) is None
                await session.execute(
                    update(AnalysisJob)
                    .where(AnalysisJob.id == item.id)
                    .values(
                        run_after=func.clock_timestamp() - timedelta(seconds=1),
                    )
                )
    async with database.session() as session, session.begin():
        running = await job_repository.claim(session, view.items[1].id)
    assert running is not None
    cancelled = await service.get(view.id, cancel=True)
    assert cancelled is not None and cancelled.counts["cancelled"] == 1
    async with database.session() as session, session.begin():
        assert not await job_repository.pin_source(session, running, b"x" * 32)
        assert not await job_repository.finish(session, running, error_code="stale")


async def test_shared_provider_pacing_and_cooldown_cannot_be_shortened(database: Database) -> None:
    first, second = PostgresMirrorBudget(database), PostgresMirrorBudget(database)
    start = asyncio.get_running_loop().time()
    await asyncio.gather(first.wait_turn(), second.wait_turn())
    assert asyncio.get_running_loop().time() - start >= 1.0
    await first.pause(120)
    await second.pause(60)
    with pytest.raises(MirrorError) as error:
        await second.wait_turn()
    assert error.value.code == "mirror_rate_limited"
    assert error.value.retry_after is not None and error.value.retry_after >= 118
    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(ProviderBudget)) == 1


async def test_publish_failure_rolls_back_delivery_intent(database: Database) -> None:
    from typing import cast

    from osu_skill_lab.infrastructure.rabbitmq import RabbitBroker

    view = await BatchService(database).submit(request(1), uuid4())
    broker = AsyncMock(spec=RabbitBroker)
    broker.publish.side_effect = RuntimeError("Broker unavailable")
    with pytest.raises(RuntimeError):
        await dispatch_once(database, cast(RabbitBroker, broker))
    broker.publish.side_effect = None
    assert await dispatch_once(database, cast(RabbitBroker, broker)) == 1
    assert await dispatch_once(database, cast(RabbitBroker, broker)) == 0
    broker.publish.assert_awaited_with(view.items[0].id)
