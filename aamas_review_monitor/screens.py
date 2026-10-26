"""The TUI's screens and dialogs: paper details, attachments, the legend, the job dialog,
sign-in, confirmation and the email, comment and template forms."""

import logging
import string
import subprocess
import zipfile
from collections.abc import Collection
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    OptionList,
    ProgressBar,
    RichLog,
    Select,
    Static,
    TextArea,
    Tree,
)
from textual.widgets.option_list import Option

from aamas_review_monitor import core, documents, outreach, papers
from aamas_review_monitor.checks import GREEN, ICONS, RED, YELLOW, Issue, legend, passed

DIALOG_CSS = "align: center middle; & > Vertical { border: thick $accent; background: $surface;"


def sent_lines(text: Text, entries: list[dict]) -> None:
    """Appends one line per history entry: when, what, to whom, outcome."""
    for e in entries:
        failed = e["status"] != "sent"
        text.append(f"{e['at'][:16].replace('T', ' ')}  ", "dim")
        text.append(f"{e['kind']} to {e['to']} via #{e['via']}: {e['subject']}")
        text.append(f"  {e['status']}\n" if failed else "\n", "bold red" if failed else "")


def details(
    number: int,
    record: dict | None,
    config: dict,
    issues: list[Issue],
    inspected: bool = False,
    sent: list[dict] | None = None,
    ignored: Collection[tuple[int, str]] = (),
) -> Text:
    """Colored metadata, checks (failed, ignored and passed) and anonymous reviews of one
    paper; passed document checks only if they were run (`inspected`)."""
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
        if (i.number, i.code) in ignored:
            text.append(f"⚪ {i.message} (ignored: x to count it again)\n", "grey50")
        else:
            text.append(f"{ICONS[i.severity]} {i.message}\n")
    for label in passed(issues):
        text.append(f"{ICONS[GREEN]} {label}\n")
    if inspected:
        for label in passed(issues, documents.DOCUMENT_CHECKS):
            text.append(f"{ICONS[GREEN]} {label}\n")
    else:
        text.append("Document checks not run: press i\n", "italic")
    section("Sent from this app" if sent else "Nothing sent from this app yet")
    sent_lines(text, sent or [])
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
        with Vertical():
            yield Input(placeholder="Filter checks (Esc closes)", id="filter")
            yield VerticalScroll(Static(self.text(""), id="legend"))

    @on(Input.Changed, "#filter")
    def refilter(self, event: Input.Changed) -> None:
        self.query_one("#legend", Static).update(self.text(event.value))

    def text(self, query: str) -> Text:
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
            entries = legend(self.config, checks, query)
            if not entries:
                text.append("\nNo check matches\n", "dim")
            for code, label, description in entries:
                text.append(f"\n{label}", "bold cyan")
                text.append(f"  {code}\n", "dim")
                text.append(f"{description}\n")
        text.highlight_words([RED], "bold red")
        text.highlight_words([YELLOW], "bold yellow")
        return text


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
        core.INTERRUPT.set()
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


class Review(ModalScreen["list[outreach.Item] | None"]):
    """Every message (or comment) about to go out, each editable, and their common subject (or
    title) with placeholders, filled in for each; returns the edited items only if the user
    types SEND."""

    DEFAULT_CSS = (
        "Review {" + DIALOG_CSS + " width: 95%; height: 90%; padding: 1 2; } }"
        " Review #review-header { height: auto; max-height: 6; }"
        " Review #review-variables { height: auto; max-height: 5; color: $text-muted; }"
        " Review #review-list { width: 1fr; } Review #review-editor { width: 3fr; }"
        " Review #review-text { height: 1fr; }"
    )
    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    def __init__(
        self,
        header: list[str],
        items: "list[outreach.Item]",
        field: str = "Subject",
        limits: tuple[int, int] | None = None,
    ) -> None:
        super().__init__()
        self.header, self.items, self.field, self.limits = header, list(items), field, limits
        self.current: int | None = None  # the item in the editor

    def compose(self) -> ComposeResult:
        with Vertical():
            yield VerticalScroll(Static(Text("\n".join(self.header))), id="review-header")
            yield Input(
                self.items[0].pattern if self.items else "",
                placeholder=f"{self.field} of all, with the placeholders below; Enter applies",
                id="review-pattern",
            )
            yield VerticalScroll(Static(id="review-placeholders"), id="review-variables")
            with Horizontal():
                yield OptionList(
                    *(
                        Option(("⚠ " if i.warnings else "") + i.heading, str(n))
                        for n, i in enumerate(self.items)
                    ),
                    id="review-list",
                )
                with Vertical(id="review-editor"):
                    yield Static(id="review-about")
                    yield Input(placeholder=self.field, id="review-title")
                    yield TextArea(id="review-text", soft_wrap=False)  # lines as sent
            yield Input(
                placeholder="Edit any of them, then type SEND to send all; Esc cancels",
                id="confirm",
            )
            yield Button("Send", id="confirm-send", variant="error")

    def on_mount(self) -> None:
        self.query_one("#review-pattern").border_title = f"{self.field} of all: Enter applies"
        self.query_one("#review-title").border_title = f"{self.field} of this one"
        self.show(0)
        self.query_one("#confirm", Input).focus()  # ready to type SEND, or Esc

    def keep(self) -> None:
        """Takes the editor's text back into the item it shows."""
        if self.current is not None:
            title, text = self.query_one("#review-title", Input), self.query_one(TextArea)
            item = self.items[self.current]
            self.items[self.current] = item._replace(title=title.value, text=text.text)

    def show(self, index: int) -> None:
        self.current, item = index, self.items[index]
        about = Text(item.heading, "bold")
        about.append(f"\n{item.warnings}" if item.warnings else "", "bold yellow")
        self.query_one("#review-about", Static).update(about)
        self.query_one("#review-title", Input).value = item.title
        lines = outreach.variables(item.values) or ["No placeholders: the same for all"]
        hint = f"Placeholders for the {self.field.lower()} of all:"
        self.query_one("#review-placeholders", Static).update(Text("\n".join([hint, *lines])))
        self.query_one(TextArea).load_text(item.text)

    @on(OptionList.OptionHighlighted, "#review-list")
    def highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if self.current is not None and event.option.id != str(self.current):
            self.keep()
            self.show(int(event.option.id or 0))

    @on(Input.Submitted, "#review-pattern")
    def apply_pattern(self, event: Input.Submitted) -> None:
        self.keep()
        pattern = string.Template(event.value)
        self.items = [
            i._replace(title=pattern.safe_substitute(i.values), pattern=event.value)
            for i in self.items
        ]
        self.show(self.current or 0)
        self.notify(f"{self.field} set on all {len(self.items)}")

    @on(Input.Submitted, "#confirm")
    @on(Button.Pressed, "#confirm-send")
    def submit(self) -> None:
        self.keep()
        if self.query_one("#confirm", Input).value.strip() != "SEND":
            self.dismiss(None)
            return
        if problems := outreach.problems(self.items, self.limits):
            self.notify("\n".join(problems), severity="error")
            return
        self.dismiss(self.items)


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


class CommentForm(ModalScreen["bool | None"]):
    """Who may read the comments; each is reviewed, and can be edited, before posting."""

    DEFAULT_CSS = "CommentForm {" + DIALOG_CSS + " width: 90%; height: auto; padding: 1 2; } }"
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, scope: str) -> None:
        super().__init__()
        self.scope = scope

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                f"Comment on {self.scope}, signed as the paper's SACs. PCs and SACs read it."
            )
            yield Checkbox("The paper's SPCs can read it too", value=True, id="spcs-read")
            yield Static("Each paper gets its own open issues, from the comment template.")
            yield Button("Review and post", id="comment-post", variant="primary")

    @on(Button.Pressed, "#comment-post")
    def submit(self) -> None:
        self.dismiss(self.query_one(Checkbox).value)


class Templates(ModalScreen["outreach.Template | None"]):
    """Picks an email template, the one suggested for the chosen issues highlighted; drafts are
    previewed before anything is sent."""

    DEFAULT_CSS = "Templates {" + DIALOG_CSS + " width: 90%; height: auto; padding: 1 2; } }"
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, scope: str, issues: list[Issue]) -> None:
        super().__init__()
        self.scope = scope
        self.choices = outreach.templates()
        self.suggested = outreach.suggest(self.choices, issues)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"Email {self.scope} with a template. Every message is previewed first.")
            yield OptionList(
                *(
                    Option(
                        Text.assemble(
                            (t.name, "bold"),
                            f"  to {t.audience}",
                            ("  suggested" if t == self.suggested else "", "bold green"),
                            "\n",
                            t.description,
                        ),
                        t.key,
                    )
                    for t in self.choices
                ),
                id="templates",
            )

    def on_mount(self) -> None:
        if self.suggested:
            self.query_one(OptionList).highlighted = self.choices.index(self.suggested)

    @on(OptionList.OptionSelected, "#templates")
    def chosen(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(next(t for t in self.choices if t.key == event.option.id))


class Actions(ModalScreen["str | None"]):
    """What can be done on the marked papers or SPCs (else the selected one): picks an action."""

    DEFAULT_CSS = "Actions {" + DIALOG_CSS + " width: 70; height: auto; padding: 1 2; } }"
    BINDINGS = [("escape,a", "dismiss", "Cancel")]

    def __init__(self, scope: str, choices: list[tuple[str, str, str]]) -> None:
        super().__init__()
        self.scope, self.choices = scope, choices  # (label, key, action)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(self.scope, "bold"))
            yield OptionList(
                *(
                    Option(Text.assemble(label, (f"  {key}", "dim")), a)
                    for label, key, a in self.choices
                ),
                id="actions",
            )

    @on(OptionList.OptionSelected, "#actions")
    def chosen(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)
