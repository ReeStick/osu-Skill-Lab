"""Selected API metadata; no difficulty attributes or upstream output blobs."""

from dataclasses import dataclass
from datetime import datetime

API_RESPONSE_VERSION = "20240529"
METADATA_SCHEMA_VERSION = "osu-api-metadata/1"


@dataclass(frozen=True, slots=True)
class OsuMetadata:
    beatmap_id: int
    beatmap_set_id: int
    md5: str | None
    title: str
    artist: str
    set_creator: str
    creator_id: int
    difficulty_name: str
    status: str
    last_updated: datetime
    fetched_at: datetime
    api_response_version: str = API_RESPONSE_VERSION
    metadata_schema_version: str = METADATA_SCHEMA_VERSION


class OsuApiError(RuntimeError):
    def __init__(self, code: str, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.retry_after = code, message, retry_after
