import httpx
import pytest

from osu_skill_lab.config import Settings
from osu_skill_lab.main import create_app

pytestmark = pytest.mark.integration


async def test_readiness_uses_real_postgres(database_settings: Settings) -> None:
    app = create_app(database_settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
