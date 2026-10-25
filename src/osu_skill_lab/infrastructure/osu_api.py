"""Bounded osu! API v2 lookup using guest client-credentials tokens."""

import asyncio
import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Annotated, Literal

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, ValidationError

from osu_skill_lab.application.osu_metadata import API_RESPONSE_VERSION, OsuApiError, OsuMetadata
from osu_skill_lab.config import Settings

Identifier = Annotated[int, Field(strict=True, gt=0, le=10**12)]
MetadataText = Annotated[str, Field(max_length=512, pattern=r"^[^\x00]*$")]


class ApiSet(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: Identifier
    title: MetadataText
    artist: MetadataText
    creator: Annotated[str, Field(max_length=256, pattern=r"^[^\x00]*$")]


class ApiBeatmap(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: Identifier
    beatmapset_id: Identifier
    user_id: Identifier
    checksum: Annotated[str, Field(pattern=r"^[a-fA-F0-9]{32}$")] | None = None
    mode: Literal["osu", "taiko", "fruits", "mania"]
    version: MetadataText
    status: Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[^\x00]*$")]
    last_updated: AwareDatetime
    beatmapset: ApiSet


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    access_token: SecretStr
    token_type: Literal["Bearer"]
    expires_in: Annotated[int, Field(strict=True, ge=1, le=365 * 86400)]


@dataclass(frozen=True, slots=True)
class CachedFailure:
    code: str
    message: str


class OsuApiClient:
    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.http = http or httpx.AsyncClient(
            timeout=settings.osu_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
        )
        self._clock, self._sleep = clock, sleep
        self._lock = asyncio.Lock()
        self._token: SecretStr | None = None
        self._token_expires_at = 0.0
        self._next_request_at = 0.0
        self._blocked_until = 0.0
        self._blocked_failure = CachedFailure("osu_rate_limited", "osu! API requests are paused")
        self._cache: OrderedDict[str, tuple[float, OsuMetadata | CachedFailure]] = OrderedDict()

    async def close(self) -> None:
        await self.http.aclose()
        self._token = None
        self._cache.clear()

    async def lookup_checksum(self, md5: str) -> OsuMetadata:
        if len(md5) != 32 or any(char not in "0123456789abcdef" for char in md5):
            raise ValueError("Expected lowercase MD5 hex")
        if self.settings.osu_client_id is None or self.settings.osu_client_secret is None:
            raise OsuApiError("osu_not_configured", "osu! API credentials are not configured")
        async with self._lock:
            cached = self._cache.get(md5)
            if cached is not None and cached[0] > self._clock():
                self._cache.move_to_end(md5)
                if isinstance(cached[1], CachedFailure):
                    failure = cached[1]
                    remaining = max(1, math.ceil(cached[0] - self._clock()))
                    raise OsuApiError(failure.code, failure.message, retry_after=remaining)
                return cached[1]
            try:
                result = await self._lookup(md5)
            except asyncio.CancelledError:
                self._remember(
                    md5,
                    CachedFailure("osu_rate_limited", "A previous osu! request was interrupted"),
                    60,
                )
                raise
            except OsuApiError as exc:
                if exc.code not in {"osu_not_configured", "osu_rate_limited"}:
                    self._remember(md5, CachedFailure(exc.code, exc.message), 60)
                raise
            self._remember(md5, result, self.settings.osu_cache_ttl_seconds)
            return result

    def _remember(self, key: str, value: OsuMetadata | CachedFailure, ttl: int) -> None:
        self._cache[key] = (self._clock() + ttl, value)
        self._cache.move_to_end(key)
        while len(self._cache) > 256:
            self._cache.popitem(last=False)

    def _pause(self, code: str, message: str, delay: int = 60) -> None:
        self._blocked_until = self._clock() + delay
        self._blocked_failure = CachedFailure(code, message)

    async def _lookup(self, md5: str) -> OsuMetadata:
        for attempt in range(2):
            await self._ensure_token()
            assert self._token is not None
            response, data = await self._send(
                "/api/v2/beatmaps/lookup",
                headers={
                    "Authorization": f"Bearer {self._token.get_secret_value()}",
                    "x-api-version": API_RESPONSE_VERSION,
                },
                params={"checksum": md5},
            )
            if response == 401:
                self._token = None
                if attempt == 0:
                    continue
            if response in {401, 403}:
                self._token = None
                self._pause("osu_auth_failed", "osu! API authentication failed")
                raise OsuApiError("osu_auth_failed", "osu! API authentication failed")
            if response == 404:
                raise OsuApiError("osu_not_found", "No matching beatmap found on osu!")
            if response != 200:
                raise OsuApiError("osu_unavailable", "osu! API is unavailable")
            try:
                model = ApiBeatmap.model_validate_json(data)
            except ValidationError:
                raise OsuApiError(
                    "osu_bad_response", "Invalid osu! API metadata response"
                ) from None
            if model.beatmapset.id != model.beatmapset_id:
                raise OsuApiError("osu_bad_response", "Inconsistent osu! API beatmapset identity")
            if model.mode != "osu":
                raise OsuApiError("osu_unsupported_ruleset", "Only osu!standard is supported")
            return OsuMetadata(
                model.id,
                model.beatmapset_id,
                model.checksum.lower() if model.checksum is not None else None,
                model.beatmapset.title,
                model.beatmapset.artist,
                model.beatmapset.creator,
                model.user_id,
                model.version,
                model.status,
                model.last_updated,
                datetime.now(UTC),
            )
        raise AssertionError("Authentication loop did not finish")

    async def _ensure_token(self) -> None:
        if self._token is not None and self._token_expires_at > self._clock():
            return
        assert self.settings.osu_client_secret is not None
        status_code, data = await self._send(
            "/oauth/token",
            form={
                "client_id": str(self.settings.osu_client_id),
                "client_secret": self.settings.osu_client_secret.get_secret_value(),
                "grant_type": "client_credentials",
                "scope": "public",
            },
        )
        if status_code != 200:
            self._pause("osu_auth_failed", "osu! API authentication failed")
            raise OsuApiError("osu_auth_failed", "osu! API authentication failed")
        try:
            token = TokenResponse.model_validate_json(data)
            value = token.access_token.get_secret_value()
            if (
                not value
                or len(value) > 8192
                or any(ord(char) < 33 or ord(char) > 126 for char in value)
            ):
                raise ValueError("Invalid token")
        except (ValidationError, ValueError):
            self._pause("osu_bad_response", "Invalid osu! OAuth response")
            raise OsuApiError("osu_bad_response", "Invalid osu! OAuth response") from None
        self._token = token.access_token
        self._token_expires_at = self._clock() + token.expires_in - min(30, token.expires_in / 10)

    async def _send(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        form: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        now = self._clock()
        if self._blocked_until > now:
            raise OsuApiError(
                self._blocked_failure.code,
                self._blocked_failure.message,
                retry_after=max(1, math.ceil(self._blocked_until - now)),
            )
        await self._sleep(max(0, self._next_request_at - now))
        self._next_request_at = self._clock() + 1.05
        try:
            async with asyncio.timeout(self.settings.osu_timeout_seconds):
                async with self.http.stream(
                    "POST" if form is not None else "GET",
                    "https://osu.ppy.sh" + path,
                    headers={"Accept": "application/json", **(headers or {})},
                    params=params,
                    data=form,
                ) as response:
                    if response.status_code == 429:
                        delay = _retry_after(response.headers.get("Retry-After"))
                        self._pause("osu_rate_limited", "osu! API rate limit reached", delay)
                        raise OsuApiError(
                            "osu_rate_limited", "osu! API rate limit reached", retry_after=delay
                        )
                    maximum = 16 * 1024 if form is not None else 512 * 1024
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > maximum:
                            raise OsuApiError("osu_bad_response", "osu! API response is too large")
                        body.extend(chunk)
                    return response.status_code, bytes(body)
        except (httpx.TimeoutException, TimeoutError):
            raise OsuApiError("osu_timeout", "osu! API request timed out") from None
        except httpx.HTTPError:
            raise OsuApiError("osu_unavailable", "osu! API is unavailable") from None


def _retry_after(value: str | None) -> int:
    if value is not None:
        try:
            seconds = int(value)
            return max(60, min(seconds, 7 * 86400))
        except ValueError:
            try:
                deadline = parsedate_to_datetime(value)
                return max(
                    60, min(math.ceil((deadline - datetime.now(UTC)).total_seconds()), 7 * 86400)
                )
            except (ValueError, TypeError, OverflowError):
                pass
    return 60
