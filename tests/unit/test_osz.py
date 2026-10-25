import hashlib
import json
import stat
import warnings
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest

from osu_skill_lab.infrastructure.osz import (
    ArchiveError,
    ArchiveLimits,
    _copy_member,
    extract_osz,
)

BEATMAP = b"osu file format v14\r\n\r\n[General]\r\nMode: 0\r\n"


def make_archive(
    path: Path,
    members: list[tuple[str | ZipInfo, bytes]],
    compression: int = ZIP_DEFLATED,
) -> Path:
    with ZipFile(path, "w", compression=compression) as archive, warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:", category=UserWarning)
        for name, data in members:
            archive.writestr(name, data)
    return path


def test_extracts_exact_map_bytes_and_records_provenance(tmp_path: Path) -> None:
    source = make_archive(
        tmp_path / "input.osz",
        [
            ("nested/map.OSU", BEATMAP),
            ("audio.mp3", b"not real audio"),
            ("background.jpg", b"not a real image"),
            ("nested/", b""),
        ],
    )
    source_before = source.read_bytes()
    output = tmp_path / "output"
    result = extract_osz(source, output)
    assert not result.reused
    assert result.archive_sha256 == hashlib.sha256(source_before).hexdigest()
    assert result.archive_size_bytes == len(source_before)
    assert result.directory == output / result.archive_sha256
    assert source.read_bytes() == source_before
    assert result.skipped_entries == 3
    (beatmap,) = result.beatmaps
    assert beatmap.member_name == "nested/map.OSU"
    assert (result.directory / beatmap.filename).read_bytes() == BEATMAP
    assert beatmap.sha256 == hashlib.sha256(BEATMAP).hexdigest()
    assert beatmap.size_bytes == len(BEATMAP)
    assert {path.suffix for path in result.directory.iterdir()} == {".osu", ".json"}
    manifest = json.loads((result.directory / "manifest.json").read_bytes())
    assert manifest["source_kind"] == "local_osz"
    assert manifest["archive_sha256"] == result.archive_sha256
    assert manifest["beatmaps"][0]["member_name"] == "nested/map.OSU"


def test_repeat_and_renamed_archive_reuse_identical_output(tmp_path: Path) -> None:
    source = make_archive(tmp_path / "first.osz", [("map.osu", BEATMAP)])
    first = extract_osz(source, tmp_path / "output")
    manifest = first.directory / "manifest.json"
    before = manifest.read_bytes(), manifest.stat().st_mtime_ns
    renamed = tmp_path / "renamed.osz"
    source.rename(renamed)
    second = extract_osz(renamed, tmp_path / "output")
    assert second.reused
    assert first.directory == second.directory
    assert (manifest.read_bytes(), manifest.stat().st_mtime_ns) == before


@pytest.mark.parametrize("damage", ["map", "manifest", "extra", "missing"])
def test_existing_corrupt_output_is_not_overwritten(tmp_path: Path, damage: str) -> None:
    source = make_archive(tmp_path / "input.osz", [("map.osu", BEATMAP)])
    first = extract_osz(source, tmp_path / "output")
    if damage == "map":
        (first.directory / first.beatmaps[0].filename).write_bytes(b"x" * len(BEATMAP))
    elif damage == "manifest":
        (first.directory / "manifest.json").write_text("{}", encoding="utf-8")
    elif damage == "extra":
        (first.directory / "unexpected.txt").write_text("keep me", encoding="utf-8")
    else:
        (first.directory / first.beatmaps[0].filename).unlink()
    before = {path.name: path.read_bytes() for path in first.directory.iterdir()}
    with pytest.raises(ArchiveError, match="refusing to overwrite"):
        extract_osz(source, tmp_path / "output")
    assert {path.name: path.read_bytes() for path in first.directory.iterdir()} == before
    assert list((tmp_path / "output").iterdir()) == [first.directory]


@pytest.mark.parametrize(
    "name",
    [
        "../escape.osu",
        "/absolute.osu",
        "folder/../../escape.osu",
        "folder\\..\\escape.osu",
        "C:\\escape.osu",
        "C:escape.osu",
        "\\\\server\\share\\escape.osu",
        "map:stream.osu",
        "./map.osu",
        "nested//map.osu",
    ],
)
def test_rejects_unsafe_map_paths(tmp_path: Path, name: str) -> None:
    source = make_archive(tmp_path / "input.osz", [(name, BEATMAP)])
    output = tmp_path / "output"
    with pytest.raises(ArchiveError, match="Unsafe"):
        extract_osz(source, output)
    assert list(output.iterdir()) == []
    assert not (tmp_path / "escape.osu").exists()


@pytest.mark.parametrize("names", [["map.osu", "map.osu"], ["map.osu", "MAP.OSU"]])
def test_rejects_duplicate_map_names(tmp_path: Path, names: list[str]) -> None:
    source = make_archive(tmp_path / "input.osz", [(name, BEATMAP) for name in names])
    with pytest.raises(ArchiveError, match="Duplicate"):
        extract_osz(source, tmp_path / "output")


def test_rejects_symlink_members(tmp_path: Path) -> None:
    symlink = ZipInfo("link.osu")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    source = make_archive(tmp_path / "input.osz", [(symlink, b"../outside.osu")])
    with pytest.raises(ArchiveError, match="regular file"):
        extract_osz(source, tmp_path / "output")


@pytest.mark.parametrize(
    ("limit", "value"),
    [
        ("max_archive_bytes", 10),
        ("max_entries", 1),
        ("max_beatmaps", 1),
        ("max_beatmap_bytes", 10),
        ("max_total_beatmap_bytes", len(BEATMAP)),
    ],
)
def test_rejects_excessive_archives(tmp_path: Path, limit: str, value: int) -> None:
    source = make_archive(tmp_path / "input.osz", [("a.osu", BEATMAP), ("b.osu", BEATMAP)])
    limits = replace(ArchiveLimits(), **{limit: value})
    output = tmp_path / "output"
    with pytest.raises(ArchiveError, match=limit):
        extract_osz(source, output, limits=limits)
    assert list(output.iterdir()) == []


def test_accepts_exact_byte_limits(tmp_path: Path) -> None:
    source = make_archive(tmp_path / "input.osz", [("map.osu", BEATMAP)])
    limits = ArchiveLimits(
        max_archive_bytes=source.stat().st_size,
        max_entries=1,
        max_beatmaps=1,
        max_beatmap_bytes=len(BEATMAP),
        max_total_beatmap_bytes=len(BEATMAP),
    )
    assert len(extract_osz(source, tmp_path / "output", limits=limits).beatmaps) == 1


def test_stream_budget_stops_actual_decoded_bytes(tmp_path: Path) -> None:
    # The streaming guard must also work independently of central directory claims.
    with pytest.raises(ArchiveError, match="Decoded beatmap"):
        _copy_member(BytesIO(b"x" * 1000), tmp_path / "map.osu", 10)
    assert (tmp_path / "map.osu").stat().st_size <= 10


def test_corrupt_second_member_leaves_no_partial_result(tmp_path: Path) -> None:
    damaged_payload = b"unique second beatmap payload"
    source = make_archive(
        tmp_path / "input.osz", [("a.osu", BEATMAP), ("b.osu", damaged_payload)], ZIP_STORED
    )
    source.write_bytes(source.read_bytes().replace(damaged_payload, b"x" * len(damaged_payload)))
    output = tmp_path / "output"
    with pytest.raises(ArchiveError, match="unreadable ZIP"):
        extract_osz(source, output)
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("content", [None, b"not a ZIP"])
def test_rejects_archives_without_maps_or_bad_zip(tmp_path: Path, content: bytes | None) -> None:
    source = make_archive(tmp_path / "input.osz", [("audio.mp3", b"unused")])
    if content is not None:
        source.write_bytes(content)
    with pytest.raises(ArchiveError):
        extract_osz(source, tmp_path / "output")


def test_rejects_unsupported_compression(tmp_path: Path) -> None:
    source = make_archive(tmp_path / "input.osz", [("map.osu", BEATMAP)], ZIP_BZIP2)
    with pytest.raises(ArchiveError, match="compression"):
        extract_osz(source, tmp_path / "output")


def test_rejects_encrypted_member_before_decompression(tmp_path: Path) -> None:
    source = make_archive(tmp_path / "input.osz", [("map.osu", BEATMAP)])
    content = bytearray(source.read_bytes())
    assert content[:4] == b"PK\x03\x04"
    central_directory = content.index(b"PK\x01\x02")
    # Set the encryption flag in both ZIP headers, without adding a password.
    content[6] |= 1
    content[central_directory + 8] |= 1
    source.write_bytes(content)
    with pytest.raises(ArchiveError, match="Encrypted"):
        extract_osz(source, tmp_path / "output")


def test_ignores_unused_assets_without_decoding_them(tmp_path: Path) -> None:
    asset = b"unique unused asset"
    source = make_archive(
        tmp_path / "input.osz", [("map.osu", BEATMAP), ("../audio.mp3", asset)], ZIP_STORED
    )
    source.write_bytes(source.read_bytes().replace(asset, b"x" * len(asset)))
    result = extract_osz(source, tmp_path / "output")
    assert len(result.beatmaps) == 1
    assert result.skipped_entries == 1
    assert not (tmp_path / "audio.mp3").exists()


def test_invalid_limits_and_source_extension(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        ArchiveLimits(max_entries=0)
    with pytest.raises(ArchiveError, match="extension"):
        extract_osz(tmp_path / "file.zip", tmp_path / "output")
