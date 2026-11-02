import asyncio
import contextlib
import json
import zipfile

from textual.widgets import Static, Tree

from aamas_review_monitor import core
from aamas_review_monitor import tui
from aamas_review_monitor.tui import Attachment, Busy, Login, Monitor, Paper, Review
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
            await pilot.press(*"spc")  # the filter has the focus
            legend = str(app.screen.query_one("#legend", Static).render())
            assert "SPC assigned" in legend and "Enough reviewers assigned" not in legend
            await pilot.press("escape")

    asyncio.run(scenario())


async def until(pilot, condition, timeout=15, state=lambda: ""):
    """Waits for `condition()` to hold, e.g. for a background job's effect; on a timeout, says
    what `state()` was."""
    waited = 0.0
    while not condition() and waited < timeout:
        await pilot.pause(0.02)
        waited += 0.02
    assert condition(), f"timed out: {state()}"


async def done(app, pilot, effect):
    """Waits for the job started by the last key or click to end with its visible `effect`.
    Waiting for an effect, not for a quiet spell, is what makes this deterministic: a job may
    start some ticks after the key, from a dismissed dialog's callback."""

    def running():
        return [f"{w.name} ({w.state.name})" for w in app.workers if w.is_running]

    def state():
        return f"screen {app.screen!r}, effect {effect()}, running {running()}"

    await until(
        pilot, lambda: effect() and not isinstance(app.screen, Busy) and not running(), state=state
    )


async def reviewing(app, pilot):
    """The Review dialog, once it has opened and filled its editor with the first item."""
    ready = lambda: isinstance(app.screen, Review) and app.screen.current is not None  # noqa: E731
    await until(pilot, ready, state=lambda: f"screen {app.screen!r}")
    return app.screen


async def confirm(app, pilot, answer):
    """Types `answer` in the Review dialog's box, once it has the focus, and presses Enter."""
    assert isinstance(app.screen, Review)
    box = app.screen.query_one("#confirm")
    await until(pilot, lambda: app.focused is box, state=lambda: f"focus on {app.focused!r}")
    await pilot.press(*answer, "enter")


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


def second_paper():
    """Caches a copy of #7 as #8, for jobs on several papers."""
    import copy

    from aamas_review_monitor import papers

    (record,) = papers.load(core.DIR_PAPERS, [7])
    papers.save([copy.deepcopy(record) | {"number": 8}], core.DIR_PAPERS, [])


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
            await done(app, pilot, lambda: isinstance(app.screen, Attachment))
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
    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    notes: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message, **kw: notes.append(message))

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.press("e")
            await pilot.press("escape")  # cancelling the form sends nothing
            for answer in ("no", "SEND"):
                await pilot.press("e")
                app.screen.query_one("#subject").value = "Hi"
                app.screen.query_one("#body").load_text("Dear {{fullname}}")
                await pilot.click("#send")
                await reviewing(app, pilot)
                assert app.screen.items[0].heading == "To late-reviewers of #7 (2), via #7"
                await confirm(app, pilot, answer)
                await done(app, pilot, lambda: bool(notes) and not isinstance(app.screen, Review))
                assert len(client.messages) == (answer == "SEND"), notes

    asyncio.run(scenario())
    assert notes == ["Nothing sent", "Sent 1 of 1"]
    assert client.messages[0][0] == ("Hi", ["~Rev_B1", "~Rev_C1"], "Dear {{fullname}}")


def test_tui_signs_in_with_the_app_suspended(tmp_path, monkeypatch):
    """openreview-py prompts for multi-factor codes in the terminal: the app must not hide it."""
    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    monkeypatch.setattr(core, "resume", lambda config: None)
    suspended: list[bool] = []

    @contextlib.contextmanager
    def suspend():
        suspended.append(True)
        yield
        suspended.append(False)

    monkeypatch.setattr(app, "suspend", suspend)
    monkeypatch.setattr(core, "login", lambda config, *creds: suspended.append(creds) or client)
    assert app.sign_in(("sac@example.org", "secret")) is client
    assert suspended == [True, ("sac@example.org", "secret"), False]


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
            await done(app, pilot, lambda: isinstance(app.screen, Login))
            app.screen.query_one("#username").value = "sac@example.org"
            app.screen.query_one("#password").value = "secret"
            await pilot.click("#signin")
            await done(app, pilot, lambda: app.query_one("#issues").row_count > 0)
            assert signed == [("sac@example.org", "secret")]
            assert not isinstance(app.screen, (Login, Busy))
            assert app.query_one("#issues").row_count > 0  # reloaded from the new snapshot

    asyncio.run(scenario())


def test_tui_inspects_the_pdf_and_shows_the_results(tmp_path, monkeypatch):
    from aamas_review_monitor import documents

    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    monkeypatch.setattr(documents.papers, "pdf_pages", lambda pdf: ["A Paper\nAnonymous Author(s)"])
    monkeypatch.setattr(documents, "pdfinfo", lambda pdf: {"Page size": "612 x 792 pts"})
    monkeypatch.setattr(documents, "pdffonts", lambda pdf: [])

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.press("i")
            await done(app, pilot, lambda: isinstance(app.screen, Paper))
            assert client.downloads == [("pdf", "abc")]  # fetched first, then inspected
            assert isinstance(app.screen, Paper)
            text = app.screen.text.plain
            assert "🟡 no AAMAS 2027 copyright block" in text
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
    second_paper()

    async def scenario():
        async with app.run_test() as pilot:
            app.marked = {(7, "x"), (8, "x")}  # #8 is cached but not in the snapshot, so not shown
            await pilot.press("p")
            await done(app, pilot, lambda: bool(notes))

    asyncio.run(scenario())
    assert notes[-1] == "#7: rate limited\n#8: rate limited\n0 of 2 papers have pdf: cached"


def test_command_palette_and_footer_offer_each_tabs_actions(tmp_path, monkeypatch):
    from textual.widgets import TabbedContent

    app, _, _ = cached_monitor(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test() as pilot:
            offered = set()
            tables = ["#issues", "#spcs", "#history", "#areas", "#rubrics"]
            for tab, table in zip(tui.TAB_ACTIONS, tables):  # together, they offer every action
                app.query_one(TabbedContent).active = tab
                app.query_one(table).focus()  # as `t` does
                await pilot.pause()
                titles = {c.title for c in app.get_system_commands(app.screen)}
                offered |= titles
                shown = {
                    b.binding.action.split("(")[0]
                    for b in app.active_bindings.values()
                    if b.enabled
                }
                assert ("score_areas" in shown) == (tab == "areas-tab"), tab
                assert ("mark" in shown) == (tab in ("papers", "spcs-tab")), tab
                assert "switch_tab" in shown and "sync" in shown
            assert {title for title, _, _ in tui.COMMANDS} <= offered
            for _, _, action in tui.COMMANDS:  # every action names a real method
                name = action.split("(")[0]
                assert hasattr(app, f"action_{name}"), name
            app.query_one(TabbedContent).active = "papers"
            await pilot.pause()
            commands = {c.title: c for c in app.get_system_commands(app.screen)}
            assert "Score areas" not in commands
            await commands["Legend"].callback()
            await pilot.pause()
            assert isinstance(app.screen, tui.Legend)
            assert not any(c.title == "Legend" for c in app.get_system_commands(app.screen))

    asyncio.run(scenario())


def test_tui_bulk_inspect_downloads_what_is_missing(tmp_path, monkeypatch):
    from aamas_review_monitor import documents

    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    second_paper()
    monkeypatch.setattr(documents.papers, "pdf_pages", lambda pdf: ["A Paper\nAnonymous Author(s)"])
    monkeypatch.setattr(documents, "pdfinfo", lambda pdf: {})
    monkeypatch.setattr(documents, "pdffonts", lambda pdf: [])
    notes: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message, **kw: notes.append(message))

    async def scenario():
        async with app.run_test() as pilot:
            app.marked = {(7, "x"), (8, "x")}
            await pilot.press("i")
            await done(app, pilot, lambda: len(notes) == 1)
            assert notes == ["Inspected 2 of 2 papers"]
            assert client.downloads == [("pdf", "abc")] * 2
            assert 7 in app.inspected and any(i.code == "template" for i in app.issues)
            monkeypatch.setattr(core, "resume", lambda config: None)  # cached: no login needed
            await pilot.press("i")
            await done(app, pilot, lambda: len(notes) == 2)
            assert client.downloads == [("pdf", "abc")] * 2 and not isinstance(app.screen, Login)

    asyncio.run(scenario())


def test_bulk_job_logs_its_steps_and_can_be_interrupted(tmp_path, monkeypatch):
    import threading

    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    second_paper()
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
            app.marked = {(7, "x"), (8, "x")}
            await pilot.press("p")
            await pilot.pause()
            assert isinstance(app.screen, Busy)
            await asyncio.to_thread(started.wait, 5)
            await pilot.press("escape")  # interrupt while #7 is downloading
            release.set()
            await done(app, pilot, lambda: any("interrupted" in n for n in notes))

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
            assert spcs.row_count == 1 and spcs.get_row_at(0)[:4] == ["", "~Spc_One1", 1, 1]
            panel = str(app.query_one("#spc-issues").render())
            assert "#7" in panel and "ratings [3, 6]" in panel
            await pilot.press("m")
            await choose_template(app, pilot, "spc-digest")
            (item,) = (await reviewing(app, pilot)).items
            assert item.heading == "To ~Spc_One1, via #7" and "ratings [3, 6]" in item.text
            await confirm(app, pilot, "SEND")
            await done(app, pilot, lambda: bool(app.sent))
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
            await pilot.press("asterisk")  # every paper shown
            await pilot.press("m")
            await choose_template(app, pilot, "spc-deadline")  # no meta-review issue yet
            assert not isinstance(app.screen, Review)
            await pilot.press("m")
            await choose_template(app, pilot, "spc-digest")
            await reviewing(app, pilot)
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(scenario())
    assert client.messages == []
    assert notes == ["4 issues marked", "Nothing to send with Meta-review deadline", "Nothing sent"]


def test_comment_then_history_tab_details_and_spc_panel_show_it(tmp_path, monkeypatch):
    app, client, _ = cached_monitor(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("c")
            form = app.screen
            assert isinstance(form, tui.CommentForm)
            form.query_one("#spcs-read").value = False
            await pilot.click("#comment-post")
            review = await reviewing(app, pilot)
            assert review.header[0] == "1 comments, readable by PCs, SACs"
            text = review.query_one("#review-text")
            assert "ratings [3, 6]" in text.text  # editable before posting
            text.load_text("Please check the reviews.")
            hint = str(review.query_one("#review-placeholders").render())
            assert "$paper" in hint and "(here: #7)" in hint
            pattern = review.query_one("#review-pattern")
            pattern.value = "Reviews of $paper"
            pattern.focus()
            await pilot.press("enter")
            assert review.query_one("#review-title").value == "Reviews of #7"
            review.query_one("#confirm").focus()
            await confirm(app, pilot, "SEND")
            await done(app, pilot, lambda: bool(app.sent))

            ((_, _, note),) = client.comments
            assert note.content["title"]["value"] == "Reviews of #7"
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
            await pilot.press("t")  # Areas: loads the cached scores (none here)
            await done(app, pilot, lambda: app.area_results is not None)
            await pilot.press("t", "t")  # Rubrics, then back to Papers
            table = app.query_one("#issues")
            rows = [table.get_row_at(r) for r in range(table.row_count)]
            commented = [r for r in rows if r[2] == 7 and r[1] != "🟢"]
            assert commented and all(r[3] and not r[4] for r in commented)  # date, no email
            await pilot.press("n")  # only issues never sent: none of #7's
            assert all(table.get_row_at(r)[2] != 7 for r in range(table.row_count))
            await pilot.press("n")
            assert table.row_count == len(rows)
            await pilot.press("enter")
            assert "comment to PCs, SACs via #7" in app.screen.text.plain

    asyncio.run(scenario())
    assert core.FILE_HISTORY.is_file()  # the temporary one (see conftest)


def test_marks_scope_the_action_menu_and_wide_terminals_show_details(tmp_path, monkeypatch):
    app, _, _ = cached_monitor(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(150, 40)) as pilot:
            header = str(app.query_one("#summary").render())
            assert "  ·  " in header and "Snapshot of " in header  # phase · freshness
            assert "Paper #7" in str(app.query_one("#paper-detail").render())
            await pilot.press("space")
            table = app.query_one("#issues")
            assert {n for n, _ in app.marked} == {7}
            marks = [table.get_row_at(r)[0] for r in range(table.row_count)]
            assert marks[0] == "✔" and set(marks[1:]) == {""}  # the issue, not its paper
            await pilot.press("a")
            menu = app.screen
            assert isinstance(menu, tui.Actions) and menu.scope == "Act on paper #7"
            actions = [a for *_, a in menu.choices]
            menu.query_one("#actions").highlighted = actions.index("comment")
            await pilot.press("enter")
            await until(pilot, lambda: isinstance(app.screen, tui.CommentForm))
            await pilot.press("escape", "space")
            assert app.marked == set() and table.get_row_at(0)[0] == ""
            await pilot.press("t", "space", "a")  # SPCs tab: templated email only
            assert app.marked_spcs == {"~Spc_One1"}
            assert [a for *_, a in app.screen.choices] == ["mail"]
            await pilot.press("escape", "t", "a")  # History: nothing to act on
            assert not isinstance(app.screen, tui.Actions)

    asyncio.run(scenario())


def test_narrow_terminals_hide_the_details_panel(tmp_path, monkeypatch):
    app, _, _ = cached_monitor(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            assert not app.query_one("#paper-panel").display

    asyncio.run(scenario())


def test_panel_handlers_survive_a_screen_being_built_or_torn_down(tmp_path, monkeypatch):
    app, _, _ = cached_monitor(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test() as pilot:
            for panel in ("#paper-panel", "#spc-panel", "#history-panel"):
                await app.query_one(panel).remove()  # as during shutdown
            await pilot.resize_terminal(130, 30)  # on_resize updates the paper panel
            app.show_spc()
            app.show_history()
            await pilot.press("g")
            assert app.hide_green  # still running and taking keys

    asyncio.run(scenario())


def test_review_edits_each_message_and_refuses_empty_ones(tmp_path, monkeypatch):
    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    second_paper()

    async def scenario():
        async with app.run_test(size=(140, 40)) as pilot:
            app.marked = {(7, "x"), (8, "x")}
            await pilot.press("e")
            app.screen.query_one("#subject").value = "Hi"
            app.screen.query_one("#body").load_text("Dear {{fullname}}")
            await pilot.click("#send")
            review = await reviewing(app, pilot)
            assert len(review.items) == 2
            review.query_one("#review-title").value = "Hi, paper 7"
            review.query_one("#review-list").highlighted = 1  # to the second message
            await pilot.pause()
            assert review.query_one("#review-title").value == "Hi"
            review.query_one("#review-text").load_text("")  # empty: refused
            await confirm(app, pilot, "SEND")
            assert isinstance(app.screen, Review) and client.messages == []
            review.query_one("#review-text").load_text("Dear {{fullname}}, about #8")
            review.query_one("#confirm").value = ""
            await confirm(app, pilot, "SEND")
            await done(app, pilot, lambda: len(app.sent) == 2)

    asyncio.run(scenario())
    assert [m[0][0] for m in client.messages] == ["Hi, paper 7", "Hi"]
    assert client.messages[1][0][2] == "Dear {{fullname}}, about #8"


def test_ignored_issues_stay_listed_in_gray_and_out_of_comments(tmp_path, monkeypatch):
    app, _, _ = cached_monitor(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(140, 40)) as pilot:
            table = app.query_one("#issues")
            rows = [table.get_row_at(r) for r in range(table.row_count)]
            row = next(n for n, r in enumerate(rows) if r[6] == "ratings [3, 6]")
            table.move_cursor(row=row)
            await pilot.press("x")
            assert (7, "disagreement") in app.ignored
            assert table.row_count == len(rows)  # still listed
            assert table.cursor_row == row and table.get_row_at(row)[1] == "⚪"
            assert "ratings [3, 6] (ignored" in app.paper_text(7).plain
            assert all(i.code != "disagreement" for i in app.by_spc()["~Spc_One1"])  # uncounted
            await pilot.press("c")
            await pilot.click("#comment-post")
            (item,) = (await reviewing(app, pilot)).items
            assert "ratings [3, 6]" not in item.text and "review of 1 words" in item.text

    asyncio.run(scenario())


def test_open_the_pdf_directly_and_the_papers_folder(tmp_path, monkeypatch):
    app, client, _ = cached_monitor(tmp_path, monkeypatch)
    launched: list[list[str]] = []
    monkeypatch.setattr(
        tui.papers.subprocess, "Popen", lambda command, **kw: launched.append(command)
    )

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.press("v")  # not downloaded yet: fetched first, then opened
            await done(app, pilot, lambda: bool(launched))
            assert launched[-1][-1] == str(tmp_path / "papers" / "7" / "pdf_v1.pdf")
            await pilot.press("w")
            assert launched[-1][-1] == str(tmp_path / "papers" / "7")
            assert not isinstance(app.screen, Attachment)  # no dialog in between

    asyncio.run(scenario())
    assert client.downloads == [("pdf", "abc")]


def test_comments_list_only_the_marked_issues(tmp_path, monkeypatch):
    app, _, _ = cached_monitor(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(140, 40)) as pilot:
            table = app.query_one("#issues")
            (_, _, n1, *_, first), (_, _, n2, *_, second) = map(table.get_row_at, (0, 1))
            assert n1 == n2 == 7  # two issues of one paper
            await pilot.press("space", "c")
            app.screen.query_one("#spcs-read").value = False
            await pilot.click("#comment-post")
            review = await reviewing(app, pilot)
            text = review.query_one("#review-text").text
            assert first in text and second not in text

    asyncio.run(scenario())


def test_mark_dialog_marks_the_issues_matching_every_chosen_group(tmp_path, monkeypatch):
    app, _, _ = cached_monitor(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("plus")
            dialog = app.screen
            assert isinstance(dialog, tui.Marks)
            options = [value for _, value in dialog.options]
            assert "sent:unsent" in options and "check:disagreement" in options
            marks = dialog.query_one("#marks")
            marks.select("check:disagreement")
            marks.select("sent:unsent")
            await pilot.click("#marks-apply")
            assert {code for _, code in app.marked} == {"disagreement"}
            await pilot.press("plus")
            await pilot.click("#marks-none")
            assert app.marked == set()

    asyncio.run(scenario())


def test_areas_tab_scores_sorts_hides_and_explains(monkeypatch):
    from textual.widgets import SelectionList

    from aamas_review_monitor import areas, papers
    from tests.test_models import FakeEndpoint, resolves_to
    from tests.test_scores import CONFIG as AREAS_CONFIG
    from tests.test_scores import PAGE, RECORDS

    endpoint = FakeEndpoint(monkeypatch)
    resolves_to(monkeypatch, "127.0.0.1")
    monkeypatch.setattr(areas, "DIR_RUBRICS_DEFAULT", core.DIR_DATA / "none")
    for rubric in areas.parse(PAGE, "https://example.org/call"):
        areas.save(rubric, core.DIR_RUBRICS)
    papers.save(RECORDS, core.DIR_PAPERS, [])
    core.DIR_SNAPSHOTS.mkdir(parents=True)
    snapshot = {"taken_at": "2026-11-11T08:00:00", "papers": [paper(1), paper(2, reviews=1)]}
    (core.DIR_SNAPSHOTS / "2026-11-11T080000.json").write_text(json.dumps(snapshot))

    async def scenario():
        app = Monitor(AREAS_CONFIG)
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.press("t", "t", "t")  # Areas: nothing embedded yet, nothing asked
            await done(app, pilot, lambda: app.area_results is not None)
            table = app.query_one("#areas")
            assert table.row_count == 2 and endpoint.requests == []
            assert table.get_row_at(0)[1] == "Multiagent learning"  # the title
            assert table.get_row_at(0)[-1].plain.strip() == "—"  # the shares come last
            await pilot.press("k")
            choices = app.screen.query_one(SelectionList)
            assert choices.selected == ["title", "keywords", "abstract"]
            choices.select("reviews")
            await pilot.click("#marks-apply")
            await done(app, pilot, lambda: bool(app.area_results))
            assert app.area_include == ("title", "keywords", "abstract", "reviews")
            assert "This is about robots and swarms." in endpoint.requests[-1]["input"]
            app.sort_areas("ROBOT")
            assert [table.get_row_at(r)[0] for r in range(2)] == ["2", "1"]
            labels = [str(c.label) for c in table.columns.values()]
            assert labels[:3] == ["#", "Title", "Best"] and labels[-2:] == ["LEARN", "ROBOT ▼1"]
            app.sort_areas("ROBOT")  # again: ascending
            assert [table.get_row_at(r)[0] for r in range(2)] == ["1", "2"]
            detail = str(app.query_one("#area-detail").render())
            assert "#1  Multiagent learning" in detail and "LEARN" in detail
            assert "Multiagent learning" in detail.split("LEARN", 1)[1]  # the nearest topic
            await pilot.press("h")
            app.screen.query_one(SelectionList).deselect("LEARN")
            await pilot.click("#marks-apply")
            labels = [str(c.label) for c in table.columns.values()]
            assert "LEARN" not in labels and labels[-1] == "ROBOT ▲1"
            assert core.areas_view() == {"hidden": ["LEARN"], "sort": [("ROBOT", False)]}

    asyncio.run(scenario())


def test_labels_and_rubric_edits_report_what_they_change(monkeypatch):
    from textual.widgets import OptionList, TextArea

    from aamas_review_monitor import areas, papers
    from tests.test_models import FakeEndpoint, resolves_to
    from tests.test_scores import CONFIG as AREAS_CONFIG
    from tests.test_scores import PAGE, RECORDS

    FakeEndpoint(monkeypatch)
    resolves_to(monkeypatch, "127.0.0.1")
    monkeypatch.setattr(areas, "DIR_RUBRICS_DEFAULT", core.DIR_DATA / "none")
    for rubric in areas.parse(PAGE, "https://example.org/call"):
        areas.save(rubric, core.DIR_RUBRICS)
    papers.save(RECORDS, core.DIR_PAPERS, [])
    core.DIR_SNAPSHOTS.mkdir(parents=True)
    snapshot = {"taken_at": "2026-11-11T08:00:00", "papers": [paper(1), paper(2)]}
    (core.DIR_SNAPSHOTS / "2026-11-11T080000.json").write_text(json.dumps(snapshot))
    config = AREAS_CONFIG | {"areas_include": ["title", "abstract"]}

    async def scenario():
        app = Monitor(config)
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.press("t", "t", "t")
            await done(app, pilot, lambda: app.area_results is not None)
            await pilot.press("k")
            await pilot.click("#marks-apply")
            await done(app, pilot, lambda: bool(app.area_results))
            app.sort_areas("number")
            table = app.query_one("#areas")
            await pilot.press("y")  # #1: its best area, LEARN
            await done(app, pilot, lambda: app.labels == {1: "LEARN"})
            assert table.get_row_at(0)[4].plain == "LEARN"  # #, Title, Best, Margin, Label
            await pilot.press("down", "b")  # #2: pick LEARN, its second area
            options = app.screen.query_one(OptionList)
            assert options.get_option_at_index(0).id == "ROBOT"
            options.highlighted = 1
            await pilot.press("enter")
            await done(app, pilot, lambda: app.labels == {1: "LEARN", 2: "LEARN"})
            assert "labels: best area 1/2" in str(app.query_one("#area-detail").render())

            await pilot.press("t")  # Rubrics: LEARN in the editor
            editor = app.query_one("#rubric-editor", TextArea)
            assert app.rubric_code == "LEARN" and "Multiagent learning" in editor.text
            editor.load_text(editor.text.replace("- Multiagent learning", "- area: ["))
            await pilot.press("ctrl+s")
            assert "not saved" in str(app.query_one("#rubric-note").render())
            editor.load_text(
                areas.dump(app.rubrics["LEARN"]).replace(
                    "- Multiagent learning", "- Multiagent learning\n- Robots in swarms"
                )
            )
            assert "LEARN" in app.rubric_drafts
            await pilot.press("ctrl+s")
            await done(app, pilot, lambda: "changed" in str(app.query_one("#rubric-note").render()))
            note = str(app.query_one("#rubric-note").render())
            assert "Fixed: #2; broken: none" in note and app.rubric_drafts == {}
            assert areas.load(core.DIR_RUBRICS)["LEARN"]["topics"][-1] == "Robots in swarms"
            assert app.query_one("#rubrics").get_row_at(0)[1] == "yours, edited"
            editor.load_text("anything")
            await pilot.press("ctrl+r")
            assert "Robots in swarms" in editor.text
            app.query_one("#rubrics").move_cursor(row=1)  # ROBOT: saving it stays on it
            await pilot.pause()
            editor.load_text(editor.text.replace("exemplars: []", "exemplars:\n- Drones"))
            await pilot.press("ctrl+s")
            await done(
                app,
                pilot,
                lambda: "ROBOT saved. What" in str(app.query_one("#rubric-note").render()),
            )
            assert app.rubric_code == "ROBOT" and "code: ROBOT" in editor.text
            editor.focus()
            await pilot.press("escape", "t")  # out of the editor, then to the next tab
            assert app.query_one("#tabs").active == "papers" and "code: ROBOT" in editor.text

    asyncio.run(scenario())
