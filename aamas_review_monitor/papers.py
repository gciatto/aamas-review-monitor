"""Per-paper operations over the local cache of collector records: metadata, reviews, PDFs, emails.

Layout: `<dir>/<number>/record.json` plus downloaded attachments next to it.
"""

import json
import re
from datetime import datetime, timezone
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

from aamas_review_monitor import logger
from aamas_review_monitor.collector import person, replies

ROLES = ("reviewers", "late-reviewers", "spcs")


def _write(file: Path, data: bytes) -> None:
    file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    file.touch(mode=0o600)
    file.write_bytes(data)


def save(records: list[dict], directory: Path, attachments: list[str]) -> list[str]:
    """Caches the records; returns the attachments that changed since the previous sync."""
    changes = []
    for record in records:
        file = directory / str(record["number"]) / "record.json"
        if file.is_file():
            old = json.loads(file.read_text(encoding="utf-8"))["content"]
            for field in attachments:
                if old.get(field) != record["content"].get(field):
                    changes.append(f"#{record['number']}: {field} updated")
        _write(file, json.dumps(record, indent=1).encode())
    return changes


def load(directory: Path, numbers: list[int] | None = None) -> list[dict]:
    """The cached records of the given papers (all if None); FileNotFoundError if one is missing."""
    files = [directory / str(n) / "record.json" for n in numbers] if numbers else None
    files = files or sorted(directory.glob("*/record.json"), key=lambda f: int(f.parent.name))
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def fields(content: dict, skip: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """Non-empty (key, value) pairs of a note's content, lists joined by commas."""
    pairs = []
    for key, field in content.items():
        value = field.get("value") if isinstance(field, dict) else None
        if key in skip or value in (None, "", []):
            continue
        pairs.append((key, ", ".join(map(str, value)) if isinstance(value, list) else str(value)))
    return pairs


def metadata_fields(record: dict, config: dict) -> list[tuple[str, str]]:
    skip = (config["field_pdf"], config["field_supplementary"], "venue", "venueid")
    return fields(record["content"], skip)


def review_blocks(record: dict, reveal: bool = False) -> list[tuple[str, list[tuple[str, str]]]]:
    """(title, fields) of each review and meta-review; reviewers stay anonymous unless `reveal`."""
    blocks = []
    for kind in ("review", "meta_review"):
        for reply in replies(record, kind):
            signature = reply["signatures"][0]
            who = person(record, signature) if reveal else signature.removeprefix(record["prefix"])
            blocks.append((f"{record['names'][kind]} by {who}", fields(reply["content"])))
    return blocks


def _lines(pairs: list[tuple[str, str]]) -> list[str]:
    return [f"{key}: {value}" for key, value in pairs]


def metadata(record: dict, config: dict) -> str:
    head = f"#{record['number']}  {config['url_forum']}{record['id']}"
    return "\n".join([head, *_lines(metadata_fields(record, config))])


def reviews(record: dict, reveal: bool = False) -> str:
    blocks = review_blocks(record, reveal)
    text = ["\n".join([f"== {title}", *_lines(pairs)]) for title, pairs in blocks]
    return "\n\n".join(text) or f"#{record['number']}: no reviews yet"


def attachment(record: dict, field: str, directory: Path) -> Path | None:
    """Where the current version of an attachment is cached; None if the paper has none."""
    value = record["content"].get(field, {}).get("value")
    # ponytail: OpenReview attachment paths change with each upload, so the name is the version
    return (
        directory / str(record["number"]) / f"{field}_{PurePosixPath(value).name}"
        if value
        else None
    )


def download(client: Any, record: dict, field: str, directory: Path) -> Path | None:
    """Downloads an attachment unless the cached copy is current; None if the paper has none."""
    target = attachment(record, field, directory)
    if target and not target.is_file():
        for old in target.parent.glob(f"{field}_*"):  # older versions and their extracted text
            old.unlink()
        _write(target, client.get_attachment(field, id=record["id"]))
    return target


def tool(name: str, *args: str) -> str:
    """The output of an xpdf tool (pdftotext, pdfinfo, pdffonts); FileNotFoundError if missing."""
    found = shutil.which(name)
    if not found:
        raise FileNotFoundError(f"{name} not found: install xpdf (`brew install xpdf`)")
    run = subprocess.run([found, *args], check=True, capture_output=True)
    return run.stdout.decode("utf-8", errors="replace")


def pdf_pages(pdf: Path) -> list[str]:
    """The text of each page of a PDF, as many pages as pdfinfo counts, cached next to it.

    Pages are converted one at a time (pdftotext -f N -l N), so text is always attributed to
    its page, even across blank pages. pdftotext's default mode follows reading order, so
    two-column pages (as in AAMAS) come out one column after the other; `-layout` would
    interleave the columns line by line.
    """
    cache = pdf.with_name(pdf.name + ".pages.txt")
    if not cache.is_file():
        info = re.search(r"^Pages:\s*(\d+)", tool("pdfinfo", str(pdf)), re.M)
        pages = [
            tool("pdftotext", "-enc", "UTF-8", "-q", "-f", str(n), "-l", str(n), str(pdf), "-")
            for n in range(1, int(info.group(1)) + 1 if info else 1)
        ]
        _write(cache, "\f".join(page.replace("\f", "") for page in pages).encode())
    return cache.read_text(encoding="utf-8", errors="replace").split("\f")


def pdf_text(pdf: Path) -> str:
    """A PDF's text for reading, with a marker where each page starts."""
    pages = pdf_pages(pdf)
    return "\n".join(f"── page {n} of {len(pages)} ──\n{page}" for n, page in enumerate(pages, 1))


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


def zip_entries(path: Path) -> list[zipfile.ZipInfo]:
    """The entries of a zip file, capped for huge archives."""
    with zipfile.ZipFile(path) as archive:
        return archive.infolist()[:5000]


def contents(path: Path) -> str:
    """A PDF's text, a zip's file list, or why neither can be shown."""
    if path.suffix.lower() == ".pdf":
        return pdf_text(path)
    if path.suffix.lower() == ".zip":
        files = [e for e in zip_entries(path) if not e.is_dir()]
        return "\n".join(f"{e.filename}  ({e.file_size:,} bytes)" for e in files)
    return f"No preview for {path.suffix} files"


def recipients(record: dict, role: str) -> tuple[str, str, list[str]]:
    """Message invitation, parent group and recipients for one paper and role."""
    names, prefix = record["names"], record["prefix"]
    group = names["area_chairs"] if role == "spcs" else names["reviewers"]
    invitation = f"{prefix}{group}/-/Message" if role == "spcs" else f"{prefix}-/Message"
    members = record["groups"].get(group, [])
    if role == "late-reviewers":
        done = {r["signatures"][0] for r in replies(record, "review")}
        done |= {person(record, s) for s in done}
        members = [m for m in members if m not in done and person(record, m) not in done]
    return invitation, prefix + group, members


class Draft(NamedTuple):
    """One message, fully composed: sent through `record`'s message `invitation`."""

    record: dict
    invitation: str
    parent: str
    members: list[str]
    subject: str
    body: str
    to: str  # who it is for, for previews and logs ("reviewers of #7", "~Ada_Lovelace1")
    papers: tuple[int, ...] = ()  # the papers it is about (default: the one it goes through)
    template: str = ""  # the template it came from, if any
    issues: tuple[tuple[int, str], ...] = ()  # (number, code) of the issues it lists


class Comment(NamedTuple):
    """An Official_Comment on a paper's forum, signed as its SACs."""

    record: dict
    title: str
    text: str
    spcs_read: bool  # the paper's SPCs can read it (PCs and SACs always can)
    issues: tuple[tuple[int, str], ...] = ()  # (number, code) of the issues it lists


def record_history(file: Path | None, entry: dict) -> None:
    """Appends what the app sent (or failed to send) to the history, one JSON object per line."""
    if file is None:
        return
    file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    file.touch(mode=0o600)
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    with file.open("a", encoding="utf-8") as out:
        out.write(json.dumps(entry) + "\n")


def history(file: Path) -> list[dict]:
    """Everything the app sent, newest first."""
    if not file.is_file():
        return []
    lines = file.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in reversed(lines) if line.strip()]


def about(entry: dict, number: int) -> bool:
    return entry["via"] == number or number in entry.get("papers", [])


def mentions(entry: dict, number: int, code: str, message: str) -> bool:
    """Whether a history entry lists an issue: by its recorded issues or, in entries from
    before they were recorded, by the issue's message in the body."""
    if "issues" in entry:
        return [number, code] in entry["issues"]
    return about(entry, number) and message in entry["body"]


def deliver(
    client: Any,
    drafts: list[Draft],
    progress: Callable[[int, int], None] | None = None,
    history_file: Path | None = None,
) -> list[str]:
    """Posts the drafts, each signed as its paper's SACs, and records them in the history;
    returns the failures. `progress(sent, total)` runs before each message (it may stop the
    batch there, by raising)."""
    failures = []
    for count, d in enumerate(drafts):
        if progress:
            progress(count, len(drafts))
        entry = {
            "kind": "email",
            "via": d.record["number"],
            "papers": list(d.papers or (d.record["number"],)),
            "to": d.to,
            "recipients": d.members,
            "subject": d.subject,
            "body": d.body,
            "template": d.template,
            "issues": list(d.issues),
        }
        try:
            client.post_message(
                d.subject,
                d.members,
                d.body,
                invitation=d.invitation,
                signature=d.record["prefix"] + d.record["names"]["senior_area_chairs"],
                parentGroup=d.parent,
            )
            logger.debug("%s: sent to %d recipients", d.to, len(d.members))
            record_history(history_file, entry | {"status": "sent"})
        except Exception as e:  # keep going: the other messages are independent
            failures.append(f"{d.to}: not sent ({e})")
            logger.error("%s: not sent: %s", d.to, e)
            record_history(history_file, entry | {"status": f"failed: {e}"})
    return failures


def readers(comment: Comment) -> list[str]:
    """PCs and the paper's SACs always (the invitation requires them), its SPCs optionally."""
    prefix, names = comment.record["prefix"], comment.record["names"]
    venue = prefix.rsplit(f"/{names['submission']}", 1)[0]  # ".../Submission7/" -> venue id
    found = [f"{venue}/Program_Chairs", prefix + names["senior_area_chairs"]]
    return found + ([prefix + names["area_chairs"]] if comment.spcs_read else [])


def post_comments(
    client: Any,
    comments: list[Comment],
    progress: Callable[[int, int], None] | None = None,
    history_file: Path | None = None,
) -> list[str]:
    """Posts the comments and records them in the history; returns the failures."""
    from openreview.api import Note  # type: ignore[import-untyped]

    failures = []
    for count, c in enumerate(comments):
        if progress:
            progress(count, len(comments))
        number, prefix = c.record["number"], c.record["prefix"]
        entry = {
            "kind": "comment",
            "via": number,
            "papers": [number],
            "to": "PCs, SACs" + (" and SPCs" if c.spcs_read else ""),
            "recipients": readers(c),
            "subject": c.title,
            "body": c.text,
            "template": "",
            "issues": list(c.issues),
        }
        try:
            client.post_note_edit(
                invitation=f"{prefix}-/Official_Comment",
                signatures=[prefix + c.record["names"]["senior_area_chairs"]],
                note=Note(
                    forum=c.record["id"],
                    replyto=c.record["id"],
                    readers=readers(c),
                    content={"title": {"value": c.title}, "comment": {"value": c.text}},
                ),
            )
            logger.debug("#%s: comment posted", number)
            record_history(history_file, entry | {"status": "sent"})
        except Exception as e:  # keep going: the other papers' comments are independent
            failures.append(f"#{number}: not posted ({e})")
            logger.error("#%s: comment not posted: %s", number, e)
            record_history(history_file, entry | {"status": f"failed: {e}"})
    return failures
