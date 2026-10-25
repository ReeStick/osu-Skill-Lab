from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from osu_skill_lab.application.osu_metadata import OsuApiError, OsuMetadata
from osu_skill_lab.infrastructure.models import BeatmapInput, OsuBeatmapMatch


async def save_match(session: AsyncSession, input_id: int, metadata: OsuMetadata) -> None:
    expected = await session.scalar(
        select(BeatmapInput.source_md5).where(BeatmapInput.id == input_id)
    )
    if metadata.md5 is None or expected != bytes.fromhex(metadata.md5):
        raise OsuApiError("osu_checksum_mismatch", "osu! checksum does not match the input")
    values = asdict(metadata)
    values["source_md5"] = bytes.fromhex(values.pop("md5"))
    statement = insert(OsuBeatmapMatch).values(input_id=input_id, **values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[OsuBeatmapMatch.input_id],
            set_=values,
            where=OsuBeatmapMatch.fetched_at <= statement.excluded.fetched_at,
        )
    )
