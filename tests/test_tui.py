import asyncio
import json

from aamas_review_monitor import __main__ as cli
from aamas_review_monitor.tui import Monitor, Paper
from tests.test_checks import CONFIG, paper


def test_tui_lists_and_filters_issues(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DIR_SNAPSHOTS", tmp_path)
    monkeypatch.setattr(cli, "DIR_PAPERS", tmp_path / "papers")
    snapshot = {"taken_at": "2026-11-11T08:00:00", "papers": [paper(1, spcs=[]), paper(2, words=9)]}
    (tmp_path / "2026-11-11T080000.json").write_text(json.dumps(snapshot))
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)

    async def scenario():
        app = Monitor(CONFIG)
        async with app.run_test() as pilot:
            table = app.query_one("#issues")
            assert table.row_count == 4  # no SPC on #1, three short reviews on #2
            await pilot.press("slash", *"no spc", "enter")
            assert table.row_count == 1
            await pilot.press("o")
            assert opened == ["https://openreview.net/forum?id=p1"]
            await pilot.press("d")
            assert isinstance(app.screen, Paper) and "#1: not cached" in app.screen.text
            await pilot.press("escape")
            assert not isinstance(app.screen, Paper)

    asyncio.run(scenario())
