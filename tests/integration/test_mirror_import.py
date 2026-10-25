import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from osu_skill_lab.application.osu_metadata import OsuMetadata
from osu_skill_lab.application.preparation import PreparedAnalysis, prepare_analysis
from osu_skill_lab.application.sources import SourceReceipt
from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.analysis_repository import (
    get_analysis,
    list_analyses,
    save_analysis,
)
from osu_skill_lab.infrastructure.hinamizawa import HinamizawaClient
from osu_skill_lab.infrastructure.models import (
    AnalysisResult,
    BeatmapInput,
    BeatmapSource,
    OsuBeatmapMatch,
)
from osu_skill_lab.infrastructure.osu_repository import save_match
from osu_skill_lab.infrastructure.source_repository import save_source
from osu_skill_lab.main import create_app

pytestmark = pytest.mark.integration
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "analytic-v14.osu"


@pytest.fixture
def data() -> bytes:
    return (
        FIXTURE.read_bytes()
        .replace(b"BeatmapID: 0", b"BeatmapID: 123")
        .replace(b"BeatmapSetID: -1", b"BeatmapSetID: 456")
    )


@pytest.fixture
def candidate(data: bytes) -> PreparedAnalysis:
    parsed = prepare_analysis(data)
    assert isinstance(parsed, PreparedAnalysis)
    return parsed


@pytest.fixture
def receipt(candidate: PreparedAnalysis) -> SourceReceipt:
    now = datetime.now(UTC)
    return SourceReceipt(
        123,
        456,
        candidate.source_sha256,
        candidate.source_md5,
        now - timedelta(days=1),
        now,
        now,
        "local_duckdb",
        "local_corpus",
    )


def batch(data: bytes) -> dict[str, object]:
    return {
        "success": True,
        "requested": {"ids": [123], "md5": []},
        "missing": {"ids": [], "md5": []},
        "unresolved": {"ids": [], "md5": [], "reason": None},
        "results": [
            {
                "id": 123,
                "beatmapset_id": 456,
                "mode": "osu",
                "checksum": hashlib.md5(data, usedforsecurity=False).hexdigest(),
                "last_updated": "2026-10-01T00:00:00Z",
                "hinai_source": "local_duckdb",
            }
        ],
    }


async def no_delay(seconds: float) -> None:
    await asyncio.sleep(0)


async def test_import_download_analysis_source_repeat_and_get(
    migrated_engine: AsyncEngine,
    database_settings: Settings,
    data: bytes,
) -> None:
    requests: list[httpx.Request] = []

    def remote(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "mirror.hinamizawa.ai"
        assert "Authorization" not in request.headers
        if request.url.path == "/v3/osu/beatmaps/batch":
            return httpx.Response(200, json=batch(data))
        assert request.url.path == "/api/osu/123"
        return httpx.Response(200, content=data, headers={"x-hinai-osu-source": "local_corpus"})

    api = HinamizawaClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(remote)), sleep=no_delay
    )
    app = create_app(database_settings)
    async with app.router.lifespan_context(app):
        app.state.database.session_factory.configure(bind=migrated_engine)
        app.state.mirror_import.api = api
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            first, second = await asyncio.gather(
                client.post("/imports/hinamizawa/123"),
                client.post("/imports/hinamizawa/123"),
            )
            assert sorted([first.status_code, second.status_code]) == [200, 201]
            imported = first if first.status_code == 201 else second
            assert first.json() == second.json()
            record = imported.json()
            assert record["beatmap"]["identity_status"] == "unverified"
            assert record["beatmap"]["osu"] is None
            assert record["features"]["hit_object_count"] == 4
            assert len(record["beatmap"]["sources"]) == 1
            source = record["beatmap"]["sources"][0]
            assert source["provider"] == "hinamizawa"
            assert source["requested_beatmap_id"] == 123
            assert source["metadata_md5"] == hashlib.md5(data, usedforsecurity=False).hexdigest()
            assert (await client.get(f"/analyses/{record['id']}")).json() == record
            assert (await client.get("/analyses?limit=1")).json()["items"] == [record]
            repeated = await client.post(
                "/imports/hinamizawa/123", params={"expected_sha256": record["beatmap"]["sha256"]}
            )
            assert repeated.status_code == 200 and repeated.json() == record
            assert len(requests) == 2
            wrong_pin = await client.post(
                "/imports/hinamizawa/123", params={"expected_sha256": "0" * 64}
            )
            assert wrong_pin.status_code == 409
            assert len(requests) == 2
    await api.close()
    sessions = async_sessionmaker(migrated_engine)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(BeatmapInput)) == 1
        assert await session.scalar(select(func.count()).select_from(AnalysisResult)) == 1
        assert await session.scalar(select(func.count()).select_from(BeatmapSource)) == 1
        assert await session.scalar(select(func.count()).select_from(OsuBeatmapMatch)) == 0


@pytest.mark.parametrize(
    ("fault", "status"), [("md5", 409), ("sha256", 409), ("id", 422), ("format", 422)]
)
async def test_failed_import_never_leaves_input_result_or_source(
    migrated_engine: AsyncEngine,
    database_settings: Settings,
    data: bytes,
    fault: str,
    status: int,
) -> None:
    if fault == "id":
        data = data.replace(b"BeatmapID: 123", b"BeatmapID: 999")
    if fault == "format":
        data = data.replace(b"format v14", b"format v13")
    metadata = batch(data)

    def remote(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/osu/beatmaps/batch":
            return httpx.Response(200, json=metadata)
        return httpx.Response(200, content=data + (b"\n// changed" if fault == "md5" else b""))

    api = HinamizawaClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(remote)), sleep=no_delay
    )
    app = create_app(database_settings)
    async with app.router.lifespan_context(app):
        app.state.database.session_factory.configure(bind=migrated_engine)
        app.state.mirror_import.api = api
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/imports/hinamizawa/123",
                params={"expected_sha256": "0" * 64} if fault == "sha256" else {},
            )
            assert response.status_code == status, response.text
    await api.close()
    sessions = async_sessionmaker(migrated_engine)
    async with sessions() as session:
        for model in (BeatmapInput, AnalysisResult, BeatmapSource):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_source_constraint_failure_rolls_back_analysis(
    migrated_engine: AsyncEngine,
    candidate: PreparedAnalysis,
    receipt: SourceReceipt,
) -> None:
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    with pytest.raises(DBAPIError):
        async with sessions() as session, session.begin():
            result = await save_analysis(session, candidate)
            await save_source(
                session, result.record.beatmap.input_id, replace(receipt, adapter_version="x" * 65)
            )
    async with sessions() as session:
        for model in (BeatmapInput, AnalysisResult, BeatmapSource):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_concurrent_source_observations_preserve_latest_and_version_identity(
    migrated_engine: AsyncEngine,
    candidate: PreparedAnalysis,
    receipt: SourceReceipt,
) -> None:
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sessions() as session, session.begin():
        original = await save_analysis(session, candidate)
    older = replace(
        receipt,
        file_fetched_at=receipt.file_fetched_at - timedelta(hours=1),
        file_source_layer="old",
    )
    barrier = asyncio.Barrier(4)

    async def save(item: SourceReceipt) -> None:
        async with sessions() as session, session.begin():
            await barrier.wait()
            await save_source(session, original.record.beatmap.input_id, item)

    await asyncio.gather(save(receipt), save(older), save(receipt), save(older))
    async with sessions() as session, session.begin():
        await save_source(
            session,
            original.record.beatmap.input_id,
            replace(receipt, adapter_version="hinamizawa/test-next"),
        )
    async with sessions() as session:
        result = await get_analysis(session, original.record.id)
        assert result is not None
        assert len(result.beatmap.sources) == 2
        assert all(source.file_source_layer != "old" for source in result.beatmap.sources)
        assert result.beatmap.sources[0].file_fetched_at == receipt.file_fetched_at
        assert result.beatmap.identity_status == "unverified"
        page = await list_analyses(session, limit=1, after_id=0)
        assert page.items == (result,) and page.next_after_id is None


async def test_receipt_for_other_bytes_cannot_be_attached(
    migrated_engine: AsyncEngine,
    candidate: PreparedAnalysis,
    receipt: SourceReceipt,
) -> None:
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sessions() as session, session.begin():
        result = await save_analysis(session, candidate)
    with pytest.raises(ValueError, match="does not match"):
        async with sessions() as session, session.begin():
            await save_source(
                session, result.record.beatmap.input_id, replace(receipt, source_sha256=b"0" * 32)
            )
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(BeatmapSource)) == 0


async def test_recent_official_checksum_conflict_rejects_mirror_before_download(
    migrated_engine: AsyncEngine,
    database_settings: Settings,
    candidate: PreparedAnalysis,
    data: bytes,
) -> None:
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        result = await save_analysis(session, candidate)
        await save_match(
            session,
            result.record.beatmap.input_id,
            OsuMetadata(
                123,
                456,
                candidate.source_md5.hex(),
                "Official",
                "Artist",
                "Creator",
                7,
                "Difficulty",
                "ranked",
                now,
                now,
            ),
        )
    requests: list[httpx.Request] = []

    def remote(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/v3/osu/beatmaps/batch"
        return httpx.Response(200, json=batch(data + b"\n// different revision"))

    api = HinamizawaClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(remote)), sleep=no_delay
    )
    app = create_app(database_settings)
    async with app.router.lifespan_context(app):
        app.state.database.session_factory.configure(bind=migrated_engine)
        app.state.mirror_import.api = api
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/imports/hinamizawa/123")
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "mirror_checksum_mismatch"
    await api.close()
    assert len(requests) == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(BeatmapInput)) == 1
        assert await session.scalar(select(func.count()).select_from(AnalysisResult)) == 1
        assert await session.scalar(select(func.count()).select_from(BeatmapSource)) == 0
