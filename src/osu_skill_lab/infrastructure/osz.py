"""Extract only beatmap bytes from local .osz files, without trusting ZIP paths."""

import hashlib
import json
import stat
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
from typing import IO
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo
from zlib import error as ZlibError

CHUNK_SIZE = 64 * 1024
EXTRACTOR_VERSION = "1"


class ArchiveError(ValueError):
    """Invalid, unsupported or excessive archive; no published output was written."""


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 128 * 1024 * 1024
    max_entries: int = 10_000
    max_beatmaps: int = 256
    max_beatmap_bytes: int = 4 * 1024 * 1024
    max_total_beatmap_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        if any(value <= 0 for value in asdict(self).values()):
            raise ValueError("All archive limits must be positive")


@dataclass(frozen=True)
class ExtractedBeatmap:
    member_name: str
    filename: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ExtractionResult:
    archive_sha256: str
    archive_size_bytes: int
    directory: Path
    beatmaps: tuple[ExtractedBeatmap, ...]
    skipped_entries: int
    reused: bool


def _snapshot(source: Path, target: Path, limit: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    # A snapshot makes the checksum describe the exact bytes subsequently decoded.
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        while chunk := incoming.read(min(CHUNK_SIZE, limit - size + 1)):
            size += len(chunk)
            if size > limit:
                raise ArchiveError("Archive exceeds max_archive_bytes")
            digest.update(chunk)
            outgoing.write(chunk)
    return digest.hexdigest(), size


def _select_members(archive: ZipFile, limits: ArchiveLimits) -> list[ZipInfo]:
    entries = archive.infolist()
    if len(entries) > limits.max_entries:
        raise ArchiveError("Archive exceeds max_entries")
    selected: list[ZipInfo] = []
    names: set[str] = set()
    total_size = 0
    for member in entries:
        if member.is_dir() or not member.filename.casefold().endswith(".osu"):
            continue
        name = member.orig_filename
        normalized = name.replace("\\", "/")
        if (
            "\x00" in name
            or normalized.startswith("/")
            or PureWindowsPath(name).drive
            or any(part in {"", ".", ".."} for part in normalized.split("/"))
            or ":" in normalized
        ):
            raise ArchiveError("Unsafe beatmap member path")
        if normalized.casefold() in names:
            raise ArchiveError("Duplicate beatmap member path")
        names.add(normalized.casefold())
        file_type = stat.S_IFMT(member.external_attr >> 16)
        if file_type not in {0, stat.S_IFREG}:
            raise ArchiveError("Beatmap member must be a regular file")
        if member.flag_bits & 1:
            raise ArchiveError("Encrypted beatmap members are not supported")
        if member.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
            raise ArchiveError("Unsupported beatmap compression method")
        if member.file_size > limits.max_beatmap_bytes:
            raise ArchiveError("Beatmap exceeds max_beatmap_bytes")
        total_size += member.file_size
        if total_size > limits.max_total_beatmap_bytes:
            raise ArchiveError("Beatmaps exceed max_total_beatmap_bytes")
        selected.append(member)
        if len(selected) > limits.max_beatmaps:
            raise ArchiveError("Archive exceeds max_beatmaps")
    if not selected:
        raise ArchiveError("Archive contains no .osu files")
    return sorted(selected, key=lambda member: member.filename.casefold())


def _copy_member(source: IO[bytes], target: Path, limit: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with target.open("xb") as outgoing:
        while chunk := source.read(min(CHUNK_SIZE, limit - size + 1)):
            size += len(chunk)
            if size > limit:
                raise ArchiveError("Decoded beatmap exceeds extraction byte limit")
            digest.update(chunk)
            outgoing.write(chunk)
    return digest.hexdigest(), size


def _verify_existing(
    directory: Path, manifest: bytes, beatmaps: tuple[ExtractedBeatmap, ...]
) -> None:
    def regular_file(path: Path, expected_size: int) -> bool:
        return (
            not path.is_symlink()
            and not path.is_junction()
            and path.is_file()
            and path.stat().st_size == expected_size
        )

    def mismatch() -> ArchiveError:
        return ArchiveError("Existing extraction differs; refusing to overwrite it")

    if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
        raise mismatch()
    if {path.name for path in directory.iterdir()} != {
        "manifest.json",
        *(beatmap.filename for beatmap in beatmaps),
    }:
        raise mismatch()
    manifest_path = directory / "manifest.json"
    if not regular_file(manifest_path, len(manifest)):
        raise mismatch()
    with manifest_path.open("rb") as file:
        if file.read(len(manifest) + 1) != manifest:
            raise mismatch()
    for beatmap in beatmaps:
        path = directory / beatmap.filename
        if not regular_file(path, beatmap.size_bytes):
            raise mismatch()
        with path.open("rb") as file:
            content = file.read(beatmap.size_bytes + 1)
        if (
            len(content) != beatmap.size_bytes
            or hashlib.sha256(content).hexdigest() != beatmap.sha256
        ):
            raise mismatch()


def extract_osz(
    source: Path, output_root: Path, *, limits: ArchiveLimits | None = None
) -> ExtractionResult:
    """Publish a complete, content-addressed extraction or leave existing results alone.

    output_root is an operator-controlled directory. ZIP paths are metadata only.
    This does not parse .osu syntax or verify unused assets inside the archive.
    """
    limits = limits if limits is not None else ArchiveLimits()
    if source.suffix.casefold() != ".osz":
        raise ArchiveError("Source must have an .osz extension")
    output_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".extract-", dir=output_root) as temporary:
        staging = Path(temporary)
        snapshot = staging / "source.osz"
        archive_hash, archive_size = _snapshot(source, snapshot, limits.max_archive_bytes)
        result_dir = staging / "result"
        result_dir.mkdir()
        extracted: list[ExtractedBeatmap] = []
        total_size = 0
        try:
            with ZipFile(snapshot) as archive:
                members = _select_members(archive, limits)
                skipped = len(archive.infolist()) - len(members)
                for index, member in enumerate(members):
                    temporary_map = result_dir / f"{index:04d}.osu"
                    byte_limit = min(
                        limits.max_beatmap_bytes, limits.max_total_beatmap_bytes - total_size
                    )
                    with archive.open(member) as incoming:
                        digest, size = _copy_member(incoming, temporary_map, byte_limit)
                    if size != member.file_size:
                        raise ArchiveError("Decoded beatmap size does not match ZIP metadata")
                    total_size += size
                    filename = f"{index:04d}-{digest}.osu"
                    temporary_map.rename(result_dir / filename)
                    extracted.append(ExtractedBeatmap(member.filename, filename, digest, size))
        except (
            BadZipFile,
            NotImplementedError,
            RuntimeError,
            EOFError,
            UnicodeError,
            ZlibError,
        ) as exc:
            raise ArchiveError("Invalid or unreadable ZIP data") from exc

        beatmaps = tuple(extracted)
        manifest = (
            json.dumps(
                {
                    "manifest_version": 1,
                    "extractor_version": EXTRACTOR_VERSION,
                    "source_kind": "local_osz",
                    "archive_sha256": archive_hash,
                    "archive_size_bytes": archive_size,
                    "limits": asdict(limits),
                    "beatmaps": [asdict(beatmap) for beatmap in beatmaps],
                    "skipped_entries": skipped,
                },
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        (result_dir / "manifest.json").write_bytes(manifest)
        destination = output_root / archive_hash
        reused = False
        if destination.exists() or destination.is_symlink() or destination.is_junction():
            _verify_existing(destination, manifest, beatmaps)
            reused = True
        else:
            try:
                result_dir.rename(destination)
            except OSError:
                # Another invocation may have published the same complete directory.
                if not destination.exists():
                    raise
                _verify_existing(destination, manifest, beatmaps)
                reused = True
        return ExtractionResult(archive_hash, archive_size, destination, beatmaps, skipped, reused)
