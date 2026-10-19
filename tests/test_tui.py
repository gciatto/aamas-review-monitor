import asyncio
import json

from aamas_review_monitor import __main__ as cli
from aamas_review_monitor.tui import Monitor, Paper
from tests.test_checks import CONFIG, paper


def test_tui_lists_and_filters_issues(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DIR_SNAPSHOTS", tmp_path)
    monkeypatch.setattr(cli, "DIR_PAPERS", tmp_path / "papers")
    papers = [paper(1, spcs=[]), paper(2, words=9), paper(3)]
    snapshot = {"taken_at": "2026-11-11T08:00:00", "papers": papers}
    (tmp_path / "2026-11-11T080000.json").write_text(json.dumps(snapshot))
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)

    async def scenario():
        app = Monitor(CONFIG)
        async with app.run_test() as pilot:
            table = app.query_one("#issues")
            assert table.row_count == 5  # no SPC on #1, three short reviews on #2, #3 GREEN
            await pilot.press("g")
            assert table.row_count == 4
            await pilot.press("g", "slash", *"no spc", "enter")
            assert table.row_count == 1
            await pilot.press("o")
            assert opened == ["https://openreview.net/forum?id=p1"]
            await pilot.press("enter")
            assert isinstance(app.screen, Paper)
            text = app.screen.text.plain
            assert "Not cached" in text and "RED    no SPC assigned" in text
            assert "GREEN  enough reviewers assigned" in text
            await pilot.press("escape")
            assert not isinstance(app.screen, Paper)

    asyncio.run(scenario())


def cached_monitor(tmp_path, monkeypatch, answer="SEND"):
    """A Monitor over one cached synthetic paper, with a fake client and no real terminal."""
    from aamas_review_monitor import papers
    from aamas_review_monitor.collector import fetch, snapshot
    from tests.test_collector import FakeClient
    from tests.test_papers import CONFIG as PAPERS

    config = CONFIG | PAPERS
    monkeypatch.setattr(cli, "DIR_SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(cli, "DIR_PAPERS", tmp_path / "papers")
    records = fetch(FakeClient(), config)
    papers.save(records, cli.DIR_PAPERS, [])
    (tmp_path / "snapshots").mkdir()
    snap = snapshot(records, config) | {"taken_at": "2026-10-19T08:00:00"}
    (tmp_path / "snapshots" / "a.json").write_text(json.dumps(snap))
    client = FakeClient()
    monkeypatch.setattr(cli, "login", lambda config: client)
    monkeypatch.setattr(Monitor, "in_terminal", lambda self, job: job())
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    return Monitor(config), client, opened


def test_tui_downloads_and_opens_the_pdf(tmp_path, monkeypatch):
    app, client, opened = cached_monitor(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.press("p")
            await pilot.press("U")  # paper 7 has no supplementary material
        assert client.downloads == [("pdf", "abc")]
        assert len(opened) == 1 and opened[0].endswith("/papers/7/pdf_v1.pdf")

    asyncio.run(scenario())


def test_tui_email_form_sends_only_after_send(tmp_path, monkeypatch):
    for answer, sent in [("no", 0), ("SEND", 1)]:
        app, client, _ = cached_monitor(tmp_path / answer, monkeypatch, answer)

        async def scenario():
            async with app.run_test() as pilot:
                await pilot.press("e")
                await pilot.press("escape")  # cancelling the form sends nothing
                await pilot.press("e")
                app.screen.query_one("#subject").value = "Hi"
                app.screen.query_one("#body").load_text("Dear {{fullname}}")
                await pilot.click("#send")
                await pilot.pause()

        asyncio.run(scenario())
        assert len(client.messages) == sent
        if sent:
            assert client.messages[0][0] == ("Hi", ["~Rev_B1", "~Rev_C1"], "Dear {{fullname}}")
