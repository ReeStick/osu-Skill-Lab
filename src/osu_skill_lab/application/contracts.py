from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from osu_skill_lab.analysis.features import BasicFeatures
from osu_skill_lab.analysis.models import DifficultySettings


@dataclass(frozen=True, slots=True)
class BeatmapIdentity:
    input_id: int
    sha256: str
    md5: str
    byte_size: int
    format_version: int
    ruleset: int
    claimed_beatmap_id: int | None
    claimed_beatmap_set_id: int | None
    title: str
    artist: str
    creator: str
    difficulty_name: str
    metadata_parser_version: str
    identity_status: Literal["unverified"] = "unverified"


@dataclass(frozen=True, slots=True)
class AnalysisRecord:
    id: int
    beatmap: BeatmapIdentity
    algorithm_version: str
    parser_version: str
    configuration: dict[str, object]
    configuration_sha256: str
    difficulty: DifficultySettings
    stack_leniency: float
    features: BasicFeatures
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SaveAnalysisOutcome:
    record: AnalysisRecord
    created: bool


@dataclass(frozen=True, slots=True)
class AnalysisPage:
    items: tuple[AnalysisRecord, ...]
    next_after_id: int | None
