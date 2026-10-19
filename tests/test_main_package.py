import json
import subprocess
import sys

from aamas_review_monitor import __main__ as cli
from aamas_review_monitor import __version__
from tests.test_checks import CONFIG, paper


def test_version_comes_from_package_metadata():
    assert __version__.count(".") == 2


def test_report_compares_latest_two_snapshots(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "DIR_DATA", tmp_path)
    monkeypatch.setattr(cli, "DIR_SNAPSHOTS", tmp_path / "s")
    (tmp_path / "s").mkdir()
    (tmp_path / "config.json").write_text(json.dumps(CONFIG))
    old = {"taken_at": "2026-11-10T08:00:00", "papers": [paper(1, spcs=[]), paper(2, reviews=0)]}
    new = {"taken_at": "2026-11-11T08:00:00", "papers": [paper(1), paper(2, reviews=0)]}
    (tmp_path / "s" / "2026-11-10T080000.json").write_text(json.dumps(old))
    (tmp_path / "s" / "2026-11-11T080000.json").write_text(json.dumps(new))
    cli.main(["report", "--csv", str(tmp_path / "issues.csv")])
    out = capsys.readouterr().out
    assert out.startswith("2 papers: 1 RED, 0 YELLOW, 1 GREEN")
    assert "0 new issues, 1 resolved" in out
    assert "~SPC_One1: 1 open (1 RED), 0 resolved since" in out
    assert (tmp_path / "issues.csv").read_text().count("\n") == 2


def test_run_as_module_without_command_fails():
    out = subprocess.run([sys.executable, "-m", "aamas_review_monitor"], capture_output=True)
    assert out.returncode == 2
