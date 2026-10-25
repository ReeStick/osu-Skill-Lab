from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from osu_skill_lab.application.service import AnalysisService
from osu_skill_lab.infrastructure.database import Database


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


async def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    async with database.session() as session:
        yield session


def get_analysis_service(request: Request) -> AnalysisService:
    return cast(AnalysisService, request.app.state.analysis_service)
