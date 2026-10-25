import json
from dataclasses import asdict, replace

import pytest

from osu_skill_lab.analysis.features import ALGORITHM_VERSION, extract_basic_features
from osu_skill_lab.analysis.models import ParsedBeatmap
from osu_skill_lab.analysis.parser import parse_osu


def beatmap(objects: str = "", timing: str = "0,500,4,0,0,100,1,0") -> ParsedBeatmap:
    return parse_osu(
        (
            "osu file format v14\n"
            "[Difficulty]\n"
            "HPDrainRate:5\nCircleSize:4\nOverallDifficulty:8\n"
            "SliderMultiplier:1.4\nSliderTickRate:1\n"
            f"[TimingPoints]\n{timing}\n[HitObjects]\n{objects}\n"
        ).encode()
    )


def test_measures_known_time_and_geometry_using_only_circle_and_slider_heads() -> None:
    parsed = beatmap(
        "256,192,50,8,0,80\n"
        "0,0,100,1,0\n"
        "3,4,300,2,0,L|1000:1000,2,1000\n"
        "500,500,450,8,0,650\n"
        "3,12,700,1,0\n"
        "0,16,1000,1,0\n"
        "256,192,2000,8,0,10000",
        "-1000,500,4,0,0,100,1,0\n0,-0.1,4,0,0,100,0,0\n9000,250,4,0,0,100,1,0",
    )
    measured = extract_basic_features(parsed)
    assert measured.hit_object_count == 7
    assert (measured.circle_count, measured.slider_count, measured.spinner_count) == (3, 1, 3)
    assert measured.timing_point_count == 3
    assert (measured.red_timing_point_count, measured.inherited_timing_point_count) == (2, 1)
    assert (measured.red_bpm_min, measured.red_bpm_max) == (120, 240)
    assert (measured.first_object_start_ms, measured.last_object_start_ms) == (50, 2000)
    assert measured.object_start_span_ms == 1950  # Last spinner end is deliberately ignored.
    assert (measured.head_object_count, measured.head_pair_count) == (4, 3)
    assert (measured.head_interval_min_ms, measured.head_interval_max_ms) == (200, 400)
    assert (measured.head_interval_mean_ms, measured.head_interval_median_ms) == (300, 300)
    assert measured.zero_head_interval_count == 0
    assert (measured.raw_head_distance_min_px, measured.raw_head_distance_max_px) == (5, 8)
    assert measured.raw_head_distance_mean_px == 6


def test_simultaneous_heads_keep_zero_intervals_and_file_order() -> None:
    measured = extract_basic_features(
        beatmap("0,0,1000,1,0\n3,4,1000,1,0\n3,12,1000,1,0\n3,12,1300,1,0\n3,12,2200,1,0")
    )
    assert measured.zero_head_interval_count == 2
    assert measured.head_pair_count == 4
    assert (measured.head_interval_min_ms, measured.head_interval_max_ms) == (0, 900)
    assert measured.head_interval_mean_ms == 300
    assert measured.head_interval_median_ms == 150
    assert measured.raw_head_distance_min_px == 0
    assert measured.raw_head_distance_max_px == 8
    assert measured.raw_head_distance_mean_px == 3.25


def test_empty_map_has_no_start_range_or_pair_aggregates() -> None:
    measured = extract_basic_features(beatmap())
    assert measured.hit_object_count == 0
    assert (measured.circle_count, measured.slider_count, measured.spinner_count) == (0, 0, 0)
    assert measured.first_object_start_ms is None
    assert measured.last_object_start_ms is None
    assert measured.object_start_span_ms is None
    assert (
        measured.head_object_count
        == measured.head_pair_count
        == measured.zero_head_interval_count
        == 0
    )
    assert measured.head_interval_min_ms is None
    assert measured.head_interval_max_ms is None
    assert measured.head_interval_mean_ms is None
    assert measured.head_interval_median_ms is None
    assert measured.raw_head_distance_min_px is None
    assert measured.raw_head_distance_max_px is None
    assert measured.raw_head_distance_mean_px is None


@pytest.mark.parametrize(
    ("objects", "head_count"),
    [
        ("10,20,-100,1,0", 1),
        ("10,20,-100,2,0,L|30:40,1,40", 1),
        ("10,20,-100,8,0,5000", 0),
    ],
)
def test_single_object_has_zero_start_span_and_no_pairs(objects: str, head_count: int) -> None:
    measured = extract_basic_features(beatmap(objects))
    assert (measured.first_object_start_ms, measured.last_object_start_ms) == (-100, -100)
    assert measured.object_start_span_ms == 0
    assert measured.head_object_count == head_count
    assert measured.head_pair_count == measured.zero_head_interval_count == 0
    assert measured.head_interval_mean_ms is None
    assert measured.head_interval_median_ms is None
    assert measured.raw_head_distance_mean_px is None


def test_only_spinners_do_not_create_head_pairs() -> None:
    measured = extract_basic_features(beatmap("0,0,100,8,0,1000\n500,500,2000,8,0,9000"))
    assert measured.spinner_count == 2
    assert measured.object_start_span_ms == 1900
    assert measured.head_object_count == measured.head_pair_count == 0
    assert measured.head_interval_min_ms is None
    assert measured.raw_head_distance_max_px is None


def test_raw_coordinates_are_not_clamped_or_stacked() -> None:
    parsed = beatmap("-100,500,100,1,0\n-100,500,200,1,0\n500,1300,300,1,0")
    measured = extract_basic_features(parsed)
    assert measured.raw_head_distance_min_px == 0
    assert measured.raw_head_distance_max_px == 1000
    assert measured.raw_head_distance_mean_px == 500
    assert extract_basic_features(replace(parsed, stack_leniency=0)) == measured


def test_results_are_deterministic_and_finite_json_scalars_at_parser_limits() -> None:
    parsed = beatmap(
        "-1000000000000,-1000000000000,-1000000000000,1,0\n"
        "1000000000000,1000000000000,1000000000000,1,0",
        "0,1e-300,4,0,0,100,1,0",
    )
    measured = extract_basic_features(parsed)
    assert ALGORITHM_VERSION == "basic-raw/1"
    assert measured == extract_basic_features(parsed)
    assert measured.object_start_span_ms == 2e12
    assert measured.raw_head_distance_max_px == pytest.approx(2e12 * 2**0.5)
    assert measured.red_bpm_max == pytest.approx(6e304)
    payload = asdict(measured)
    assert all(value is None or isinstance(value, int | float) for value in payload.values())
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload
