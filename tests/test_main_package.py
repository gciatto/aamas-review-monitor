import json
from pathlib import Path
import subprocess
import sys

from aamas_review_monitor import __main__ as cli
from aamas_review_monitor import core
from aamas_review_monitor import __version__
from tests.test_checks import CONFIG, paper


def test_version_comes_from_package_metadata():
    assert __version__.count(".") == 2


def test_report_compares_latest_two_snapshots(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(core, "DIR_DATA", tmp_path)
    monkeypatch.setattr(core, "DIR_SNAPSHOTS", tmp_path / "s")
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


def test_legend_lists_every_check(capsys):
    from aamas_review_monitor.checks import CHECKS
    from aamas_review_monitor.documents import DOCUMENT_CHECKS

    cli.main(["legend"])
    out = capsys.readouterr().out
    assert all(f"({f.__name__})" in out for f in CHECKS + DOCUMENT_CHECKS)
    assert "{" not in out.replace("{'", "")  # every placeholder filled, labels have none


def test_inspect_prints_document_issues_and_show_includes_them(tmp_path, monkeypatch, capsys):
    from aamas_review_monitor import documents, papers
    from aamas_review_monitor.collector import fetch, snapshot
    from tests.test_collector import FakeClient

    config = core.load_config()
    monkeypatch.setattr(core, "DIR_PAPERS", tmp_path / "papers")
    monkeypatch.setattr(core, "DIR_SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(core, "login", lambda config: FakeClient())
    records = fetch(FakeClient(), config)
    papers.save(records, core.DIR_PAPERS, [])
    core.DIR_SNAPSHOTS.mkdir()
    (core.DIR_SNAPSHOTS / "a.json").write_text(json.dumps(snapshot(records, config)))
    monkeypatch.setattr(documents.papers, "pdf_text", lambda pdf: "A Paper\nAnonymous Author(s)\f")
    monkeypatch.setattr(documents, "pdfinfo", lambda pdf: {"Page size": "595 x 842 pts"})
    monkeypatch.setattr(documents, "pdffonts", lambda pdf: [])
    cli.main(["show", "7"])
    assert "Document checks not run: `inspect 7`" in capsys.readouterr().out
    cli.main(["inspect", "7"])
    out = capsys.readouterr().out
    assert out.startswith("#7: 2 document issues") and "RED    page size 595 x 842 pt" in out
    cli.main(["issues", "7"])
    out = capsys.readouterr().out
    assert (
        "RED    no AAMAS 2027 copyright block" in out and "GREEN  Anonymous submission mode" in out
    )


def test_retry_policy_comes_from_config_and_command_line(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    import requests

    from aamas_review_monitor import papers
    from aamas_review_monitor.collector import fetch
    from tests.test_collector import FakeClient

    client = core.tune(SimpleNamespace(session=requests.Session()), core.load_config())
    retry = client.session.get_adapter("https://api2.openreview.net").max_retries
    assert (retry.total, retry.connect, retry.backoff_factor, retry.backoff_max) == (8, 8, 1, 120)
    assert 429 in retry.status_forcelist and "POST" not in retry.allowed_methods

    class Flaky(FakeClient):
        def get_attachment(self, field_name, id):
            raise ConnectionError("still down after the retries")

    seen: list[dict] = []
    monkeypatch.setattr(core, "login", lambda config: seen.append(config) or Flaky())
    monkeypatch.setattr(core, "DIR_PAPERS", tmp_path)
    papers.save(fetch(FakeClient(), core.load_config()), tmp_path, [])
    cli.main(["--retries", "2", "--backoff", "0.5", "download", "7"])
    assert (seen[0]["retries"], seen[0]["backoff_seconds"], seen[0]["backoff_max_seconds"]) == (
        2,
        0.5,
        120,
    )
    assert capsys.readouterr().out == "[1/1] #7: failed (still down after the retries)\n"


def cached_cli(tmp_path, monkeypatch):
    """The CLI over one cached synthetic paper (#7), with a fake client."""
    from aamas_review_monitor import papers
    from aamas_review_monitor.collector import fetch, snapshot
    from tests.test_collector import FakeClient

    config, client = core.load_config(), FakeClient()
    monkeypatch.setattr(core, "DIR_PAPERS", tmp_path / "papers")
    monkeypatch.setattr(core, "DIR_SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(core, "login", lambda config: client)
    records = fetch(client, config)
    papers.save(records, core.DIR_PAPERS, [])
    core.DIR_SNAPSHOTS.mkdir()
    snap = snapshot(records, config) | {"taken_at": "2026-10-19T08:00:00"}
    (core.DIR_SNAPSHOTS / "a.json").write_text(json.dumps(snap))
    return client


def test_report_filters_and_lists_green_papers(tmp_path, monkeypatch, capsys):
    cached_cli(tmp_path, monkeypatch)
    cli.main(["report", "--filter", "ratings"])
    out = capsys.readouterr().out
    assert "ratings [3, 6]" in out and "review of 1 words" not in out
    cli.main(
        ["report", "--filter", "nothing like this", "--green", "--csv", str(tmp_path / "x.csv")]
    )
    assert "#7" not in capsys.readouterr().out
    assert (tmp_path / "x.csv").read_text().count("\n") == 1  # header only


def test_browse_and_attachment(tmp_path, monkeypatch, capsys):
    import zipfile

    from aamas_review_monitor import papers

    client = cached_cli(tmp_path, monkeypatch)
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    cli.main(["browse", "7"])
    assert opened == ["https://openreview.net/forum?id=abc"]

    launched: list[list[str]] = []
    monkeypatch.setattr(papers.subprocess, "Popen", lambda command, **kw: launched.append(command))
    monkeypatch.setattr(papers, "pdf_text", lambda pdf: "left column\nright column")
    cli.main(["attachment", "7", "--contents", "--open", "--reveal"])
    out = capsys.readouterr().out.splitlines()
    assert Path(out[0]).parts[-3:] == ("papers", "7", "pdf_v1.pdf")
    assert out[1:] == ["left column", "right column"]
    assert client.downloads == [("pdf", "abc")] and len(launched) == 2

    record = core.DIR_PAPERS / "7" / "record.json"
    data = json.loads(record.read_text())
    data["content"]["supplementary_material"] = {"value": "/attachment/s1.zip"}
    record.write_text(json.dumps(data))
    with zipfile.ZipFile(record.parent / "supplementary_material_s1.zip", "w") as archive:
        archive.writestr("code/main.py", "print()")
    cli.main(["attachment", "7", "--supplementary", "--contents"])
    assert capsys.readouterr().out.splitlines()[1] == "code/main.py  (7 bytes)"


def test_inspect_downloads_missing_pdf_and_supplementary(tmp_path, monkeypatch, capsys):
    import io
    import zipfile

    from aamas_review_monitor import documents

    client = cached_cli(tmp_path, monkeypatch)
    record = core.DIR_PAPERS / "7" / "record.json"
    data = json.loads(record.read_text())
    data["content"]["supplementary_material"] = {"value": "/attachment/s1.zip"}
    record.write_text(json.dumps(data))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("main.py", "print()")
    attachments = {"pdf": b"%PDF", "supplementary_material": buffer.getvalue()}
    monkeypatch.setattr(
        client,
        "get_attachment",
        lambda field, id: client.downloads.append(field) or attachments[field],
    )
    monkeypatch.setattr(documents.papers, "pdf_text", lambda pdf: "A Paper\nAnonymous Author(s)\f")
    monkeypatch.setattr(documents, "pdfinfo", lambda pdf: {})
    monkeypatch.setattr(documents, "pdffonts", lambda pdf: [])
    cli.main(["inspect"])  # every paper: downloads what is missing
    assert sorted(client.downloads) == ["pdf", "supplementary_material"]
    assert "#7: 1 document issues" in capsys.readouterr().out
    cli.main(["inspect", "7"])  # all cached now: nothing downloaded again
    assert len(client.downloads) == 2


def test_retries_are_logged_and_their_waits_interruptible(caplog):
    import time

    import pytest

    retry = core.LoggedRetry(total=3, backoff_factor=30, status_forcelist=[429])
    retry = retry.increment("GET", "/notes", error=ConnectionError("reset"))
    retry = retry.increment("GET", "/notes", error=ConnectionError("reset"))
    assert "ConnectionError on GET /notes: retry 2 of 3" in caplog.text
    core.INTERRUPT.set()
    try:
        start = time.monotonic()
        with pytest.raises(core.Interrupted):
            retry.sleep()  # would wait 60 s (30 s, doubled once) without the interruption
        assert time.monotonic() - start < 5
        assert "waiting 60 s before retrying" in caplog.text
    finally:
        core.INTERRUPT.clear()


def test_outreach_previews_then_sends_only_after_send(tmp_path, monkeypatch, capsys):
    client = cached_cli(tmp_path, monkeypatch)
    for answer, sent in [("no", 0), ("SEND", 1)]:
        monkeypatch.setattr("builtins.input", lambda prompt="", answer=answer: answer)
        cli.main(["outreach", "spc-digest"])
        out = capsys.readouterr().out
        assert out.startswith("1 messages\n") and "=== To ~Spc_One1, via #7 ===" in out
        assert "ratings [3, 6]" in out and "review of 1 words" in out
        assert len(client.messages) == sent
    cli.main(["outreach", "spc-digest", "--spc", "~Someone_Else1"])
    assert capsys.readouterr().out.startswith("0 messages")


def test_email_previews_then_sends_only_after_send(tmp_path, monkeypatch, capsys):
    client = cached_cli(tmp_path, monkeypatch)
    (tmp_path / "body.txt").write_text("Dear {{fullname}}")
    for answer, sent in [("no", 0), ("SEND", 1)]:
        monkeypatch.setattr("builtins.input", lambda prompt="", answer=answer: answer)
        cli.main(
            ["email", "late-reviewers", "--subject", "Hi", "--body", str(tmp_path / "body.txt")]
        )
        out = capsys.readouterr().out
        assert "=== To late-reviewers of #7 (2), via #7 ===\nSubject: Hi" in out
        assert len(client.messages) == sent
    assert out.rstrip().endswith("Sent 1 of 1")
    cli.main(["email", "spcs", "--subject", "Hi", "--body", str(tmp_path / "body.txt"), "7"])
    assert client.messages[-1][0][1] == [
        "ifaamas.org/AAMAS/2027/Conference/Submission7/Area_Chair_9jqi"
    ]


def test_comment_posts_issues_and_history_records_emails_and_comments(
    tmp_path, monkeypatch, capsys
):
    client = cached_cli(tmp_path, monkeypatch)
    monkeypatch.setattr(core, "FILE_HISTORY", tmp_path / "history.jsonl")
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")
    cli.main(["comment", "7"])
    out = capsys.readouterr().out
    assert out.startswith("1 comments, readable by PCs, SACs\n") and "- 🟡 ratings [3, 6]" in out
    assert client.comments == [] and out.rstrip().endswith("Nothing posted")

    monkeypatch.setattr("builtins.input", lambda prompt="": "SEND")
    cli.main(["comment", "7", "--spcs"])
    ((invitation, signatures, note),) = client.comments
    assert invitation == "ifaamas.org/AAMAS/2027/Conference/Submission7/-/Official_Comment"
    assert signatures == ["ifaamas.org/AAMAS/2027/Conference/Submission7/Senior_Area_Chairs"]
    assert note.forum == note.replyto == "abc"
    assert note.readers[-1].endswith("Submission7/Area_Chairs")  # --spcs
    assert "ratings [3, 6]" in note.content["comment"]["value"]
    cli.main(["outreach", "spc-digest"])
    capsys.readouterr()

    cli.main(["history", "7"])
    out = capsys.readouterr().out.splitlines()
    assert "email    via #7  sent    to ~Spc_One1" in out[0]  # newest first
    assert "(spc-digest)" in out[1]
    assert "comment  via #7  sent    to PCs, SACs and SPCs" in out[2]
    assert out[-1].startswith("2 entries in")
    cli.main(["history", "99"])
    assert capsys.readouterr().out.strip() == "Nothing sent from the app yet"


def test_retry_policy_covers_the_edit_endpoints_too():
    from types import SimpleNamespace

    import requests

    url = "https://api2.openreview.net/notes/edits"
    client = SimpleNamespace(session=requests.Session(), note_edits_url=url)
    core.tune(client, core.load_config())
    assert "POST" not in client.session.get_adapter(url).max_retries.allowed_methods
