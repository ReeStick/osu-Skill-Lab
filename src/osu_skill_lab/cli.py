"""Offline commands; importing this module does not configure or connect to a database."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from osu_skill_lab.infrastructure.osz import ArchiveError, extract_osz


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="osu-skill-lab")
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract-osz", help="Extract only .osu files from local .osz")
    extract.add_argument("source", type=Path, help="One archive or a directory (non-recursive)")
    extract.add_argument("--output-dir", type=Path, default=Path("data/unpacked_osu_maps"))
    args = parser.parse_args(argv)
    source = Path(args.source)
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
            result = extract_osz(path, Path(args.output_dir))
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


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
