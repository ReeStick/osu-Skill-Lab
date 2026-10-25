"""Selective v14 osu!standard reader. Media, samples and storyboard are ignored."""

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Literal, cast

from osu_skill_lab.analysis.models import (
    BeatmapMetadata,
    DifficultySettings,
    HitCircle,
    ParsedBeatmap,
    ParserLimits,
    Position,
    Slider,
    Spinner,
    TimingPoint,
)

PARSER_VERSION = "osu-standard-v14/1"
_OBJECT_TYPE_MASK = 1 | 2 | 8 | 128  # Circle, slider, spinner, mania hold.
_INTEGER = re.compile(r"[+-]?[0-9]+")
_HEADER = re.compile(r"osu file format v([0-9]+)")
_KEYS = {
    "General": {"Mode", "StackLeniency"},
    "Metadata": {
        "Title",
        "Artist",
        "Creator",
        "Version",
        "TitleUnicode",
        "ArtistUnicode",
        "Source",
        "Tags",
        "BeatmapID",
        "BeatmapSetID",
    },
    "Difficulty": {
        "HPDrainRate",
        "CircleSize",
        "OverallDifficulty",
        "ApproachRate",
        "SliderMultiplier",
        "SliderTickRate",
    },
}
_SECTIONS = {*_KEYS, "TimingPoints", "HitObjects"}


class BeatmapParseError(ValueError):
    def __init__(
        self, code: str, message: str, *, section: str | None = None, line_number: int | None = None
    ) -> None:
        self.code = code
        self.message = message
        self.section = section
        self.line_number = line_number
        location = f" [{section or 'file'}:{line_number or '-'}]"
        super().__init__(message + location)


@dataclass(frozen=True, slots=True)
class _Field:
    value: str
    line_number: int


def _number(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or abs(result) > 1e12 or "_" in value:
        raise ValueError("Expected a finite number with absolute value at most 1e12")
    return result


def _integer(value: str) -> int:
    if _INTEGER.fullmatch(value.strip()) is None:
        raise ValueError("Expected an integer")
    result = int(value)
    if abs(result) > 1_000_000_000_000:
        raise ValueError("Integer exceeds the supported numeric range")
    return result


def _get(fields: dict[str, _Field], key: str, section: str, default: str | None = None) -> _Field:
    if key in fields:
        return fields[key]
    if default is not None:
        return _Field(default, 0)
    raise BeatmapParseError("missing_field", f"Missing {key}", section=section)


def _setting(fields: dict[str, _Field], key: str, default: str | None = None) -> float:
    field = _get(fields, key, "Difficulty", default)
    try:
        value = _number(field.value)
        if key in {"HPDrainRate", "CircleSize", "OverallDifficulty", "ApproachRate"}:
            if not 0 <= value <= 10:
                raise ValueError("Difficulty setting must be between 0 and 10")
        elif value <= 0:
            raise ValueError("Slider setting must be positive")
        return value
    except ValueError as exc:
        raise BeatmapParseError(
            "invalid_value",
            f"Invalid {key}: {exc}",
            section="Difficulty",
            line_number=field.line_number or None,
        ) from None


def _metadata(fields: dict[str, _Field]) -> BeatmapMetadata:
    def text(key: str) -> str:
        return fields[key].value if key in fields else ""

    def identifier(key: str) -> int | None:
        if key not in fields:
            return None
        try:
            value = _integer(fields[key].value)
            if value < -1:
                raise ValueError("Unsupported map ID")
            return value if value > 0 else None
        except ValueError:
            raise BeatmapParseError(
                "invalid_value",
                f"Invalid {key}",
                section="Metadata",
                line_number=fields[key].line_number,
            ) from None

    return BeatmapMetadata(
        text("Title"),
        text("Artist"),
        text("Creator"),
        text("Version"),
        text("TitleUnicode"),
        text("ArtistUnicode"),
        text("Source"),
        tuple(text("Tags").split()),
        identifier("BeatmapID"),
        identifier("BeatmapSetID"),
    )


def _timing_point(line: str, line_number: int) -> TimingPoint:
    parts = [part.strip() for part in line.split(",")]
    try:
        if len(parts) != 8:
            raise ValueError("Timing point must have eight fields")
        time, beat_length = _number(parts[0]), _number(parts[1])
        meter, inherited_flag, effects = _integer(parts[2]), _integer(parts[6]), _integer(parts[7])
        if inherited_flag not in {0, 1}:
            raise ValueError("Uninherited flag must be 0 or 1")
        if (inherited_flag == 1 and beat_length <= 0) or (inherited_flag == 0 and beat_length >= 0):
            raise ValueError("Beat length sign does not match the uninherited flag")
        if meter < 0 or (inherited_flag == 1 and meter == 0) or effects < 0:
            raise ValueError("Invalid meter or effects")
        if not math.isfinite((60_000 if inherited_flag else -100) / beat_length):
            raise ValueError("Timing value would produce a non-finite rate")
        return TimingPoint(time, beat_length, meter, bool(inherited_flag), effects, line_number)
    except (ValueError, OverflowError) as exc:
        raise BeatmapParseError(
            "invalid_value",
            str(exc),
            section="TimingPoints",
            line_number=line_number,
        ) from None


def _hit_object(line: str, line_number: int, limits: ParserLimits) -> HitCircle | Slider | Spinner:
    parts = [part.strip() for part in line.split(",")]
    try:
        if len(parts) < 5:
            raise ValueError("Hit object must have at least five fields")
        position = Position(_number(parts[0]), _number(parts[1]))
        time, flags = _number(parts[2]), _integer(parts[3])
        if not 0 <= flags <= 255 or (flags & _OBJECT_TYPE_MASK) not in {1, 2, 8}:
            raise BeatmapParseError(
                "unsupported_object",
                "Expected exactly one standard object type",
                section="HitObjects",
                line_number=line_number,
            )
        base = (position, time, flags, line_number)
        if flags & 1:
            return HitCircle(*base)
        if flags & 8:
            if len(parts) < 6:
                raise ValueError("Spinner end time is required")
            end = _number(parts[5])
            if end < time:
                raise ValueError("Spinner ends before its start")
            return Spinner(*base, end)
        if len(parts) < 8:
            raise ValueError("Slider path, spans and pixel length are required")
        path = parts[5].split("|")
        if len(path) < 2 or path[0] not in {"B", "C", "L", "P"}:
            raise ValueError("Unsupported or empty slider path")
        if len(path) > limits.max_slider_control_points:
            raise BeatmapParseError(
                "too_many_control_points",
                "Slider exceeds max_slider_control_points",
                section="HitObjects",
                line_number=line_number,
            )
        points = [position]
        for anchor in path[1:]:
            xy = anchor.split(":")
            if len(xy) != 2:
                raise ValueError("Slider control point must be x:y")
            points.append(Position(_number(xy[0]), _number(xy[1])))
        spans, length = _integer(parts[6]), _number(parts[7])
        if not 1 <= spans <= limits.max_slider_spans or length <= 0:
            raise ValueError("Slider spans or pixel length outside supported range")
        curve = cast(Literal["B", "C", "L", "P"], path[0])
        return Slider(*base, curve, tuple(points), spans, length)
    except BeatmapParseError:
        raise
    except (ValueError, OverflowError) as exc:
        raise BeatmapParseError(
            "invalid_value",
            str(exc),
            section="HitObjects",
            line_number=line_number,
        ) from None


def parse_osu(data: bytes, *, limits: ParserLimits | None = None) -> ParsedBeatmap:
    """Read only analytical v14 fields; never open referenced resources."""
    limits = limits if limits is not None else ParserLimits()
    if len(data) > limits.max_file_bytes:
        raise BeatmapParseError("file_too_large", "Input exceeds max_file_bytes")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise BeatmapParseError("invalid_encoding", "Expected UTF-8 with optional BOM") from None
    lines = text.splitlines()
    if lines and len(lines[0]) > limits.max_line_characters:
        raise BeatmapParseError("line_too_long", "Line exceeds max_line_characters", line_number=1)
    match = _HEADER.fullmatch(lines[0].strip()) if lines else None
    if match is None:
        raise BeatmapParseError("invalid_header", "Expected osu file format header", line_number=1)
    if match[1] != "14":
        raise BeatmapParseError("unsupported_version", "Only .osu v14 is supported", line_number=1)
    section = ""
    seen_sections: set[str] = set()
    fields: dict[str, dict[str, _Field]] = {name: {} for name in _KEYS}
    timing: list[TimingPoint] = []
    objects: list[HitCircle | Slider | Spinner] = []
    total_control_points = 0
    for line_number, raw in enumerate(lines[1:], start=2):
        if len(raw) > limits.max_line_characters:
            raise BeatmapParseError(
                "line_too_long",
                "Line exceeds max_line_characters",
                line_number=line_number,
            )
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            if section in _SECTIONS:
                if section in seen_sections:
                    raise BeatmapParseError(
                        "duplicate_section",
                        "Repeated analytical section",
                        section=section,
                        line_number=line_number,
                    )
                seen_sections.add(section)
            continue
        if section in _KEYS:
            key, separator, value = line.partition(":")
            key = key.strip()
            if key not in _KEYS[section]:
                continue
            if not separator or key in fields[section]:
                raise BeatmapParseError(
                    "duplicate_field" if key in fields[section] else "invalid_value",
                    f"Repeated or malformed {key}",
                    section=section,
                    line_number=line_number,
                )
            fields[section][key] = _Field(value.strip(), line_number)
        elif section == "TimingPoints":
            if len(timing) >= limits.max_timing_points:
                raise BeatmapParseError(
                    "too_many_timing_points",
                    "Input exceeds max_timing_points",
                    section=section,
                    line_number=line_number,
                )
            point = _timing_point(line, line_number)
            if timing and point.time_ms < timing[-1].time_ms:
                raise BeatmapParseError(
                    "unsorted_timing_points",
                    "Timing points must be chronological",
                    section=section,
                    line_number=line_number,
                )
            timing.append(point)
        elif section == "HitObjects":
            if len(objects) >= limits.max_hit_objects:
                raise BeatmapParseError(
                    "too_many_objects",
                    "Input exceeds max_hit_objects",
                    section=section,
                    line_number=line_number,
                )
            hit_object = _hit_object(line, line_number, limits)
            if isinstance(hit_object, Slider):
                total_control_points += len(hit_object.control_points)
                if total_control_points > limits.max_total_control_points:
                    raise BeatmapParseError(
                        "too_many_control_points",
                        "Input exceeds max_total_control_points",
                        section=section,
                        line_number=line_number,
                    )
            objects.append(hit_object)

    for required in ("Difficulty", "TimingPoints", "HitObjects"):
        if required not in seen_sections:
            raise BeatmapParseError("missing_section", f"Missing {required}", section=required)
    general = fields["General"]
    for key, default in (("Mode", "0"), ("StackLeniency", "0.7")):
        field = _get(general, key, "General", default)
        try:
            number = _integer(field.value) if key == "Mode" else _number(field.value)
            if key == "Mode" and number != 0:
                raise BeatmapParseError(
                    "unsupported_mode",
                    "Only osu!standard is supported",
                    section="General",
                    line_number=field.line_number or None,
                )
            if key == "StackLeniency" and not 0 <= number <= 1:
                raise ValueError("StackLeniency must be between 0 and 1")
        except BeatmapParseError:
            raise
        except ValueError:
            raise BeatmapParseError(
                "invalid_value",
                f"Invalid {key}",
                section="General",
                line_number=field.line_number or None,
            ) from None
    if not any(point.uninherited for point in timing):
        raise BeatmapParseError(
            "missing_tempo",
            "At least one uninherited timing point is required",
            section="TimingPoints",
        )
    settings = fields["Difficulty"]
    od = _setting(settings, "OverallDifficulty")
    difficulty = DifficultySettings(
        _setting(settings, "HPDrainRate"),
        _setting(settings, "CircleSize"),
        od,
        _setting(settings, "ApproachRate", str(od)),
        _setting(settings, "SliderMultiplier"),
        _setting(settings, "SliderTickRate"),
    )
    ordered = sorted(objects, key=lambda hit: hit.start_time_ms)
    warnings = ("hit_objects_stably_sorted",) if objects != ordered else ()
    return ParsedBeatmap(
        PARSER_VERSION,
        14,
        hashlib.sha256(data).hexdigest(),
        limits,
        _metadata(fields["Metadata"]),
        difficulty,
        _number(_get(general, "StackLeniency", "General", "0.7").value),
        tuple(timing),
        tuple(ordered),
        warnings,
    )
