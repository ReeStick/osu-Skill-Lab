import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from osu_skill_lab.application.osu_metadata import OsuApiError
from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.osu_api import OsuApiClient

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "osu-api-metadata.json"
MD5 = "a" * 32


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds
        await asyncio.sleep(0)


class Remote:
    def __init__(self, payload: dict[str, object], clock: FakeClock) -> None:
        self.payload, self.clock = payload, clock
        self.requests: list[httpx.Request] = []
        self.times: list[float] = []
        self.status = 200
        self.token_status = 200
        self.first_unauthorized = False
        self.failure: httpx.HTTPError | None = None
        self.raw: bytes | None = None
        self.token_raw: bytes | None = None
        self.retry_after = "120"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.times.append(self.clock())
        assert request.url.host == "osu.ppy.sh"
        if request.url.path == "/oauth/token":
            assert request.method == "POST"
            assert "Authorization" not in request.headers
            if self.token_raw is not None:
                return httpx.Response(self.token_status, content=self.token_raw)
            return httpx.Response(
                self.token_status,
                json={
                    "access_token": "private-bearer-token",
                    "token_type": "Bearer",
                    "expires_in": 120,
                },
            )
        assert request.url.path == "/api/v2/beatmaps/lookup"
        assert request.headers["Authorization"] == "Bearer private-bearer-token"
        assert request.headers["x-api-version"] == "20240529"
        assert set(request.url.params) == {"checksum"}
        if self.failure is not None:
            raise self.failure
        if self.first_unauthorized:
            self.first_unauthorized = False
            return httpx.Response(401)
        if self.raw is not None:
            return httpx.Response(self.status, content=self.raw)
        return httpx.Response(
            self.status, json=self.payload, headers={"Retry-After": self.retry_after}
        )


@pytest.fixture
def payload() -> dict[str, object]:
    return dict(json.loads(FIXTURE.read_text(encoding="utf-8")))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def remote(payload: dict[str, object], clock: FakeClock) -> Remote:
    return Remote(payload, clock)


@pytest.fixture
async def api(remote: Remote, clock: FakeClock) -> AsyncIterator[OsuApiClient]:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr("postgresql+asyncpg://unused@localhost/unit_test"),
        osu_client_id=123,
        osu_client_secret=SecretStr("private-client-secret"),
    )
    client = OsuApiClient(
        settings,
        http=httpx.AsyncClient(transport=httpx.MockTransport(remote)),
        clock=clock,
        sleep=clock.sleep,
    )
    try:
        yield client
    finally:
        await client.close()


async def test_lookup_uses_guest_oauth_and_selects_only_bounded_metadata(
    api: OsuApiClient,
    remote: Remote,
) -> None:
    metadata = await api.lookup_checksum(MD5)
    assert metadata.beatmap_id == 123
    assert metadata.md5 == MD5
    assert metadata.title == "Synthetic API title"
    assert metadata.creator_id == 7
    assert "difficulty_rating" not in asdict(metadata)
    assert "failtimes" not in asdict(metadata)
    token_request = remote.requests[0].content.decode()
    assert "grant_type=client_credentials" in token_request
    assert "scope=public" in token_request
    assert "client_secret=private-client-secret" in token_request
    assert remote.times[1] - remote.times[0] >= 1.05 - 1e-9


async def test_concurrent_repeats_share_lookup_and_token(api: OsuApiClient, remote: Remote) -> None:
    metadata = await asyncio.gather(*(api.lookup_checksum(MD5) for _ in range(10)))
    assert all(item == metadata[0] for item in metadata)
    assert len(remote.requests) == 2


async def test_expired_cache_is_refetched_and_expired_token_reacquired(
    api: OsuApiClient,
    remote: Remote,
    clock: FakeClock,
) -> None:
    await api.lookup_checksum(MD5)
    clock.now += 3601
    await api.lookup_checksum(MD5)
    assert [request.url.path for request in remote.requests] == [
        "/oauth/token",
        "/api/v2/beatmaps/lookup",
        "/oauth/token",
        "/api/v2/beatmaps/lookup",
    ]


async def test_401_refreshes_token_and_retries_exactly_once(
    api: OsuApiClient, remote: Remote
) -> None:
    remote.first_unauthorized = True
    assert (await api.lookup_checksum(MD5)).beatmap_id == 123
    assert len(remote.requests) == 4
    assert all(
        right - left >= 1.05 - 1e-9
        for left, right in zip(remote.times, remote.times[1:], strict=False)
    )


async def test_second_401_is_not_retried_again(api: OsuApiClient, remote: Remote) -> None:
    remote.status = 401
    with pytest.raises(OsuApiError) as error:
        await api.lookup_checksum(MD5)
    assert error.value.code == "osu_auth_failed"
    assert len(remote.requests) == 4


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (403, "osu_auth_failed"),
        (404, "osu_not_found"),
        (500, "osu_unavailable"),
        (302, "osu_unavailable"),
    ],
)
async def test_status_failures_are_cached_without_extra_requests(
    api: OsuApiClient,
    remote: Remote,
    status: int,
    code: str,
) -> None:
    remote.status = status
    for _ in range(2):
        with pytest.raises(OsuApiError) as error:
            await api.lookup_checksum(MD5)
        assert error.value.code == code
    assert len(remote.requests) == 2


async def test_429_sets_shared_cooldown_and_honours_retry_after(
    api: OsuApiClient,
    remote: Remote,
    clock: FakeClock,
) -> None:
    remote.status = 429
    with pytest.raises(OsuApiError) as error:
        await api.lookup_checksum(MD5)
    assert error.value.code == "osu_rate_limited"
    assert error.value.retry_after == 120
    with pytest.raises(OsuApiError):
        await api.lookup_checksum("b" * 32)
    assert len(remote.requests) == 2
    clock.now += 121
    remote.status = 200
    await api.lookup_checksum(MD5)
    assert len(remote.requests) == 4  # Token has also expired.


@pytest.mark.parametrize(
    "field", ["id", "checksum", "mode", "version", "last_updated", "beatmapset"]
)
async def test_invalid_metadata_is_rejected(api: OsuApiClient, remote: Remote, field: str) -> None:
    invalid: dict[str, object] = {
        "id": True,
        "checksum": "bad",
        "mode": "unknown",
        "version": "bad\x00title",
        "last_updated": "2026-01-01T00:00:00",
        "beatmapset": None,
    }
    remote.payload[field] = invalid[field]
    with pytest.raises(OsuApiError) as error:
        await api.lookup_checksum(MD5)
    assert error.value.code == "osu_bad_response"


async def test_missing_checksum_is_explicitly_nullable_metadata(
    api: OsuApiClient, remote: Remote
) -> None:
    remote.payload["checksum"] = None
    assert (await api.lookup_checksum(MD5)).md5 is None


async def test_nonstandard_ruleset_is_rejected(api: OsuApiClient, remote: Remote) -> None:
    remote.payload["mode"] = "mania"
    with pytest.raises(OsuApiError) as error:
        await api.lookup_checksum(MD5)
    assert error.value.code == "osu_unsupported_ruleset"


@pytest.mark.parametrize(
    "body", [b"not JSON", b"x" * (512 * 1024 + 1)], ids=["malformed", "oversized"]
)
async def test_malformed_and_oversized_response_is_bounded(
    api: OsuApiClient,
    remote: Remote,
    body: bytes,
) -> None:
    remote.raw = body
    with pytest.raises(OsuApiError) as error:
        await api.lookup_checksum(MD5)
    assert error.value.code == "osu_bad_response"


@pytest.mark.parametrize("is_timeout", [True, False])
async def test_transport_errors_do_not_leak_secrets(
    api: OsuApiClient,
    remote: Remote,
    caplog: pytest.LogCaptureFixture,
    is_timeout: bool,
) -> None:
    exception = httpx.ReadTimeout if is_timeout else httpx.ConnectError
    remote.failure = exception("private-client-secret private-bearer-token")
    with pytest.raises(OsuApiError) as error:
        await api.lookup_checksum(MD5)
    assert error.value.code == ("osu_timeout" if is_timeout else "osu_unavailable")
    assert "private-client-secret" not in str(error.value) + caplog.text
    assert "private-bearer-token" not in str(error.value) + caplog.text


@pytest.mark.parametrize(
    "body", [b"not JSON", b"{}", b"x" * (16 * 1024 + 1)], ids=["malformed", "missing", "oversized"]
)
async def test_invalid_oauth_response_does_not_reach_lookup(
    api: OsuApiClient,
    remote: Remote,
    body: bytes,
) -> None:
    remote.token_raw = body
    with pytest.raises(OsuApiError) as error:
        await api.lookup_checksum(MD5)
    assert error.value.code == "osu_bad_response"
    assert len(remote.requests) == 1


async def test_unconfigured_api_does_not_make_any_requests(remote: Remote) -> None:
    settings = Settings(
        _env_file=None, database_url=SecretStr("postgresql+asyncpg://x@localhost/test")
    )
    client = OsuApiClient(settings, http=httpx.AsyncClient(transport=httpx.MockTransport(remote)))
    try:
        with pytest.raises(OsuApiError) as error:
            await client.lookup_checksum(MD5)
        assert error.value.code == "osu_not_configured"
        assert not remote.requests
    finally:
        await client.close()


async def test_bad_credentials_pause_other_checksums_without_misreporting_rate_limit(
    api: OsuApiClient,
    remote: Remote,
) -> None:
    remote.token_status = 401
    for checksum in (MD5, "b" * 32):
        with pytest.raises(OsuApiError) as error:
            await api.lookup_checksum(checksum)
        assert error.value.code == "osu_auth_failed"
    assert len(remote.requests) == 1


async def test_cancellation_closes_request_and_prevents_immediate_repoll(
    payload: dict[str, object],
    clock: FakeClock,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def remote(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/oauth/token":
            return httpx.Response(
                200, json={"access_token": "token", "token_type": "Bearer", "expires_in": 120}
            )
        entered.set()
        await release.wait()
        return httpx.Response(200, json=payload)

    settings = Settings(
        _env_file=None,
        database_url=SecretStr("postgresql+asyncpg://x@localhost/test"),
        osu_client_id=1,
        osu_client_secret=SecretStr("secret"),
    )
    client = OsuApiClient(
        settings,
        http=httpx.AsyncClient(transport=httpx.MockTransport(remote)),
        clock=clock,
        sleep=clock.sleep,
    )
    try:
        running = asyncio.create_task(client.lookup_checksum(MD5))
        async with asyncio.timeout(2):
            await entered.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        with pytest.raises(OsuApiError) as error:
            await client.lookup_checksum(MD5)
        assert error.value.code == "osu_rate_limited"
        assert calls == 2
        clock.now += 61
        release.set()
        assert (await client.lookup_checksum(MD5)).beatmap_id == 123
        assert calls == 3
    finally:
        await client.close()
