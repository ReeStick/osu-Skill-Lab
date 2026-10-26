import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI

from osu_skill_lab.api.analyses import router as analyses_router
from osu_skill_lab.api.batches import router as batches_router
from osu_skill_lab.api.health import router as health_router
from osu_skill_lab.api.imports import router as imports_router
from osu_skill_lab.api.osu import router as osu_router
from osu_skill_lab.application.batches import BatchService
from osu_skill_lab.application.mirror_import import MirrorImportService
from osu_skill_lab.application.osu_verification import OsuVerificationService
from osu_skill_lab.application.service import AnalysisService
from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.infrastructure.hinamizawa import HinamizawaClient
from osu_skill_lab.infrastructure.osu_api import OsuApiClient
from osu_skill_lab.infrastructure.provider_budget import PostgresMirrorBudget


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(configuration)
        executor = ProcessPoolExecutor(max_workers=2)
        app.state.database = database
        app.state.analysis_service = AnalysisService(database, executor, max_in_flight=2)
        app.state.batch_service = BatchService(database)
        osu_api = OsuApiClient(configuration)
        mirror = HinamizawaClient(
            timeout=configuration.mirror_timeout_seconds,
            cache_ttl=configuration.mirror_cache_ttl_seconds,
            budget=PostgresMirrorBudget(database),
        )
        app.state.mirror_import = MirrorImportService(
            mirror,
            app.state.analysis_service,
            official_cache_ttl=configuration.osu_cache_ttl_seconds,
        )
        app.state.osu_verification = OsuVerificationService(
            database,
            app.state.analysis_service,
            osu_api,
            cache_ttl=configuration.osu_cache_ttl_seconds,
        )
        try:
            yield
        finally:
            try:
                await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)
            finally:
                try:
                    try:
                        await mirror.close()
                    finally:
                        await osu_api.close()
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
    app.include_router(osu_router)
    app.include_router(imports_router)
    app.include_router(batches_router)
    return app
