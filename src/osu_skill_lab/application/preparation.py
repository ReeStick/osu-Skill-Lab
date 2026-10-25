"""Pure process-worker entry point. Only compact records leave the worker."""

import hashlib
import json
from dataclasses import asdict, dataclass

from osu_skill_lab.analysis.features import ALGORITHM_VERSION, BasicFeatures, extract_basic_features
from osu_skill_lab.analysis.models import DifficultySettings, ParserLimits
from osu_skill_lab.analysis.parser import BeatmapParseError, parse_osu


@dataclass(frozen=True, slots=True)
class InputMetadata:
    title: str
    artist: str
    creator: str
    version: str
    beatmap_id: int | None
    beatmap_set_id: int | None


@dataclass(frozen=True, slots=True)
class PreparedAnalysis:
    source_sha256: bytes
    source_md5: bytes
    byte_size: int
    format_version: int
    metadata: InputMetadata
    difficulty: DifficultySettings
    stack_leniency: float
    parser_version: str
    algorithm_version: str
    configuration: dict[str, object]
    configuration_sha256: bytes
    features: BasicFeatures


@dataclass(frozen=True, slots=True)
class PreparationFailure:
    code: str
    message: str
    section: str | None = None
    line_number: int | None = None


def prepare_analysis(data: bytes) -> PreparedAnalysis | PreparationFailure:
    """Snapshot bytes are temporary; neither bytes nor parsed object arrays are returned."""
    try:
        limits = ParserLimits()
        beatmap = parse_osu(data, limits=limits)
    except BeatmapParseError as exc:
        # Return a pickle-safe value: the exception constructor is not pickle-compatible.
        return PreparationFailure(exc.code, exc.message, exc.section, exc.line_number)
    for name, maximum in (("title", 512), ("artist", 512), ("creator", 256), ("version", 512)):
        value = getattr(beatmap.metadata, name)
        if "\x00" in value:
            return PreparationFailure(
                "invalid_metadata", f"Metadata {name} contains a NUL character", section="Metadata"
            )
        if len(value) > maximum:
            return PreparationFailure(
                "metadata_too_long", f"Metadata {name} exceeds {maximum} characters"
            )
    configuration: dict[str, object] = {
        "ruleset": 0,
        "mods": [],
        "coordinate_space": "raw",
        "parser_limits": asdict(limits),
    }
    canonical = json.dumps(configuration, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return PreparedAnalysis(
        bytes.fromhex(beatmap.source_sha256),
        hashlib.md5(data, usedforsecurity=False).digest(),
        len(data),
        beatmap.format_version,
        InputMetadata(
            beatmap.metadata.title,
            beatmap.metadata.artist,
            beatmap.metadata.creator,
            beatmap.metadata.version,
            beatmap.metadata.beatmap_id,
            beatmap.metadata.beatmap_set_id,
        ),
        beatmap.difficulty,
        beatmap.stack_leniency,
        beatmap.parser_version,
        ALGORITHM_VERSION,
        configuration,
        hashlib.sha256(canonical.encode("utf-8")).digest(),
        extract_basic_features(beatmap),
    )
