"""Per-paper operations over the local cache of collector records: metadata, reviews, PDFs, emails.

Layout: `<dir>/<number>/record.json` plus downloaded attachments next to it.
"""

import json
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
    return fields(record["content"], (config["field_pdf"], config["field_supplementary"]))


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


def download(client: Any, record: dict, field: str, directory: Path) -> Path | None:
    """Downloads an attachment unless the cached copy is current; None if the paper has none."""
    value = record["content"].get(field, {}).get("value")
    if not value:
        return None
    # ponytail: OpenReview attachment paths change with each upload, so the name is the version
    target = directory / str(record["number"]) / f"{field}_{PurePosixPath(value).name}"
    if not target.is_file():
        for old in target.parent.glob(f"{field}_*"):
            old.unlink()
        _write(target, client.get_attachment(field, id=record["id"]))
    return target


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


def email(
    client: Any,
    records: list[dict],
    role: str,
    subject: str,
    body: str,
    confirm: Callable[[str], str] | None = None,
) -> int:
    """Sends one message per paper to `role`, only after the user types SEND. Returns how many."""
    plan = [(record, *recipients(record, role)) for record in records]
    plan = [p for p in plan if p[3]]
    if not plan:
        print(f"No {role} to email")
        return 0
    total = sum(len(p[3]) for p in plan)
    numbers = ", ".join(f"#{p[0]['number']}" for p in plan)
    print(f"To: {role} of papers {numbers}")
    print(f"({len(plan)} messages, {total} recipients)\nSubject: {subject}\n\n{body}\n")
    if (confirm or input)(f"Type SEND to send {len(plan)} messages: ").strip() != "SEND":
        print("Nothing sent")
        return 0
    sent = 0
    for record, invitation, parent, members in plan:
        try:
            client.post_message(
                subject,
                members,
                body,
                invitation=invitation,
                signature=record["prefix"] + record["names"]["senior_area_chairs"],
                parentGroup=parent,
            )
            sent += 1
        except Exception as e:  # keep going: the other papers' messages are independent
            print(f"#{record['number']}: not sent ({e})")
    print(f"Sent {sent} of {len(plan)} messages")
    return sent
