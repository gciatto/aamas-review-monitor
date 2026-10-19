"""Textual front end: the same checks and report as the CLI, as a filterable, sortable table."""

import logging
import os
import subprocess
import webbrowser
import zipfile
from collections.abc import Callable, Iterable
from functools import partial
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    ProgressBar,
    RichLog,
    Select,
    Static,
    TextArea,
    Tree,
)

from aamas_review_monitor import __main__ as cli
from aamas_review_monitor import logger
from aamas_review_monitor import documents, papers
from aamas_review_monitor.checks import (
    GREEN,
    RED,
    YELLOW,
    Issue,
    check,
    green_rows,
    legend,
    matches,
    passed,
    report,
)

ICONS = {RED: "🔴", YELLOW: "🟡", GREEN: "🟢"}
RANKS = {ICONS[RED]: 0, ICONS[YELLOW]: 1, ICONS[GREEN]: 2}
DIALOG_CSS = "align: center middle; & > Vertical { border: thick $accent; background: $surface;"
Job = Callable[[Any, Callable[[int, int], None]], Any]  # (client, progress) -> result


def details(
    number: int, record: dict | None, config: dict, issues: list[Issue], inspected: bool = False
) -> Text:
    """Colored metadata, checks (failed and passed) and anonymous reviews of one paper;
    passed document checks only if they were run (`inspected`)."""
    text = Text()

    def section(title: str) -> None:
        text.append(f"\n{title}\n", "bold underline")

    def pairs(items: list[tuple[str, str]]) -> None:
        for key, value in items:
            text.append(f"{key}: ", "bold cyan")
            text.append(f"{value}\n")

    text.append(f"Paper #{number}\n", "bold")
    if record is None:
        text.append("Not cached: press s to sync\n", "italic")
    else:
        text.append(f"{config['url_forum']}{record['id']}\n", "underline blue")
        pairs(papers.metadata_fields(record, config))
    section("Checks")
    for i in issues:
        text.append(f"{ICONS[i.severity]} {i.message}\n")
    for label in passed(issues):
        text.append(f"{ICONS[GREEN]} {label}\n")
    if inspected:
        for label in passed(issues, documents.DOCUMENT_CHECKS):
            text.append(f"{ICONS[GREEN]} {label}\n")
    else:
        text.append("Document checks not run: press i\n", "italic")
    if record is not None:
        blocks = papers.review_blocks(record)
        section("Reviews and meta-reviews" if blocks else "No reviews yet")
        for title, items in blocks:
            text.append(f"\n{title}\n", "bold magenta")
            pairs(items)
    return text


class Paper(Screen):
    """Metadata, issues and anonymous reviews of one paper, from the local cache."""

    BINDINGS = [("escape,q", "app.pop_screen", "Back")]

    def __init__(self, text: Text) -> None:
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(Static(self.text))
        yield Footer()


class Attachment(ModalScreen):
    """A downloaded attachment: its path, OS actions, and its contents (zip tree or PDF text)."""

    DEFAULT_CSS = "Attachment {" + DIALOG_CSS + " width: 90%; height: 90%; padding: 0 1; } }"
    BINDINGS = [
        ("escape,q", "dismiss", "Back"),
        ("c", "folder", "Show in folder"),
        ("v", "view", "Open with default app"),
        ("y", "copy", "Copy path"),
    ]

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(str(self.path), "bold cyan"), id="path")
            yield self.contents()
        yield Footer()

    def contents(self) -> Widget:
        try:
            if self.path.suffix.lower() == ".zip":
                return self.zip_tree()
            if self.path.suffix.lower() == ".pdf":
                return VerticalScroll(Static(Text(papers.pdf_text(self.path)), id="text"))
        except (OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as e:
            return Static(Text(f"Cannot show the contents: {e}", "italic red"))
        return Static(Text("No preview for this file type", "italic"))

    def zip_tree(self) -> Tree:
        tree: Tree[None] = Tree(self.path.name, id="tree")
        tree.root.expand()
        nodes = {"": tree.root}
        for info in papers.zip_entries(self.path):
            parts = info.filename.rstrip("/").split("/")
            for depth in range(1, len(parts) + 1):
                key, parent = "/".join(parts[:depth]), nodes["/".join(parts[: depth - 1])]
                if key in nodes:
                    continue
                if depth == len(parts) and not info.is_dir():
                    nodes[key] = parent.add_leaf(f"{parts[-1]}  ({info.file_size:,} bytes)")
                else:
                    nodes[key] = parent.add(parts[depth - 1], expand=True)
        return tree

    def action_folder(self) -> None:
        papers.os_open(self.path, reveal=True)

    def action_view(self) -> None:
        papers.os_open(self.path)

    def action_copy(self) -> None:
        self.app.copy_to_clipboard(str(self.path))
        self.notify("Path copied")


class Legend(ModalScreen):
    """What the icons mean and what each check verifies, from the checks' docstrings."""

    DEFAULT_CSS = "Legend {" + DIALOG_CSS + " width: 90%; height: 85%; padding: 1 2; } }"
    BINDINGS = [("escape,q,l", "dismiss", "Close")]

    def __init__(self, config: dict) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        text = Text()
        text.append("Status\n", "bold underline")
        text.append(f"{ICONS[RED]} serious, needs you   {ICONS[YELLOW]} needs SPC attention   ")
        text.append(f"{ICONS[GREEN]} no process issue\n")
        sections = [
            ("Paper checks", None),
            ("Document checks (press i)", documents.DOCUMENT_CHECKS),
        ]
        for title, checks in sections:
            text.append(f"\n{title}\n", "bold underline")
            for code, label, description in legend(self.config, checks):
                text.append(f"\n{label}", "bold cyan")
                text.append(f"  {code}\n", "dim")
                text.append(f"{description}\n")
        text.highlight_words([RED], "bold red")
        text.highlight_words([YELLOW], "bold yellow")
        with Vertical():
            yield VerticalScroll(Static(text, id="legend"))


class Busy(ModalScreen):
    """Blocks the UI while a background job runs: progress, its log (steps, retries, waits,
    failures), and a way to interrupt it."""

    DEFAULT_CSS = (
        "Busy {" + DIALOG_CSS + " width: 90%; height: auto; padding: 1 2; } }"
        " Busy RichLog { height: 12; border: round $panel; } Busy Button { margin-top: 1; }"
    )
    BINDINGS = [("escape", "interrupt", "Interrupt")]
    STYLES = {logging.WARNING: "yellow", logging.ERROR: "bold red"}

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.label)
            yield ProgressBar(total=None, show_eta=False)  # bounces until a total is known
            yield RichLog(id="log", max_lines=2000, wrap=True)
            yield Button("Interrupt (Esc)", id="interrupt", variant="warning")

    def progress(self, done: int, total: int) -> None:
        self.query_one(ProgressBar).update(total=total, progress=done)

    def write(self, level: int, message: str) -> None:
        self.query_one(RichLog).write(Text(message, self.STYLES.get(level, "")))

    @on(Button.Pressed, "#interrupt")
    def action_interrupt(self) -> None:
        cli.INTERRUPT.set()
        button = self.query_one(Button)
        button.label, button.disabled = "Interrupting after the current step…", True
        self.write(logging.WARNING, "Interrupting: work already done is kept")


class DialogLog(logging.Handler):
    """Forwards the package's log records, emitted by a job's thread, to its Busy dialog."""

    def __init__(self, app: App, busy: Busy) -> None:
        super().__init__(logging.DEBUG)
        self.app, self.busy = app, busy
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.app.call_from_thread(self.busy.write, record.levelno, self.format(record))
        except RuntimeError:  # emitted by the UI thread itself
            self.busy.write(record.levelno, self.format(record))


class Login(ModalScreen[tuple[str, str] | None]):
    """Asks for OpenReview credentials; the resulting session token is kept for a week."""

    DEFAULT_CSS = "Login {" + DIALOG_CSS + " width: 60; height: auto; padding: 1 2; } }"
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Sign in to OpenReview")
            yield Input(placeholder="Username (email)", id="username")
            yield Input(placeholder="Password", password=True, id="password")
            yield Button("Sign in", id="signin", variant="primary")

    @on(Input.Submitted, "#password")
    @on(Button.Pressed, "#signin")
    def submit(self) -> None:
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        if username and password:
            self.dismiss((username, password))


class Confirm(ModalScreen[bool]):
    """Shows the emails about to be sent; True only if the user types SEND."""

    DEFAULT_CSS = "Confirm {" + DIALOG_CSS + " width: 90%; height: 80%; padding: 1 2; } }"
    BINDINGS = [("escape", "dismiss(False)", "Cancel")]

    def __init__(self, summary: str) -> None:
        super().__init__()
        self.summary = summary

    def compose(self) -> ComposeResult:
        with Vertical():
            yield VerticalScroll(Static(Text(self.summary)))
            yield Input(placeholder="Type SEND to send, Esc to cancel", id="confirm")
            yield Button("Send", id="confirm-send", variant="error")

    @on(Input.Submitted, "#confirm")
    @on(Button.Pressed, "#confirm-send")
    def submit(self) -> None:
        self.dismiss(self.query_one("#confirm", Input).value.strip() == "SEND")


class Email(Screen[dict | None]):
    """Collects role, subject and body; a Confirm dialog follows before anything is sent."""

    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, scope: str) -> None:
        super().__init__()
        self.scope = scope

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"Email {self.scope}. Nothing is sent before you confirm by typing SEND.")
        roles = [(role, role) for role in papers.ROLES]
        yield Select(roles, value="late-reviewers", allow_blank=False, id="role")
        yield Input(placeholder="Subject", id="subject")
        yield TextArea(id="body")
        yield Static("{{fullname}} in the body becomes each recipient's name.")
        yield Button("Review and send", id="send", variant="primary")
        yield Footer()

    def on_button_pressed(self) -> None:
        subject = self.query_one("#subject", Input).value.strip()
        body = self.query_one(TextArea).text.strip()
        if not subject or not body:
            self.notify("Subject and body are required", severity="error")
            return
        self.dismiss({"role": self.query_one(Select).value, "subject": subject, "body": body})


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
        ("d", "details", "Details"),
        ("p", "download('field_pdf')", "PDF (P: all)"),
        ("u", "download('field_supplementary')", "Supp. (U: all)"),
        ("i", "inspect", "Inspect (I: all)"),
        ("e", "email", "Email (E: all)"),
        ("s", "sync", "Sync"),
        ("l", "legend", "Legend"),
        ("g", "toggle_green", "🟢 on/off"),
        ("o", "open", "Browser"),
        ("r", "reload", "Reload"),
        Binding("P", "download('field_pdf', True)", "All PDFs", show=False),
        Binding("U", "download('field_supplementary', True)", "All supplementary", show=False),
        Binding("E", "email(True)", "Email all", show=False),
        Binding("I", "inspect(True)", "Inspect all", show=False),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, config: dict) -> None:
        super().__init__()
        self.config = config
        self.issues: list[Issue] = []  # plus one GREEN row per paper without issues
        self.hide_green = False
        self.inspected: set[int] = (
            set()
        )  # papers whose current PDF went through the document checks

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="summary")
        yield Input(
            placeholder="Filter by SPC, paper # or issue (f to focus, Enter to apply)", id="filter"
        )
        yield DataTable(id="issues", cursor_type="row", zebra_stripes=True)
        yield Footer(compact=True)

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("Status", "Paper", "SPC", "Issue")
        self.action_reload()
        self.query_one(DataTable).focus()

    def action_reload(self) -> None:
        latest, previous = cli.load_snapshots()
        if latest is None:
            self.issues = []
            text = f"No snapshots in {cli.DIR_SNAPSHOTS}: press s to sync"
        else:
            extra, self.inspected = documents.snapshot_issues(latest, self.config, cli.DIR_PAPERS)
            self.issues = check(latest, self.config) + extra
            self.issues += green_rows(latest, self.issues)
            summary = report(latest, self.config, previous, extra)
            text = summary.split("\n\n")[0]  # the summary lines
            for severity, icon in ICONS.items():
                text = text.replace(f" {severity}", f" {icon}")
        self.query_one("#summary", Static).update(text)
        self.fill()

    def fill(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        needle = self.query_one(Input).value.lower()
        for n, i in enumerate(self.issues):
            if matches(i, needle) and not (self.hide_green and i.severity == GREEN):
                spcs = ", ".join(i.spcs) or "(no SPC)"
                table.add_row(ICONS[i.severity], i.number, spcs, i.message, key=str(n))

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
        self.query_one(DataTable).focus()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        event.data_table.sort(
            event.column_key,
            key=lambda v: v if isinstance(v, int) else RANKS.get(str(v), str(v)),
        )

    def on_data_table_row_selected(self) -> None:
        self.action_details()

    def selected(self) -> Issue | None:
        table = self.query_one(DataTable)
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
            (record,) = papers.load(cli.DIR_PAPERS, [number])
        except FileNotFoundError:
            record = None
        inspected = number in self.inspected
        self.push_screen(Paper(details(number, record, self.config, mine, inspected)))

    def scope(self, every: bool) -> list[int]:
        """The selected paper or, with `every`, all the papers shown."""
        if not every:
            issue = self.selected()
            return [issue.number] if issue else []
        rows = self.query_one(DataTable).rows
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
            if cli.INTERRUPT.is_set():
                raise cli.Interrupted
            self.call_from_thread(busy.progress, count, total)

        cli.INTERRUPT.clear()
        handler, level = DialogLog(self, busy), logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)  # per-paper steps go to the dialog, not the terminal
        try:
            client = None if offline else cli.resume(self.config)
            if client is None and not offline:
                env = (os.environ.get("OPENREVIEW_USERNAME"), os.environ.get("OPENREVIEW_PASSWORD"))
                credentials = credentials or (env if all(env) else None)
                if credentials is None:
                    self.call_from_thread(busy.dismiss)
                    self.call_from_thread(self.ask_login, label, job, done)
                    return
                client = cli.login(self.config, *credentials)
            result = job(client, progress)
        except cli.Interrupted:
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
            lambda client, progress: cli.sync(self.config, client, progress),
            done,
        )

    def action_download(self, key: str, every: bool = False) -> None:
        if not (numbers := self.scope(every)):
            return
        field = self.config[key]
        if not every:  # one paper: show it, downloading first only if needed
            try:
                (record,) = papers.load(cli.DIR_PAPERS, numbers)
            except FileNotFoundError:
                self.notify(f"#{numbers[0]} is not cached: press s to sync", severity="error")
                return
            path = papers.attachment(record, field, cli.DIR_PAPERS)
            if path is None:
                self.notify(f"#{numbers[0]} has no {field}")
            elif path.is_file():
                self.push_screen(Attachment(path))
            else:
                self.online(
                    f"Downloading {field} of #{numbers[0]}…",
                    lambda client, _: papers.download(client, record, field, cli.DIR_PAPERS),
                    lambda path: self.push_screen(Attachment(path)),
                )
            return

        def job(client: Any, progress: Callable[[int, int], None]) -> tuple[int, list[str]]:
            records, found, failures = papers.load(cli.DIR_PAPERS, numbers), 0, []
            for count, record in enumerate(records):
                progress(count, len(records))
                try:  # after the retries, one failure must not stop the other downloads
                    path = papers.download(client, record, field, cli.DIR_PAPERS)
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
            records = papers.load(cli.DIR_PAPERS, numbers)
        except FileNotFoundError as e:
            self.notify(f"Not cached: {e.filename}. Press s to sync", severity="error")
            return

        def job(client: Any, progress: Callable[[int, int], None]) -> list[str]:
            failures = []
            for count, record in enumerate(records):
                progress(count, len(records))
                try:
                    found = documents.inspect_paper(
                        record, self.config, cli.DIR_PAPERS, lambda: client
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

        offline = all(documents.downloaded(r, self.config, cli.DIR_PAPERS) for r in records)
        label = f"Inspecting {len(records)} papers…" if every else f"Inspecting #{numbers[0]}…"
        self.online(label, job, done, offline=offline)

    def action_email(self, every: bool = False) -> None:
        if not (numbers := self.scope(every)):
            return

        def review(form: dict | None) -> None:
            if not form:
                return
            try:
                messages = papers.plan(papers.load(cli.DIR_PAPERS, numbers), form["role"])
            except FileNotFoundError as e:
                self.notify(f"Not cached: {e.filename}. Press s to sync", severity="error")
                return
            if not messages:
                self.notify(f"No {form['role']} to email")
                return

            def send(confirmed: bool | None) -> None:
                if not confirmed:
                    self.notify("Nothing sent")
                    return
                self.online(
                    f"Sending {len(messages)} messages…",
                    lambda client, progress: papers.send(
                        client, messages, form["subject"], form["body"], progress
                    ),
                    lambda failures: self.notify(
                        "\n".join([*failures, f"Sent {len(messages) - len(failures)}"]),
                        severity="error" if failures else "information",
                    ),
                )

            self.push_screen(Confirm(papers.describe(messages, **form)), send)

        scope = f"paper #{numbers[0]}" if len(numbers) == 1 else f"{len(numbers)} papers"
        self.push_screen(Email(scope), review)
