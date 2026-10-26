"""Annotation decisions, rule drafts and portable baseline models are separate data."""

import hashlib
import json
from datetime import datetime
from math import exp, isfinite
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from osu_skill_lab.analysis.features import BasicFeatures
from osu_skill_lab.application.preparation import pipeline_identity

FEATURE_TITLES = {
    "hit_object_count": ("Объекты", "шт."),
    "circle_count": ("Круги", "шт."),
    "slider_count": ("Слайдеры", "шт."),
    "spinner_count": ("Спиннеры", "шт."),
    "timing_point_count": ("Timing points", "шт."),
    "red_timing_point_count": ("Красные timing points", "шт."),
    "inherited_timing_point_count": ("Inherited points / SV", "шт."),
    "red_bpm_min": ("Минимальный red BPM", "BPM"),
    "red_bpm_max": ("Максимальный red BPM", "BPM"),
    "first_object_start_ms": ("Старт первого объекта", "ms"),
    "last_object_start_ms": ("Старт последнего объекта", "ms"),
    "object_start_span_ms": ("Размах стартов объектов", "ms"),
    "head_object_count": ("Heads кругов и слайдеров", "шт."),
    "head_pair_count": ("Пары heads", "шт."),
    "head_interval_min_ms": ("Минимальный интервал heads", "ms"),
    "head_interval_max_ms": ("Максимальный интервал heads", "ms"),
    "head_interval_mean_ms": ("Средний интервал heads", "ms"),
    "head_interval_median_ms": ("Медиана интервалов heads", "ms"),
    "zero_head_interval_count": ("Нулевые интервалы heads", "шт."),
    "raw_head_distance_min_px": ("Минимальная дистанция heads", "px"),
    "raw_head_distance_max_px": ("Максимальная дистанция heads", "px"),
    "raw_head_distance_mean_px": ("Средняя дистанция heads", "px"),
}
FEATURE_KEYS = tuple(FEATURE_TITLES)
LabelValue = Literal["yes", "no", "unsure", "unreviewed"]
Partition = Literal["train", "validation"]
Scalar = Annotated[float, Field(allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


class FeatureProfile(Contract):
    algorithm_version: str
    parser_version: str
    configuration_sha256: str

    @property
    def fingerprint(self) -> str:
        return digest(self.model_dump())


def current_profile() -> FeatureProfile:
    algorithm, parser, configuration = pipeline_identity()
    return FeatureProfile(
        algorithm_version=algorithm, parser_version=parser, configuration_sha256=configuration.hex()
    )


class TagWrite(Contract):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2048)

    @field_validator("name", "description")
    @classmethod
    def clean_text(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Text must be nonblank and contain no NUL")
        return value.strip()


class TagView(TagWrite):
    id: UUID
    definition_sha256: str
    scope: Literal["whole_map_nm"] = "whole_map_nm"
    created_at: datetime


class LabelWrite(Contract):
    analysis_id: int = Field(gt=0, le=2**63 - 1)
    value: LabelValue
    partition: Partition = "train"
    expected_event_id: int | None = Field(default=None, gt=0, le=2**63 - 1)


class LabelView(Contract):
    id: int
    analysis_id: int
    value: LabelValue
    partition: Partition
    created_at: datetime


class LabRow(Contract):
    analysis_id: int
    input_id: int
    sha256: str
    beatmap_id: int | None
    beatmap_set_id: int | None
    title: str
    artist: str
    version: str
    features: BasicFeatures
    label: LabelView | None = None


class Normalizer(Contract):
    means: dict[str, Scalar]
    scales: dict[str, Scalar]

    @model_validator(mode="after")
    def validate_keys(self) -> "Normalizer":
        if set(self.means) != set(FEATURE_KEYS) or set(self.scales) != set(FEATURE_KEYS):
            raise ValueError("Normalizer must describe the current feature catalog")
        if any(value <= 0 for value in self.scales.values()):
            raise ValueError("Scales must be positive")
        return self


class DatasetView(Contract):
    profile: FeatureProfile
    profile_sha256: str
    dataset_sha256: str
    feature_catalog: list[dict[str, str]]
    normalizer: Normalizer
    rows: list[LabRow]
    truncated: bool


class RuleWrite(Contract):
    name: str = Field(min_length=1, max_length=128)
    kind: Literal["manual", "model"] = "manual"
    profile_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    threshold: float = Field(default=0.5, ge=0, le=1)
    bias: float = Field(default=0, ge=-10, le=10)
    weights: dict[str, Annotated[float, Field(ge=-5, le=5)]] = Field(
        default_factory=dict, max_length=22
    )
    normalizer: Normalizer | None = None
    model_id: UUID | None = None

    @model_validator(mode="after")
    def validate_rule(self) -> "RuleWrite":
        if not self.name.strip() or "\x00" in self.name:
            raise ValueError("Rule name must be nonblank and contain no NUL")
        if set(self.weights) - set(FEATURE_KEYS):
            raise ValueError("Unknown feature")
        if self.kind == "manual" and (self.normalizer is None or self.model_id is not None):
            raise ValueError("Manual rule requires a normalizer and no model")
        if self.kind == "model" and (
            self.model_id is None or self.normalizer is not None or self.weights or self.bias
        ):
            raise ValueError("Model rule requires only model identity and threshold")
        return self


class RuleView(Contract):
    id: UUID
    tag_id: UUID
    configuration_sha256: str
    specification: RuleWrite
    created_at: datetime


class TrainRequest(Contract):
    analysis_ids: list[Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]] = Field(
        min_length=4, max_length=1000
    )

    @model_validator(mode="after")
    def unique_ids(self) -> "TrainRequest":
        if len(set(self.analysis_ids)) != len(self.analysis_ids):
            raise ValueError("Repeated analysis ID")
        return self


class ModelArtifact(Contract):
    format_version: Literal["binary-logistic/1"] = "binary-logistic/1"
    tag_id: UUID
    profile: FeatureProfile
    feature_keys: list[str] = Field(min_length=1, max_length=22)
    medians: dict[str, Scalar]
    means: dict[str, Scalar]
    scales: dict[str, Scalar]
    coefficients: list[Scalar] = Field(min_length=2, max_length=44)
    intercept: Scalar
    sklearn_version: str
    numpy_version: str
    training_sha256: str

    @model_validator(mode="after")
    def validate_shape(self) -> "ModelArtifact":
        keys = set(self.feature_keys)
        if len(keys) != len(self.feature_keys) or keys - set(FEATURE_KEYS):
            raise ValueError("Invalid model features")
        if any(set(values) != keys for values in (self.medians, self.means, self.scales)):
            raise ValueError("Model transform mismatch")
        if len(self.coefficients) != 2 * len(keys) or any(v <= 0 for v in self.scales.values()):
            raise ValueError("Model shape mismatch")
        return self


class ModelSummary(Contract):
    id: UUID
    tag_id: UUID
    artifact_sha256: str
    training_sha256: str
    train_count: int
    validation_count: int
    excluded_same_set: int
    latest_event_id: int
    created_at: datetime


class ModelView(ModelSummary):
    artifact: ModelArtifact


def sigmoid(value: float) -> float:
    if not isfinite(value):
        raise ValueError("Nonfinite score")
    return 1 / (1 + exp(-value)) if value >= 0 else exp(value) / (1 + exp(value))


def model_score(artifact: ModelArtifact, features: dict[str, float | None]) -> float:
    values, missing = [], []
    for key in artifact.feature_keys:
        value = features[key]
        missing.append(float(value is None))
        raw = artifact.medians[key] if value is None else value
        values.append((raw - artifact.means[key]) / artifact.scales[key])
    return sigmoid(
        artifact.intercept
        + sum(w * x for w, x in zip(artifact.coefficients, values + missing, strict=True))
    )
