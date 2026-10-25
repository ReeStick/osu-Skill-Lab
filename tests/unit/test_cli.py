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
