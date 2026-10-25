from dataclasses import dataclass

from osu_skill_lab.analysis.models import (
    BeatmapMetadata,
    DifficultySettings,
    HitCircle,
    ParsedBeatmap,
    Slider,
    Spinner,
)


@dataclass(frozen=True, slots=True)
class BeatmapSummary:
    parser_version: str
    format_version: int
    source_sha256: str
    metadata: BeatmapMetadata
    difficulty: DifficultySettings
    stack_leniency: float
    hit_objects: int
    circles: int
    sliders: int
    spinners: int
    timing_points: int
    tempo_points: int
    inherited_points: int
    bpm_min: float
    bpm_max: float
    first_object_start_ms: float | None
    last_object_start_ms: float | None
    warnings: tuple[str, ...]


def summarize_beatmap(beatmap: ParsedBeatmap) -> BeatmapSummary:
    """Raw setting/count summary; BPM extrema cover red lines, not weighted playtime."""
    tempos = [bpm for point in beatmap.timing_points if (bpm := point.bpm) is not None]
    objects = beatmap.hit_objects
    return BeatmapSummary(
        beatmap.parser_version,
        beatmap.format_version,
        beatmap.source_sha256,
        beatmap.metadata,
        beatmap.difficulty,
        beatmap.stack_leniency,
        len(objects),
        sum(isinstance(hit, HitCircle) for hit in objects),
        sum(isinstance(hit, Slider) for hit in objects),
        sum(isinstance(hit, Spinner) for hit in objects),
        len(beatmap.timing_points),
        len(tempos),
        len(beatmap.timing_points) - len(tempos),
        min(tempos),
        max(tempos),
        objects[0].start_time_ms if objects else None,
        objects[-1].start_time_ms if objects else None,
        beatmap.warnings,
    )
