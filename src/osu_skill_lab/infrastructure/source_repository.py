from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from osu_skill_lab.application.sources import SourceObservation, SourceReceipt
from osu_skill_lab.infrastructure.models import BeatmapInput, BeatmapSource, OsuBeatmapMatch


async def recent_official_md5(
    session: AsyncSession,
    beatmap_id: int,
    since: datetime,
) -> str | None:
    digest = await session.scalar(
        select(OsuBeatmapMatch.source_md5)
        .where(OsuBeatmapMatch.beatmap_id == beatmap_id, OsuBeatmapMatch.fetched_at >= since)
        .order_by(OsuBeatmapMatch.fetched_at.desc(), OsuBeatmapMatch.input_id.desc())
        .limit(1)
    )
    return digest.hex() if digest is not None else None


async def save_source(session: AsyncSession, input_id: int, receipt: SourceReceipt) -> None:
    source = await session.get(BeatmapInput, input_id)
    if (
        source is None
        or source.source_sha256 != receipt.source_sha256
        or source.source_md5 != receipt.source_md5
        or source.claimed_beatmap_id not in {None, receipt.requested_beatmap_id}
        or source.claimed_beatmap_set_id not in {None, receipt.metadata_beatmap_set_id}
    ):
        raise ValueError("Source receipt does not match the input")
    values = asdict(receipt)
    values.pop("source_sha256")
    values["metadata_md5"] = values.pop("source_md5")
    statement = insert(BeatmapSource).values(input_id=input_id, **values)
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_beatmap_sources_observation",
            set_=values,
            where=BeatmapSource.file_fetched_at <= statement.excluded.file_fetched_at,
        )
    )


async def list_sources(
    session: AsyncSession,
    input_ids: Sequence[int],
) -> dict[int, tuple[SourceObservation, ...]]:
    if not input_ids:
        return {}
    rows = await session.scalars(
        select(BeatmapSource)
        .where(BeatmapSource.input_id.in_(input_ids))
        .order_by(BeatmapSource.id)
    )
    grouped: dict[int, list[SourceObservation]] = {}
    for row in rows:
        grouped.setdefault(row.input_id, []).append(
            SourceObservation(
                row.id,
                row.provider,
                row.requested_beatmap_id,
                row.metadata_beatmap_set_id,
                row.metadata_md5.hex(),
                row.adapter_version,
                row.metadata_schema_version,
                row.metadata_last_updated,
                row.metadata_fetched_at,
                row.file_fetched_at,
                row.metadata_source_layer,
                row.file_source_layer,
                row.metadata_freshness,
                row.http_etag,
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}
