import asyncio
import json
import zipfile

from textual.widgets import Static, Tree

from aamas_review_monitor import core
from aamas_review_monitor import tui
from aamas_review_monitor.tui import Attachment, Busy, Confirm, Login, Monitor, Paper
from tests.test_checks import CONFIG, paper


def test_tui_lists_and_filters_issues(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DIR_SNAPSHOTS", tmp_path)
    monkeypatch.setattr(core, "DIR_PAPERS", tmp_path / "papers")
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
            assert "🟢 Enough reviewers assigned" in text
            await pilot.press("p", "f", "i")  # table actions are off on the details screen
            assert isinstance(app.screen, Paper)
            await pilot.press("escape")
            assert not isinstance(app.screen, Paper)
            await pilot.press("l")
            legend = str(app.screen.query_one("#legend", Static).render())
            assert "Enough reviewers assigned" in legend and "fewer than 3 reviewers" in legend
            await pilot.press("escape")

    asyncio.run(scenario())


async def settle(app, pilot, timeout=15):
    """Waits until the app has been idle (no job running, no progress dialog) for a while: a job
    may start only from a callback, e.g. a dismissed dialog's, some ticks after the action."""
    idle, waited = 0, 0.0
    while idle < 10 and waited < timeout:
        await pilot.pause(0.05)
        await app.workers.wait_for_complete()
        busy = isinstance(app.screen, Busy) or any(w.is_running for w in app.workers)
        idle, waited = (0 if busy else idle + 1), waited + 0.05
    await pilot.pause()


async def until(pilot, condition, timeout=15):
    """Waits for `condition()` to hold, e.g. for a background job's effect."""
    waited = 0.0
    while not condition() and waited < timeout:
        await pilot.pause(0.05)
        waited += 0.05
    assert condition(), "timed out"


def cached_monitor(tmp_path, monkeypatch):
    """A Monitor over one cached synthetic paper, with a fake client and no real terminal."""
    from aamas_review_monitor import papers
    from aamas_review_monitor.collector import fetch, snapshot
    from tests.test_collector import FakeClient
    from tests.test_papers import CONFIG as PAPERS

    config = CONFIG | PAPERS
    monkeypatch.setattr(core, "DIR_SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(core, "DIR_PAPERS", tmp_path / "papers")
    records = fetch(FakeClient(), config)
    papers.save(records, core.DIR_PAPERS, [])
    (tmp_path / "snapshots").mkdir()
    snap = snapshot(records, config) | {"taken_at": "2026-10-19T08:00:00"}
    (tmp_path / "snapshots" / "a.json").write_text(json.dumps(snap))
    client = FakeClient()
    monkeypatch.setattr(core, "resume", lambda config: client)  # as if a token were cached
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    return Monitor(config), client, opened


def test_tui_downloads_once_then_shows_the_pdf(tmp_path, monkeypatch):
    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    launched: list[list[str]] = []
    monkeypatch.setattr(
        tui.papers.subprocess, "Popen", lambda command, **kw: launched.append(command)
    )
    monkeypatch.setattr(tui.papers, "pdf_text", lambda path: "left column\nright column")

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.press("p")
            await settle(app, pilot)
            assert isinstance(app.screen, Attachment)
            path = str(app.screen.path)
            assert app.screen.path == tmp_path / "papers" / "7" / "pdf_v1.pdf"
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
                if sent:
                    await until(pilot, lambda: len(client.messages) == sent)
                await settle(app, pilot)

        asyncio.run(scenario())
        assert len(client.messages) == sent
        if sent:
            assert client.messages[0][0] == ("Hi", ["~Rev_B1", "~Rev_C1"], "Dear {{fullname}}")


def test_tui_signs_in_and_syncs_in_background(tmp_path, monkeypatch):
    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    monkeypatch.setattr(core, "resume", lambda config: None)  # no valid token
    monkeypatch.delenv("OPENREVIEW_USERNAME", raising=False)
    signed: list[tuple] = []
    monkeypatch.setattr(core, "login", lambda config, *creds: signed.append(creds) or client)
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


def test_tui_inspects_the_pdf_and_shows_the_results(tmp_path, monkeypatch):
    from aamas_review_monitor import documents

    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    monkeypatch.setattr(documents.papers, "pdf_text", lambda pdf: "A Paper\nAnonymous Author(s)\f")
    monkeypatch.setattr(documents, "pdfinfo", lambda pdf: {"Page size": "612 x 792 pts"})
    monkeypatch.setattr(documents, "pdffonts", lambda pdf: [])

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.press("i")
            await settle(app, pilot)
            assert client.downloads == [("pdf", "abc")]  # fetched first, then inspected
            assert isinstance(app.screen, Paper)
            text = app.screen.text.plain
            assert "🔴 no AAMAS 2027 copyright block" in text
            assert "🟢 US Letter pages" in text and "not run" not in text
            await pilot.press("escape")
            codes = {i.code for i in app.issues if i.number == 7}
            assert "template" in codes

    asyncio.run(scenario())


def test_tui_bulk_download_survives_a_failure(tmp_path, monkeypatch):
    app, client, _ = cached_monitor(tmp_path, monkeypatch)

    def broken(field_name, id):
        raise ConnectionError("rate limited")

    monkeypatch.setattr(client, "get_attachment", broken)
    notes: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message, **kw: notes.append(message))

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.press("P")
            await settle(app, pilot)
            assert not isinstance(app.screen, Busy)

    asyncio.run(scenario())
    assert notes == ["#7: rate limited\n0 of 1 papers have pdf: cached"]


def test_command_palette_offers_every_action(tmp_path, monkeypatch):
    app, _, _ = cached_monitor(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test() as pilot:
            commands = {c.title: c for c in app.get_system_commands(app.screen)}
            assert {title for title, _, _ in tui.COMMANDS} <= set(commands)
            for _, _, action in tui.COMMANDS:  # every action names a real method
                name = action.split("(")[0]
                assert hasattr(app, f"action_{name}"), name
            await commands["Legend"].callback()
            await pilot.pause()
            assert isinstance(app.screen, tui.Legend)
            assert not any(c.title == "Legend" for c in app.get_system_commands(app.screen))

    asyncio.run(scenario())


def test_tui_bulk_inspect_downloads_what_is_missing(tmp_path, monkeypatch):
    from aamas_review_monitor import documents

    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    monkeypatch.setattr(documents.papers, "pdf_text", lambda pdf: "A Paper\nAnonymous Author(s)\f")
    monkeypatch.setattr(documents, "pdfinfo", lambda pdf: {})
    monkeypatch.setattr(documents, "pdffonts", lambda pdf: [])

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.press("I")
            await settle(app, pilot)
            assert client.downloads == [("pdf", "abc")]
            assert 7 in app.inspected and any(i.code == "template" for i in app.issues)
            monkeypatch.setattr(core, "resume", lambda config: None)  # cached: no login needed
            await pilot.press("I")
            await settle(app, pilot)
            assert client.downloads == [("pdf", "abc")] and not isinstance(app.screen, Login)

    asyncio.run(scenario())


def test_bulk_job_logs_its_steps_and_can_be_interrupted(tmp_path, monkeypatch):
    import copy
    import threading

    from aamas_review_monitor import papers

    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    (record,) = papers.load(core.DIR_PAPERS, [7])
    second = copy.deepcopy(record) | {"number": 8}
    papers.save([second], core.DIR_PAPERS, [])
    release, started = threading.Event(), threading.Event()

    def slow(field_name, id):
        client.downloads.append(id)
        started.set()
        release.wait(5)
        return b"%PDF"

    monkeypatch.setattr(client, "get_attachment", slow)
    lines: list[str] = []
    monkeypatch.setattr(tui.Busy, "write", lambda self, level, message: lines.append(message))
    notes: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message, **kw: notes.append(message))

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.press("P")  # papers 7 and 8
            await pilot.pause()
            assert isinstance(app.screen, Busy)
            await asyncio.to_thread(started.wait, 5)
            await pilot.press("escape")  # interrupt while #7 is downloading
            release.set()
            await settle(app, pilot)
            assert not isinstance(app.screen, Busy)

    asyncio.run(scenario())
    assert client.downloads == ["abc"]  # stopped before the second paper
    assert any("Interrupting" in line for line in lines)
    assert any("#7: pdf_v1.pdf" in line for line in lines)
    assert any("interrupted: completed steps are kept" in n for n in notes)


async def choose_template(app, pilot, key):
    screen = app.screen
    assert isinstance(screen, tui.Templates)
    screen.query_one("#templates").highlighted = [t.key for t in screen.choices].index(key)
    await pilot.press("enter")
    await pilot.pause()


def test_spc_tab_lists_issues_per_spc_and_sends_a_digest(tmp_path, monkeypatch):
    app, client, _ = cached_monitor(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("t")
            spcs = app.query_one("#spcs")
            assert spcs.row_count == 1 and spcs.get_row_at(0)[:3] == ["~Spc_One1", 1, 1]
            panel = str(app.query_one("#spc-issues").render())
            assert "#7" in panel and "ratings [3, 6]" in panel
            await pilot.press("m")
            await choose_template(app, pilot, "spc-digest")
            assert isinstance(app.screen, Confirm)
            assert "=== To ~Spc_One1, via #7 ===" in app.screen.summary
            assert "ratings [3, 6]" in app.screen.summary
            app.screen.query_one("#confirm").value = "SEND"
            await pilot.click("#confirm-send")
            await until(pilot, lambda: len(client.messages) == 1)
            await settle(app, pilot)
            panel = str(app.query_one("#spc-issues").render())
            assert "Sent to them from this app" in panel and "email to ~Spc_One1 via #7" in panel

    asyncio.run(scenario())
    ((args, kwargs),) = client.messages
    assert args[1] == ["ifaamas.org/AAMAS/2027/Conference/Submission7/Area_Chair_9jqi"]
    assert args[0] == "AAMAS 2027: status of your papers (#7)"


def test_papers_tab_templated_reminder_to_late_reviewers_can_be_cancelled(tmp_path, monkeypatch):
    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    notes: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message, **kw: notes.append(message))

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.press("M")
            await choose_template(app, pilot, "spc-deadline")  # no meta-review issue yet
            assert not isinstance(app.screen, Confirm)
            await pilot.press("M")
            await choose_template(app, pilot, "spc-digest")
            assert isinstance(app.screen, Confirm)
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(scenario())
    assert client.messages == []
    assert notes == ["Nothing to send with Meta-review deadline", "Nothing sent"]


def test_comment_then_history_tab_details_and_spc_panel_show_it(tmp_path, monkeypatch):
    app, client, _ = cached_monitor(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("c")
            form = app.screen
            assert isinstance(form, tui.CommentForm)
            text = form.query_one("#comment-text")
            assert "ratings [3, 6]" in text.text
            text.load_text("Please check the reviews.")
            form.query_one("#spcs-read").value = False
            await pilot.click("#comment-post")
            assert isinstance(app.screen, Confirm)
            assert app.screen.summary.startswith("1 comments, readable by PCs, SACs\n")
            app.screen.query_one("#confirm").value = "SEND"
            await pilot.click("#confirm-send")
            await until(pilot, lambda: len(client.comments) == 1)
            await settle(app, pilot)

            ((_, _, note),) = client.comments
            assert note.content["comment"]["value"] == "Please check the reviews."
            assert not any(r.endswith("/Area_Chairs") for r in note.readers)  # no SPCs
            await pilot.press("t", "t")  # Papers -> SPCs -> History
            history = app.query_one("#history")
            assert history.row_count == 1 and history.get_row_at(0)[2:5] == [
                "comment",
                7,
                "PCs, SACs",
            ]
            assert "Please check the reviews." in str(app.query_one("#history-entry").render())
            await pilot.press("t")  # back to Papers
            await pilot.press("enter")
            assert "comment to PCs, SACs via #7" in app.screen.text.plain

    asyncio.run(scenario())
    assert core.FILE_HISTORY.is_file()  # the temporary one (see conftest)
