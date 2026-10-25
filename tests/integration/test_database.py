import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.database import Database

pytestmark = pytest.mark.integration


async def test_database_ping_and_explicit_transactions(database_settings: Settings) -> None:
    database = Database(database_settings)
    try:
        await database.ping()
        async with database.session() as session, session.begin():
            assert await session.scalar(text("SELECT 42")) == 42
    finally:
        await database.close()


async def test_session_rolls_back_uncommitted_work(
    schema_engine: AsyncEngine, database_settings: Settings
) -> None:
    async with schema_engine.begin() as connection:
        await connection.execute(text("CREATE TABLE transaction_probe (value integer NOT NULL)"))
    database = Database(database_settings)
    database.session_factory.configure(bind=schema_engine)
    try:
        async with database.session() as session:
            await session.execute(text("INSERT INTO transaction_probe VALUES (1)"))
        async with database.session() as session:
            assert await session.scalar(text("SELECT count(*) FROM transaction_probe")) == 0
            await session.execute(text("INSERT INTO transaction_probe VALUES (2)"))
            await session.commit()
        async with database.session() as session:
            assert await session.scalar(text("SELECT value FROM transaction_probe")) == 2
        with pytest.raises(RuntimeError, match="use case failed"):
            async with database.session() as session:
                await session.execute(text("INSERT INTO transaction_probe VALUES (3)"))
                raise RuntimeError("use case failed")
        async with database.session() as session:
            assert await session.scalar(text("SELECT count(*) FROM transaction_probe")) == 1
    finally:
        await database.close()
