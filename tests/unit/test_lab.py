import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from osu_skill_lab.analysis.label_baseline import TrainingExample, train_baseline
from osu_skill_lab.application.lab_contracts import (
    FEATURE_KEYS,
    Normalizer,
    RuleWrite,
    TagWrite,
    TrainRequest,
    current_profile,
    model_score,
)
from osu_skill_lab.infrastructure.model_artifacts import ArtifactUnavailable, ModelArtifactStore


def example(index: int, value: str, amount: float | None) -> TrainingExample:
    features: dict[str, float | None] = dict.fromkeys(FEATURE_KEYS)
    features["hit_object_count"] = amount
    features["circle_count"] = float(index)
    return TrainingExample(index, index, f"{index:064x}", f"set:{index}", value, "train", features)


def examples() -> tuple[TrainingExample, ...]:
    return tuple(example(i, "yes" if i > 2 else "no", float(i * 10)) for i in range(1, 5))


def test_preprocessing_uses_only_training_and_excludes_control_families() -> None:
    rows = examples()
    control = replace(example(5, "yes", 100000), partition="validation", group="set:held")
    leaked = replace(example(6, "no", -100000), group="set:held")
    uncertain = example(7, "unsure", 999999)
    result = train_baseline(uuid4(), current_profile(), (*rows, control, leaked, uncertain))
    assert result.train_count == 4 and result.validation_count == 1
    assert result.excluded_same_set == 1
    assert result.artifact.means["hit_object_count"] == 25
    assert result.artifact.medians["hit_object_count"] == 25
    assert [row.analysis_id for row in result.examples] == [1, 2, 3, 4, 5]
    assert "red_bpm_min" not in result.artifact.feature_keys
    assert model_score(result.artifact, rows[0].features) < model_score(
        result.artifact, rows[3].features
    )


def test_missing_features_determinism_and_event_provenance() -> None:
    rows = (*examples()[:3], example(4, "yes", None))
    tag = uuid4()
    first = train_baseline(tag, current_profile(), rows)
    repeat = train_baseline(tag, current_profile(), rows)
    assert first.artifact == repeat.artifact
    assert 0 < model_score(first.artifact, rows[-1].features) < 1
    assert first.artifact.medians["hit_object_count"] == 20
    changed = train_baseline(tag, current_profile(), (*rows[:3], replace(rows[-1], event_id=99)))
    assert changed.artifact.training_sha256 != first.artifact.training_sha256


def test_requires_two_explicit_examples_per_class_after_exclusion() -> None:
    rows = (*examples()[:3], example(4, "unsure", 40))
    with pytest.raises(ValueError, match="по два"):
        train_baseline(uuid4(), current_profile(), rows)


def test_artifact_roundtrip_no_overwrite_and_checksum_guard(tmp_path: Path) -> None:
    store = ModelArtifactStore(tmp_path / "models")
    artifact = train_baseline(uuid4(), current_profile(), examples()).artifact
    model_id = uuid4()
    checksum = store.save(model_id, artifact)
    assert store.load(model_id, checksum) == artifact
    with pytest.raises(ArtifactUnavailable):
        store.save(model_id, artifact)
    path = store.directory / f"{model_id}.json"
    path.write_text("{}")
    with pytest.raises(ArtifactUnavailable):
        store.load(model_id, checksum)
    store.remove_owned(model_id, checksum)
    assert path.exists(), "Do not remove a changed or foreign artifact"


def test_artifact_io_failure_is_safe(tmp_path: Path) -> None:
    target = tmp_path / "not-a-directory"
    target.write_text("occupied")
    artifact = train_baseline(uuid4(), current_profile(), examples()).artifact
    with pytest.raises(ArtifactUnavailable):
        ModelArtifactStore(target).save(uuid4(), artifact)


def test_request_contracts_reject_ambiguous_or_unknown_data() -> None:
    with pytest.raises(ValidationError):
        TagWrite(name="  ", description="criteria")
    with pytest.raises(ValidationError):
        TrainRequest(analysis_ids=[1, 2, 3, 3])
    with pytest.raises(ValidationError):
        RuleWrite(
            name="bad",
            profile_sha256="0" * 64,
            dataset_sha256="1" * 64,
            weights={"invented_pp": 1},
            normalizer=Normalizer(
                means=dict.fromkeys(FEATURE_KEYS, 0), scales=dict.fromkeys(FEATURE_KEYS, 1)
            ),
        )


def test_trained_portable_model_matches_browser_scoring() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed for cross-language scoring verification")
    rows = (*examples(), example(5, "no", None))
    artifact = train_baseline(uuid4(), current_profile(), rows).artifact
    script = Path(__file__).resolve().parents[1] / "web" / "model-parity.mjs"
    result = subprocess.run(
        [node, str(script)],
        input=json.dumps(
            {
                "artifact": artifact.model_dump(mode="json"),
                "features": [row.features for row in rows],
            }
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    assert json.loads(result.stdout) == pytest.approx(
        [model_score(artifact, row.features) for row in rows], abs=1e-12
    )
