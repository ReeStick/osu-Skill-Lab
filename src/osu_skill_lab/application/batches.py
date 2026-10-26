"""Bounded HTTP contracts and transactional batch use cases."""

import hashlib
import json
import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from asyncpg import PostgresError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError

from osu_skill_lab.application.service import AnalysisUnavailableError
from osu_skill_lab.infrastructure.database import Database

logger = logging.getLogger(__name__)
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


class BatchItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    beatmap_id: Annotated[int, Field(strict=True, gt=0, le=10**12)]
    expected_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["hinamizawa"] = "hinamizawa"
    items: list[BatchItemRequest] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_items(self) -> "BatchRequest":
        seen: dict[int, BatchItemRequest] = {}
        for item in self.items:
            if item.beatmap_id in seen and seen[item.beatmap_id] != item:
                raise ValueError("Repeated ID has conflicting checksum pins")
            seen[item.beatmap_id] = item
        self.items = list(seen.values())
        return self

    def fingerprint(self) -> bytes:
        value = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(value.encode()).digest()


class BatchItemView(BaseModel):
    id: int
    beatmap_id: int
    status: str
    attempts: int
    expected_sha256: str | None
    observed_sha256: str | None
    analysis_id: int | None
    next_attempt_at: datetime | None
    error_code: str | None
    error_message: str | None


class BatchView(BaseModel):
    id: UUID
    provider: str
    status: str
    created_at: datetime
    cancel_requested_at: datetime | None
    algorithm_version: str
    parser_version: str
    configuration_sha256: str
    counts: dict[str, int]
    items: list[BatchItemView]


class BatchConflict(ValueError):
    pass


class BatchCapacityError(RuntimeError):
    pass


class BatchService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def submit(self, request: BatchRequest, key: UUID) -> BatchView:
        from osu_skill_lab.infrastructure import job_repository

        try:
            async with self.database.session() as session, session.begin():
                return await job_repository.submit(session, request, key)
        except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
            logger.warning("Batch persistence unavailable (%s)", type(exc).__name__)
            raise AnalysisUnavailableError("Batch storage unavailable") from None

    async def get(self, batch_id: UUID, *, cancel: bool = False) -> BatchView | None:
        from osu_skill_lab.infrastructure import job_repository

        try:
            async with self.database.session() as session, session.begin():
                if cancel:
                    await job_repository.cancel(session, batch_id)
                return await job_repository.get_batch(session, batch_id)
        except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
            logger.warning("Batch persistence unavailable (%s)", type(exc).__name__)
            raise AnalysisUnavailableError("Batch storage unavailable") from None
