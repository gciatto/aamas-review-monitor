"""Textual front end: the same checks and report as the CLI, as a filterable, sortable table."""

import logging
import os
import webbrowser
from collections.abc import Callable, Iterable
from datetime import date
from functools import partial, wraps
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Static,
    TabbedContent,
    TabPane,
)

from aamas_review_monitor import core, documents, logger, outreach, papers
from aamas_review_monitor.checks import (
    GREEN,
    ICONS,
    RED,
    YELLOW,
    Issue,
    green_rows,
    matches,
    phase,
    summary,
)
from aamas_review_monitor.screens import (
    Actions,
    Attachment,
    Busy,
    CommentForm,
    DialogLog,
    Email,
    Legend,
    Login,
    Paper,
    Review,
    Templates,
    details,
    sent_lines,
)

IGNORED, GRAY = "⚪", "grey50"  # how ignored issues look
RANKS = {ICONS[RED]: 0, ICONS[YELLOW]: 1, ICONS[GREEN]: 2, IGNORED: 3}
MARK = "✔"
Job = Callable[[Any, Callable[[int, int], None]], Any]  # (client, progress) -> result


# The command palette (ctrl+p): (title, help ending with the key, action), the same actions
# as the key bindings. Actions on papers apply to the marked ones, else to the selected one.
COMMANDS = [
    ("Sync with OpenReview", "Fetch papers, reviews and a new snapshot  [s]", "sync"),
    ("Reload", "Re-read the cached snapshots and results  [r]", "reload"),
    ("Filter", "By SPC, #paper, issue text or color  [f]", "focus('filter')"),
    ("Show or hide green papers", "Papers without issues  [g]", "toggle_green"),
    ("Ignore or count again", "The selected issue: gray, uncounted, left out of emails and comments  [x]", "ignore"),
    ("Mark or unmark", "The selected paper (or SPC), to act on several at once  [space]", "mark"),
    ("Mark all shown", "Every paper (or SPC) shown; if all are marked, clears the marks  [*]", "mark_all"),
    ("Actions", "What can be done on the marked papers or SPCs, else on the selected one  [a]", "actions"),
    ("Paper details", "Metadata, checks, anonymous reviews of the selected paper  [d]", "details"),
    ("Open on OpenReview", "The selected paper's forum, in the browser  [o]", "open"),
    ("Open the PDF", "The selected paper's PDF in your default viewer, downloading it if needed  [v]", "view_pdf"),
    ("Open the paper's folder", "Where its data is kept: record, PDF, supplementary, text, results  [w]", "folder"),
    ("PDF", "One paper: path, text, open; marked papers: download the missing ones  [p]", "download('field_pdf')"),
    ("Supplementary material: file tree", "One paper: path, file tree, open; marked papers: download  [u]", "download('field_supplementary')"),
    ("Inspect", "Document checks, downloading what is missing  [i]", "inspect"),
    ("Templated email", "From a template, to SPCs (SPCs tab) or to the papers' people  [m]", "mail"),
    ("Comment", "Post each paper's issues on its forum (one paper: editable)  [c]", "comment"),
    ("Email", "Free-form, to reviewers, late reviewers or SPCs, one message per paper  [e]", "email"),
    ("Switch tab", "Papers, SPCs, History  [t]", "switch_tab"),
    ("Legend", "What each check verifies, with the current thresholds  [l]", "legend"),
]  # fmt: skip


# Actions that work on the main table, so only while it is on screen
TABLE_ACTIONS = {a.split("(")[0] for _, _, a in COMMANDS}
# What the action menu offers, per tab
MENU = {
    "papers": [
        "details", "open", "view_pdf", "folder", "download('field_pdf')", "download('field_supplementary')",
        "inspect", "mail", "comment", "email",
    ],
    "spcs-tab": ["mail"],
}  # fmt: skip


def mounted(handler: Callable) -> Callable:
    """Skips a panel handler while the main screen is being built or torn down: Textual may
    deliver resize and row-highlight messages then, when the widgets they update are missing,
    and an exception in a handler would close the app."""

    @wraps(handler)
    def guarded(self: "Monitor", *args: Any) -> None:
        try:
            handler(self, *args)
        except NoMatches:
            pass

    return guarded


def numbered(numbers: list[int]) -> str:
    shown = ", ".join(f"#{n}" for n in numbers[:8]) + (", …" if len(numbers) > 8 else "")
    return f"paper #{numbers[0]}" if len(numbers) == 1 else f"{len(numbers)} papers ({shown})"


class Monitor(App):
    TITLE = "AAMAS Review Monitor"
    # Actions on papers apply to the marked ones (space, *), else to the selected one; the
    # footer shows the few keys needed to get anywhere, the menu (a) the rest with their keys
    BINDINGS = [
        # in footer order: what is used most comes first, as narrow terminals cut the tail
        ("f", "focus('filter')", "Filter"),
        ("space", "mark", "Mark"),
        ("asterisk", "mark_all", "Mark all"),
        ("a", "actions", "Actions"),
        ("t", "switch_tab", "Tab"),
        ("s", "sync", "Sync"),
        ("l", "legend", "Legend"),
        ("g", "toggle_green", "🟢 on/off"),
        ("x", "ignore", "Ignore"),
        ("q", "quit", "Quit"),
        Binding("d", "details", "Details", show=False),
        Binding("o", "open", "Browser", show=False),
        Binding("v", "view_pdf", "Open PDF", show=False),
        Binding("w", "folder", "Paper folder", show=False),
        Binding("p", "download('field_pdf')", "PDF", show=False),
        Binding("u", "download('field_supplementary')", "Supplementary", show=False),
        Binding("i", "inspect", "Inspect", show=False),
        Binding("m", "mail", "Templated email", show=False),
        Binding("c", "comment", "Comment", show=False),
        Binding("e", "email", "Email", show=False),
        Binding("r", "reload", "Reload", show=False),
    ]

    def __init__(self, config: dict) -> None:
        super().__init__()
        self.config = config
        self.issues: list[Issue] = []  # plus one GREEN row per paper without issues
        self.ignored: set[tuple[int, str]] = set()  # (number, code) the user ignores
        self.hide_green = False
        # papers whose current PDF went through the document checks
        self.inspected: set[int] = set()
        self.latest: dict | None = None  # the latest snapshot
        self.papers: list[dict] = []  # the latest snapshot's
        self.sent: list[dict] = []  # the history, newest first
        self.marked: set[int] = set()  # papers
        self.marked_spcs: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="summary")
        with TabbedContent(id="tabs"):
            with TabPane("Papers", id="papers"):
                with Horizontal():
                    with Vertical(id="queue"):
                        yield Input(
                            placeholder="Filter by SPC, paper # or issue (f to focus, Enter to apply)",
                            id="filter",
                        )
                        yield DataTable(id="issues", cursor_type="row", zebra_stripes=True)
                    yield VerticalScroll(Static(id="paper-detail"), id="paper-panel")
            with TabPane("SPCs", id="spcs-tab"):
                with Horizontal():
                    yield DataTable(id="spcs", cursor_type="row", zebra_stripes=True)
                    yield VerticalScroll(Static(id="spc-issues"), id="spc-panel")
            with TabPane("History", id="history-tab"):
                with Horizontal():
                    yield DataTable(id="history", cursor_type="row", zebra_stripes=True)
                    yield VerticalScroll(Static(id="history-entry"), id="history-panel")
        yield Footer(compact=True)

    DEFAULT_CSS = (
        "#queue { width: 3fr; } #paper-panel { width: 2fr; padding: 0 1; }"
        " #spcs { width: 1fr; } #spc-panel { width: 2fr; padding: 0 1; }"
        " #history { width: 3fr; } #history-panel { width: 2fr; padding: 0 1; }"
    )
    PANEL_WIDTH_MIN = 120  # narrower terminals keep the whole width for the queue

    def on_mount(self) -> None:
        issues = self.query_one("#issues", DataTable)
        self.mark_column = issues.add_column("", width=1)  # empty until something is marked
        issues.add_columns("Status", "Paper", "SPC", "Issue")
        self.query_one("#history", DataTable).add_columns("", "When", "Kind", "Via", "To")
        spcs = self.query_one("#spcs", DataTable)
        self.spc_mark_column = spcs.add_column("", width=1)
        spcs.add_columns("SPC", "Papers", "Open", ICONS[RED], ICONS[YELLOW])
        self.action_reload()
        issues.focus()

    @mounted
    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#paper-panel").display = event.size.width >= self.PANEL_WIDTH_MIN
        self.show_paper()

    def action_reload(self) -> None:
        state = core.current(self.config)
        self.latest, self.inspected, self.ignored = state.latest, state.inspected, state.ignored
        self.papers = state.latest["papers"] if state.latest else []
        if state.latest is None:
            self.issues = []
            text = f"No snapshots in {core.DIR_SNAPSHOTS}: press s to sync"
        else:
            self.issues = state.issues + green_rows(state.latest, state.issues)
            lines = summary(
                state.latest, self.config, state.previous, state.documents, state.ignored
            )
            text = "\n".join(lines)
            for severity, icon in ICONS.items():
                text = text.replace(f" {severity}", f" {icon}")
        fresh = core.freshness(self.latest, self.config)
        header = Text(f"{phase(self.config, date.today())}  ·  ", "bold")
        header.append(fresh, "bold yellow" if fresh.startswith("⚠") else "")
        self.query_one("#summary", Static).update(Text.assemble(header, "\n", text))
        self.fill()
        self.fill_spcs()
        self.fill_history()

    def fill(self) -> None:
        table = self.query_one("#issues", DataTable)
        table.clear()
        needle = self.query_one("#filter", Input).value.lower()
        for n, i in enumerate(self.issues):
            if matches(i, needle) and not (self.hide_green and i.severity == GREEN):
                spcs = ", ".join(i.spcs) or "(no SPC)"
                mark = MARK if i.number in self.marked else ""
                if (i.number, i.code) in self.ignored:  # still listed, in gray
                    gray = [Text(str(c), GRAY) for c in (i.number, spcs, i.message)]
                    table.add_row(mark, IGNORED, *gray, key=str(n))
                else:
                    table.add_row(mark, ICONS[i.severity], i.number, spcs, i.message, key=str(n))
        self.show_paper()

    def active(self) -> list[Issue]:
        """The issues not ignored: what emails and comments are about."""
        return [i for i in self.issues if (i.number, i.code) not in self.ignored]

    def action_ignore(self) -> None:
        """Ignores the selected issue, or counts it again if it is ignored."""
        issue = self.selected()
        if self.query_one(TabbedContent).active != "papers" or issue is None:
            return
        if issue.severity == GREEN:
            self.notify("Nothing to ignore: every check passes")
            return
        key, table = (issue.number, issue.code), self.query_one("#issues", DataTable)
        undo, row = key in self.ignored, table.cursor_row
        core.ignore({key}, undo)
        self.action_reload()
        table.move_cursor(row=row)
        what = "counted again" if undo else "ignored: gray, left out of emails and comments"
        self.notify(f"#{issue.number} {issue.message}: {what}")

    def by_spc(self) -> dict[str, list[Issue]]:
        """Open issues per SPC, every SPC of the snapshot included."""
        found: dict[str, list[Issue]] = {
            spc: [] for p in self.papers for spc in p["spcs"] or ["(no SPC)"]
        }
        for i in self.active():
            if i.severity != GREEN:
                for spc in i.spcs or ("(no SPC)",):
                    found.setdefault(spc, []).append(i)
        return found

    def fill_history(self) -> None:
        self.sent = papers.history(core.FILE_HISTORY)
        table = self.query_one("#history", DataTable)
        table.clear()
        for n, e in enumerate(self.sent):
            ok = ICONS[GREEN] if e["status"] == "sent" else ICONS[RED]
            when = e["at"][:16].replace("T", " ")
            table.add_row(ok, when, e["kind"], e["via"], e["to"], key=str(n))
        self.show_history()

    @on(DataTable.RowHighlighted, "#history")
    @mounted
    def show_history(self) -> None:
        table, text = self.query_one("#history", DataTable), Text()
        if table.row_count:
            e = self.sent[
                int(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value or 0)
            ]
            text.append(f"{e['kind'].title()} {e['status']}, {e['at']}\n", "bold")
            text.append(f"To: {e['to']} ({', '.join(e['recipients'])})\n")
            text.append(f"Via #{e['via']}, about {', '.join(f'#{n}' for n in e['papers'])}\n")
            if e["template"]:
                text.append(f"Template: {e['template']}\n")
            text.append(f"\n{e['subject']}\n\n", "bold cyan")
            text.append(e["body"])
        else:
            text.append("Nothing sent from this app yet", "italic")
        self.query_one("#history-entry", Static).update(text)

    def fill_spcs(self) -> None:
        table = self.query_one("#spcs", DataTable)
        table.clear()
        count = {
            spc: sum(spc in (p["spcs"] or ["(no SPC)"]) for p in self.papers)
            for spc in self.by_spc()
        }
        for spc, mine in sorted(
            self.by_spc().items(),
            key=lambda kv: (-sum(i.severity == RED for i in kv[1]), -len(kv[1]), kv[0]),
        ):
            reds = sum(i.severity == RED for i in mine)
            mark = MARK if spc in self.marked_spcs else ""
            numbers = len({i.number for i in mine})
            table.add_row(mark, spc, count[spc], numbers, reds, len(mine) - reds, key=spc)
        self.show_spc()

    def selected_spc(self) -> str | None:
        table = self.query_one("#spcs", DataTable)
        if not table.row_count:
            return None
        return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)

    @on(DataTable.RowHighlighted, "#spcs")
    @mounted
    def show_spc(self) -> None:
        spc, text = self.selected_spc(), Text()
        mine = self.by_spc().get(spc or "", [])
        if spc:
            text.append(f"{spc}\n", "bold")
            numbers = [p["number"] for p in self.papers if spc in (p["spcs"] or ["(no SPC)"])]
            text.append(f"{len(numbers)} papers: {', '.join(f'#{n}' for n in sorted(numbers))}\n\n")
        for number in sorted({i.number for i in mine}):
            text.append(f"#{number}\n", "bold cyan")
            for i in (i for i in mine if i.number == number):
                text.append(f"  {ICONS[i.severity]} {i.message}\n")
        if spc and not mine:
            text.append(f"{ICONS[GREEN]} nothing to do\n")
        theirs = [e for e in self.sent if e["to"] == spc]
        if spc and theirs:
            text.append("\nSent to them from this app\n", "bold underline")
            sent_lines(text, theirs)
        self.query_one("#spc-issues", Static).update(text)

    def action_switch_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        order = {"papers": ("spcs-tab", "#spcs"), "spcs-tab": ("history-tab", "#history")}
        tabs.active, table = order.get(tabs.active, ("papers", "#issues"))
        self.query_one(table, DataTable).focus()

    def sent_notice(self, failures: list[str], total: int, verb: str = "Sent") -> None:
        """After sending: the outcome, and the history tab updated."""
        self.fill_history()
        self.fill_spcs()
        summary = f"{verb} {total - len(failures)} of {total}"
        self.notify(
            "\n".join([*failures, summary]), severity="error" if failures else "information"
        )

    def review_then(
        self,
        review: "tuple[list[str], list[outreach.Item]]",
        field: str,
        limits: tuple[int, int] | None,
        verb: str,
        go: "Callable[[list[outreach.Item]], None]",
    ) -> None:
        """Shows everything about to go out, editable; calls `go` with the edited items only
        after a typed SEND."""

        def reviewed(items: "list[outreach.Item] | None") -> None:
            if items is None:
                self.notify(f"Nothing {verb.lower()}")
            else:
                go(items)

        self.push_screen(Review(*review, field, limits), reviewed)

    def notes(self) -> list[str]:
        return [core.freshness(self.latest, self.config)]

    def send(self, drafts: list[papers.Draft], unreachable: list[str], what: str = "") -> None:
        def go(items: "list[outreach.Item]") -> None:
            edited = [d._replace(subject=i.title, body=i.text) for d, i in zip(drafts, items)]
            self.online(
                f"Sending {len(edited)} messages{what}…",
                lambda client, progress: papers.deliver(
                    client, edited, progress, core.FILE_HISTORY
                ),
                lambda failures: self.sent_notice(failures, len(edited)),
            )

        review = outreach.review(drafts, unreachable, self.sent, self.notes())
        self.review_then(review, "Subject", None, "Sent", go)

    def action_comment(self) -> None:
        if not (numbers := self.scope()):
            return

        def compose(spcs_read: bool | None) -> None:
            if spcs_read is None:
                return
            found, skipped = outreach.comments(
                self.active(), core.records(), set(numbers), spcs_read, self.config
            )
            if not found:
                self.notify("\n".join([*skipped, "Nothing to comment on"]))
                return

            def go(items: "list[outreach.Item]") -> None:
                edited = [c._replace(title=i.title, text=i.text) for c, i in zip(found, items)]
                self.online(
                    f"Posting {len(edited)} comments…",
                    lambda client, progress: papers.post_comments(
                        client, edited, progress, core.FILE_HISTORY
                    ),
                    lambda failures: self.sent_notice(failures, len(edited), "Posted"),
                )

            review = outreach.review_comments(found, skipped, self.sent, self.notes())
            self.review_then(review, "Title", outreach.COMMENT_LIMITS, "Posted", go)

        self.push_screen(CommentForm(numbered(numbers)), compose)

    def action_mail(self) -> None:
        spcs: set[str] | None = None
        numbers: set[int] | None = None
        if self.on_spcs():
            if not (chosen_spcs := self.spc_scope()):
                return
            spcs = set(chosen_spcs)
            scope = chosen_spcs[0] if len(spcs) == 1 else f"{len(spcs)} marked SPCs"
        else:
            if not (shown := self.scope()):
                return
            numbers, scope = set(shown), numbered(shown)

        def chosen(template: outreach.Template | None) -> None:
            if template is None:
                return
            latest = self.latest
            today = date.fromisoformat(latest["taken_at"][:10]) if latest else date.today()
            records = core.records()
            drafts, unreachable = outreach.compose(
                template, self.active(), records, self.config, today, spcs, numbers
            )
            if not drafts:
                self.notify("\n".join([*unreachable, f"Nothing to send with {template.name}"]))
                return

            self.send(drafts, unreachable, f" ({template.name})")

        self.push_screen(Templates(scope), chosen)

    def action_legend(self) -> None:
        self.push_screen(Legend(self.config))

    def action_toggle_green(self) -> None:
        self.hide_green = not self.hide_green
        self.fill()

    @on(Input.Changed, "#filter")
    def filter_changed(self) -> None:
        self.fill()

    @on(Input.Submitted, "#filter")
    def filter_submitted(self) -> None:
        self.query_one("#issues", DataTable).focus()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        event.data_table.sort(
            event.column_key,
            key=lambda v: (
                v
                if isinstance(v, int)
                else int(str(v))  # a gray paper number
                if str(v).isdigit()
                else RANKS.get(str(v), str(v))
            ),
        )

    @on(DataTable.RowSelected, "#issues")
    def issue_selected(self) -> None:
        self.action_details()

    def selected(self) -> Issue | None:
        table = self.query_one("#issues", DataTable)
        if not table.row_count:
            return None
        row = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return self.issues[int(row.value or 0)]

    def action_open(self) -> None:
        if issue := self.selected():
            webbrowser.open(issue.url)

    def action_details(self) -> None:
        if issue := self.selected():
            self.show_details(issue.number)

    def paper_text(self, number: int) -> Text:
        mine = [i for i in self.issues if i.number == number and i.severity != GREEN]
        try:
            (record,) = core.records(number)
        except FileNotFoundError:
            record = None
        inspected = number in self.inspected
        sent = [e for e in self.sent if papers.about(e, number)]
        return details(number, record, self.config, mine, inspected, sent, self.ignored)

    def show_details(self, number: int) -> None:
        self.push_screen(Paper(self.paper_text(number)))

    @on(DataTable.RowHighlighted, "#issues")
    @mounted
    def show_paper(self) -> None:
        """The selected paper's details, beside the queue when the terminal is wide enough."""
        panel = self.query_one("#paper-panel")
        if panel.display:
            issue = self.selected()
            text = self.paper_text(issue.number) if issue else Text("No paper", "italic")
            self.query_one("#paper-detail", Static).update(text)

    def shown(self) -> list[int]:
        rows = self.query_one("#issues", DataTable).rows
        return sorted({self.issues[int(k.value or 0)].number for k in rows})

    def scope(self) -> list[int]:
        """The marked papers, else the selected one."""
        if self.marked:
            return sorted(self.marked)
        issue = self.selected()
        return [issue.number] if issue else []

    def spc_scope(self) -> list[str]:
        """The marked SPCs, else the selected one."""
        spc = self.selected_spc()
        return sorted(self.marked_spcs) if self.marked_spcs else [spc] if spc else []

    def on_spcs(self) -> bool:
        return self.query_one(TabbedContent).active == "spcs-tab"

    def show_marks(self) -> None:
        """Updates the mark column in place, keeping the cursor where it is."""
        table = self.query_one("#issues", DataTable)
        for key in table.rows:
            mark = MARK if self.issues[int(key.value or 0)].number in self.marked else ""
            table.update_cell(key, self.mark_column, mark)
        spcs = self.query_one("#spcs", DataTable)
        for key in spcs.rows:
            mark = MARK if key.value in self.marked_spcs else ""
            spcs.update_cell(key, self.spc_mark_column, mark)

    def action_mark(self) -> None:
        if self.on_spcs():
            if spc := self.selected_spc():
                self.marked_spcs ^= {spc}
        elif issue := self.selected():
            self.marked ^= {issue.number}
        self.show_marks()

    def action_mark_all(self) -> None:
        if self.on_spcs():
            shown = {str(k.value) for k in self.query_one("#spcs", DataTable).rows}
            self.marked_spcs = set() if shown <= self.marked_spcs else self.marked_spcs | shown
            count, what = len(self.marked_spcs), "SPCs"
        else:
            papers_shown = set(self.shown())
            self.marked = set() if papers_shown <= self.marked else self.marked | papers_shown
            count, what = len(self.marked), "papers"
        self.show_marks()
        what = what[:-1] if count == 1 else what
        self.notify(f"{count} {what} marked" if count else "Marks cleared")

    def action_actions(self) -> None:
        tab = self.query_one(TabbedContent).active
        if tab not in MENU:
            self.notify("Nothing to act on in the history")
            return
        if tab == "spcs-tab":
            if not (spcs := self.spc_scope()):
                return
            scope = spcs[0] if len(spcs) == 1 else f"{len(spcs)} marked SPCs"
        else:
            if not (numbers := self.scope()):
                return
            scope = numbered(numbers)
        choices = [
            (title, help.rsplit("[", 1)[1].rstrip("]"), action)
            for title, help, action in COMMANDS
            if action in MENU[tab]
        ]

        def chosen(action: str | None) -> None:
            if action:
                self.call_later(self.run_action, action)

        self.push_screen(Actions(f"Act on {scope}", choices), chosen)

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        if screen.query("#issues"):  # the main screen, where the actions apply
            for title, help, action in COMMANDS:
                yield SystemCommand(title, help, partial(self.run_action, action))

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        # While a job runs, the UI only allows quitting; the table's actions need the table
        if isinstance(self.screen, Busy):
            return action == "quit"
        return action not in TABLE_ACTIONS or bool(self.screen.query("#issues"))

    def online(
        self,
        label: str,
        job: Job,
        done: Callable[[Any], object],
        credentials: Any = None,
        offline: bool = False,
    ) -> None:
        """Runs `job` in the background behind a Busy dialog, signing in first unless `offline`
        (then the job gets no client)."""
        busy = Busy(label)
        self.push_screen(busy)
        self.run_online(busy, label, job, done, credentials, offline)

    @work(thread=True)
    def run_online(
        self,
        busy: Busy,
        label: str,
        job: Job,
        done: Callable[[Any], object],
        credentials: Any,
        offline: bool,
    ) -> None:
        def progress(count: int, total: int) -> None:
            if core.INTERRUPT.is_set():
                raise core.Interrupted
            self.call_from_thread(busy.progress, count, total)

        core.INTERRUPT.clear()
        handler, level = DialogLog(self, busy), logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)  # per-paper steps go to the dialog, not the terminal
        try:
            client = None if offline else core.resume(self.config)
            if client is None and not offline:
                env = (os.environ.get("OPENREVIEW_USERNAME"), os.environ.get("OPENREVIEW_PASSWORD"))
                credentials = credentials or (env if all(env) else None)
                if credentials is None:
                    self.call_from_thread(busy.dismiss)
                    self.call_from_thread(self.ask_login, label, job, done)
                    return
                client = core.login(self.config, *credentials)
            result = job(client, progress)
        except core.Interrupted:
            self.call_from_thread(busy.dismiss)
            self.call_from_thread(self.action_reload)  # show what was done before stopping
            message = f"{label.rstrip('…')} interrupted: completed steps are kept"
            self.call_from_thread(self.notify, message, severity="warning")
            return
        except Exception as e:  # shown to the user; the app keeps running
            self.call_from_thread(busy.dismiss)
            self.call_from_thread(self.notify, f"{label} failed: {e}", severity="error")
            return
        finally:
            logger.removeHandler(handler)
            logger.setLevel(level)
        self.call_from_thread(busy.dismiss)
        self.call_from_thread(done, result)

    def ask_login(self, label: str, job: Job, done: Callable[[Any], object]) -> None:
        def signed_in(credentials: tuple[str, str] | None) -> None:
            if credentials:
                self.online(label, job, done, credentials)

        self.push_screen(Login(), signed_in)

    def action_sync(self) -> None:
        def done(result: tuple[Path, list[str]]) -> None:
            self.action_reload()
            self.notify("\n".join([*result[1], "Synced with OpenReview"]))

        self.online(
            "Syncing with OpenReview…",
            lambda client, progress: core.sync(self.config, client, progress),
            done,
        )

    def with_attachment(self, number: int, key: str, then: Callable[[Path], object]) -> None:
        """Calls `then` with a paper's attachment, downloading it first only if needed."""
        field = self.config[key]
        try:
            (record,) = core.records(number)
        except FileNotFoundError:
            self.notify(f"#{number} is not cached: press s to sync", severity="error")
            return
        path = papers.attachment(record, field, core.DIR_PAPERS)
        if path is None:
            self.notify(f"#{number} has no {field}")
        elif path.is_file():
            then(path)
        else:
            self.online(
                f"Downloading {field} of #{number}…",
                lambda client, _: papers.download(client, record, field, core.DIR_PAPERS),
                then,
            )

    def action_view_pdf(self) -> None:
        if issue := self.selected():
            self.with_attachment(issue.number, "field_pdf", papers.os_open)

    def action_folder(self) -> None:
        if issue := self.selected():
            folder = core.DIR_PAPERS / str(issue.number)
            if folder.is_dir():
                papers.os_open(folder)
            else:
                self.notify(f"#{issue.number} is not cached: press s to sync", severity="error")

    def action_download(self, key: str) -> None:
        if not (numbers := self.scope()):
            return
        field = self.config[key]
        if len(numbers) == 1:  # one paper: show it, downloading first only if needed
            self.with_attachment(numbers[0], key, lambda path: self.push_screen(Attachment(path)))
            return

        def job(client: Any, progress: Callable[[int, int], None]) -> tuple[int, list[str]]:
            records, found, failures = core.records(*numbers), 0, []
            progress(0, len(records))
            downloads = core.download_each(client, records, field)
            for count, (record, path, error) in enumerate(downloads, 1):
                if error:
                    failures.append(f"#{record['number']}: {error}")
                    logger.error("#%s: download failed: %s", record["number"], error)
                else:
                    found += path is not None
                    logger.debug("#%s: %s", record["number"], path.name if path else f"no {field}")
                progress(count, len(records))  # may stop the job here
            return found, failures

        def done(result: tuple[int, list[str]]) -> None:
            found, failures = result
            summary = f"{found} of {len(numbers)} papers have {field}: cached"
            self.notify(
                "\n".join([*failures, summary]), severity="error" if failures else "information"
            )

        self.online(f"Downloading {field} of {len(numbers)} papers…", job, done)

    def action_inspect(self) -> None:
        if not (numbers := self.scope()):
            return
        try:
            records = core.records(*numbers)
        except FileNotFoundError as e:
            self.notify(f"Not cached: {e.filename}. Press s to sync", severity="error")
            return

        def job(client: Any, progress: Callable[[int, int], None]) -> list[str]:
            failures = []
            progress(0, len(records))
            results = core.inspect_each(records, self.config, lambda: client)
            for count, (record, found, error) in enumerate(results, 1):
                if error:
                    failures.append(f"#{record['number']}: {error}")
                    logger.error("#%s: not inspected: %s", record["number"], error)
                else:
                    logger.debug("#%s: %d document issues", record["number"], len(found))
                progress(count, len(records))  # may stop the job here
            return failures

        def done(failures: list[str]) -> None:
            self.action_reload()
            ok = len(records) - len(failures)
            self.notify("\n".join([*failures, f"Inspected {ok} of {len(records)} papers"]))
            if len(numbers) == 1 and not failures:
                self.show_details(numbers[0])

        offline = all(documents.downloaded(r, self.config, core.DIR_PAPERS) for r in records)
        label = f"Inspecting {numbered(numbers)}…"
        self.online(label, job, done, offline=offline)

    def action_email(self) -> None:
        if not (numbers := self.scope()):
            return

        def review(form: dict | None) -> None:
            if not form:
                return
            try:
                drafts, unreachable = outreach.direct(core.records(*numbers), **form)
            except FileNotFoundError as e:
                self.notify(f"Not cached: {e.filename}. Press s to sync", severity="error")
                return
            if not drafts:
                self.notify(f"No {form['role']} to email")
                return
            self.send(drafts, unreachable)

        self.push_screen(Email(numbered(numbers)), review)
