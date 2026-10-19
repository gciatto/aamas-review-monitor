"""Textual front end: the same checks and report as the CLI, as a filterable, sortable table."""

import logging
import os
import subprocess
import webbrowser
from collections.abc import Callable, Iterable
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
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
    summary,
)
from aamas_review_monitor.screens import (
    Attachment,
    Busy,
    CommentForm,
    Confirm,
    DialogLog,
    Email,
    Legend,
    Login,
    Paper,
    Templates,
    details,
    sent_lines,
)

RANKS = {ICONS[RED]: 0, ICONS[YELLOW]: 1, ICONS[GREEN]: 2}
Job = Callable[[Any, Callable[[int, int], None]], Any]  # (client, progress) -> result


# The command palette (ctrl+p): (title, help, action), the same actions as the key bindings
COMMANDS = [
    ("Sync with OpenReview", "Fetch papers, reviews and a new snapshot  [s]", "sync"),
    ("Reload", "Re-read the cached snapshots and results  [r]", "reload"),
    ("Filter", "By SPC, #paper, issue text or color  [f]", "focus('filter')"),
    ("Show or hide green papers", "Papers without issues  [g]", "toggle_green"),
    ("Paper details", "Metadata, checks, anonymous reviews of the selected paper  [d]", "details"),
    ("Open on OpenReview", "The selected paper's forum, in the browser  [o]", "open"),
    ("PDF", "Of the selected paper: path, text, open  [p]", "download('field_pdf')"),
    ("PDFs of all shown papers", "Download the missing ones  [P]", "download('field_pdf', True)"),
    ("Supplementary material", "Of the selected paper: path, files, open  [u]", "download('field_supplementary')"),
    ("Supplementary material of all shown papers", "Download the missing ones  [U]", "download('field_supplementary', True)"),
    ("Inspect", "Document checks of the selected paper, downloading what is missing  [i]", "inspect"),
    ("Inspect all shown papers", "Document checks, downloading what is missing  [I]", "inspect(True)"),
    ("Email", "Reviewers, late reviewers or SPCs of the selected paper  [e]", "email"),
    ("Email all shown papers", "Reviewers, late reviewers or SPCs, one message per paper  [E]", "email(True)"),
    ("Templated email", "From a template, to the selected SPC (SPCs tab) or paper's people  [m]", "mail"),
    ("Templated email to everyone shown", "From a template: all SPCs, or all shown papers' people  [M]", "mail(True)"),
    ("Comment", "Post the selected paper's issues on its forum, editable  [c]", "comment"),
    ("Comment on all shown papers", "Each paper's issues on its forum  [C]", "comment(True)"),
    ("Switch tab", "Papers, SPCs, History  [t]", "switch_tab"),
    ("Legend", "What each check verifies, with the current thresholds  [l]", "legend"),
]  # fmt: skip


# Actions that work on the main table, so only while it is on screen
TABLE_ACTIONS = {a.split("(")[0] for _, _, a in COMMANDS}


class Monitor(App):
    TITLE = "AAMAS Review Monitor"
    # Lowercase keys act on the selected paper; uppercase ones on all the papers shown, hidden
    # from the footer but named in their lowercase twin's label
    BINDINGS = [
        # in footer order: what is used most comes first, as narrow terminals cut the tail
        ("f", "focus('filter')", "Filter"),
        ("t", "switch_tab", "Tab"),
        ("d", "details", "Details"),
        ("s", "sync", "Sync"),
        ("p", "download('field_pdf')", "PDF (P: all)"),
        ("u", "download('field_supplementary')", "Supp. (U: all)"),
        ("i", "inspect", "Inspect (I: all)"),
        ("m", "mail", "Template (M: all)"),
        ("c", "comment", "Comment (C: all)"),
        ("e", "email", "Email (E: all)"),
        ("l", "legend", "Legend"),
        ("g", "toggle_green", "🟢 on/off"),
        ("o", "open", "Browser"),
        ("r", "reload", "Reload"),
        Binding("P", "download('field_pdf', True)", "All PDFs", show=False),
        Binding("U", "download('field_supplementary', True)", "All supplementary", show=False),
        Binding("E", "email(True)", "Email all", show=False),
        Binding("I", "inspect(True)", "Inspect all", show=False),
        Binding("M", "mail(True)", "Templated email to all", show=False),
        Binding("C", "comment(True)", "Comment on all", show=False),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, config: dict) -> None:
        super().__init__()
        self.config = config
        self.issues: list[Issue] = []  # plus one GREEN row per paper without issues
        self.hide_green = False
        # papers whose current PDF went through the document checks
        self.inspected: set[int] = set()
        self.latest: dict | None = None  # the latest snapshot
        self.papers: list[dict] = []  # the latest snapshot's
        self.sent: list[dict] = []  # the history, newest first

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="summary")
        with TabbedContent(id="tabs"):
            with TabPane("Papers", id="papers"):
                yield Input(
                    placeholder="Filter by SPC, paper # or issue (f to focus, Enter to apply)",
                    id="filter",
                )
                yield DataTable(id="issues", cursor_type="row", zebra_stripes=True)
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
        "#spcs { width: 1fr; } #spc-panel { width: 2fr; padding: 0 1; }"
        " #history { width: 3fr; } #history-panel { width: 2fr; padding: 0 1; }"
    )

    def on_mount(self) -> None:
        self.query_one("#issues", DataTable).add_columns("Status", "Paper", "SPC", "Issue")
        self.query_one("#history", DataTable).add_columns("", "When", "Kind", "Via", "To")
        self.query_one("#spcs", DataTable).add_columns(
            "SPC", "Papers", "Open", ICONS[RED], ICONS[YELLOW]
        )
        self.action_reload()
        self.query_one("#issues", DataTable).focus()

    def action_reload(self) -> None:
        state = core.current(self.config)
        self.latest, self.inspected = state.latest, state.inspected
        self.papers = state.latest["papers"] if state.latest else []
        if state.latest is None:
            self.issues = []
            text = f"No snapshots in {core.DIR_SNAPSHOTS}: press s to sync"
        else:
            self.issues = state.issues + green_rows(state.latest, state.issues)
            lines = summary(state.latest, self.config, state.previous, state.documents)
            text = "\n".join(lines)
            for severity, icon in ICONS.items():
                text = text.replace(f" {severity}", f" {icon}")
        self.query_one("#summary", Static).update(text)
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
                table.add_row(ICONS[i.severity], i.number, spcs, i.message, key=str(n))

    def by_spc(self) -> dict[str, list[Issue]]:
        """Open issues per SPC, every SPC of the snapshot included."""
        found: dict[str, list[Issue]] = {
            spc: [] for p in self.papers for spc in p["spcs"] or ["(no SPC)"]
        }
        for i in self.issues:
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
            table.add_row(
                spc, count[spc], len({i.number for i in mine}), reds, len(mine) - reds, key=spc
            )
        self.show_spc()

    def selected_spc(self) -> str | None:
        table = self.query_one("#spcs", DataTable)
        if not table.row_count:
            return None
        return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)

    @on(DataTable.RowHighlighted, "#spcs")
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

    def confirm_then(self, preview: str, label: str, job: Job, total: int, verb: str) -> None:
        """Shows everything about to go out; runs `job` only after a typed SEND."""

        def go(confirmed: bool | None) -> None:
            if not confirmed:
                self.notify(f"Nothing {verb.lower()}")
                return
            self.online(label, job, lambda failures: self.sent_notice(failures, total, verb))

        self.push_screen(Confirm(preview), go)

    def notes(self) -> list[str]:
        return [core.freshness(self.latest, self.config)]

    def send(self, drafts: list[papers.Draft], unreachable: list[str], what: str = "") -> None:
        self.confirm_then(
            outreach.preview(drafts, unreachable, self.sent, self.notes()),
            f"Sending {len(drafts)} messages{what}…",
            lambda client, progress: papers.deliver(client, drafts, progress, core.FILE_HISTORY),
            len(drafts),
            "Sent",
        )

    def action_comment(self, every: bool = False) -> None:
        if not (numbers := self.scope(every)):
            return
        records = core.records()
        draft, _ = outreach.comments(self.issues, records, set(numbers[:1]), True)
        text = draft[0].text if draft and not every else None
        if not every and not draft:
            self.notify(f"#{numbers[0]}: no open issues to comment on, or not cached")
            return

        def compose(form: tuple[bool, str | None] | None) -> None:
            if form is None:
                return
            spcs_read, edited = form
            found, skipped = outreach.comments(self.issues, records, set(numbers), spcs_read)
            if edited is not None:
                found = [c._replace(text=edited) for c in found]
            if not found:
                self.notify("\n".join([*skipped, "Nothing to comment on"]))
                return

            self.confirm_then(
                outreach.preview_comments(found, skipped, self.sent, self.notes()),
                f"Posting {len(found)} comments…",
                lambda client, progress: papers.post_comments(
                    client, found, progress, core.FILE_HISTORY
                ),
                len(found),
                "Posted",
            )

        scope = f"paper #{numbers[0]}" if len(numbers) == 1 else f"{len(numbers)} papers"
        self.push_screen(CommentForm(scope, text), compose)

    def action_mail(self, every: bool = False) -> None:
        on_spcs = self.query_one(TabbedContent).active == "spcs-tab"
        spcs: set[str] | None = None
        numbers: set[int] | None = None
        if on_spcs:
            spc = self.selected_spc()
            if not every and spc is None:
                return
            spcs = None if every else {spc or ""}
            scope = "every SPC" if every else spc
        else:
            if not (shown := self.scope(every)):
                return
            numbers = set(shown)
            scope = f"paper #{shown[0]}" if len(shown) == 1 else f"{len(shown)} papers"

        def chosen(template: outreach.Template | None) -> None:
            if template is None:
                return
            latest = self.latest
            today = date.fromisoformat(latest["taken_at"][:10]) if latest else date.today()
            records = core.records()
            drafts, unreachable = outreach.compose(
                template, self.issues, records, self.config, today, spcs, numbers
            )
            if not drafts:
                self.notify("\n".join([*unreachable, f"Nothing to send with {template.name}"]))
                return

            self.send(drafts, unreachable, f" ({template.name})")

        self.push_screen(Templates(scope or ""), chosen)

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
            key=lambda v: v if isinstance(v, int) else RANKS.get(str(v), str(v)),
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

    def show_details(self, number: int) -> None:
        mine = [i for i in self.issues if i.number == number and i.severity != GREEN]
        try:
            (record,) = core.records(number)
        except FileNotFoundError:
            record = None
        inspected = number in self.inspected
        sent = [e for e in self.sent if papers.about(e, number)]
        self.push_screen(Paper(details(number, record, self.config, mine, inspected, sent)))

    def scope(self, every: bool) -> list[int]:
        """The selected paper or, with `every`, all the papers shown."""
        if not every:
            issue = self.selected()
            return [issue.number] if issue else []
        rows = self.query_one("#issues", DataTable).rows
        return sorted({self.issues[int(k.value or 0)].number for k in rows})

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

    def action_download(self, key: str, every: bool = False) -> None:
        if not (numbers := self.scope(every)):
            return
        field = self.config[key]
        if not every:  # one paper: show it, downloading first only if needed
            try:
                (record,) = core.records(*numbers)
            except FileNotFoundError:
                self.notify(f"#{numbers[0]} is not cached: press s to sync", severity="error")
                return
            path = papers.attachment(record, field, core.DIR_PAPERS)
            if path is None:
                self.notify(f"#{numbers[0]} has no {field}")
            elif path.is_file():
                self.push_screen(Attachment(path))
            else:
                self.online(
                    f"Downloading {field} of #{numbers[0]}…",
                    lambda client, _: papers.download(client, record, field, core.DIR_PAPERS),
                    lambda path: self.push_screen(Attachment(path)),
                )
            return

        def job(client: Any, progress: Callable[[int, int], None]) -> tuple[int, list[str]]:
            records, found, failures = core.records(*numbers), 0, []
            for count, record in enumerate(records):
                progress(count, len(records))
                try:  # after the retries, one failure must not stop the other downloads
                    path = papers.download(client, record, field, core.DIR_PAPERS)
                    found += path is not None
                    logger.debug("#%s: %s", record["number"], path.name if path else f"no {field}")
                except Exception as e:
                    failures.append(f"#{record['number']}: {e}")
                    logger.error("#%s: download failed: %s", record["number"], e)
            progress(len(records), len(records))
            return found, failures

        def done(result: tuple[int, list[str]]) -> None:
            found, failures = result
            summary = f"{found} of {len(numbers)} papers have {field}: cached"
            self.notify(
                "\n".join([*failures, summary]), severity="error" if failures else "information"
            )

        self.online(f"Downloading {field} of {len(numbers)} papers…", job, done)

    def action_inspect(self, every: bool = False) -> None:
        if not (numbers := self.scope(every)):
            return
        try:
            records = core.records(*numbers)
        except FileNotFoundError as e:
            self.notify(f"Not cached: {e.filename}. Press s to sync", severity="error")
            return

        def job(client: Any, progress: Callable[[int, int], None]) -> list[str]:
            failures = []
            for count, record in enumerate(records):
                progress(count, len(records))
                try:
                    found = documents.inspect_paper(
                        record, self.config, core.DIR_PAPERS, lambda: client
                    )
                    logger.debug("#%s: %d document issues", record["number"], len(found))
                except (OSError, subprocess.CalledProcessError) as e:
                    failures.append(f"#{record['number']}: {e}")
                    logger.error("#%s: not inspected: %s", record["number"], e)
            progress(len(records), len(records))
            return failures

        def done(failures: list[str]) -> None:
            self.action_reload()
            ok = len(records) - len(failures)
            self.notify("\n".join([*failures, f"Inspected {ok} of {len(records)} papers"]))
            if not every and not failures:
                self.show_details(numbers[0])

        offline = all(documents.downloaded(r, self.config, core.DIR_PAPERS) for r in records)
        label = f"Inspecting {len(records)} papers…" if every else f"Inspecting #{numbers[0]}…"
        self.online(label, job, done, offline=offline)

    def action_email(self, every: bool = False) -> None:
        if not (numbers := self.scope(every)):
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

        scope = f"paper #{numbers[0]}" if len(numbers) == 1 else f"{len(numbers)} papers"
        self.push_screen(Email(scope), review)
