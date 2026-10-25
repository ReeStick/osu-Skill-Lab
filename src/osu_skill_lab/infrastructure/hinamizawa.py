"""Metadata batches and bounded raw downloads from one explicit, credential-free provider."""

import asyncio
import hashlib
import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Annotated, Literal

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from osu_skill_lab.analysis.models import ParserLimits
from osu_skill_lab.application.sources import (
    DownloadedBeatmap,
    MirrorError,
    MirrorIssue,
    MirrorMetadata,
    MirrorResolution,
    SourceReceipt,
)

Identifier = Annotated[int, Field(strict=True, gt=0, le=10**12)]
Label = Annotated[str, Field(max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]


class Identifiers(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    ids: list[Identifier] = Field(max_length=100)
    md5: list[str] = Field(max_length=100)


class Unresolved(Identifiers):
    reason: Label | None = None


class MetadataRow(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: Identifier
    beatmapset_id: Identifier
    checksum: Annotated[str, Field(pattern=r"^[a-fA-F0-9]{32}$")] | None = None
    mode: Literal["osu", "taiko", "fruits", "mania"]
    last_updated: AwareDatetime
    hinai_source: Label | None = None


class BatchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    success: Literal[True]
    requested: Identifiers
    missing: Identifiers
    unresolved: Unresolved
    results: list[MetadataRow] = Field(max_length=100)


class HinamizawaClient:
    def __init__(
        self,
        *,
        timeout: float = 20,
        cache_ttl: int = 600,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.timeout, self.cache_ttl = timeout, cache_ttl
        self.http = http or httpx.AsyncClient(
            timeout=timeout, trust_env=False, follow_redirects=False
        )
        self._clock, self._sleep = clock, sleep
        self._lock = asyncio.Lock()
        self._next_request_at = 0.0
        self._blocked_until = 0.0
        self._cache: OrderedDict[int, tuple[float, MirrorMetadata | MirrorIssue]] = OrderedDict()
        self._raw_attempts: OrderedDict[int, float] = OrderedDict()

    async def close(self) -> None:
        await self.http.aclose()
        self._cache.clear()
        self._raw_attempts.clear()

    async def resolve_ids(self, ids: Sequence[int]) -> MirrorResolution:
        if (
            not ids
            or len(ids) > 100
            or any(type(item) is not int or not 0 < item <= 10**12 for item in ids)
        ):
            raise ValueError("Expected 1 to 100 positive difficulty IDs")
        unique = tuple(dict.fromkeys(ids))
        async with self._lock:
            resolved: dict[int, MirrorMetadata | MirrorIssue] = {}
            pending = []
            for identifier in unique:
                cached = self._cache.get(identifier)
                if cached is not None and cached[0] > self._clock():
                    resolved[identifier] = cached[1]
                    self._cache.move_to_end(identifier)
                else:
                    pending.append(identifier)
            if pending:
                status, body, headers = await self._get(
                    "/v3/osu/beatmaps/batch",
                    maximum=2 * 1024 * 1024,
                    params={"ids": ",".join(map(str, pending))},
                )
                if status != 200:
                    self._blocked_until = self._clock() + 60
                    raise MirrorError(
                        "mirror_unavailable",
                        "Mirror metadata unavailable",
                        retryable=True,
                        retry_after=60,
                    )
                try:
                    parsed = BatchResponse.model_validate_json(body)
                    grouped = (
                        [row.id for row in parsed.results]
                        + parsed.missing.ids
                        + parsed.unresolved.ids
                    )
                    if (
                        set(parsed.requested.ids) != set(pending)
                        or len(parsed.requested.ids) != len(pending)
                        or len(grouped) != len(set(grouped))
                        or set(grouped) != set(pending)
                        or parsed.requested.md5
                        or parsed.missing.md5
                        or parsed.unresolved.md5
                    ):
                        raise ValueError("Inconsistent batch partition")
                    freshness = _header(headers, "x-hinai-freshness", 64)
                    now = datetime.now(UTC)
                    for row in parsed.results:
                        resolved[row.id] = MirrorMetadata(
                            row.id,
                            row.beatmapset_id,
                            row.checksum.lower() if row.checksum else None,
                            {"osu": 0, "taiko": 1, "fruits": 2, "mania": 3}[row.mode],
                            row.last_updated,
                            now,
                            row.hinai_source,
                            freshness,
                        )
                    for identifier in parsed.missing.ids:
                        resolved[identifier] = MirrorIssue(identifier, "missing")
                    for identifier in parsed.unresolved.ids:
                        resolved[identifier] = MirrorIssue(
                            identifier, "unresolved", parsed.unresolved.reason
                        )
                except (ValidationError, ValueError):
                    self._blocked_until = self._clock() + 60
                    raise MirrorError(
                        "mirror_bad_response", "Invalid mirror metadata response"
                    ) from None
                for identifier in pending:
                    value = resolved[identifier]
                    ttl = self.cache_ttl if isinstance(value, MirrorMetadata) else 60
                    self._cache[identifier] = (self._clock() + ttl, value)
                    self._cache.move_to_end(identifier)
                while len(self._cache) > 256:
                    self._cache.popitem(last=False)
            values = [resolved[identifier] for identifier in unique]
            return MirrorResolution(
                tuple(value for value in values if isinstance(value, MirrorMetadata)),
                tuple(value for value in values if isinstance(value, MirrorIssue)),
            )

    async def download(
        self,
        metadata: MirrorMetadata,
        *,
        expected_sha256: str | None = None,
    ) -> DownloadedBeatmap:
        if metadata.ruleset != 0:
            raise MirrorError("mirror_unsupported_ruleset", "Only osu!standard is supported")
        if metadata.md5 is None:
            raise MirrorError("mirror_checksum_unavailable", "Mirror metadata has no checksum")
        async with self._lock:
            previous = self._raw_attempts.get(metadata.beatmap_id)
            if previous is not None and previous > self._clock():
                raise MirrorError(
                    "mirror_rate_limited",
                    "Previous file request is still cooling down",
                    retryable=True,
                    retry_after=max(1, math.ceil(previous - self._clock())),
                )
            self._raw_attempts[metadata.beatmap_id] = self._clock() + 60
            self._raw_attempts.move_to_end(metadata.beatmap_id)
            while len(self._raw_attempts) > 256:
                self._raw_attempts.popitem(last=False)
            status, body, headers = await self._get(
                f"/api/osu/{metadata.beatmap_id}",
                maximum=ParserLimits().max_file_bytes,
            )
            if status == 404:
                raise MirrorError("mirror_not_found", "Mirror file not found")
            if status != 200:
                raise MirrorError("mirror_unavailable", "Mirror file unavailable", retryable=True)
            if body.startswith((b"\xff\xfe", b"\xfe\xff")):
                raise MirrorError(
                    "mirror_unsupported_encoding", "Only UTF-8 .osu input is supported"
                )
            if not body.removeprefix(b"\xef\xbb\xbf").startswith(b"osu file format v"):
                raise MirrorError(
                    "mirror_invalid_file", "Mirror did not return a supported .osu file"
                )
            md5 = hashlib.md5(body, usedforsecurity=False).digest()
            sha256 = hashlib.sha256(body).digest()
            if md5.hex() != metadata.md5 or (
                expected_sha256 is not None and sha256.hex() != expected_sha256
            ):
                raise MirrorError(
                    "mirror_checksum_mismatch", "Downloaded file checksum does not match"
                )
            receipt = SourceReceipt(
                metadata.beatmap_id,
                metadata.beatmap_set_id,
                sha256,
                md5,
                metadata.last_updated,
                metadata.fetched_at,
                datetime.now(UTC),
                metadata.source_layer,
                _header(headers, "x-hinai-osu-source", 64),
                metadata.freshness,
                _header(headers, "etag", 512),
            )
            return DownloadedBeatmap(body, receipt)

    async def _get(
        self,
        path: str,
        *,
        maximum: int,
        params: dict[str, str] | None = None,
    ) -> tuple[int, bytes, httpx.Headers]:
        now = self._clock()
        if now < self._blocked_until:
            raise MirrorError(
                "mirror_rate_limited",
                "Mirror requests are paused",
                retryable=True,
                retry_after=max(1, math.ceil(self._blocked_until - now)),
            )
        await self._sleep(max(0, self._next_request_at - now))
        self._next_request_at = self._clock() + 1.05
        try:
            async with asyncio.timeout(self.timeout):
                async with self.http.stream(
                    "GET",
                    "https://mirror.hinamizawa.ai" + path,
                    params=params,
                    headers={"User-Agent": "osu-skill-lab/0.1.0", "Accept": "*/*"},
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {429, 503}:
                        delay = _retry_after(response.headers.get("Retry-After"))
                        self._blocked_until = self._clock() + delay
                        code = (
                            "mirror_rate_limited"
                            if response.status_code == 429
                            else "mirror_unavailable"
                        )
                        raise MirrorError(
                            code,
                            "Mirror temporarily unavailable",
                            retryable=True,
                            retry_after=delay,
                        )
                    buffer = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(buffer) + len(chunk) > maximum:
                            raise MirrorError(
                                "mirror_response_too_large", "Mirror response exceeds byte limit"
                            )
                        buffer.extend(chunk)
                    return response.status_code, bytes(buffer), response.headers
        except asyncio.CancelledError:
            self._blocked_until = self._clock() + 60
            raise
        except (httpx.TimeoutException, TimeoutError):
            self._blocked_until = self._clock() + 60
            raise MirrorError(
                "mirror_timeout", "Mirror request timed out", retryable=True, retry_after=60
            ) from None
        except httpx.HTTPError:
            self._blocked_until = self._clock() + 60
            raise MirrorError(
                "mirror_unavailable", "Mirror unavailable", retryable=True, retry_after=60
            ) from None


def _header(headers: httpx.Headers, name: str, maximum: int) -> str | None:
    value = headers.get(name)
    if value is not None and (len(value) > maximum or "\x00" in value):
        raise MirrorError("mirror_bad_response", "Invalid mirror provenance header")
    return value


def _retry_after(value: str | None) -> int:
    if value is not None:
        try:
            return max(60, min(int(value), 7 * 86400))
        except ValueError:
            try:
                delay = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
                return max(60, min(math.ceil(delay), 7 * 86400))
            except (TypeError, ValueError, OverflowError):
                pass
    return 60
