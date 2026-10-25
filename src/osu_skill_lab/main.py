import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI

from osu_skill_lab.api.analyses import router as analyses_router
from osu_skill_lab.api.health import router as health_router
from osu_skill_lab.application.service import AnalysisService
from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.database import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(configuration)
        executor = ProcessPoolExecutor(max_workers=2)
        app.state.database = database
        app.state.analysis_service = AnalysisService(database, executor, max_in_flight=2)
        try:
            yield
        finally:
            try:
                await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)
            finally:
                await database.close()

    app = FastAPI(
        title="osu! Skill Lab",
        version="0.1.0",
        description="Versioned osu!standard measurements with compact persisted results.",
        lifespan=lifespan,
    )
    app.state.settings = configuration
    app.include_router(health_router)
    app.include_router(analyses_router)
    return app
