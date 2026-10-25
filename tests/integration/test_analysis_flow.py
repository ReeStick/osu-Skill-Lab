from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.models import AnalysisResult, BeatmapInput
from osu_skill_lab.main import create_app

pytestmark = pytest.mark.integration
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "analytic-v14.osu"


async def test_upload_process_persist_delete_input_and_retrieve(
    migrated_engine: AsyncEngine,
    database_settings: Settings,
    tmp_path: Path,
) -> None:
    delivery = tmp_path / "temporary-delivery.osu"
    delivery.write_bytes(FIXTURE.read_bytes())
    payload = delivery.read_bytes()
    app = create_app(database_settings)
    async with app.router.lifespan_context(app):
        app.state.database.session_factory.configure(bind=migrated_engine)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/analyses", content=payload, headers={"Content-Type": "application/octet-stream"}
            )
            assert response.status_code == 201, response.text
            record = response.json()
            delivery.unlink()
            assert not delivery.exists()
            assert record["features"]["hit_object_count"] == 4
            assert record["features"]["head_pair_count"] == 2
            assert record["beatmap"]["identity_status"] == "unverified"
            repeated = await client.post("/analyses", content=payload)
            assert repeated.status_code == 200, repeated.text
            assert repeated.json() == record
            fetched = await client.get(f"/analyses/{record['id']}")
            assert fetched.status_code == 200
            assert fetched.json() == record
            page = (await client.get("/analyses?limit=1")).json()
            assert page["items"] == [record]
            assert page["next_after_id"] is None
            rejected = await client.post("/analyses", content=b"not a beatmap")
            assert rejected.status_code == 422
            assert rejected.json()["detail"]["code"] == "invalid_header"
    sessions = async_sessionmaker(migrated_engine)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(BeatmapInput)) == 1
        assert await session.scalar(select(func.count()).select_from(AnalysisResult)) == 1
