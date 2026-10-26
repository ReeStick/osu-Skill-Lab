from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from osu_skill_lab.api.batches import batch_service
from osu_skill_lab.application.batches import (
    BatchCapacityError,
    BatchConflict,
    BatchRequest,
    BatchService,
)
from osu_skill_lab.application.service import AnalysisUnavailableError
from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.infrastructure.provider_budget import PostgresMirrorBudget
from osu_skill_lab.infrastructure.rabbitmq import JobMessage
from osu_skill_lab.main import create_app


@pytest.mark.parametrize(
    "body",
    [
        {"items": []},
        {"items": [{"beatmap_id": 1}] * 101},
        {"items": [{"beatmap_id": True}]},
        {"items": [{"beatmap_id": "1"}]},
        {"items": [{"beatmap_id": 0}]},
        {"items": [{"beatmap_id": 10**12 + 1}]},
        {"items": [{"beatmap_id": 1, "expected_sha256": "bad"}]},
        {"provider": "unknown", "items": [{"beatmap_id": 1}]},
        {"items": [{"beatmap_id": 1, "url": "https://untrusted.invalid"}]},
        {"items": [{"beatmap_id": 1}, {"beatmap_id": 1, "expected_sha256": "0" * 64}]},
    ],
)
async def test_invalid_batch_never_reaches_persistence(body: dict[str, object]) -> None:
    service = AsyncMock(spec=BatchService)
    app = create_app(
        Settings(_env_file=None, database_url=SecretStr("postgresql+asyncpg://x@localhost/test"))
    )
    app.dependency_overrides[batch_service] = lambda: cast(BatchService, service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/analysis-batches", json=body, headers={"Idempotency-Key": str(uuid4())}
        )
    assert response.status_code == 422
    service.submit.assert_not_called()


def test_dedup_preserves_order_and_normalizes_fingerprint() -> None:
    first = BatchRequest.model_validate(
        {"items": [{"beatmap_id": 2}, {"beatmap_id": 1}, {"beatmap_id": 2}]}
    )
    second = BatchRequest.model_validate({"items": [{"beatmap_id": 2}, {"beatmap_id": 1}]})
    assert [item.beatmap_id for item in first.items] == [2, 1]
    assert first.fingerprint() == second.fingerprint()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (BatchConflict("Different request"), 409),
        (BatchCapacityError(), 429),
        (AnalysisUnavailableError("Private transport details"), 503),
    ],
)
async def test_admission_failures_and_no_credentials_in_error(
    error: Exception, status: int
) -> None:
    service = AsyncMock(spec=BatchService)
    service.submit.side_effect = error
    app = create_app(
        Settings(_env_file=None, database_url=SecretStr("postgresql+asyncpg://x@localhost/test"))
    )
    app.dependency_overrides[batch_service] = lambda: cast(BatchService, service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/analysis-batches",
            json={"items": [{"beatmap_id": 1}]},
            headers={"Idempotency-Key": str(uuid4())},
        )
    assert response.status_code == status
    assert "Private" not in response.text
    if status == 429:
        assert response.headers["Retry-After"] == "5"


@pytest.mark.parametrize(
    "data",
    [
        b'{"item_id":true}',
        b'{"item_id":1,"version":2}',
        b'{"item_id":-1}',
        b'{"item_id":1,"raw":"osu"}',
    ],
)
def test_notification_rejects_bad_identity_and_extra_payload(data: bytes) -> None:
    with pytest.raises(ValidationError):
        JobMessage.model_validate_json(data)


@pytest.mark.parametrize("key", [None, "invalid"])
async def test_idempotency_header_is_required_uuid(key: str | None) -> None:
    service = AsyncMock(spec=BatchService)
    app = create_app(
        Settings(_env_file=None, database_url=SecretStr("postgresql+asyncpg://x@localhost/test"))
    )
    app.dependency_overrides[batch_service] = lambda: cast(BatchService, service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            "/analysis-batches",
            json={"items": [{"beatmap_id": 1}]},
            headers={"Idempotency-Key": key} if key else {},
        )
    assert result.status_code == 422
    service.submit.assert_not_called()


@pytest.mark.parametrize("operation", ["wait", "pause"])
async def test_budget_storage_error_is_safe_unavailability(operation: str) -> None:
    class UnavailableDatabase:
        @asynccontextmanager
        async def session(self) -> AsyncIterator[AsyncSession]:
            raise SQLAlchemyError("private DSN details")
            yield  # pragma: no cover

    budget = PostgresMirrorBudget(cast(Database, UnavailableDatabase()))
    with pytest.raises(AnalysisUnavailableError, match="^Mirror request budget unavailable$"):
        if operation == "wait":
            await budget.wait_turn()
        else:
            await budget.pause(60)
