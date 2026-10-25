import asyncio
import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from osu_skill_lab.application.sources import MirrorError
from osu_skill_lab.infrastructure.hinamizawa import HinamizawaClient

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "analytic-v14.osu"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds
        await asyncio.sleep(0)


class Remote:
    def __init__(self, data: bytes, clock: Clock) -> None:
        self.data, self.clock = data, clock
        self.requests: list[httpx.Request] = []
        self.times: list[float] = []
        self.missing: set[int] = set()
        self.unresolved: set[int] = set()
        self.status = 200
        self.raw_status = 200
        self.mode = "osu"
        self.checksum: str | None = hashlib.md5(data, usedforsecurity=False).hexdigest()
        self.raw_override: bytes | None = None
        self.body_override: bytes | None = None
        self.corrupt: str | None = None
        self.failure: httpx.HTTPError | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.times.append(self.clock())
        assert request.url.host == "mirror.hinamizawa.ai"
        assert request.headers["User-Agent"].startswith("osu-skill-lab/")
        assert "Authorization" not in request.headers and "Cookie" not in request.headers
        if self.failure:
            raise self.failure
        if request.url.path.startswith("/api/osu/"):
            assert not request.url.params
            return httpx.Response(
                self.raw_status,
                content=self.raw_override if self.raw_override is not None else self.data,
                headers={
                    "ETag": 'W/"synthetic"',
                    "x-hinai-osu-source": "local_corpus",
                    "Retry-After": "90",
                },
            )
        assert request.url.path == "/v3/osu/beatmaps/batch"
        if self.body_override is not None:
            return httpx.Response(self.status, content=self.body_override)
        ids = [int(item) for item in request.url.params["ids"].split(",")]
        found = [
            identifier for identifier in ids if identifier not in self.missing | self.unresolved
        ]
        rows = [
            {
                "id": identifier,
                "beatmapset_id": 456,
                "mode": self.mode,
                "checksum": self.checksum,
                "last_updated": "2026-10-01T00:00:00Z",
                "hinai_source": "local_duckdb",
                "pp_data": {"never_import": 999},
            }
            for identifier in found
        ]
        if self.corrupt == "duplicate" and rows:
            rows.append(rows[0])
        if self.corrupt == "dropped":
            rows.clear()
        if self.corrupt == "unrequested":
            rows[0]["id"] = 999
        if self.corrupt == "requested":
            ids = [999]
        return httpx.Response(
            self.status,
            json={
                "success": True,
                "requested": {"ids": ids, "md5": []},
                "results": rows,
                "missing": {"ids": sorted(self.missing & set(ids)), "md5": []},
                "unresolved": {
                    "ids": sorted(self.unresolved & set(ids)),
                    "md5": [],
                    "reason": "upstream_cap",
                },
            },
            headers={"Retry-After": "90", "x-hinai-freshness": "local"},
        )


@pytest.fixture
def data() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def remote(data: bytes, clock: Clock) -> Remote:
    return Remote(data, clock)


@pytest.fixture
async def api(remote: Remote, clock: Clock) -> AsyncIterator[HinamizawaClient]:
    client = HinamizawaClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(remote)),
        clock=clock,
        sleep=clock.sleep,
    )
    try:
        yield client
    finally:
        await client.close()


async def test_batch_deduplicates_ids_and_preserves_missing_vs_unresolved(
    api: HinamizawaClient,
    remote: Remote,
) -> None:
    remote.missing = {124}
    remote.unresolved = {125}
    result = await api.resolve_ids([123, 124, 125, 123])
    assert [item.beatmap_id for item in result.items] == [123]
    assert [(item.beatmap_id, item.kind) for item in result.issues] == [
        (124, "missing"),
        (125, "unresolved"),
    ]
    assert result.issues[1].reason == "upstream_cap"
    assert remote.requests[0].url.params["ids"] == "123,124,125"
    assert await api.resolve_ids([123, 124, 125]) == result
    assert len(remote.requests) == 1


async def test_unresolved_cache_expires_without_turning_it_into_missing(
    api: HinamizawaClient,
    remote: Remote,
    clock: Clock,
) -> None:
    remote.unresolved = {123}
    assert (await api.resolve_ids([123])).issues[0].kind == "unresolved"
    clock.now += 61
    remote.unresolved.clear()
    assert (await api.resolve_ids([123])).items[0].beatmap_id == 123
    assert len(remote.requests) == 2


@pytest.mark.parametrize(
    "ids",
    [[], [0], [-1], [True], [10**12 + 1], list(range(1, 102))],
    ids=["empty", "zero", "negative", "bool", "overflow", "too_many"],
)
async def test_invalid_ids_never_reach_provider(
    api: HinamizawaClient, remote: Remote, ids: list[int]
) -> None:
    with pytest.raises(ValueError):
        await api.resolve_ids(ids)
    assert not remote.requests


@pytest.mark.parametrize("fault", ["duplicate", "dropped", "unrequested", "requested"])
async def test_inconsistent_batch_partition_is_rejected(
    api: HinamizawaClient,
    remote: Remote,
    fault: str,
) -> None:
    remote.corrupt = fault
    with pytest.raises(MirrorError) as error:
        await api.resolve_ids([123])
    assert error.value.code == "mirror_bad_response"


async def test_download_retains_exact_bytes_and_bounded_provenance(
    api: HinamizawaClient,
    remote: Remote,
    data: bytes,
) -> None:
    metadata = (await api.resolve_ids([123])).items[0]
    downloaded = await api.download(metadata)
    assert downloaded.data == data
    assert downloaded.receipt.source_sha256 == hashlib.sha256(data).digest()
    assert downloaded.receipt.provider == "hinamizawa"
    assert downloaded.receipt.metadata_source_layer == "local_duckdb"
    assert downloaded.receipt.file_source_layer == "local_corpus"
    assert downloaded.receipt.http_etag == 'W/"synthetic"'
    assert remote.times[1] - remote.times[0] >= 1.05 - 1e-9
    with pytest.raises(MirrorError) as error:
        await api.download(metadata)
    assert error.value.code == "mirror_rate_limited"
    assert len(remote.requests) == 2


async def test_metadata_without_checksum_does_not_download(
    api: HinamizawaClient, remote: Remote
) -> None:
    remote.checksum = None
    metadata = (await api.resolve_ids([123])).items[0]
    with pytest.raises(MirrorError) as error:
        await api.download(metadata)
    assert error.value.code == "mirror_checksum_unavailable"
    assert len(remote.requests) == 1


async def test_nonstandard_mode_does_not_download(api: HinamizawaClient, remote: Remote) -> None:
    remote.mode = "mania"
    metadata = (await api.resolve_ids([123])).items[0]
    with pytest.raises(MirrorError) as error:
        await api.download(metadata)
    assert error.value.code == "mirror_unsupported_ruleset"
    assert len(remote.requests) == 1


@pytest.mark.parametrize("kind", ["metadata_md5", "expected_sha256"])
async def test_checksum_mismatch_is_explicit(
    api: HinamizawaClient, remote: Remote, kind: str
) -> None:
    if kind == "metadata_md5":
        remote.checksum = "b" * 32
    metadata = (await api.resolve_ids([123])).items[0]
    with pytest.raises(MirrorError) as error:
        await api.download(
            metadata, expected_sha256="0" * 64 if kind == "expected_sha256" else None
        )
    assert error.value.code == "mirror_checksum_mismatch"


@pytest.mark.parametrize(
    "body",
    [b'{"error":"not a map"}', b"", b"x" * (4 * 1024 * 1024 + 1)],
    ids=["json_200", "empty_200", "too_large"],
)
async def test_invalid_download_body_is_not_accepted(
    api: HinamizawaClient,
    remote: Remote,
    body: bytes,
) -> None:
    metadata = (await api.resolve_ids([123])).items[0]
    remote.raw_override = body
    with pytest.raises(MirrorError) as error:
        await api.download(metadata)
    assert error.value.code in {"mirror_invalid_file", "mirror_response_too_large"}


@pytest.mark.parametrize("status", [429, 503])
async def test_upstream_cooldown_is_shared_without_retrying_other_ids(
    api: HinamizawaClient,
    remote: Remote,
    clock: Clock,
    status: int,
) -> None:
    remote.status = status
    with pytest.raises(MirrorError) as error:
        await api.resolve_ids([123])
    assert error.value.retry_after == 90
    with pytest.raises(MirrorError):
        await api.resolve_ids([124])
    assert len(remote.requests) == 1
    clock.now += 91
    remote.status = 200
    assert (await api.resolve_ids([124])).items[0].beatmap_id == 124


@pytest.mark.parametrize(
    "body", [b"not JSON", b"x" * (2 * 1024 * 1024 + 1)], ids=["bad_json", "oversize"]
)
async def test_metadata_body_is_bounded(api: HinamizawaClient, remote: Remote, body: bytes) -> None:
    remote.body_override = body
    with pytest.raises(MirrorError) as error:
        await api.resolve_ids([123])
    assert error.value.code in {"mirror_bad_response", "mirror_response_too_large"}


async def test_timeout_does_not_expose_transport_message(
    api: HinamizawaClient, remote: Remote
) -> None:
    remote.failure = httpx.ReadTimeout("private transport details")
    with pytest.raises(MirrorError) as error:
        await api.resolve_ids([123])
    assert error.value.code == "mirror_timeout" and error.value.retryable
    assert "private transport" not in str(error.value)


async def test_cancelled_exchange_releases_lock_and_applies_cooldown(
    data: bytes,
    clock: Clock,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    remote = Remote(data, clock)
    calls = 0

    async def blocked(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return remote(request)

    api = HinamizawaClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(blocked)),
        clock=clock,
        sleep=clock.sleep,
    )
    try:
        task = asyncio.create_task(api.resolve_ids([123]))
        async with asyncio.timeout(2):
            await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(MirrorError) as error:
            await api.resolve_ids([124])
        assert error.value.code == "mirror_rate_limited" and calls == 1
        clock.now += 61
        release.set()
        assert (await api.resolve_ids([124])).items[0].beatmap_id == 124
        assert calls == 2
    finally:
        await api.close()


async def test_utf16_is_explicitly_unsupported_without_transcoding(
    api: HinamizawaClient,
    remote: Remote,
) -> None:
    metadata = (await api.resolve_ids([123])).items[0]
    remote.raw_override = "osu file format v14\n".encode("utf-16")
    with pytest.raises(MirrorError) as error:
        await api.download(metadata)
    assert error.value.code == "mirror_unsupported_encoding"
