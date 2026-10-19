"""Textual front end: the same checks and report as the CLI, as a filterable, sortable table."""

import subprocess
import sys
import webbrowser
import zipfile
from collections.abc import Callable
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
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
    Select,
    Static,
    TextArea,
    Tree,
)

from aamas_review_monitor import __main__ as cli
from aamas_review_monitor import papers
from aamas_review_monitor.checks import GREEN, RED, YELLOW, Issue, check, passed, report

STYLES = {RED: "bold red", YELLOW: "bold yellow", GREEN: "bold green"}
RANKS = {RED: 0, YELLOW: 1, GREEN: 2}


def details(number: int, record: dict | None, config: dict, issues: list[Issue]) -> Text:
    """Colored metadata, checks (failed and passed) and anonymous reviews of one paper."""
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
        text.append(f"{i.severity:6} ", STYLES[i.severity])
        text.append(f"{i.message}\n")
    for label in passed(issues):
        text.append(f"{GREEN:6} ", STYLES[GREEN])
        text.append(f"{label}\n")
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


def os_open(path: Path, reveal: bool = False) -> None:
    """Opens a file with its default app or, with `reveal`, shows it in Finder/Explorer."""
    if sys.platform == "darwin":
        command = ["open", "-R", str(path)] if reveal else ["open", str(path)]
    elif sys.platform == "win32":
        command = (
            ["explorer", f"/select,{path}"] if reveal else ["cmd", "/c", "start", "", str(path)]
        )
    else:  # file managers cannot portably select a file: open its folder
        command = ["xdg-open", str(path.parent if reveal else path)]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Attachment(ModalScreen):
    """A downloaded attachment: its path, OS actions, and its contents (zip tree or PDF text)."""

    DEFAULT_CSS = """
    Attachment { align: center middle; }
    #dialog { width: 90%; height: 90%; border: thick $accent; background: $surface; padding: 0 1; }
    """
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
        with Vertical(id="dialog"):
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
        with zipfile.ZipFile(self.path) as archive:
            for info in archive.infolist():
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
        os_open(self.path, reveal=True)

    def action_view(self) -> None:
        os_open(self.path)

    def action_copy(self) -> None:
        self.app.copy_to_clipboard(str(self.path))
        self.notify("Path copied")


class Email(Screen[dict | None]):
    """Collects role, subject and body; sending is confirmed later, in the plain terminal."""

    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, scope: str) -> None:
        super().__init__()
        self.scope = scope

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"Email {self.scope}. Nothing is sent before you type SEND in the terminal.")
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


class Monitor(App):
    TITLE = "AAMAS Review Monitor"
    # Lowercase keys act on the selected paper; uppercase ones on all the papers shown
    BINDINGS = [
        ("d", "details", "Details"),
        ("o", "open", "Open in browser"),
        ("g", "toggle_green", "Hide/show GREEN"),
        ("p", "download('field_pdf')", "PDF"),
        ("u", "download('field_supplementary')", "Supplementary"),
        ("e", "email", "Email"),
        Binding("P", "download('field_pdf', True)", "All PDFs", show=False),
        Binding("U", "download('field_supplementary', True)", "All supplementary", show=False),
        Binding("E", "email(True)", "Email all", show=False),
        ("s", "sync", "Sync"),
        ("r", "reload", "Reload"),
        ("f", "focus('filter')", "Filter"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, config: dict) -> None:
        super().__init__()
        self.config = config
        self.issues: list[Issue] = []  # plus one GREEN row per paper without issues
        self.hide_green = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="summary")
        yield Input(
            placeholder="Filter by SPC, paper # or issue (f to focus, Enter to apply)", id="filter"
        )
        yield DataTable(id="issues", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("Severity", "Paper", "SPC", "Issue")
        self.action_reload()
        self.query_one(DataTable).focus()

    def action_reload(self) -> None:
        latest, previous = cli.load_snapshots()
        if latest is None:
            self.issues = []
            text = f"No snapshots in {cli.DIR_SNAPSHOTS}: press s to sync"
        else:
            self.issues = check(latest, self.config)
            flagged = {i.number for i in self.issues}
            self.issues += [
                Issue(p["number"], GREEN, "ok", "all checks pass", p["url"], tuple(p["spcs"]))
                for p in latest["papers"]
                if p["number"] not in flagged
            ]
            text = report(latest, self.config, previous).split("\n\n")[0]  # the summary lines
        self.query_one("#summary", Static).update(text)
        self.fill()

    def fill(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        needle = self.query_one(Input).value.lower()
        for n, i in enumerate(self.issues):
            spcs = ", ".join(i.spcs) or "(no SPC)"
            if self.hide_green and i.severity == GREEN:
                continue
            if needle in f"{i.severity} #{i.number} {spcs} {i.message}".lower():
                severity = Text(i.severity, style=STYLES.get(i.severity, ""))
                table.add_row(severity, i.number, spcs, i.message, key=str(n))

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
        if not (issue := self.selected()):
            return
        mine = [i for i in self.issues if i.number == issue.number and i.severity != GREEN]
        try:
            (record,) = papers.load(cli.DIR_PAPERS, [issue.number])
        except FileNotFoundError:
            record = None
        self.push_screen(Paper(details(issue.number, record, self.config, mine)))

    def scope(self, every: bool) -> list[int]:
        """The selected paper or, with `every`, all the papers shown."""
        if not every:
            issue = self.selected()
            return [issue.number] if issue else []
        rows = self.query_one(DataTable).rows
        return sorted({self.issues[int(k.value or 0)].number for k in rows})

    def in_terminal(self, job: Callable[[], object]) -> None:
        # Back to the plain terminal, where login may prompt and email asks for SEND
        with self.suspend():
            try:
                job()
            except Exception as e:  # keep the TUI alive; the error stays on screen
                print(f"Failed: {e}")
            input("Press Enter to return")

    def action_sync(self) -> None:
        self.in_terminal(lambda: print(f"Saved {cli.sync(self.config)}"))
        self.action_reload()

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
                return
            if not path.is_file():
                self.in_terminal(
                    lambda: papers.download(cli.login(self.config), record, field, cli.DIR_PAPERS)
                )
            if path.is_file():
                self.push_screen(Attachment(path))
            return

        def job() -> None:
            client = cli.login(self.config)
            for record in papers.load(cli.DIR_PAPERS, numbers):
                path = papers.download(client, record, field, cli.DIR_PAPERS)
                print(f"#{record['number']}: {path or f'no {field}'}")

        self.in_terminal(job)

    def action_email(self, every: bool = False) -> None:
        if not (numbers := self.scope(every)):
            return

        def send(form: dict | None) -> None:
            if form:  # loading inside the job, so a missing cache is reported, not raised
                self.in_terminal(
                    lambda: papers.email(
                        cli.login(self.config), papers.load(cli.DIR_PAPERS, numbers), **form
                    )
                )

        scope = f"paper #{numbers[0]}" if len(numbers) == 1 else f"{len(numbers)} papers"
        self.push_screen(Email(scope), send)
