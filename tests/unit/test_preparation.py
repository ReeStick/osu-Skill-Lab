import hashlib
import json
import pickle
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import pytest

from osu_skill_lab.application.preparation import (
    PreparationFailure,
    PreparedAnalysis,
    prepare_analysis,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "analytic-v14.osu"


def test_preparation_contains_only_compact_metadata_settings_and_measurements() -> None:
    source = FIXTURE.read_bytes()
    result = prepare_analysis(source)
    assert isinstance(result, PreparedAnalysis)
    assert result.source_sha256 == hashlib.sha256(source).digest()
    assert result.source_md5 == hashlib.md5(source, usedforsecurity=False).digest()
    assert result.features.hit_object_count == 4
    assert result.features.head_object_count == 3
    assert result.features.head_pair_count == 2
    assert result.configuration["mods"] == []
    assert result.configuration["coordinate_space"] == "raw"
    canonical = json.dumps(result.configuration, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode()).digest() == result.configuration_sha256
    assert len(canonical.encode()) < 4096
    record = asdict(result)
    assert all(
        key not in record for key in ("data", "source_bytes", "hit_objects", "timing_points")
    )
    assert all(
        isinstance(value, int | float) or value is None for value in record["features"].values()
    )
    assert set(record["metadata"]) == {
        "title",
        "artist",
        "creator",
        "version",
        "beatmap_id",
        "beatmap_set_id",
    }


def test_failure_is_a_pickle_safe_value_with_parse_location() -> None:
    result = prepare_analysis(b"invalid format")
    assert isinstance(result, PreparationFailure)
    assert result.code == "invalid_header"
    assert result.line_number == 1
    assert pickle.loads(pickle.dumps(result)) == result


def test_metadata_size_is_bounded_without_silent_truncation() -> None:
    source = FIXTURE.read_bytes().replace(
        b"Title: Synthetic: analytical fixture", b"Title: " + b"x" * 513
    )
    result = prepare_analysis(source)
    assert isinstance(result, PreparationFailure)
    assert result.code == "metadata_too_long"


@pytest.mark.parametrize("field", [b"Title", b"Artist", b"Creator", b"Version"])
def test_persisted_metadata_rejects_nul_without_exposing_the_value(field: bytes) -> None:
    source = FIXTURE.read_bytes().replace(field + b":", field + b":private\x00metadata")
    result = prepare_analysis(source)
    assert isinstance(result, PreparationFailure)
    assert result.code == "invalid_metadata"
    assert result.section == "Metadata"
    assert "private" not in result.message
    assert "\x00" not in result.message


def test_real_process_can_return_valid_results_and_expected_parse_failures() -> None:
    with ProcessPoolExecutor(max_workers=1) as pool:
        result = pool.submit(prepare_analysis, FIXTURE.read_bytes()).result(timeout=20)
        failure = pool.submit(prepare_analysis, b"not osu").result(timeout=20)
    assert isinstance(result, PreparedAnalysis)
    assert result.features.hit_object_count == 4
    assert isinstance(failure, PreparationFailure)
    assert failure.code == "invalid_header"
