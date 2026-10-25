"""Download provenance is distinct from file claims and official API verification."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

HINAMIZAWA_ADAPTER_VERSION = "hinamizawa/1"
HINAMIZAWA_SCHEMA_VERSION = "hinamizawa-batch/1"


@dataclass(frozen=True, slots=True)
class SourceReceipt:
    requested_beatmap_id: int
    metadata_beatmap_set_id: int
    source_sha256: bytes
    source_md5: bytes
    metadata_last_updated: datetime
    metadata_fetched_at: datetime
    file_fetched_at: datetime
    metadata_source_layer: str | None = None
    file_source_layer: str | None = None
    metadata_freshness: str | None = None
    http_etag: str | None = None
    provider: Literal["hinamizawa"] = "hinamizawa"
    adapter_version: str = HINAMIZAWA_ADAPTER_VERSION
    metadata_schema_version: str = HINAMIZAWA_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class SourceObservation:
    id: int
    provider: str
    requested_beatmap_id: int
    metadata_beatmap_set_id: int
    metadata_md5: str
    adapter_version: str
    metadata_schema_version: str
    metadata_last_updated: datetime
    metadata_fetched_at: datetime
    file_fetched_at: datetime
    metadata_source_layer: str | None
    file_source_layer: str | None
    metadata_freshness: str | None
    http_etag: str | None


@dataclass(frozen=True, slots=True)
class MirrorMetadata:
    beatmap_id: int
    beatmap_set_id: int
    md5: str | None
    ruleset: int
    last_updated: datetime
    fetched_at: datetime
    source_layer: str | None = None
    freshness: str | None = None


@dataclass(frozen=True, slots=True)
class MirrorIssue:
    beatmap_id: int
    kind: Literal["missing", "unresolved"]
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MirrorResolution:
    items: tuple[MirrorMetadata, ...]
    issues: tuple[MirrorIssue, ...]


@dataclass(frozen=True, slots=True)
class DownloadedBeatmap:
    data: bytes = field(repr=False)
    receipt: SourceReceipt


class MirrorError(RuntimeError):
    def __init__(
        self, code: str, message: str, *, retryable: bool = False, retry_after: int | None = None
    ) -> None:
        super().__init__(message)
        self.code, self.message = code, message
        self.retryable, self.retry_after = retryable, retry_after
