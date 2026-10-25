"""Fixed-size measurements of raw beatmap data, without gameplay normalization."""

from dataclasses import dataclass
from itertools import pairwise
from math import hypot
from statistics import fmean, median

from osu_skill_lab.analysis.models import HitCircle, ParsedBeatmap, Slider, Spinner

ALGORITHM_VERSION = "basic-raw/1"


@dataclass(frozen=True, slots=True)
class BasicFeatures:
    """Raw measurements; timestamps are starts, never full map/play durations.

    Head pairs join consecutive circles/slider heads, skipping spinners. Distances
    use unmodified file coordinates: no slider ends, stacking, mods, coordinate
    clamping, or effective gameplay values. BPM extrema cover all red lines, not
    only the playable range. None means an aggregate has no observations.
    """

    hit_object_count: int
    circle_count: int
    slider_count: int
    spinner_count: int
    timing_point_count: int
    red_timing_point_count: int
    inherited_timing_point_count: int
    red_bpm_min: float | None
    red_bpm_max: float | None
    first_object_start_ms: float | None
    last_object_start_ms: float | None
    object_start_span_ms: float | None
    head_object_count: int
    head_pair_count: int
    head_interval_min_ms: float | None
    head_interval_max_ms: float | None
    head_interval_mean_ms: float | None
    head_interval_median_ms: float | None
    zero_head_interval_count: int
    raw_head_distance_min_px: float | None
    raw_head_distance_max_px: float | None
    raw_head_distance_mean_px: float | None


def extract_basic_features(beatmap: ParsedBeatmap) -> BasicFeatures:
    """Measure a parser-validated, chronologically ordered beatmap in memory.

    The parser's finite numeric and object-count limits bound work and values.
    Output contains only deterministic JSON-safe scalars, with no object data or
    claims about difficulty, PP, skill profiles, or tournament slots.
    """
    objects = beatmap.hit_objects
    heads = tuple(hit for hit in objects if isinstance(hit, HitCircle | Slider))
    intervals = [right.start_time_ms - left.start_time_ms for left, right in pairwise(heads)]
    distances = [
        hypot(right.position.x - left.position.x, right.position.y - left.position.y)
        for left, right in pairwise(heads)
    ]
    red_bpms = [point.bpm for point in beatmap.timing_points if point.bpm is not None]
    first_start = objects[0].start_time_ms if objects else None
    last_start = objects[-1].start_time_ms if objects else None
    return BasicFeatures(
        hit_object_count=len(objects),
        circle_count=sum(isinstance(hit, HitCircle) for hit in objects),
        slider_count=sum(isinstance(hit, Slider) for hit in objects),
        spinner_count=sum(isinstance(hit, Spinner) for hit in objects),
        timing_point_count=len(beatmap.timing_points),
        red_timing_point_count=len(red_bpms),
        inherited_timing_point_count=len(beatmap.timing_points) - len(red_bpms),
        red_bpm_min=min(red_bpms) if red_bpms else None,
        red_bpm_max=max(red_bpms) if red_bpms else None,
        first_object_start_ms=first_start,
        last_object_start_ms=last_start,
        object_start_span_ms=(
            last_start - first_start if first_start is not None and last_start is not None else None
        ),
        head_object_count=len(heads),
        head_pair_count=len(intervals),
        head_interval_min_ms=min(intervals) if intervals else None,
        head_interval_max_ms=max(intervals) if intervals else None,
        head_interval_mean_ms=fmean(intervals) if intervals else None,
        head_interval_median_ms=median(intervals) if intervals else None,
        zero_head_interval_count=intervals.count(0),
        raw_head_distance_min_px=min(distances) if distances else None,
        raw_head_distance_max_px=max(distances) if distances else None,
        raw_head_distance_mean_px=fmean(distances) if distances else None,
    )
