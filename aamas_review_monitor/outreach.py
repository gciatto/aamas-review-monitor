"""Templated emails: SPC digests and reviewer reminders, composed from the issues found.

Composition is deterministic: a template picks issue codes and an audience, and each recipient
gets one draft listing their papers' issues. OpenReview lets a SAC write only through a paper's
message invitation, to that paper's reviewers or SPCs: an SPC's digest goes through one of
their papers (any message reaches them), a reviewer reminder through the paper it is about.
"""

import string
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import NamedTuple

from aamas_review_monitor.checks import GREEN, ICONS, Issue
from aamas_review_monitor.collector import person
from aamas_review_monitor.papers import Comment, Draft, recipients
from aamas_review_monitor.resources import DIR_TEMPLATES, FILE_COMMENT

AUDIENCES = ("spcs", "late-reviewers")


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


def _lines(issues: list[Issue]) -> str:
    return "\n".join(f"- #{i.number} ({i.url}): {i.message}" for i in issues)


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
                "issues": _lines(theirs),
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
            drafts.append(
                Draft(
                    paper, invitation, parent, members, subject, body, to, (number,), template.key
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


def preview(
    drafts: list[Draft],
    unreachable: list[str],
    sent: Sequence[dict] = (),
    notes: Sequence[str] = (),
) -> str:
    """Every draft in full, for a confirmation: who, through which paper, subject and body; and
    a warning on those whose recipients already got the same email (`sent`, the history).
    `notes` go under the count, e.g. how old the snapshot is."""
    earlier = [repeats(d, sent) for d in drafts]
    blocks = [
        f"=== To {d.to}, via #{d.record['number']} ===\n{_before(e)}Subject: {d.subject}\n\n{d.body}"
        for d, e in zip(drafts, earlier)
    ]
    skipped = [f"Not reachable: {line}" for line in unreachable]
    warned = _warnings(earlier, "went out")
    return "\n".join([f"{len(drafts)} messages", *notes, *warned, *skipped, "", *blocks])


def comments(
    issues: list[Issue], records: list[dict], numbers: set[int], spcs_read: bool
) -> tuple[list[Comment], list[str]]:
    """One forum comment per paper listing its open issues, from the comment template; also the
    papers that cannot get one, and why."""
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
            lines = "\n".join(f"- {ICONS[i.severity]} {i.message}" for i in theirs)
            text = string.Template(body).safe_substitute(issues=lines).strip() + "\n"
            found.append(Comment(by_number[number], title, text, spcs_read))
    return found, skipped


def preview_comments(
    found: list[Comment], skipped: list[str], sent: Sequence[dict] = (), notes: Sequence[str] = ()
) -> str:
    """Every comment in full, warning on the papers the app already commented on (`sent`)."""
    readers = "PCs, SACs" + (" and SPCs" if found and found[0].spcs_read else "")
    earlier = [
        [
            e
            for e in sent
            if e["kind"] == "comment" and e["status"] == "sent" and e["via"] == c.record["number"]
        ]
        for c in found
    ]
    blocks = [
        f"=== Comment on #{c.record['number']} ===\n{_before(e)}Title: {c.title}\n\n{c.text}"
        for c, e in zip(found, earlier)
    ]
    lines = [
        f"{len(found)} comments, readable by {readers}",
        *notes,
        *_warnings(earlier, "papers were commented on"),
        *(f"Skipped: {s}" for s in skipped),
    ]
    return "\n".join([*lines, "", *blocks])
