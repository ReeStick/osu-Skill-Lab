from dataclasses import asdict
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osu_skill_lab.analysis.features import BasicFeatures
from osu_skill_lab.application.lab_contracts import (
    FEATURE_KEYS,
    FeatureProfile,
    LabelValue,
    LabelView,
    LabRow,
    ModelSummary,
    Partition,
    RuleView,
    RuleWrite,
    TagView,
    TagWrite,
    current_profile,
    digest,
)
from osu_skill_lab.infrastructure.lab_models import LabLabelEvent, LabModel, LabRule, LabTag
from osu_skill_lab.infrastructure.models import AnalysisResult, BeatmapInput


def tag_view(row: LabTag) -> TagView:
    return TagView(
        id=row.id,
        name=row.name,
        description=row.description,
        definition_sha256=row.definition_sha256.hex(),
        created_at=row.created_at,
    )


def label_view(row: LabLabelEvent) -> LabelView:
    return LabelView(
        id=row.id,
        analysis_id=row.analysis_id,
        value=cast(LabelValue, row.value),
        partition=cast(Partition, row.partition),
        created_at=row.created_at,
    )


def rule_view(row: LabRule) -> RuleView:
    return RuleView(
        id=row.id,
        tag_id=row.tag_id,
        configuration_sha256=row.configuration_sha256.hex(),
        specification=RuleWrite.model_validate(row.specification),
        created_at=row.created_at,
    )


def model_summary(row: LabModel) -> ModelSummary:
    return ModelSummary(
        id=row.id,
        tag_id=row.tag_id,
        artifact_sha256=row.artifact_sha256.hex(),
        training_sha256=row.training_sha256.hex(),
        train_count=row.train_count,
        validation_count=row.validation_count,
        excluded_same_set=row.excluded_same_set,
        latest_event_id=row.latest_event_id,
        created_at=row.created_at,
    )


async def create_tag(session: AsyncSession, body: TagWrite) -> TagView:
    definition = digest(
        {"name": body.name, "description": body.description, "scope": "whole_map_nm"}
    )
    row = LabTag(
        id=uuid4(),
        name=body.name,
        canonical_name=body.name.casefold(),
        description=body.description,
        definition_sha256=bytes.fromhex(definition),
    )
    session.add(row)
    await session.flush()
    return tag_view(row)


async def latest_labels(
    session: AsyncSession, tag_id: UUID, input_ids: list[int]
) -> dict[int, LabelView]:
    if not input_ids:
        return {}
    rows = await session.scalars(
        select(LabLabelEvent)
        .where(
            LabLabelEvent.tag_id == tag_id,
            LabLabelEvent.input_id.in_(input_ids),
        )
        .distinct(LabLabelEvent.input_id)
        .order_by(LabLabelEvent.input_id, LabLabelEvent.id.desc())
    )
    return {row.input_id: label_view(row) for row in rows}


async def dataset_rows(
    session: AsyncSession,
    tag_id: UUID | None,
    *,
    limit: int = 500,
    analysis_ids: list[int] | None = None,
) -> tuple[list[LabRow], bool]:
    profile = current_profile()
    query = (
        select(AnalysisResult, BeatmapInput)
        .join(BeatmapInput)
        .where(
            AnalysisResult.algorithm_version == profile.algorithm_version,
            AnalysisResult.parser_version == profile.parser_version,
            AnalysisResult.configuration_sha256 == bytes.fromhex(profile.configuration_sha256),
        )
        .order_by(AnalysisResult.id)
    )
    if analysis_ids is not None:
        query = query.where(AnalysisResult.id.in_(analysis_ids))
    rows = (await session.execute(query.limit(limit + 1))).all()
    labels = (
        await latest_labels(session, tag_id, [row[1].id for row in rows[:limit]]) if tag_id else {}
    )
    result = []
    for analysis, source in rows[:limit]:
        features = BasicFeatures(**{key: getattr(analysis, key) for key in FEATURE_KEYS})
        result.append(
            LabRow(
                analysis_id=analysis.id,
                input_id=source.id,
                sha256=source.source_sha256.hex(),
                beatmap_id=source.claimed_beatmap_id,
                beatmap_set_id=source.claimed_beatmap_set_id,
                title=source.title,
                artist=source.artist,
                version=source.difficulty_name,
                features=features,
                label=labels.get(source.id),
            )
        )
    return result, len(rows) > limit


def feature_values(row: LabRow) -> dict[str, float | None]:
    return {
        key: float(value) if value is not None else None
        for key, value in asdict(row.features).items()
    }


def compatible(profile: FeatureProfile) -> bool:
    return profile == current_profile()
