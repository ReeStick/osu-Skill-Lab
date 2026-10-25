from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from osu_skill_lab.api.imports import mirror_import_service
from osu_skill_lab.application.mirror_import import MirrorImportService
from osu_skill_lab.application.sources import MirrorError
from osu_skill_lab.config import Settings
from osu_skill_lab.main import create_app


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("mirror_not_found", 404),
        ("mirror_checksum_unavailable", 409),
        ("mirror_checksum_mismatch", 409),
        ("mirror_unsupported_ruleset", 422),
        ("mirror_unsupported_encoding", 422),
        ("mirror_busy", 429),
        ("mirror_rate_limited", 429),
        ("mirror_unresolved", 503),
        ("mirror_unavailable", 503),
        ("mirror_timeout", 504),
        ("mirror_bad_response", 502),
    ],
)
async def test_import_errors_expose_selected_contract(code: str, status: int) -> None:
    service = AsyncMock(spec=MirrorImportService)
    service.import_id.side_effect = MirrorError(
        code, "Public failure", retryable=True, retry_after=60
    )
    app = create_app(
        Settings(_env_file=None, database_url=SecretStr("postgresql+asyncpg://x@localhost/test"))
    )
    app.dependency_overrides[mirror_import_service] = lambda: cast(MirrorImportService, service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/imports/hinamizawa/123")
    assert response.status_code == status
    assert response.json() == {
        "detail": {"code": code, "message": "Public failure", "retryable": True}
    }
    assert response.headers["Retry-After"] == "60"
    service.import_id.assert_awaited_once_with(123, expected_sha256=None)


@pytest.mark.parametrize(
    "target", ["0", "-1", "1000000000001", "invalid", "123?expected_sha256=wrong"]
)
async def test_invalid_import_parameters_are_rejected_before_network(target: str) -> None:
    service = AsyncMock(spec=MirrorImportService)
    app = create_app(
        Settings(_env_file=None, database_url=SecretStr("postgresql+asyncpg://x@localhost/test"))
    )
    app.dependency_overrides[mirror_import_service] = lambda: cast(MirrorImportService, service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/imports/hinamizawa/" + target)
    assert response.status_code == 422
    service.import_id.assert_not_called()
