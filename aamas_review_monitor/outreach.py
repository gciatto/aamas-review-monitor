"""Templated emails: SPC digests and reviewer reminders, composed from the issues found.

Composition is deterministic: a template picks issue codes and an audience, and each recipient
gets one draft listing their papers' issues. OpenReview lets a SAC write only through a paper's
message invitation, to that paper's reviewers or SPCs: an SPC's digest goes through one of
their papers (any message reaches them), a reviewer reminder through the paper it is about.
"""

import string
import textwrap
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import NamedTuple

from aamas_review_monitor.checks import GREEN, ICONS, Issue, legend
from aamas_review_monitor.collector import person
from aamas_review_monitor.papers import Comment, Draft, recipients
from aamas_review_monitor.resources import DIR_TEMPLATES, FILE_COMMENT

AUDIENCES = ("spcs", "late-reviewers")
COMMENT_CHARS_MAX = 5000  # OpenReview's Official_Comment limit
COMMENT_LIMITS = (500, COMMENT_CHARS_MAX)  # title, text


class Template(NamedTuple):
    key: str  # the file name without extension, e.g. "spc-digest"
    name: str
    description: str
    audience: str  # "spcs": one draft per SPC; "late-reviewers": one per paper
    codes: frozenset[str]  # issue codes it is about; empty for all
    subject: str
    body: str

    def covers(self, issue: Issue) -> bool:
        return not self.codes or issue.code.split(":")[0] in self.codes


def parse(key: str, text: str) -> Template:
    """A template file: `Key: value` header lines, a `---` line, then the body. Placeholders
    use `$name` (OpenReview's own `{{fullname}}` is left alone)."""
    header, _, body = text.partition("\n---\n")
    fields = dict(line.split(":", 1) for line in header.strip().splitlines())
    fields = {k.strip().lower(): v.strip() for k, v in fields.items()}
    codes = {c.strip() for c in fields["codes"].split(",")} - {"*", ""}
    assert fields["audience"] in AUDIENCES, f"{key}: unknown audience {fields['audience']}"
    return Template(
        key, fields["name"], fields["description"], fields["audience"], frozenset(codes),
        fields["subject"], body.strip() + "\n",
    )  # fmt: skip


def templates(directory: Path = DIR_TEMPLATES) -> list[Template]:
    return [parse(f.stem, f.read_text(encoding="utf-8")) for f in sorted(directory.glob("*.txt"))]


def _day(iso: str) -> str:
    day = date.fromisoformat(iso) if iso else None
    return f"{day.day} {day:%B %Y}" if day else "?"  # not %-d: Windows lacks it


def _values(config: dict, today: date) -> dict[str, str]:
    values = {}
    for key in ("reviews", "meta_reviews", "acknowledgements"):
        deadline = config.get(f"deadline_{key}", "")
        values[f"deadline_{key}"] = _day(deadline)
        values[f"days_{key}"] = (
            str((date.fromisoformat(deadline) - today).days) if deadline else "?"
        )
    return values


def _legend(config: dict) -> dict[str, tuple[str, str]]:
    """Label and description of every paper and document check, by code."""
    from aamas_review_monitor.documents import DOCUMENT_CHECKS  # documents imports papers

    entries = legend(config) + legend(config, DOCUMENT_CHECKS)
    return {code: (label, text) for code, label, text in entries}


def _paper_line(issue: Issue) -> str:
    return f"- #{issue.number} ({issue.url}): {issue.message}"


def _lines(
    issues: list[Issue],
    line: Callable[[Issue], str] = _paper_line,
    explained: dict[str, tuple[str, str]] | None = None,
) -> str:
    """One line per issue; with `explained` (the legend), a paper's first issue from each
    check is followed by what that check verifies, so readers know why it was flagged."""
    found, seen = [], set()
    for i in issues:
        found.append(line(i))
        code = i.code.split(":")[0]
        if explained and code in explained and (i.number, code) not in seen:
            seen.add((i.number, code))
            label, text = explained[code]
            found.append(
                textwrap.fill(
                    f"{label}: {text}", 92, initial_indent="    ", subsequent_indent="    "
                )
            )
    return "\n".join(found)


def _route(spc: str, records: dict[int, dict], numbers: list[int]) -> tuple[dict, str] | None:
    """A paper of the SPC's, and the member of its SPC group who is the SPC."""
    for record in (records[n] for n in numbers if n in records):
        for member in record["groups"].get(record["names"]["area_chairs"], []):
            if person(record, member) == spc:
                return record, member
    return None


def compose(
    template: Template,
    issues: list[Issue],
    records: list[dict],
    config: dict,
    today: date,
    spcs: set[str] | None = None,
    numbers: set[int] | None = None,
) -> tuple[list[Draft], list[str]]:
    """Drafts for the template's audience about the issues it covers, optionally only for some
    SPCs or papers; also the recipients that cannot be reached, and why."""
    chosen = [
        i
        for i in issues
        if template.covers(i) and (numbers is None or i.number in numbers) and i.severity != GREEN
    ]
    by_number = {r["number"]: r for r in records}
    values = _values(config, today)
    drafts, unreachable = [], []
    if template.audience == "spcs":
        mine: dict[str, list[Issue]] = defaultdict(list)
        for i in chosen:
            for spc in i.spcs:
                if spcs is None or spc in spcs:
                    mine[spc].append(i)
        for spc, theirs in sorted(mine.items()):
            route = _route(spc, by_number, sorted({i.number for i in theirs}))
            if route is None:
                unreachable.append(f"{spc}: none of their papers is cached")
                continue
            record, member = route
            papers = sorted({i.number for i in theirs})
            fill = values | {
                "count": str(len(papers)),
                "papers": ", ".join(f"#{n}" for n in papers),
                "issues": _lines(theirs, explained=_legend(config)),
            }
            invitation, parent, _ = recipients(record, "spcs")
            subject = string.Template(template.subject).safe_substitute(fill)
            body = string.Template(template.body).safe_substitute(fill)
            drafts.append(
                Draft(
                    record,
                    invitation,
                    parent,
                    [member],
                    subject,
                    body,
                    spc,
                    tuple(papers),
                    template.key,
                    tuple((i.number, i.code) for i in theirs),
                )
            )
    else:
        for number in sorted({i.number for i in chosen}):
            theirs = [i for i in chosen if i.number == number]
            if number not in by_number:
                unreachable.append(f"#{number}: not cached")
                continue
            paper = by_number[number]
            if spcs is not None and not set(theirs[0].spcs) & spcs:
                continue
            invitation, parent, members = recipients(paper, "late-reviewers")
            if not members:
                unreachable.append(f"#{number}: no late reviewer to write to")
                continue
            fill = values | {
                "paper": f"#{number}",
                "url": theirs[0].url,
                "count": "1",
                "papers": f"#{number}",
                "issues": _lines(theirs),
            }
            subject = string.Template(template.subject).safe_substitute(fill)
            body = string.Template(template.body).safe_substitute(fill)
            to = f"late reviewers of #{number} ({len(members)})"
            listed = tuple((i.number, i.code) for i in theirs)
            drafts.append(
                Draft(
                    paper,
                    invitation,
                    parent,
                    members,
                    subject,
                    body,
                    to,
                    (number,),
                    template.key,
                    listed,
                )
            )
    return drafts, unreachable


def direct(
    records: list[dict], role: str, subject: str, body: str
) -> tuple[list[Draft], list[str]]:
    """The same message, written by the user, to `role` of each paper; also the papers with no
    one to write to."""
    drafts, unreachable = [], []
    for record in records:
        number = record["number"]
        invitation, parent, members = recipients(record, role)
        if not members:
            unreachable.append(f"#{number}: no {role} to write to")
            continue
        to = f"{role} of #{number} ({len(members)})"
        drafts.append(Draft(record, invitation, parent, members, subject, body, to))
    return drafts, unreachable


def repeats(draft: Draft, sent: Sequence[dict]) -> list[dict]:
    """Earlier emails from the history with the same template (or subject, if it has none) that
    reached any of the draft's recipients."""
    key = draft.template or draft.subject
    return [
        e
        for e in sent
        if e["kind"] == "email"
        and e["status"] == "sent"
        and (e["template"] or e["subject"]) == key
        and set(e["recipients"]) & set(draft.members)
    ]


def _warnings(found: list[list[dict]], what: str) -> list[str]:
    count = sum(bool(f) for f in found)
    return [f"⚠ {count} of {len(found)} {what} before: see below"] if count else []


def _before(entries: list[dict]) -> str:
    return "".join(
        f"⚠ Already sent {e['at'][:16].replace('T', ' ')}: {e['subject']}\n" for e in entries
    )


class Item(NamedTuple):
    """One message or comment under review: where it goes, warnings, and its editable text."""

    heading: str  # "To ~Ada_Lovelace1, via #7", "Comment on #7"
    warnings: str  # "⚠ Already sent ..." lines, or ""
    title: str  # subject, or comment title
    text: str  # body, or comment text


def review(
    drafts: list[Draft],
    unreachable: list[str],
    sent: Sequence[dict] = (),
    notes: Sequence[str] = (),
) -> tuple[list[str], list[Item]]:
    """Header lines (count, `notes` such as the snapshot's age, warnings, unreachable people)
    and one item per draft, warning on those whose recipients already got the same email
    (`sent`, the history)."""
    earlier = [repeats(d, sent) for d in drafts]
    items = [
        Item(f"To {d.to}, via #{d.record['number']}", _before(e), d.subject, d.body)
        for d, e in zip(drafts, earlier)
    ]
    skipped = [f"Not reachable: {line}" for line in unreachable]
    return [f"{len(drafts)} messages", *notes, *_warnings(earlier, "went out"), *skipped], items


def render(header: list[str], items: list[Item], field: str = "Subject") -> str:
    """A review as plain text, every item in full."""
    blocks = [f"=== {i.heading} ===\n{i.warnings}{field}: {i.title}\n\n{i.text}" for i in items]
    return "\n".join([*header, "", *blocks])


def preview(
    drafts: list[Draft],
    unreachable: list[str],
    sent: Sequence[dict] = (),
    notes: Sequence[str] = (),
) -> str:
    """Every draft in full, for a confirmation: see `review`."""
    return render(*review(drafts, unreachable, sent, notes))


def comments(
    issues: list[Issue], records: list[dict], numbers: set[int], spcs_read: bool, config: dict
) -> tuple[list[Comment], list[str]]:
    """One forum comment per paper listing its open issues, each check explained once, from the
    comment template; also the papers that cannot get one, and why."""
    header, _, body = FILE_COMMENT.read_text(encoding="utf-8").partition("\n---\n")
    title = header.split(":", 1)[1].strip()
    by_number = {r["number"]: r for r in records}
    found, skipped = [], []
    for number in sorted(numbers):
        theirs = [i for i in issues if i.number == number and i.severity != GREEN]
        if number not in by_number:
            skipped.append(f"#{number}: not cached")
        elif not theirs:
            skipped.append(f"#{number}: no open issues")
        else:
            # explained if it fits OpenReview's limit, else the bare list, else nothing
            for explained in (_legend(config), None):
                lines = _lines(theirs, lambda i: f"- {ICONS[i.severity]} {i.message}", explained)
                text = string.Template(body).safe_substitute(issues=lines).strip() + "\n"
                if len(text) <= COMMENT_CHARS_MAX:
                    listed = tuple((i.number, i.code) for i in theirs)
                    found.append(Comment(by_number[number], title, text, spcs_read, listed))
                    break
            else:
                skipped.append(
                    f"#{number}: {len(text)} characters, OpenReview allows {COMMENT_CHARS_MAX}"
                )
    return found, skipped


def review_comments(
    found: list[Comment], skipped: list[str], sent: Sequence[dict] = (), notes: Sequence[str] = ()
) -> tuple[list[str], list[Item]]:
    """Header lines and one item per comment, warning on the papers the app already commented
    on (`sent`)."""
    readers = "PCs, SACs" + (" and SPCs" if found and found[0].spcs_read else "")
    earlier = [
        [
            e
            for e in sent
            if e["kind"] == "comment" and e["status"] == "sent" and e["via"] == c.record["number"]
        ]
        for c in found
    ]
    items = [
        Item(f"Comment on #{c.record['number']}", _before(e), c.title, c.text)
        for c, e in zip(found, earlier)
    ]
    header = [
        f"{len(found)} comments, readable by {readers}",
        *notes,
        *_warnings(earlier, "papers were commented on"),
        *(f"Skipped: {s}" for s in skipped),
    ]
    return header, items


def preview_comments(
    found: list[Comment], skipped: list[str], sent: Sequence[dict] = (), notes: Sequence[str] = ()
) -> str:
    """Every comment in full: see `review_comments`."""
    return render(*review_comments(found, skipped, sent, notes), "Title")


def problems(items: list[Item], limits: tuple[int, int] | None) -> list[str]:
    """What prevents sending the (edited) items: empty texts, or longer than `limits`
    (title, text) allow."""
    found = []
    for i in items:
        if not i.title.strip() or not i.text.strip():
            found.append(f"{i.heading}: empty")
        elif limits and (len(i.title) > limits[0] or len(i.text) > limits[1]):
            found.append(f"{i.heading}: longer than OpenReview allows ({limits[0]}/{limits[1]})")
    return found
