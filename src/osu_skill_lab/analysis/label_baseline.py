"""Pure CPU training entry point; only a small portable artifact leaves the process."""

import warnings
from dataclasses import dataclass
from statistics import fmean, median, pstdev
from uuid import UUID

from osu_skill_lab.application.lab_contracts import (
    FEATURE_KEYS,
    FeatureProfile,
    ModelArtifact,
    digest,
)


@dataclass(frozen=True)
class TrainingExample:
    analysis_id: int
    event_id: int
    sha256: str
    group: str
    value: str
    partition: str
    features: dict[str, float | None]


@dataclass(frozen=True)
class TrainingResult:
    artifact: ModelArtifact
    examples: tuple[TrainingExample, ...]
    train_count: int
    validation_count: int
    excluded_same_set: int


def train_baseline(
    tag_id: UUID, profile: FeatureProfile, examples: tuple[TrainingExample, ...]
) -> TrainingResult:
    import numpy as np
    from sklearn import __version__ as sklearn_version  # type: ignore[import-untyped]
    from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]
    from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

    validation = [
        row for row in examples if row.partition == "validation" and row.value in {"yes", "no"}
    ]
    groups = {row.group for row in validation}
    candidates = [
        row for row in examples if row.partition == "train" and row.value in {"yes", "no"}
    ]
    training = [row for row in candidates if row.group not in groups]
    if any(sum(row.value == value for row in training) < 2 for value in ("yes", "no")):
        raise ValueError(
            "Нужно хотя бы по два обучающих примера «есть» и «нет» вне контрольных сетов"
        )
    keys = [key for key in FEATURE_KEYS if any(row.features[key] is not None for row in training)]
    if not keys:
        raise ValueError("Нет доступных признаков для обучения")
    medians = {
        key: median([value for row in training if (value := row.features[key]) is not None])
        for key in keys
    }
    means, scales = {}, {}
    for key in keys:
        values = [
            medians[key] if (value := row.features[key]) is None else value for row in training
        ]
        means[key], scales[key] = fmean(values), pstdev(values) or 1.0
    matrix = []
    for row in training:
        values = [(medians[key] if (value := row.features[key]) is None else value) for key in keys]
        matrix.append(
            [(value - means[key]) / scales[key] for key, value in zip(keys, values, strict=True)]
            + [float(row.features[key] is None) for key in keys]
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            estimator = LogisticRegression(solver="liblinear", C=1.0, max_iter=1000, random_state=0)
            estimator.fit(
                np.asarray(matrix, dtype=np.float64),
                np.asarray([row.value == "yes" for row in training]),
            )
    except ConvergenceWarning:
        raise ValueError("Модель не сошлась. Проверьте разметку и набор признаков") from None
    selected = tuple(training + validation)
    fingerprint = digest(
        {
            "profile": profile.model_dump(),
            "tag": str(tag_id),
            "examples": [
                (row.analysis_id, row.event_id, row.sha256, row.value, row.partition)
                for row in selected
            ],
            "provider": "binary-logistic/1",
            "sklearn": sklearn_version,
            "numpy": np.__version__,
        }
    )
    artifact = ModelArtifact(
        tag_id=tag_id,
        profile=profile,
        feature_keys=keys,
        medians=medians,
        means=means,
        scales=scales,
        coefficients=[float(v) for v in estimator.coef_[0]],
        intercept=float(estimator.intercept_[0]),
        sklearn_version=str(sklearn_version),
        numpy_version=np.__version__,
        training_sha256=fingerprint,
    )
    return TrainingResult(
        artifact, selected, len(training), len(validation), len(candidates) - len(training)
    )
