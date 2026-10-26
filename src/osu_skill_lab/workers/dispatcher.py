import asyncio
import logging
from datetime import timedelta

from sqlalchemy import func, select

from osu_skill_lab.infrastructure import job_repository
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.infrastructure.job_models import AnalysisJob
from osu_skill_lab.infrastructure.rabbitmq import RabbitBroker

logger = logging.getLogger(__name__)


async def dispatch_once(database: Database, broker: RabbitBroker, *, limit: int = 20) -> int:
    async with database.session() as session, session.begin():
        await job_repository.recover_expired(session)
    sent = 0
    # A short transaction per notification avoids locking a whole batch over the network.
    for _ in range(limit):
        async with database.session() as session, session.begin():
            row = await session.scalar(
                select(AnalysisJob)
                .where(
                    AnalysisJob.status.in_({"queued", "retry_wait"}),
                    AnalysisJob.run_after <= func.clock_timestamp(),
                    AnalysisJob.delivery_after <= func.clock_timestamp(),
                )
                .order_by(AnalysisJob.delivery_after, AnalysisJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return sent
            await broker.publish(row.id)
            now = await session.scalar(select(func.clock_timestamp()))
            assert now is not None
            row.delivery_after = now + timedelta(seconds=30)
        sent += 1
    return sent


async def serve(database: Database, broker_url: str) -> None:
    while True:
        try:
            async with RabbitBroker(broker_url) as broker:
                while True:
                    await dispatch_once(database, broker)
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Dispatcher unavailable (%s)", type(exc).__name__)
            await asyncio.sleep(5)
