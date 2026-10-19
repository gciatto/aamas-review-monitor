"""Per-paper operations over the local cache of collector records: metadata, reviews, PDFs, emails.

Layout: `<dir>/<number>/record.json` plus downloaded attachments next to it.
"""

import json
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

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


def pdf_text(pdf: Path) -> str:
    """Text of a PDF via xpdf's pdftotext, cached next to it.

    pdftotext's default mode follows reading order, so two-column pages (as in AAMAS) come out
    one column after the other; `-layout` would interleave the columns line by line.
    """
    text = pdf.with_name(pdf.name + ".txt")
    if not text.is_file():
        tool = shutil.which("pdftotext")
        if not tool:
            raise FileNotFoundError("pdftotext not found: install xpdf (`brew install xpdf`)")
        subprocess.run([tool, "-enc", "UTF-8", "-q", str(pdf), str(text)], check=True)
        text.chmod(0o600)
    return text.read_text(encoding="utf-8", errors="replace")


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


Plan = list[tuple[dict, str, str, list[str]]]  # (record, invitation, parent group, recipients)


def plan(records: list[dict], role: str) -> Plan:
    """One message per paper with someone to email in `role`."""
    return [(r, *recipients(r, role)) for r in records if recipients(r, role)[2]]


def describe(messages: Plan, role: str, subject: str, body: str) -> str:
    numbers = ", ".join(f"#{m[0]['number']}" for m in messages)
    total = sum(len(m[3]) for m in messages)
    return (
        f"To: {role} of papers {numbers}\n({len(messages)} messages, {total} recipients)\n"
        f"Subject: {subject}\n\n{body}"
    )


def send(client: Any, messages: Plan, subject: str, body: str) -> list[str]:
    """Posts the messages, signed as each paper's SACs; returns the failures."""
    failures = []
    for record, invitation, parent, members in messages:
        try:
            client.post_message(
                subject,
                members,
                body,
                invitation=invitation,
                signature=record["prefix"] + record["names"]["senior_area_chairs"],
                parentGroup=parent,
            )
        except Exception as e:  # keep going: the other papers' messages are independent
            failures.append(f"#{record['number']}: not sent ({e})")
    return failures


def email(
    client: Any,
    records: list[dict],
    role: str,
    subject: str,
    body: str,
    confirm: Callable[[str], str] | None = None,
) -> int:
    """Sends one message per paper to `role`, only after the user types SEND. Returns how many."""
    messages = plan(records, role)
    if not messages:
        print(f"No {role} to email")
        return 0
    print(describe(messages, role, subject, body) + "\n")
    if (confirm or input)(f"Type SEND to send {len(messages)} messages: ").strip() != "SEND":
        print("Nothing sent")
        return 0
    failures = send(client, messages, subject, body)
    print("\n".join([*failures, f"Sent {len(messages) - len(failures)} of {len(messages)}"]))
    return len(messages) - len(failures)
