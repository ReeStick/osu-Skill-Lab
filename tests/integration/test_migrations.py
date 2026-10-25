from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def exercise_migrations(connection: Connection) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    command.upgrade(config, "head")
    assert MigrationContext.configure(connection).get_current_revision() == head
    command.upgrade(config, "head")
    assert MigrationContext.configure(connection).get_current_revision() == head
    command.check(config)
    command.downgrade(config, "base")
    assert MigrationContext.configure(connection).get_current_revision() is None
    command.upgrade(config, "head")
    assert MigrationContext.configure(connection).get_current_revision() == head
    assert inspect(connection).get_table_names() == ["alembic_version"]


async def test_upgrade_check_downgrade_and_repeat(schema_engine: AsyncEngine) -> None:
    async with schema_engine.begin() as connection:
        await connection.run_sync(exercise_migrations)
