from collections.abc import AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
from pydantic import SecretStr

from osu_skill_lab.analysis.features import ALGORITHM_VERSION, extract_basic_features
from osu_skill_lab.analysis.parser import parse_osu
from osu_skill_lab.api.dependencies import get_analysis_service
from osu_skill_lab.application.contracts import (
    AnalysisPage,
    AnalysisRecord,
    BeatmapIdentity,
    SaveAnalysisOutcome,
)
from osu_skill_lab.application.service import (
    AnalysisBusyError,
    AnalysisInputError,
    AnalysisService,
    AnalysisUnavailableError,
)
from osu_skill_lab.config import Settings
from osu_skill_lab.main import create_app


def analysis_record() -> AnalysisRecord:
    parsed = parse_osu(
        b"osu file format v14\n"
        b"[Difficulty]\nHPDrainRate:5\nCircleSize:4\nOverallDifficulty:8\n"
        b"SliderMultiplier:1.4\nSliderTickRate:1\n"
        b"[TimingPoints]\n0,500,4,0,0,100,1,0\n"
        b"[HitObjects]\n0,0,100,1,0\n3,4,300,2,0,L|30:40,1,50\n0,0,400,8,0,600\n"
    )
    return AnalysisRecord(
        id=42,
        beatmap=BeatmapIdentity(
            input_id=7,
            sha256=parsed.source_sha256,
            md5="a" * 32,
            byte_size=246,
            format_version=14,
            ruleset=0,
            claimed_beatmap_id=123,
            claimed_beatmap_set_id=12,
            title="Synthetic title",
            artist="Synthetic artist",
            creator="Fixture author",
            difficulty_name="Fixture difficulty",
            metadata_parser_version=parsed.parser_version,
        ),
        algorithm_version=ALGORITHM_VERSION,
        parser_version=parsed.parser_version,
        configuration={"coordinate_space": "raw", "mods": "NM"},
        configuration_sha256="b" * 64,
        difficulty=parsed.difficulty,
        stack_leniency=parsed.stack_leniency,
        features=extract_basic_features(parsed),
        created_at=datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
    )


class FakeAnalysisService:
    def __init__(self, *, created: bool = True, failure: Exception | None = None) -> None:
        self.record = analysis_record()
        self.created = created
        self.failure = failure
        self.chunks: list[bytes] = []
        self.requested_ids: list[int] = []
        self.list_requests: list[tuple[int, int, int | None]] = []

    async def analyze_stream(self, chunks: AsyncIterable[bytes]) -> SaveAnalysisOutcome:
        async for chunk in chunks:
            self.chunks.append(chunk)
        if self.failure is not None:
            raise self.failure
        return SaveAnalysisOutcome(record=self.record, created=self.created)

    async def get_analysis(self, analysis_id: int) -> AnalysisRecord | None:
        self.requested_ids.append(analysis_id)
        if self.failure is not None:
            raise self.failure
        return self.record if analysis_id == self.record.id else None

    async def list_analyses(
        self, *, limit: int, after_id: int, claimed_beatmap_id: int | None = None
    ) -> AnalysisPage:
        self.list_requests.append((limit, after_id, claimed_beatmap_id))
        if self.failure is not None:
            raise self.failure
        return AnalysisPage(items=(self.record,), next_after_id=self.record.id)


@asynccontextmanager
async def client_for(service: FakeAnalysisService) -> AsyncIterator[httpx.AsyncClient]:
    configuration = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr("postgresql+asyncpg://unused:unused@127.0.0.1:1/unit_test"),
    )
    app = create_app(configuration)

    def override_service() -> AnalysisService:
        return cast(AnalysisService, service)

    app.dependency_overrides[get_analysis_service] = override_service
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


@pytest.mark.parametrize(
    "content_type", [None, "application/octet-stream", "text/plain; charset=utf-8"]
)
async def test_upload_forwards_stream_and_returns_versioned_scalar_result(
    content_type: str | None,
) -> None:
    service = FakeAnalysisService()
    chunks = (b"osu file ", b"format v14\n", b"synthetic content")

    async def body() -> AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk

    headers = {} if content_type is None else {"Content-Type": content_type}
    async with client_for(service) as client:
        response = await client.post("/analyses", content=body(), headers=headers)

    assert response.status_code == 201
    assert [chunk for chunk in service.chunks if chunk] == list(chunks)
    payload = response.json()
    assert payload["id"] == 42
    assert payload["beatmap"]["input_id"] == 7
    assert payload["beatmap"]["claimed_beatmap_id"] == 123
    assert payload["beatmap"]["identity_status"] == "unverified"
    assert payload["beatmap"]["sha256"] == service.record.beatmap.sha256
    assert payload["beatmap"]["md5"] == "a" * 32
    assert payload["algorithm_version"] == ALGORITHM_VERSION
    assert payload["features"]["hit_object_count"] == 3
    assert payload["features"]["raw_head_distance_mean_px"] == 5
    assert all(
        value is None or isinstance(value, int | float) for value in payload["features"].values()
    )
    assert "hit_objects" not in response.text
    assert "timing_points" not in response.text


async def test_repeated_versioned_analysis_returns_200() -> None:
    async with client_for(FakeAnalysisService(created=False)) as client:
        response = await client.post("/analyses", content=b"synthetic content")
    assert response.status_code == 200
    assert response.json()["id"] == 42


@pytest.mark.parametrize(
    "content_type", ["application/json", "multipart/form-data", "application/zip"]
)
async def test_unsupported_content_type_is_rejected_before_analysis(content_type: str) -> None:
    service = FakeAnalysisService()
    async with client_for(service) as client:
        response = await client.post(
            "/analyses", content=b"synthetic content", headers={"Content-Type": content_type}
        )
    assert response.status_code == 415
    assert service.chunks == []


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        ("file_too_large", 413),
        ("unsupported_version", 422),
        ("invalid_hit_object", 422),
        ("invalid_metadata", 422),
    ],
)
async def test_input_errors_preserve_structured_parser_location(
    code: str, expected_status: int
) -> None:
    failure = AnalysisInputError(
        code, "Synthetic invalid input", section="HitObjects", line_number=18
    )
    async with client_for(FakeAnalysisService(failure=failure)) as client:
        response = await client.post("/analyses", content=b"synthetic invalid content")
    assert response.status_code == expected_status
    assert response.json() == {
        "detail": {
            "code": code,
            "message": "Synthetic invalid input",
            "section": "HitObjects",
            "line_number": 18,
        }
    }


async def test_capacity_error_has_retry_after() -> None:
    async with client_for(FakeAnalysisService(failure=AnalysisBusyError())) as client:
        response = await client.post("/analyses", content=b"synthetic content")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"


@pytest.mark.parametrize(
    ("method", "path"), [("POST", "/analyses"), ("GET", "/analyses"), ("GET", "/analyses/42")]
)
async def test_unavailable_service_is_503_without_internal_details(method: str, path: str) -> None:
    failure = AnalysisUnavailableError("postgresql://private-password@internal-host")
    async with client_for(FakeAnalysisService(failure=failure)) as client:
        response = await client.request(method, path, content=b"synthetic content")
    assert response.status_code == 503
    assert response.json() == {"detail": "Analysis service unavailable"}
    assert "private-password" not in response.text
    assert "internal-host" not in response.text


async def test_get_analysis_and_missing_record() -> None:
    service = FakeAnalysisService()
    async with client_for(service) as client:
        found = await client.get("/analyses/42")
        missing = await client.get("/analyses/99")
    assert found.status_code == 200
    assert found.json()["id"] == 42
    assert missing.status_code == 404
    assert service.requested_ids == [42, 99]


@pytest.mark.parametrize("analysis_id", ["0", "-1", "invalid", "9223372036854775808"])
async def test_get_validates_positive_id_before_service(analysis_id: str) -> None:
    service = FakeAnalysisService()
    async with client_for(service) as client:
        response = await client.get(f"/analyses/{analysis_id}")
    assert response.status_code == 422
    assert service.requested_ids == []


async def test_list_forwards_pagination_and_unverified_site_id_filter() -> None:
    service = FakeAnalysisService()
    async with client_for(service) as client:
        default_page = await client.get("/analyses")
        filtered_page = await client.get("/analyses?limit=5&after_id=40&claimed_beatmap_id=123")
    assert default_page.status_code == filtered_page.status_code == 200
    assert service.list_requests == [(20, 0, None), (5, 40, 123)]
    assert filtered_page.json()["next_after_id"] == 42
    assert [item["id"] for item in filtered_page.json()["items"]] == [42]


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "after_id=-1",
        "after_id=9223372036854775808",
        "claimed_beatmap_id=0",
        "claimed_beatmap_id=-1",
        "claimed_beatmap_id=9223372036854775808",
    ],
)
async def test_list_validates_pagination_before_service(query: str) -> None:
    service = FakeAnalysisService()
    async with client_for(service) as client:
        response = await client.get(f"/analyses?{query}")
    assert response.status_code == 422
    assert service.list_requests == []


async def test_maximum_bigint_ids_are_accepted_at_the_http_boundary() -> None:
    service = FakeAnalysisService()
    maximum = 2**63 - 1
    async with client_for(service) as client:
        missing = await client.get(f"/analyses/{maximum}")
        page = await client.get(f"/analyses?after_id={maximum}&claimed_beatmap_id={maximum}")
    assert missing.status_code == 404
    assert page.status_code == 200
    assert service.requested_ids == [maximum]
    assert service.list_requests == [(20, maximum, maximum)]


async def test_openapi_documents_raw_binary_body_and_result_statuses() -> None:
    async with client_for(FakeAnalysisService()) as client:
        schema = (await client.get("/openapi.json")).json()
    upload = schema["paths"]["/analyses"]["post"]
    assert upload["requestBody"]["required"] is True
    assert upload["requestBody"]["content"]["application/octet-stream"]["schema"] == {
        "type": "string",
        "format": "binary",
    }
    assert {"200", "201", "413", "415", "422", "429", "503"} <= upload["responses"].keys()
    assert upload["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AnalysisRecord"
    }
