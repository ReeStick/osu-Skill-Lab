import asyncio
import logging
from typing import Annotated, Literal, cast

from asyncpg import PostgresError
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from osu_skill_lab.api.dependencies import get_database
from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.database import Database

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unavailable"]


@router.get("/live")
async def liveness() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    responses={503: {"model": ReadinessResponse, "description": "Database unavailable"}},
)
async def readiness(
    request: Request,
    response: Response,
    database: Annotated[Database, Depends(get_database)],
) -> ReadinessResponse:
    settings = cast(Settings, request.app.state.settings)
    try:
        async with asyncio.timeout(settings.database_timeout_seconds):
            await database.ping()
    except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
        # Connection messages can contain credentials or server details.
        logger.warning("Database readiness failed (%s)", type(exc).__name__)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="unavailable", database="unavailable")
    return ReadinessResponse(status="ok", database="ok")
