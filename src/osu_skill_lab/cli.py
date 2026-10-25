"""Offline commands; importing this module does not configure or connect to a database."""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from osu_skill_lab.analysis.models import ParserLimits
from osu_skill_lab.analysis.parser import BeatmapParseError, parse_osu
from osu_skill_lab.analysis.summary import summarize_beatmap
from osu_skill_lab.infrastructure.osz import ArchiveError, extract_osz


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="osu-skill-lab")
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract-osz", help="Extract only .osu files from local .osz")
    extract.add_argument("source", type=Path, help="One archive or a directory (non-recursive)")
    extract.add_argument("--output-dir", type=Path, default=Path("data/unpacked_osu_maps"))
    inspect = commands.add_parser("inspect-osu", help="Summarize analytical fields of .osu v14")
    inspect.add_argument("source", type=Path, help="One .osu file or a directory")
    inspect.add_argument("--recursive", action="store_true", help="Search nested directories")
    args = parser.parse_args(argv)
    source = Path(args.source)
    if args.command == "inspect-osu":
        return _inspect_osu(source, recursive=args.recursive)
    return _extract_osz(source, Path(args.output_dir))


def _extract_osz(source: Path, output_dir: Path) -> int:
    try:
        sources = (
            sorted(
                (
                    path
                    for path in source.iterdir()
                    if path.is_file() and path.suffix.lower() == ".osz"
                ),
                key=lambda path: path.name.casefold(),
            )
            if source.is_dir()
            else [source]
        )
    except OSError:
        print("Cannot read source directory", file=sys.stderr)
        return 1
    if not sources:
        print("Source directory contains no .osz archives", file=sys.stderr)
        return 1
    failed = False
    for path in sources:
        try:
            result = extract_osz(path, output_dir)
        except (ArchiveError, OSError) as exc:
            print(json.dumps({"archive": path.name, "error": str(exc)}), file=sys.stderr)
            failed = True
            continue
        print(
            json.dumps(
                {
                    "archive": path.name,
                    "archive_sha256": result.archive_sha256,
                    "maps": len(result.beatmaps),
                    "output": str(result.directory),
                    "reused": result.reused,
                }
            )
        )
    return int(failed)


def _inspect_osu(source: Path, *, recursive: bool) -> int:
    try:
        if source.is_dir():
            candidates = source.rglob("*") if recursive else source.iterdir()
            paths = sorted(
                (
                    path
                    for path in candidates
                    if path.is_file() and path.suffix.casefold() == ".osu"
                ),
                key=lambda path: str(path).casefold(),
            )
        else:
            paths = [source]
    except OSError:
        print("Cannot read source directory", file=sys.stderr)
        return 1
    if not paths:
        print("Source directory contains no .osu files", file=sys.stderr)
        return 1
    failed = False
    limits = ParserLimits()
    for path in paths:
        try:
            if path.suffix.casefold() != ".osu":
                raise BeatmapParseError("invalid_extension", "Expected an .osu file")
            with path.open("rb") as file:
                data = file.read(limits.max_file_bytes + 1)
            summary = summarize_beatmap(parse_osu(data, limits=limits))
            print(json.dumps({"file": str(path), **asdict(summary)}, allow_nan=False))
        except BeatmapParseError as exc:
            print(
                json.dumps(
                    {
                        "file": str(path),
                        "error": {
                            "code": exc.code,
                            "message": exc.message,
                            "section": exc.section,
                            "line_number": exc.line_number,
                        },
                    }
                ),
                file=sys.stderr,
            )
            failed = True
        except OSError as exc:
            print(json.dumps({"file": str(path), "error": str(exc)}), file=sys.stderr)
            failed = True
    return int(failed)


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
