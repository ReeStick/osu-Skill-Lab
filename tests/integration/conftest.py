import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from osu_skill_lab.config import Settings


@pytest.fixture
def database_settings() -> Settings:
    url = os.getenv("OSU_LAB_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set OSU_LAB_TEST_DATABASE_URL to run PostgreSQL integration tests")
    settings = Settings(_env_file=None, environment="test", database_url=SecretStr(url))
    database = make_url(settings.database_url.get_secret_value()).database
    if database is None or not database.endswith("_test"):
        pytest.fail("Integration database name must end with _test; refusing to modify it")
    return settings


@pytest.fixture
async def schema_engine(database_settings: Settings) -> AsyncIterator[AsyncEngine]:
    url = database_settings.database_url.get_secret_value()
    admin_engine = create_async_engine(url, poolclass=NullPool)
    schema_name = f"test_{uuid4().hex}"
    async with admin_engine.begin() as connection:
        await connection.execute(CreateSchema(schema_name))
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema_name}},
    )
    try:
        yield engine
    finally:
        await engine.dispose()
        try:
            async with admin_engine.begin() as connection:
                await connection.execute(DropSchema(schema_name, cascade=True))
        finally:
            await admin_engine.dispose()
