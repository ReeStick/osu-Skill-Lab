from dataclasses import asdict, fields

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from osu_skill_lab.analysis.features import BasicFeatures
from osu_skill_lab.analysis.models import DifficultySettings
from osu_skill_lab.application.contracts import (
    AnalysisPage,
    AnalysisRecord,
    BeatmapIdentity,
    SaveAnalysisOutcome,
)
from osu_skill_lab.application.preparation import PreparedAnalysis
from osu_skill_lab.infrastructure.models import AnalysisResult, BeatmapInput


def _record(result: AnalysisResult, source: BeatmapInput) -> AnalysisRecord:
    return AnalysisRecord(
        result.id,
        BeatmapIdentity(
            source.id,
            source.source_sha256.hex(),
            source.source_md5.hex(),
            source.byte_size,
            source.format_version,
            source.ruleset,
            source.claimed_beatmap_id,
            source.claimed_beatmap_set_id,
            source.title,
            source.artist,
            source.creator,
            source.difficulty_name,
            source.metadata_parser_version,
        ),
        result.algorithm_version,
        result.parser_version,
        result.configuration,
        result.configuration_sha256.hex(),
        DifficultySettings(
            **{field.name: getattr(result, field.name) for field in fields(DifficultySettings)}
        ),
        result.stack_leniency,
        BasicFeatures(
            **{field.name: getattr(result, field.name) for field in fields(BasicFeatures)}
        ),
        result.created_at,
    )


async def get_analysis(session: AsyncSession, analysis_id: int) -> AnalysisRecord | None:
    row = (
        await session.execute(
            select(AnalysisResult, BeatmapInput)
            .join(BeatmapInput)
            .where(AnalysisResult.id == analysis_id)
        )
    ).one_or_none()
    return _record(*row) if row is not None else None


async def list_analyses(
    session: AsyncSession, *, limit: int, after_id: int, claimed_beatmap_id: int | None = None
) -> AnalysisPage:
    query = (
        select(AnalysisResult, BeatmapInput).join(BeatmapInput).where(AnalysisResult.id > after_id)
    )
    if claimed_beatmap_id is not None:
        query = query.where(BeatmapInput.claimed_beatmap_id == claimed_beatmap_id)
    rows = (await session.execute(query.order_by(AnalysisResult.id).limit(limit + 1))).all()
    items = tuple(_record(*row) for row in rows[:limit])
    return AnalysisPage(items, items[-1].id if len(rows) > limit else None)


async def save_analysis(session: AsyncSession, candidate: PreparedAnalysis) -> SaveAnalysisOutcome:
    metadata = candidate.metadata
    input_id = await session.scalar(
        insert(BeatmapInput)
        .values(
            source_sha256=candidate.source_sha256,
            source_md5=candidate.source_md5,
            byte_size=candidate.byte_size,
            format_version=candidate.format_version,
            ruleset=0,
            claimed_beatmap_id=metadata.beatmap_id,
            claimed_beatmap_set_id=metadata.beatmap_set_id,
            title=metadata.title,
            artist=metadata.artist,
            creator=metadata.creator,
            difficulty_name=metadata.version,
            metadata_parser_version=candidate.parser_version,
        )
        .on_conflict_do_nothing(index_elements=[BeatmapInput.source_sha256])
        .returning(BeatmapInput.id)
    )
    if input_id is None:
        # Separate statement gets a fresh READ COMMITTED snapshot after a conflicting insert.
        input_id = await session.scalar(
            select(BeatmapInput.id).where(BeatmapInput.source_sha256 == candidate.source_sha256)
        )
    if input_id is None:
        raise RuntimeError("Input conflict resolved without a visible row")
    result_id = await session.scalar(
        insert(AnalysisResult)
        .values(
            input_id=input_id,
            algorithm_version=candidate.algorithm_version,
            parser_version=candidate.parser_version,
            configuration=candidate.configuration,
            configuration_sha256=candidate.configuration_sha256,
            stack_leniency=candidate.stack_leniency,
            **asdict(candidate.difficulty),
            **asdict(candidate.features),
        )
        .on_conflict_do_nothing(constraint="uq_analysis_results_identity")
        .returning(AnalysisResult.id)
    )
    created = result_id is not None
    if result_id is None:
        result_id = await session.scalar(
            select(AnalysisResult.id).where(
                AnalysisResult.input_id == input_id,
                AnalysisResult.algorithm_version == candidate.algorithm_version,
                AnalysisResult.parser_version == candidate.parser_version,
                AnalysisResult.configuration_sha256 == candidate.configuration_sha256,
            )
        )
    if result_id is None:
        raise RuntimeError("Analysis conflict resolved without a visible row")
    record = await get_analysis(session, result_id)
    if record is None:
        raise RuntimeError("Saved analysis is not visible")
    return SaveAnalysisOutcome(record, created)
