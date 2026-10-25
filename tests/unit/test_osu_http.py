from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from osu_skill_lab.api.osu import verification_service
from osu_skill_lab.application.osu_metadata import OsuApiError
from osu_skill_lab.application.osu_verification import OsuVerificationService
from osu_skill_lab.config import Settings
from osu_skill_lab.main import create_app


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("analysis_not_found", 404),
        ("osu_not_found", 404),
        ("osu_checksum_mismatch", 409),
        ("osu_checksum_unavailable", 409),
        ("osu_unsupported_ruleset", 422),
        ("osu_busy", 429),
        ("osu_rate_limited", 429),
        ("osu_not_configured", 503),
        ("osu_auth_failed", 503),
        ("osu_storage_unavailable", 503),
        ("osu_timeout", 504),
        ("osu_bad_response", 502),
        ("osu_unavailable", 502),
    ],
)
async def test_verification_errors_have_structured_public_contract(
    code: str, expected: int
) -> None:
    service = AsyncMock(spec=OsuVerificationService)
    service.verify.side_effect = OsuApiError(code, "Public failure", retry_after=60)
    app = create_app(
        Settings(_env_file=None, database_url=SecretStr("postgresql+asyncpg://x@localhost/test"))
    )
    app.dependency_overrides[verification_service] = lambda: cast(OsuVerificationService, service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/analyses/123/verify-osu")
    assert response.status_code == expected
    assert response.json() == {"detail": {"code": code, "message": "Public failure"}}
    assert response.headers["Retry-After"] == "60"
    service.verify.assert_awaited_once_with(123)


@pytest.mark.parametrize("identifier", ["0", "-1", "9223372036854775808", "invalid"])
async def test_verification_id_is_validated_before_external_access(identifier: str) -> None:
    service = AsyncMock(spec=OsuVerificationService)
    app = create_app(
        Settings(_env_file=None, database_url=SecretStr("postgresql+asyncpg://x@localhost/test"))
    )
    app.dependency_overrides[verification_service] = lambda: cast(OsuVerificationService, service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/analyses/{identifier}/verify-osu")
    assert response.status_code == 422
    service.verify.assert_not_called()
