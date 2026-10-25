import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import LargeBinary, func, inspect, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from osu_skill_lab.application.contracts import SaveAnalysisOutcome
from osu_skill_lab.application.preparation import PreparedAnalysis, prepare_analysis
from osu_skill_lab.infrastructure.analysis_repository import (
    get_analysis,
    list_analyses,
    save_analysis,
)
from osu_skill_lab.infrastructure.models import AnalysisResult, BeatmapInput

pytestmark = pytest.mark.integration
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "analytic-v14.osu"


@pytest.fixture
def source_data() -> bytes:
    return (
        FIXTURE.read_bytes()
        .replace(b"BeatmapID: 0", b"BeatmapID: 123")
        .replace(b"BeatmapSetID: -1", b"BeatmapSetID: 456")
    )


@pytest.fixture
def candidate(source_data: bytes) -> PreparedAnalysis:
    return prepared(source_data)


@pytest.fixture
def sessions(migrated_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(migrated_engine, expire_on_commit=False)


def prepared(data: bytes) -> PreparedAnalysis:
    result = prepare_analysis(data)
    assert isinstance(result, PreparedAnalysis)
    return result


def with_configuration(
    candidate: PreparedAnalysis, configuration: dict[str, object]
) -> PreparedAnalysis:
    canonical = json.dumps(configuration, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return replace(
        candidate,
        configuration=configuration,
        configuration_sha256=hashlib.sha256(canonical.encode("utf-8")).digest(),
    )


async def persist(
    sessions: async_sessionmaker[AsyncSession], candidate: PreparedAnalysis
) -> SaveAnalysisOutcome:
    async with sessions() as session, session.begin():
        return await save_analysis(session, candidate)


async def counts(sessions: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    async with sessions() as session:
        inputs = await session.scalar(select(func.count()).select_from(BeatmapInput))
        results = await session.scalar(select(func.count()).select_from(AnalysisResult))
    assert inputs is not None and results is not None
    return inputs, results


async def test_roundtrip_and_repeat_preserve_immutable_input_metadata(
    sessions: async_sessionmaker[AsyncSession], candidate: PreparedAnalysis
) -> None:
    first = await persist(sessions, candidate)
    altered_metadata = replace(candidate.metadata, title="A later parser interpretation")
    second = await persist(sessions, replace(candidate, metadata=altered_metadata))

    assert first.created is True
    assert second.created is False
    assert second.record == first.record
    assert first.record.beatmap.title == candidate.metadata.title
    assert first.record.beatmap.claimed_beatmap_id == 123
    assert first.record.beatmap.claimed_beatmap_set_id == 456
    assert first.record.beatmap.identity_status == "unverified"
    assert first.record.beatmap.sha256 == candidate.source_sha256.hex()
    assert first.record.beatmap.md5 == candidate.source_md5.hex()
    assert first.record.beatmap.byte_size == candidate.byte_size
    assert first.record.configuration == candidate.configuration
    assert first.record.configuration_sha256 == candidate.configuration_sha256.hex()
    assert first.record.difficulty == candidate.difficulty
    assert first.record.stack_leniency == candidate.stack_leniency
    assert first.record.features == candidate.features
    assert first.record.created_at.utcoffset() == timedelta(0)
    async with sessions() as session:
        assert await get_analysis(session, first.record.id) == first.record
    assert await counts(sessions) == (1, 1)


async def test_concurrent_duplicate_imports_create_exactly_one_input_and_result(
    sessions: async_sessionmaker[AsyncSession], candidate: PreparedAnalysis
) -> None:
    barrier = asyncio.Barrier(6)

    async def save_concurrently() -> SaveAnalysisOutcome:
        async with sessions() as session, session.begin():
            await barrier.wait()
            return await save_analysis(session, candidate)

    outcomes = await asyncio.wait_for(
        asyncio.gather(*(save_concurrently() for _ in range(6))), timeout=30
    )

    assert sum(outcome.created for outcome in outcomes) == 1
    assert len({outcome.record.id for outcome in outcomes}) == 1
    assert len({outcome.record.beatmap.input_id for outcome in outcomes}) == 1
    assert all(outcome.record == outcomes[0].record for outcome in outcomes)
    assert await counts(sessions) == (1, 1)


async def test_changed_bytes_with_same_claimed_site_ids_remain_distinct(
    sessions: async_sessionmaker[AsyncSession], candidate: PreparedAnalysis, source_data: bytes
) -> None:
    revised = prepared(source_data + b"\n// A distinct exact input revision\n")
    original = await persist(sessions, candidate)
    changed = await persist(sessions, revised)

    assert original.created and changed.created
    assert original.record.id != changed.record.id
    assert original.record.beatmap.input_id != changed.record.beatmap.input_id
    assert original.record.beatmap.sha256 != changed.record.beatmap.sha256
    assert original.record.beatmap.claimed_beatmap_id == changed.record.beatmap.claimed_beatmap_id
    assert original.record.beatmap.claimed_beatmap_set_id == 456
    assert changed.record.beatmap.claimed_beatmap_set_id == 456
    assert original.record.features == changed.record.features
    async with sessions() as session:
        assert await get_analysis(session, original.record.id) == original.record
    assert await counts(sessions) == (2, 2)


@pytest.mark.parametrize("identity_part", ["algorithm", "parser", "configuration"])
async def test_version_and_configuration_identity_create_new_result_for_same_input(
    sessions: async_sessionmaker[AsyncSession], candidate: PreparedAnalysis, identity_part: str
) -> None:
    if identity_part == "algorithm":
        revised = replace(candidate, algorithm_version="basic-raw/test-next")
    elif identity_part == "parser":
        revised = replace(candidate, parser_version="osu-standard-v14/test-next")
    else:
        revised = with_configuration(candidate, {**candidate.configuration, "test_parameter": 2})
    original = await persist(sessions, candidate)
    changed = await persist(sessions, revised)
    repeated = await persist(sessions, revised)

    assert original.created and changed.created
    assert repeated.created is False
    assert original.record.id != changed.record.id
    assert changed.record == repeated.record
    assert original.record.beatmap == changed.record.beatmap
    assert changed.record.beatmap.metadata_parser_version == candidate.parser_version
    assert changed.record.algorithm_version == revised.algorithm_version
    assert changed.record.parser_version == revised.parser_version
    assert changed.record.configuration == revised.configuration
    assert await counts(sessions) == (1, 2)


async def test_failed_result_constraint_rolls_back_new_input(
    sessions: async_sessionmaker[AsyncSession], candidate: PreparedAnalysis
) -> None:
    invalid = replace(candidate, features=replace(candidate.features, hit_object_count=999))

    with pytest.raises(IntegrityError):
        await persist(sessions, invalid)

    assert await counts(sessions) == (0, 0)
    assert (await persist(sessions, candidate)).created is True
    assert await counts(sessions) == (1, 1)


async def test_application_failure_rolls_back_complete_save(
    sessions: async_sessionmaker[AsyncSession], candidate: PreparedAnalysis
) -> None:
    with pytest.raises(RuntimeError, match="application failed after saving"):
        async with sessions() as session, session.begin():
            await save_analysis(session, candidate)
            raise RuntimeError("application failed after saving")

    assert await counts(sessions) == (0, 0)


async def test_md5_and_claimed_ids_are_nonunique_lookup_attributes(
    sessions: async_sessionmaker[AsyncSession], candidate: PreparedAnalysis, source_data: bytes
) -> None:
    distinct = prepared(source_data + b"\n// Another input, simulated equal MD5\n")
    # Exercise schema identity with a simulated collision; this does not claim a real MD5 collision.
    distinct = replace(distinct, source_md5=candidate.source_md5)

    first = await persist(sessions, candidate)
    second = await persist(sessions, distinct)

    assert first.record.beatmap.md5 == second.record.beatmap.md5
    assert first.record.beatmap.sha256 != second.record.beatmap.sha256
    assert first.record.beatmap.claimed_beatmap_id == second.record.beatmap.claimed_beatmap_id
    assert await counts(sessions) == (2, 2)


async def test_list_cursor_filter_and_get_roundtrip(
    sessions: async_sessionmaker[AsyncSession], source_data: bytes
) -> None:
    records = []
    for index in range(4):
        data = source_data + f"\n// Revision {index}\n".encode()
        if index == 3:
            data = data.replace(b"BeatmapID: 123", b"BeatmapID: 999")
        records.append((await persist(sessions, prepared(data))).record)

    async with sessions() as session:
        first = await list_analyses(session, limit=2, after_id=0)
        assert first.items == tuple(records[:2])
        assert first.next_after_id == records[1].id
        second = await list_analyses(session, limit=2, after_id=first.next_after_id)
        assert second.items == tuple(records[2:])
        assert second.next_after_id is None

        filtered_ids: list[int] = []
        cursor = 0
        while True:
            page = await list_analyses(session, limit=1, after_id=cursor, claimed_beatmap_id=123)
            filtered_ids.extend(record.id for record in page.items)
            if page.next_after_id is None:
                break
            assert page.next_after_id > cursor
            cursor = page.next_after_id
        assert filtered_ids == [record.id for record in records[:3]]

        missing = await list_analyses(session, limit=2, after_id=0, claimed_beatmap_id=777)
        assert missing.items == ()
        assert missing.next_after_id is None
        assert await get_analysis(session, records[0].id) == records[0]
        assert await get_analysis(session, records[-1].id + 1000) is None


async def test_empty_objects_and_missing_site_ids_preserve_nullable_measurements(
    sessions: async_sessionmaker[AsyncSession], source_data: bytes
) -> None:
    data = source_data.partition(b"[HitObjects]")[0] + b"[HitObjects]\n"
    data = data.replace(b"BeatmapID: 123", b"BeatmapID: 0")
    data = data.replace(b"BeatmapSetID: 456", b"BeatmapSetID: -1")
    candidate = prepared(data)

    outcome = await persist(sessions, candidate)
    async with sessions() as session:
        record = await get_analysis(session, outcome.record.id)

    assert record is not None
    assert record.beatmap.claimed_beatmap_id is None
    assert record.beatmap.claimed_beatmap_set_id is None
    assert record.features == candidate.features
    assert record.features.hit_object_count == 0
    assert record.features.first_object_start_ms is None
    assert record.features.head_interval_mean_ms is None
    assert record.features.raw_head_distance_mean_px is None


async def test_database_rejects_oversized_configuration_without_leaving_input(
    sessions: async_sessionmaker[AsyncSession], candidate: PreparedAnalysis
) -> None:
    oversized = with_configuration(candidate, {"oversized": "x" * 4096})

    with pytest.raises(IntegrityError):
        await persist(sessions, oversized)

    assert await counts(sessions) == (0, 0)


async def test_actual_schema_has_only_digest_bytes_and_configuration_json(
    migrated_engine: AsyncEngine,
) -> None:
    async with migrated_engine.connect() as connection:
        columns = await connection.run_sync(
            lambda sync_connection: {
                table: inspect(sync_connection).get_columns(table)
                for table in (
                    "beatmap_inputs",
                    "analysis_results",
                    "osu_beatmap_matches",
                    "beatmap_sources",
                )
            }
        )

    binary_columns = set()
    json_columns = set()
    for table, definitions in columns.items():
        for column in definitions:
            name = column["name"]
            column_type = column["type"]
            assert not isinstance(column_type, ARRAY), (table, name)
            assert name not in {
                "hit_objects",
                "timing_points",
                "raw_data",
                "osu_text",
                "features",
                "feature_vector",
            }
            if isinstance(column_type, LargeBinary):
                binary_columns.add((table, name))
            if isinstance(column_type, JSONB):
                json_columns.add((table, name))

    assert binary_columns == {
        ("beatmap_inputs", "source_sha256"),
        ("beatmap_inputs", "source_md5"),
        ("analysis_results", "configuration_sha256"),
        ("osu_beatmap_matches", "source_md5"),
        ("beatmap_sources", "metadata_md5"),
    }
    assert json_columns == {("analysis_results", "configuration")}
