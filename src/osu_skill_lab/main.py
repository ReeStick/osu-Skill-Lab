from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from osu_skill_lab.api.health import router as health_router
from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.database import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(configuration)
        app.state.database = database
        try:
            yield
        finally:
            await database.close()

    app = FastAPI(
        title="osu! Skill Lab",
        version="0.1.0",
        description="Backend foundation for reproducible osu!standard beatmap analysis.",
        lifespan=lifespan,
    )
    app.state.settings = configuration
    app.include_router(health_router)
    return app
