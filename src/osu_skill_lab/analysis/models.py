from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ParserLimits:
    max_file_bytes: int = 4 * 1024 * 1024
    max_line_characters: int = 65_536
    max_hit_objects: int = 100_000
    max_timing_points: int = 100_000
    max_slider_control_points: int = 2_048
    max_total_control_points: int = 100_000
    max_slider_spans: int = 9_000

    def __post_init__(self) -> None:
        if any(value <= 0 for value in asdict(self).values()):
            raise ValueError("All parser limits must be positive")


@dataclass(frozen=True, slots=True)
class BeatmapMetadata:
    title: str
    artist: str
    creator: str
    version: str
    title_unicode: str
    artist_unicode: str
    source: str
    tags: tuple[str, ...]
    beatmap_id: int | None
    beatmap_set_id: int | None


@dataclass(frozen=True, slots=True)
class DifficultySettings:
    hp_drain_rate: float
    circle_size: float
    overall_difficulty: float
    approach_rate: float
    slider_multiplier: float
    slider_tick_rate: float


@dataclass(frozen=True, slots=True)
class TimingPoint:
    time_ms: float
    beat_length: float
    meter: int
    uninherited: bool
    effects: int
    line_number: int

    @property
    def bpm(self) -> float | None:
        return 60_000 / self.beat_length if self.uninherited else None


@dataclass(frozen=True, slots=True)
class Position:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class HitObject:
    position: Position
    start_time_ms: float
    type_flags: int
    line_number: int


@dataclass(frozen=True, slots=True)
class HitCircle(HitObject):
    pass


@dataclass(frozen=True, slots=True)
class Slider(HitObject):
    curve_type: Literal["B", "C", "L", "P"]
    control_points: tuple[Position, ...]
    spans: int
    pixel_length: float


@dataclass(frozen=True, slots=True)
class Spinner(HitObject):
    end_time_ms: float


@dataclass(frozen=True, slots=True)
class ParsedBeatmap:
    parser_version: str
    format_version: int
    source_sha256: str
    limits: ParserLimits
    metadata: BeatmapMetadata
    difficulty: DifficultySettings
    stack_leniency: float
    timing_points: tuple[TimingPoint, ...]
    hit_objects: tuple[HitCircle | Slider | Spinner, ...]
    warnings: tuple[str, ...]
