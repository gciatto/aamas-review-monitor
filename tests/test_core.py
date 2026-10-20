"""The services shared by the CLI and the TUI, tested without either front end."""

from pathlib import Path

from aamas_review_monitor import core, documents, papers
from aamas_review_monitor.collector import fetch
from tests.test_collector import FakeClient
from tests.test_papers import CONFIG


def cached(*numbers: int) -> list[dict]:
    """Caches #7 (plus copies of it as the other `numbers`) and returns the records."""
    (record,) = fetch(FakeClient(), CONFIG)
    records = [record] + [record | {"number": n} for n in numbers]
    papers.save(records, core.DIR_PAPERS, [])
    return records


def test_download_each_survives_a_failure_and_papers_without_the_file():
    class Flaky(FakeClient):
        def get_attachment(self, field_name, id):
            if self.downloads:  # the first download works, the next ones fail
                raise ConnectionError("rate limited")
            return super().get_attachment(field_name, id)

    first, second = cached(8)
    results = list(core.download_each(Flaky(), [first, second], "pdf"))
    assert [(r["number"], str(e) if e else None) for r, _, e in results] == [
        (7, None),
        (8, "rate limited"),
    ]
    assert results[0][1] == core.DIR_PAPERS / "7" / "pdf_v1.pdf"
    assert list(core.download_each(FakeClient(), [first], "supplementary_material")) == [
        (first, None, None)
    ]


def test_inspect_each_downloads_only_what_is_missing_and_survives_a_missing_tool(monkeypatch):
    def pdf_pages(pdf: Path) -> list[str]:
        if "8" in pdf.parts:
            raise FileNotFoundError("pdftotext not found")
        return ["A Paper\nAnonymous Author(s)"]

    monkeypatch.setattr(documents.papers, "pdf_pages", pdf_pages)
    monkeypatch.setattr(documents, "pdfinfo", lambda pdf: {"Page size": "612 x 792 pts"})
    monkeypatch.setattr(documents, "pdffonts", lambda pdf: [])
    client = FakeClient()
    records = cached(8)
    results = list(core.inspect_each(records, CONFIG, lambda: client))
    assert [(r["number"], str(e) if e else None) for r, _, e in results] == [
        (7, None),
        (8, "pdftotext not found"),
    ]
    assert "template" in {code for code, _ in results[0][1]}
    assert len(client.downloads) == 2  # both PDFs were missing
    list(core.inspect_each(records[:1], CONFIG, lambda: client))
    assert len(client.downloads) == 2  # cached result, current PDF: nothing fetched again


def test_nothing_synced_yet_means_no_state_and_no_records():
    assert core.current(CONFIG) == core.State(None, None, [], [], set(), set())
    assert core.records() == []  # nothing cached yet


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


def test_retry_policy_covers_the_edit_endpoints_too():
    from types import SimpleNamespace

    import requests

    url = "https://api2.openreview.net/notes/edits"
    client = SimpleNamespace(session=requests.Session(), note_edits_url=url)
    core.tune(client, core.load_config())
    assert "POST" not in client.session.get_adapter(url).max_retries.allowed_methods


def test_freshness_warns_on_old_snapshots():
    from datetime import datetime, timezone

    now, config = datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc), {"snapshot_stale_hours": 12}
    fresh = core.freshness({"taken_at": "2026-11-11T19:30:00+00:00"}, config, now)
    assert fresh.startswith("Snapshot of ") and fresh.endswith(", 30 min old")
    old = core.freshness({"taken_at": "2026-11-11T06:00:00"}, config, now)  # naive: UTC
    assert old.startswith("⚠ ") and old.endswith("14 h old: older than 12 h, sync first?")
    assert core.freshness(None, config) == "⚠ No snapshot: sync first"


def test_config_overrides_are_validated():
    import pytest

    local = core.DIR_DATA / "config.json"
    for override, error in [
        ('{"reviews_word_min": 200}', "reviews_word_min is not a setting"),
        ('{"reviewers_min": "3"}', "reviewers_min should be like 3, not '3'"),
        ('{"reviewers_min": true}', "reviewers_min should be like 3, not True"),
        ('{"deadline_reviews": "13/11/2026"}', "'13/11/2026' is not a YYYY-MM-DD date"),
    ]:
        local.write_text(override)
        with pytest.raises(ValueError, match=error):
            core.load_config()
    local.write_text('{"deadline_reviews": "2026-11-14", "backoff_seconds": 0.5}')  # was an int
    assert core.load_config()["deadline_reviews"] == "2026-11-14"


def test_requests_are_spaced_by_the_rate_cap_and_the_wait_is_interruptible(monkeypatch):
    import time

    import pytest
    from requests.adapters import HTTPAdapter

    sent: list[float] = []
    monkeypatch.setattr(
        HTTPAdapter, "send", lambda self, request, **kw: sent.append(time.monotonic())
    )
    adapter = core.ThrottledAdapter(20)  # one request every 50 ms
    for _ in range(4):
        adapter.send(None)
    assert sent[-1] - sent[0] >= 0.14  # 3 intervals, with some slack for the clock
    unlimited = core.ThrottledAdapter(0)
    start = time.monotonic()
    for _ in range(50):
        unlimited.send(None)
    assert time.monotonic() - start < 0.1
    slow = core.ThrottledAdapter(0.1)  # one request every 10 s
    slow.send(None)
    core.INTERRUPT.set()
    try:
        with pytest.raises(core.Interrupted):
            slow.send(None)
    finally:
        core.INTERRUPT.clear()


def test_ignored_issues_persist_and_can_be_counted_again():
    assert core.ignored() == set()
    core.ignore({(7, "disagreement"), (7, "short_review:~R1")})
    assert core.ignore({(7, "disagreement")}, undo=True) == {(7, "short_review:~R1")}
    assert core.ignored() == {(7, "short_review:~R1")}  # kept in the private data folder
    assert oct(core.FILE_IGNORED.stat().st_mode & 0o777) == "0o600" or core.os.name == "nt"
