"""Shared pacing/cooldown for every Hinamizawa network operation."""

import asyncio
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from asyncpg import PostgresError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from osu_skill_lab.application.service import AnalysisUnavailableError
from osu_skill_lab.application.sources import MirrorError
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.infrastructure.job_models import ProviderBudget


class PostgresMirrorBudget:
    def __init__(self, database: Database) -> None:
        self.database = database

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncSession]:
        try:
            async with self.database.session() as session, session.begin():
                yield session
        except (SQLAlchemyError, PostgresError, OSError, TimeoutError):
            raise AnalysisUnavailableError("Mirror request budget unavailable") from None

    async def wait_turn(self) -> None:
        while True:
            async with self._transaction() as session:
                await session.execute(
                    insert(ProviderBudget)
                    .values(
                        provider="hinamizawa",
                        next_request_at=func.clock_timestamp(),
                        blocked_until=func.clock_timestamp(),
                    )
                    .on_conflict_do_nothing()
                )
                row = await session.scalar(
                    select(ProviderBudget)
                    .where(
                        ProviderBudget.provider == "hinamizawa",
                    )
                    .with_for_update()
                )
                assert row is not None
                now = await session.scalar(select(func.clock_timestamp()))
                assert now is not None
                if row.blocked_until > now:
                    raise MirrorError(
                        "mirror_rate_limited",
                        "Mirror requests are paused",
                        retryable=True,
                        retry_after=max(1, math.ceil((row.blocked_until - now).total_seconds())),
                    )
                delay = (row.next_request_at - now).total_seconds()
                if delay <= 0:
                    row.next_request_at = now + timedelta(seconds=1.05)
                    return
            await asyncio.sleep(min(delay, 1.05))

    async def pause(self, seconds: int) -> None:
        async with self._transaction() as session:
            statement = insert(ProviderBudget).values(
                provider="hinamizawa",
                next_request_at=func.clock_timestamp(),
                blocked_until=func.clock_timestamp() + timedelta(seconds=seconds),
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[ProviderBudget.provider],
                    set_={
                        "blocked_until": func.greatest(
                            ProviderBudget.blocked_until,
                            statement.excluded.blocked_until,
                        )
                    },
                )
            )
