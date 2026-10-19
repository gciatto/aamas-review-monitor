import asyncio
import json
import zipfile

from textual.widgets import Static, Tree

from aamas_review_monitor import __main__ as cli
from aamas_review_monitor import tui
from aamas_review_monitor.tui import Attachment, Busy, Confirm, Login, Monitor, Paper
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
            await pilot.press("g", "f", *"no spc", "enter")
            assert table.row_count == 1
            await pilot.press("o")
            assert opened == ["https://openreview.net/forum?id=p1"]
            await pilot.press("enter")
            assert isinstance(app.screen, Paper)
            text = app.screen.text.plain
            assert "Not cached" in text and "🔴 no SPC assigned" in text
            assert "🟢 enough reviewers assigned" in text
            await pilot.press("escape")
            assert not isinstance(app.screen, Paper)

    asyncio.run(scenario())


async def settle(app, pilot):
    """Waits for background jobs and the screens they open."""
    await app.workers.wait_for_complete()
    await pilot.pause()


def cached_monitor(tmp_path, monkeypatch):
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
    monkeypatch.setattr(cli, "resume", lambda config: client)  # as if a token were cached
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    return Monitor(config), client, opened


def test_tui_downloads_once_then_shows_the_pdf(tmp_path, monkeypatch):
    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    launched: list[list[str]] = []
    monkeypatch.setattr(tui.subprocess, "Popen", lambda command, **kw: launched.append(command))
    monkeypatch.setattr(tui.papers, "pdf_text", lambda path: "left column\nright column")

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.press("p")
            await settle(app, pilot)
            assert isinstance(app.screen, Attachment)
            path = str(app.screen.path)
            assert path.endswith("/papers/7/pdf_v1.pdf")
            assert "right column" in str(app.screen.query_one("#text", Static).render())
            await pilot.press("c", "v", "escape", "p")  # second time: cached, no download
            assert isinstance(app.screen, Attachment)
            assert len(launched) == 2 and launched[1][-1] == path  # reveal, then default viewer
        assert client.downloads == [("pdf", "abc")]

    asyncio.run(scenario())


def test_tui_shows_the_tree_of_a_zip(tmp_path, monkeypatch):
    app, _, _ = cached_monitor(tmp_path, monkeypatch)
    record = tmp_path / "papers" / "7" / "record.json"
    data = json.loads(record.read_text())
    data["content"]["supplementary_material"] = {"value": "/attachment/s1.zip"}
    record.write_text(json.dumps(data))
    with zipfile.ZipFile(record.parent / "supplementary_material_s1.zip", "w") as archive:
        archive.writestr("code/main.py", "print()")
        archive.writestr("README.md", "hi")

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.press("u")
            root = app.screen.query_one("#tree", Tree).root
            assert [str(n.label).split()[0] for n in root.children] == ["code", "README.md"]
            assert str(root.children[0].children[0].label).startswith("main.py")

    asyncio.run(scenario())


def test_tui_email_sends_only_after_typing_send(tmp_path, monkeypatch):
    for answer, sent in [("no", 0), ("SEND", 1)]:
        app, client, _ = cached_monitor(tmp_path / answer, monkeypatch)

        async def scenario():
            async with app.run_test() as pilot:
                await pilot.press("e")
                await pilot.press("escape")  # cancelling the form sends nothing
                await pilot.press("e")
                app.screen.query_one("#subject").value = "Hi"
                app.screen.query_one("#body").load_text("Dear {{fullname}}")
                await pilot.click("#send")
                assert isinstance(app.screen, Confirm)
                assert "late-reviewers of papers #7" in str(app.screen.summary)
                app.screen.query_one("#confirm").value = answer
                await pilot.click("#confirm-send")
                await settle(app, pilot)

        asyncio.run(scenario())
        assert len(client.messages) == sent
        if sent:
            assert client.messages[0][0] == ("Hi", ["~Rev_B1", "~Rev_C1"], "Dear {{fullname}}")


def test_tui_signs_in_and_syncs_in_background(tmp_path, monkeypatch):
    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "resume", lambda config: None)  # no valid token
    monkeypatch.delenv("OPENREVIEW_USERNAME", raising=False)
    signed: list[tuple] = []
    monkeypatch.setattr(cli, "login", lambda config, *creds: signed.append(creds) or client)
    for old in (tmp_path / "snapshots").iterdir():
        old.unlink()

    async def scenario():
        async with app.run_test() as pilot:
            assert app.query_one("#issues").row_count == 0
            await pilot.press("s")
            await settle(app, pilot)
            assert isinstance(app.screen, Login)
            app.screen.query_one("#username").value = "sac@example.org"
            app.screen.query_one("#password").value = "secret"
            await pilot.click("#signin")
            await settle(app, pilot)
            assert signed == [("sac@example.org", "secret")]
            assert not isinstance(app.screen, (Login, Busy))
            assert app.query_one("#issues").row_count > 0  # reloaded from the new snapshot

    asyncio.run(scenario())
