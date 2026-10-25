import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from osu_skill_lab.application.osu_metadata import OsuApiError, OsuMetadata
from osu_skill_lab.application.osu_verification import OsuVerificationService
from osu_skill_lab.application.preparation import PreparedAnalysis, prepare_analysis
from osu_skill_lab.application.service import AnalysisService
from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.analysis_repository import (
    get_analysis,
    list_analyses,
    save_analysis,
)
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.infrastructure.models import AnalysisResult, BeatmapInput, OsuBeatmapMatch
from osu_skill_lab.infrastructure.osu_api import OsuApiClient
from osu_skill_lab.infrastructure.osu_repository import save_match
from osu_skill_lab.main import create_app

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def candidate() -> PreparedAnalysis:
    data = FIXTURES.joinpath("analytic-v14.osu").read_bytes()
    result = prepare_analysis(data)
    assert isinstance(result, PreparedAnalysis)
    return result


@pytest.fixture
def metadata(candidate: PreparedAnalysis) -> OsuMetadata:
    now = datetime.now(UTC)
    return OsuMetadata(
        123,
        456,
        candidate.source_md5.hex(),
        "API title",
        "API artist",
        "Set creator",
        7,
        "API difficulty",
        "ranked",
        now - timedelta(days=1),
        now,
    )


@pytest.fixture
def payload() -> dict[str, object]:
    return dict(json.loads(FIXTURES.joinpath("osu-api-metadata.json").read_text(encoding="utf-8")))


async def test_upload_verify_persist_cache_and_read_across_app_restart(
    migrated_engine: AsyncEngine,
    database_settings: Settings,
    payload: dict[str, object],
    candidate: PreparedAnalysis,
) -> None:
    requests: list[httpx.Request] = []

    def remote(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/oauth/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "synthetic-token",
                    "token_type": "Bearer",
                    "expires_in": 86400,
                },
            )
        assert request.url.params["checksum"] == candidate.source_md5.hex()
        return httpx.Response(200, json={**payload, "checksum": candidate.source_md5.hex()})

    async def no_delay(seconds: float) -> None:
        await asyncio.sleep(0)

    settings = database_settings.model_copy(
        update={"osu_client_id": 1, "osu_client_secret": SecretStr("synthetic-secret")}
    )
    api = OsuApiClient(
        settings, http=httpx.AsyncClient(transport=httpx.MockTransport(remote)), sleep=no_delay
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        app.state.database.session_factory.configure(bind=migrated_engine)
        app.state.osu_verification.api = api
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            original = await client.post(
                "/analyses", content=FIXTURES.joinpath("analytic-v14.osu").read_bytes()
            )
            assert original.status_code == 201
            identifier = original.json()["id"]
            assert original.json()["beatmap"]["identity_status"] == "unverified"
            verified = await client.post(f"/analyses/{identifier}/verify-osu")
            assert verified.status_code == 200, verified.text
            result = verified.json()
            assert result["beatmap"]["identity_status"] == "checksum_match"
            assert result["beatmap"]["osu"]["beatmap_id"] == 123
            assert result["beatmap"]["claimed_ids_match"] is None
            assert result["beatmap"]["title"] == original.json()["beatmap"]["title"]
            assert result["beatmap"]["osu"]["title"] == "Synthetic API title"
            assert result["features"] == original.json()["features"]
            assert "difficulty_rating" not in result["beatmap"]["osu"]
            repeated = await client.post(f"/analyses/{identifier}/verify-osu")
            assert repeated.json() == result
            assert len(requests) == 2
            assert (await client.get(f"/analyses/{identifier}")).json() == result
    await api.close()
    # Fresh app without credentials still serves a fresh match from PostgreSQL.
    restarted = create_app(database_settings)
    async with restarted.router.lifespan_context(restarted):
        restarted.state.database.session_factory.configure(bind=migrated_engine)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://test"
        ) as client:
            assert (await client.post(f"/analyses/{identifier}/verify-osu")).json() == result
    sessions = async_sessionmaker(migrated_engine)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(BeatmapInput)) == 1
        assert await session.scalar(select(func.count()).select_from(AnalysisResult)) == 1
        assert await session.scalar(select(func.count()).select_from(OsuBeatmapMatch)) == 1


@pytest.mark.parametrize("checksum", [None, "b" * 32])
async def test_missing_or_different_checksum_never_creates_match(
    migrated_engine: AsyncEngine,
    candidate: PreparedAnalysis,
    metadata: OsuMetadata,
    checksum: str | None,
) -> None:
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sessions() as session, session.begin():
        outcome = await save_analysis(session, candidate)
    with pytest.raises(OsuApiError, match="checksum"):
        async with sessions() as session, session.begin():
            await save_match(
                session, outcome.record.beatmap.input_id, replace(metadata, md5=checksum)
            )
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(OsuBeatmapMatch)) == 0
        assert await get_analysis(session, outcome.record.id) == outcome.record


async def test_concurrent_metadata_refresh_keeps_newest_observation_and_file_claims(
    migrated_engine: AsyncEngine,
    candidate: PreparedAnalysis,
    metadata: OsuMetadata,
) -> None:
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    candidate = replace(candidate, metadata=replace(candidate.metadata, beatmap_id=999))
    async with sessions() as session, session.begin():
        outcome = await save_analysis(session, candidate)
    old = replace(metadata, title="Old title", fetched_at=metadata.fetched_at - timedelta(hours=1))
    barrier = asyncio.Barrier(4)

    async def persist(item: OsuMetadata) -> None:
        async with sessions() as session, session.begin():
            await barrier.wait()
            await save_match(session, outcome.record.beatmap.input_id, item)

    await asyncio.gather(persist(metadata), persist(old), persist(metadata), persist(old))
    async with sessions() as session:
        record = await get_analysis(session, outcome.record.id)
        assert record is not None
        assert record.beatmap.osu == metadata
        assert record.beatmap.claimed_beatmap_id == 999
        assert record.beatmap.claimed_ids_match is False
        page = await list_analyses(session, limit=20, after_id=0)
        assert page.items == (record,)
        assert await session.scalar(select(func.count()).select_from(OsuBeatmapMatch)) == 1


async def test_expired_match_and_upstream_failure_leave_previous_observation_intact(
    migrated_engine: AsyncEngine,
    database_settings: Settings,
    candidate: PreparedAnalysis,
    metadata: OsuMetadata,
) -> None:
    database = Database(database_settings)
    database.session_factory.configure(bind=migrated_engine)
    async with database.session() as session, session.begin():
        outcome = await save_analysis(session, candidate)
        await save_match(
            session,
            outcome.record.beatmap.input_id,
            replace(metadata, fetched_at=metadata.fetched_at - timedelta(hours=2)),
        )
    api = AsyncMock(spec=OsuApiClient)
    api.lookup_checksum.side_effect = OsuApiError("osu_timeout", "Upstream timeout")
    analyses = AsyncMock(spec=AnalysisService)
    async with database.session() as session:
        previous = await get_analysis(session, outcome.record.id)
    analyses.get_analysis.return_value = previous
    service = OsuVerificationService(
        database, cast(AnalysisService, analyses), cast(OsuApiClient, api), cache_ttl=3600
    )
    try:
        with pytest.raises(OsuApiError, match="timeout"):
            await service.verify(outcome.record.id)
        async with database.session() as session:
            assert await get_analysis(session, outcome.record.id) == previous
    finally:
        await database.close()
