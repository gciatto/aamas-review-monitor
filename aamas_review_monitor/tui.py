"""Textual front end: the same checks and report as the CLI, as a filterable, sortable table."""

import webbrowser

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from aamas_review_monitor import __main__ as cli
from aamas_review_monitor import papers
from aamas_review_monitor.checks import RED, YELLOW, Issue, check, report

STYLES = {RED: "bold red", YELLOW: "yellow"}


class Paper(Screen):
    """Metadata, issues and anonymous reviews of one paper, from the local cache."""

    BINDINGS = [("escape,q", "app.pop_screen", "Back")]

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(Static(self.text, markup=False))
        yield Footer()


class Monitor(App):
    TITLE = "AAMAS Review Monitor"
    BINDINGS = [
        ("d", "details", "Details"),
        ("o", "open", "Open in browser"),
        ("s", "sync", "Sync"),
        ("r", "reload", "Reload"),
        ("slash", "focus('filter')", "Filter"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, config: dict) -> None:
        super().__init__()
        self.config = config
        self.issues: list[Issue] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="summary")
        yield Input(
            placeholder="Filter by SPC, paper # or issue (/ to focus, Enter to apply)", id="filter"
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
            text = report(latest, self.config, previous).split("\n\n")[0]  # the summary lines
        self.query_one("#summary", Static).update(text)
        self.fill()

    def fill(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        needle = self.query_one(Input).value.lower()
        for n, i in enumerate(self.issues):
            spcs = ", ".join(i.spcs) or "(no SPC)"
            if needle in f"{i.severity} #{i.number} {spcs} {i.message}".lower():
                severity = Text(i.severity, style=STYLES.get(i.severity, ""))
                table.add_row(severity, i.number, spcs, i.message, key=str(n))

    def on_input_changed(self) -> None:
        self.fill()

    def on_input_submitted(self) -> None:
        self.query_one(DataTable).focus()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        event.data_table.sort(event.column_key, key=lambda v: v if isinstance(v, int) else str(v))

    def on_data_table_row_selected(self) -> None:
        self.action_open()

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
        mine = [f"{i.severity:6} {i.message}" for i in self.issues if i.number == issue.number]
        try:
            (record,) = papers.load(cli.DIR_PAPERS, [issue.number])
            parts = [papers.metadata(record, self.config), *mine, papers.reviews(record)]
        except FileNotFoundError:
            parts = [f"#{issue.number}: not cached, press s to sync", *mine]
        self.push_screen(Paper("\n\n".join(parts)))

    def action_sync(self) -> None:
        # Back to the plain terminal, where sync may prompt for credentials
        with self.suspend():
            try:
                print(f"Saved {cli.sync(self.config)}")
            except Exception as e:  # keep the TUI alive; the error stays on screen
                print(f"Sync failed: {e}")
            input("Press Enter to return")
        self.action_reload()
