import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from osu_skill_lab.cli import main


def test_batch_extracts_valid_archive_and_reports_bad_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "input"
    source.mkdir()
    with ZipFile(source / "good.osz", "w") as archive:
        archive.writestr("map.osu", b"osu file format v14\n")
    (source / "bad.osz").write_bytes(b"invalid ZIP")
    (source / "ignore.txt").write_text("ignored", encoding="utf-8")
    output = tmp_path / "output"
    assert main(["extract-osz", str(source), "--output-dir", str(output)]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["maps"] == 1
    assert json.loads(captured.err)["archive"] == "bad.osz"
    assert len(list(output.glob("*/manifest.json"))) == 1
    (source / "bad.osz").unlink()
    assert main(["extract-osz", str(source), "--output-dir", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["reused"] is True


def test_missing_source_and_empty_directory_return_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = str(tmp_path / "output")
    assert main(["extract-osz", str(tmp_path / "missing.osz"), "--output-dir", output]) == 1
    assert json.loads(capsys.readouterr().err)["archive"] == "missing.osz"
    assert main(["extract-osz", str(tmp_path), "--output-dir", output]) == 1
    assert "contains no .osz" in capsys.readouterr().err


def test_inspect_reports_analytical_summary_without_media(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "analytic-v14.osu"
    assert main(["inspect-osu", str(fixture)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["hit_objects"] == 4
    assert report["difficulty"]["approach_rate"] == 9
    assert report["bpm_min"] == 120
    assert report["bpm_max"] == 150
    assert "AudioFilename" not in report


def test_inspect_recursive_batch_reports_parse_errors_and_continues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "analytic-v14.osu"
    (nested / "good.OSU").write_bytes(fixture.read_bytes())
    broken = tmp_path / "bad.osu"
    broken.write_bytes(b"invalid header")
    assert main(["inspect-osu", str(tmp_path)]) == 1
    first = capsys.readouterr()
    assert first.out == ""
    error = json.loads(first.err)["error"]
    assert error["code"] == "invalid_header"
    assert error["line_number"] == 1
    assert main(["inspect-osu", str(tmp_path), "--recursive"]) == 1
    mixed = capsys.readouterr()
    assert json.loads(mixed.out)["hit_objects"] == 4
    assert json.loads(mixed.err)["error"]["code"] == "invalid_header"
    broken.unlink()
    assert main(["inspect-osu", str(tmp_path), "--recursive"]) == 0


def test_inspect_rejects_missing_files_and_empty_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["inspect-osu", str(tmp_path / "missing.osu")]) == 1
    assert json.loads(capsys.readouterr().err)["error"]
    assert main(["inspect-osu", str(tmp_path)]) == 1
    assert "contains no .osu" in capsys.readouterr().err
