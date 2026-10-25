import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from osu_skill_lab.analysis.models import HitCircle, ParserLimits, Position, Slider, Spinner
from osu_skill_lab.analysis.parser import PARSER_VERSION, BeatmapParseError, parse_osu
from osu_skill_lab.analysis.summary import summarize_beatmap

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "analytic-v14.osu"


@pytest.fixture
def source() -> bytes:
    return FIXTURE.read_bytes()


def test_reads_only_analytical_data(source: bytes) -> None:
    parsed = parse_osu(source)
    assert parsed.parser_version == PARSER_VERSION
    assert parsed.source_sha256 == hashlib.sha256(source).hexdigest()
    assert parsed.format_version == 14
    assert parsed.metadata.title == "Synthetic: analytical fixture"
    assert parsed.metadata.tags == ("synthetic", "test")
    assert parsed.metadata.beatmap_id is None
    assert parsed.metadata.beatmap_set_id is None
    difficulty = parsed.difficulty
    assert (difficulty.approach_rate, difficulty.overall_difficulty) == (9, 8)
    assert (difficulty.circle_size, difficulty.hp_drain_rate) == (4, 5)
    assert (difficulty.slider_multiplier, difficulty.slider_tick_rate) == (1.4, 2)
    assert parsed.stack_leniency == 0.65
    circle, slider, spinner, last = parsed.hit_objects
    assert isinstance(circle, HitCircle)
    assert circle.position == Position(64, 96)
    assert circle.type_flags == 5
    assert isinstance(slider, Slider)
    assert slider.curve_type == "B"
    assert slider.control_points == (
        Position(128, 192),
        Position(160, 192),
        Position(160, 192),
        Position(192, 96),
    )
    assert slider.spans == 2  # Raw slides count, not repeat count.
    assert slider.pixel_length == 140.5
    assert isinstance(spinner, Spinner)
    assert (spinner.start_time_ms, spinner.end_time_ms) == (2200, 2600)
    assert isinstance(last, HitCircle)
    assert parsed.warnings == ()


def test_ignoring_media_does_not_change_analytical_values(source: bytes) -> None:
    original = parse_osu(source)
    altered = parse_osu(source.replace(b"missing", b"not-present-anywhere"))
    assert original.metadata == altered.metadata
    assert original.difficulty == altered.difficulty
    assert original.hit_objects == altered.hit_objects
    assert original.timing_points == altered.timing_points
    assert original.source_sha256 != altered.source_sha256


def test_tempo_points_are_distinct_from_sv_changes(source: bytes) -> None:
    red, green, faster, same_time_green = parse_osu(source).timing_points
    assert red.time_ms == -100
    assert red.bpm == 120
    assert red.effects == 1
    assert green.beat_length == -50
    assert green.bpm is None
    assert faster.bpm == 150
    assert faster.meter == 3
    assert same_time_green.time_ms == faster.time_ms
    assert same_time_green.bpm is None


def test_summary_reports_raw_settings_and_counts(source: bytes) -> None:
    summary = summarize_beatmap(parse_osu(source))
    assert (summary.hit_objects, summary.circles, summary.sliders, summary.spinners) == (4, 2, 1, 1)
    assert (summary.timing_points, summary.tempo_points, summary.inherited_points) == (4, 2, 2)
    assert (summary.bpm_min, summary.bpm_max) == (120, 150)
    assert (summary.first_object_start_ms, summary.last_object_start_ms) == (500, 2800)


def test_supports_bom_crlf_and_full_line_comments(source: bytes) -> None:
    variant = b"\xef\xbb\xbf" + source.replace(b"\n", b"\r\n")
    variant = variant.replace(b"[Difficulty]", b"// comment\r\n[Difficulty]")
    original, parsed = parse_osu(source), parse_osu(variant)
    assert original.difficulty == parsed.difficulty
    assert len(parsed.hit_objects) == 4
    assert parsed.source_sha256 != original.source_sha256


def test_ar_defaults_to_od_and_optional_general_metadata(source: bytes) -> None:
    data = source.replace(b"ApproachRate: 9\n", b"")
    data = data.replace(b"Mode: 0\n", b"").replace(b"StackLeniency: 0.65\n", b"")
    parsed = parse_osu(data)
    assert parsed.difficulty.approach_rate == parsed.difficulty.overall_difficulty == 8
    assert parsed.stack_leniency == 0.7
    without_metadata = data[: data.index(b"[Metadata]")] + data[data.index(b"[Difficulty]") :]
    assert parse_osu(without_metadata).metadata.title == ""


def test_positive_map_ids_are_preserved(source: bytes) -> None:
    parsed = parse_osu(
        source.replace(b"BeatmapID: 0", b"BeatmapID: 123").replace(
            b"BeatmapSetID: -1", b"BeatmapSetID: 456"
        )
    )
    assert parsed.metadata.beatmap_id == 123
    assert parsed.metadata.beatmap_set_id == 456


@pytest.mark.parametrize("curve", [b"B", b"C", b"L", b"P"])
def test_retains_supported_slider_curve_types(source: bytes, curve: bytes) -> None:
    parsed = parse_osu(source.replace(b"B|160", curve + b"|160"))
    slider = parsed.hit_objects[1]
    assert isinstance(slider, Slider)
    assert slider.curve_type.encode() == curve


def test_does_not_clamp_or_round_raw_coordinates_and_times(source: bytes) -> None:
    parsed = parse_osu(source.replace(b"64,96,500", b"-12.5,520.25,500.5"))
    assert parsed.hit_objects[0].position == Position(-12.5, 520.25)
    assert parsed.hit_objects[0].start_time_ms == 500.5


def test_unsorted_objects_are_stably_sorted_with_warning(source: bytes) -> None:
    head = source[: source.index(b"[HitObjects]")]
    body = b"[HitObjects]\n64,96,700,1,0\n10,10,500,1,0\n20,20,500,1,0\n"
    parsed = parse_osu(head + body)
    assert [obj.position.x for obj in parsed.hit_objects] == [10, 20, 64]
    assert parsed.warnings == ("hit_objects_stably_sorted",)
    assert parsed.hit_objects[0].line_number < parsed.hit_objects[1].line_number


def test_empty_object_section_is_representable(source: bytes) -> None:
    data = source[: source.index(b"[HitObjects]")] + b"[HitObjects]\n"
    summary = summarize_beatmap(parse_osu(data))
    assert summary.hit_objects == 0
    assert summary.first_object_start_ms is None
    assert summary.last_object_start_ms is None


@pytest.mark.parametrize(
    ("old", "new", "code", "section"),
    [
        (b"v14", b"v13", "unsupported_version", None),
        (b"osu file format", b"invalid header", "invalid_header", None),
        (b"Mode: 0", b"Mode: 3", "unsupported_mode", "General"),
        (b"Mode: 0", b"Mode: NaN", "invalid_value", "General"),
        (b"StackLeniency: 0.65", b"StackLeniency: 2", "invalid_value", "General"),
        (b"ApproachRate: 9", b"ApproachRate: NaN", "invalid_value", "Difficulty"),
        (b"CircleSize: 4", b"CircleSize: inf", "invalid_value", "Difficulty"),
        (b"HPDrainRate: 5", b"HPDrainRate: -1", "invalid_value", "Difficulty"),
        (b"OverallDifficulty: 8", b"OverallDifficulty: 11", "invalid_value", "Difficulty"),
        (b"SliderMultiplier: 1.4", b"SliderMultiplier: 0", "invalid_value", "Difficulty"),
        (b"SliderTickRate: 2", b"SliderTickRate: -1", "invalid_value", "Difficulty"),
        (b"BeatmapID: 0", b"BeatmapID: nope", "invalid_value", "Metadata"),
        (b"BeatmapID: 0", b"BeatmapID: -2", "invalid_value", "Metadata"),
        (b"64,96,500,5", b"64,96,500,0", "unsupported_object", "HitObjects"),
        (b"64,96,500,5", b"64,96,500,131", "unsupported_object", "HitObjects"),
        (b"64,96,500,5", b"64,96,500,3", "unsupported_object", "HitObjects"),
        (b"64,96,500,5", b"64,96,500,256", "unsupported_object", "HitObjects"),
        (b"64,96,500", b"NaN,96,500", "invalid_value", "HitObjects"),
        (b"64,96,500", b"64,96,inf", "invalid_value", "HitObjects"),
        (b"B|160:192", b"X|160:192", "invalid_value", "HitObjects"),
        (b"B|160:192", b"B|broken", "invalid_value", "HitObjects"),
        (
            b"128,192,1000,2,0,B|160:192|160:192|192:96,2,140.5,ignored,ignored,missing.wav",
            b"128,192,1000,2,0",
            "invalid_value",
            "HitObjects",
        ),
        (
            b"256,192,2200,8,0,2600,missing-sample.wav",
            b"256,192,2200,8,0",
            "invalid_value",
            "HitObjects",
        ),
        (b",2,140.5", b",0,140.5", "invalid_value", "HitObjects"),
        (b",2,140.5", b",2,0", "invalid_value", "HitObjects"),
        (b",0,2600,", b",0,2100,", "invalid_value", "HitObjects"),
        (b"-100,500,4", b"-100,0,4", "invalid_value", "TimingPoints"),
        (b"1000,-50,4", b"1000,50,4", "invalid_value", "TimingPoints"),
        (b"1000,-50,4", b"1000,NaN,4", "invalid_value", "TimingPoints"),
        (b"-100,500,4", b"-100,1e-320,4", "invalid_value", "TimingPoints"),
        (b"-100,500,4", b"-100,500,0", "invalid_value", "TimingPoints"),
        (
            b"-100,500,4,ignored,ignored,ignored,1,1",
            b"-100,500,4",
            "invalid_value",
            "TimingPoints",
        ),
        (
            b"2000,-100,4,ignored,ignored,ignored,0,1",
            b"2000,-100,4,ignored,ignored,ignored,2,1",
            "invalid_value",
            "TimingPoints",
        ),
        (b"2000,400,3", b"500,400,3", "unsorted_timing_points", "TimingPoints"),
    ],
)
def test_rejects_unsupported_or_malformed_analytical_values(
    source: bytes, old: bytes, new: bytes, code: str, section: str | None
) -> None:
    assert old in source
    with pytest.raises(BeatmapParseError) as error:
        parse_osu(source.replace(old, new, 1))
    assert error.value.code == code
    assert error.value.section == section
    assert error.value.line_number is not None


@pytest.mark.parametrize("field", [b"CircleSize: 4\n", b"SliderTickRate: 2\n"])
def test_missing_required_difficulty_field(source: bytes, field: bytes) -> None:
    with pytest.raises(BeatmapParseError) as error:
        parse_osu(source.replace(field, b""))
    assert error.value.code == "missing_field"


@pytest.mark.parametrize("section", [b"Difficulty", b"TimingPoints", b"HitObjects"])
def test_missing_required_section(source: bytes, section: bytes) -> None:
    data = source.replace(b"[" + section + b"]", b"[Ignored]")
    with pytest.raises(BeatmapParseError) as error:
        parse_osu(data)
    assert error.value.code == "missing_section"


def test_requires_a_tempo_point(source: bytes) -> None:
    data = source.replace(b"-100,500,4,ignored,ignored,ignored,1,1\n", b"")
    data = data.replace(b"2000,400,3,ignored,ignored,ignored,1,0\n", b"")
    with pytest.raises(BeatmapParseError) as error:
        parse_osu(data)
    assert error.value.code == "missing_tempo"


@pytest.mark.parametrize(
    ("extra", "code"),
    [(b"\n[Difficulty]\n", "duplicate_section"), (b"\nCircleSize: 3\n", "duplicate_field")],
)
def test_rejects_duplicate_analytical_data(source: bytes, extra: bytes, code: str) -> None:
    data = (
        source + extra
        if code == "duplicate_section"
        else source.replace(b"CircleSize: 4\n", b"CircleSize: 4\n" + extra)
    )
    with pytest.raises(BeatmapParseError) as error:
        parse_osu(data)
    assert error.value.code == code


@pytest.mark.parametrize("data", [b"", b"\xff\xfeinvalid"])
def test_bad_header_or_encoding(data: bytes) -> None:
    with pytest.raises(BeatmapParseError):
        parse_osu(data)


@pytest.mark.parametrize(
    ("limit", "value", "code"),
    [
        ("max_file_bytes", 10, "file_too_large"),
        ("max_line_characters", 10, "line_too_long"),
        ("max_hit_objects", 3, "too_many_objects"),
        ("max_timing_points", 3, "too_many_timing_points"),
        ("max_slider_control_points", 3, "too_many_control_points"),
        ("max_total_control_points", 3, "too_many_control_points"),
        ("max_slider_spans", 1, "invalid_value"),
    ],
)
def test_parser_resource_limits(source: bytes, limit: str, value: int, code: str) -> None:
    with pytest.raises(BeatmapParseError) as error:
        parse_osu(source, limits=replace(ParserLimits(), **{limit: value}))
    assert error.value.code == code


def test_exact_file_and_object_limits_are_accepted(source: bytes) -> None:
    limits = ParserLimits(max_file_bytes=len(source), max_hit_objects=4, max_timing_points=4)
    assert len(parse_osu(source, limits=limits).hit_objects) == 4


def test_results_are_reproducible_and_limits_are_validated(source: bytes) -> None:
    first, second = parse_osu(source), parse_osu(source)
    assert first == second
    with pytest.raises(ValueError, match="positive"):
        ParserLimits(max_hit_objects=0)
