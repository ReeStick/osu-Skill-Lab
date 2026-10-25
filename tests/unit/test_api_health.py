import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from asyncpg import InvalidPasswordError
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.main import create_app


def settings(timeout: float = 1.0) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr("postgresql+asyncpg://unused:unused@127.0.0.1:1/unit_test"),
        database_timeout_seconds=timeout,
    )


@asynccontextmanager
async def client_for(configuration: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(configuration)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


async def test_liveness_does_not_access_database(monkeypatch: pytest.MonkeyPatch) -> None:
    ping = AsyncMock(side_effect=AssertionError("Liveness must not access the database"))
    monkeypatch.setattr(Database, "ping", ping)
    async with client_for(settings()) as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    ping.assert_not_awaited()


async def test_readiness_reports_healthy_database(monkeypatch: pytest.MonkeyPatch) -> None:
    ping = AsyncMock()
    monkeypatch.setattr(Database, "ping", ping)
    async with client_for(settings()) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    ping.assert_awaited_once()


@pytest.mark.parametrize(
    "failure",
    [
        OSError("private-password"),
        OperationalError("SELECT 1", {}, Exception("private-password")),
        InvalidPasswordError("private-password"),
        TimeoutError("private-password"),
    ],
)
async def test_database_failures_return_503_without_secrets(
    failure: Exception, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(Database, "ping", AsyncMock(side_effect=failure))
    async with client_for(settings()) as client:
        response = await client.get("/health/ready")
        assert (await client.get("/health/live")).status_code == 200
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
    assert "private-password" not in response.text + caplog.text


async def test_readiness_has_total_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def blocked_ping(self: Database) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(Database, "ping", blocked_ping)
    async with client_for(settings(timeout=0.02)) as client:
        assert (await client.get("/health/ready")).status_code == 503


async def test_lifespan_disposes_database(monkeypatch: pytest.MonkeyPatch) -> None:
    close = AsyncMock()
    monkeypatch.setattr(Database, "close", close)
    app = create_app(settings())
    async with app.router.lifespan_context(app):
        close.assert_not_awaited()
    close.assert_awaited_once()


async def test_openapi_documents_readiness_failure() -> None:
    async with client_for(settings()) as client:
        schema = (await client.get("/openapi.json")).json()
    assert "503" in schema["paths"]["/health/ready"]["get"]["responses"]
