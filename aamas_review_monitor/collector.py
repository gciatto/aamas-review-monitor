"""Read-only OpenReview (API v2) collector.

`fetch` returns one record per paper the signed-in SAC supervises (content, replies, groups): it
is cached locally, never put in snapshots. `summarize` turns a record into snapshot metadata
(assignments, scores, word counts, reply counts): no titles, abstracts, PDFs or review text.
"""

import re
import zlib
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from aamas_review_monitor import logger


def _score(value: Any) -> int | None:
    # OpenReview scores are ints or strings like "6: marginally above threshold"
    match = re.match(r"\s*(-?\d+)", str(value))
    return int(match.group(1)) if match else None


def _words(content: dict) -> int:
    return sum(len(f["value"].split()) for f in content.values() if isinstance(f.get("value"), str))


def person(record: dict, member: str) -> str:
    # Role groups and signatures use anonymous groups (".../Area_Chair_9jqi"): resolve them to
    # profiles when their members are visible, else keep the anonymous id
    return (record["groups"].get(member.removeprefix(record["prefix"])) or [member])[0]


def replies(record: dict, kind: str) -> list[dict]:
    """Replies of one kind ("review", "meta_review", or an invitation name like "Official_Comment")."""
    name = record["names"].get(kind, kind)
    return [r for r in record["replies"] if any(i.endswith(f"/-/{name}") for i in r["invitations"])]


def fetch(
    client: Any, config: dict, progress: Callable[[int, int], None] | None = None
) -> list[dict]:
    """Records of the signed-in SAC's papers; `progress(done, total)` follows the slow part."""
    venue_id = config["venue_id"]
    venue = client.get_group(venue_id).content or {}
    names = {
        key: venue.get(f"{key}_name", {}).get("value", default)
        for key, default in [
            ("submission", "Submission"),
            ("senior_area_chairs", "Senior_Area_Chairs"),
            ("area_chairs", "Area_Chairs"),
            ("reviewers", "Reviewers"),
            ("review", "Official_Review"),
            ("meta_review", "Meta_Review"),
            ("reviewers_anon", "Reviewer_"),
            ("area_chairs_anon", "Area_Chair_"),
        ]
    }
    prefix = f"{venue_id}/{names['submission']}"
    mine = client.get_all_groups(member=client.profile.id, prefix=prefix)
    pattern = re.compile(rf"{re.escape(prefix)}(\d+)/{re.escape(names['senior_area_chairs'])}")
    numbers = {int(m.group(1)) for g in mine if (m := pattern.fullmatch(g.id))}
    logger.info("%d papers assigned to %s", len(numbers), client.profile.id)

    notes = client.get_all_notes(
        invitation=f"{venue_id}/-/{names['submission']}", details="replies"
    )
    records: list[dict] = []
    mine_notes = sorted((n for n in notes if n.number in numbers), key=lambda n: n.number)
    for note in mine_notes:
        if progress:
            progress(len(records), len(mine_notes))
        paper = f"{prefix}{note.number}/"
        groups = client.get_all_groups(prefix=paper)
        records.append(
            {
                "id": note.id,
                "number": note.number,
                "prefix": paper,
                "names": names,
                "content": note.content,
                "replies": (note.details or {}).get("replies", []),
                "groups": {g.id.removeprefix(paper): g.members for g in groups},
            }
        )
    return records


def _date(reply: dict, *keys: str) -> str | None:
    """ISO date of the first timestamp present among `keys` (OpenReview uses milliseconds)."""
    for key in keys:
        if reply.get(key):
            return datetime.fromtimestamp(reply[key] / 1000, timezone.utc).date().isoformat()
    return None


def fingerprint(text: str, size: int = 32) -> list[int]:
    """MinHash of the text's 5-word shingles: compares texts without storing them."""
    words = text.lower().split()
    shingles = {" ".join(words[i : i + 5]) for i in range(max(len(words) - 4, 1))}
    return [min(zlib.crc32(f"{k}:{s}".encode()) for s in shingles) for k in range(size)]


def _role(record: dict, signature: str) -> str:
    name = signature.removeprefix(record["prefix"])
    names = record["names"]
    if name.startswith(names.get("reviewers_anon", "Reviewer_")):
        return "reviewer"
    if name.startswith(names.get("area_chairs_anon", "Area_Chair_")):
        return "spc"
    return "authors" if name == "Authors" else "other"


def _value(content: dict, key: str) -> Any:
    return content.get(key, {}).get("value")


def summarize(record: dict, config: dict) -> dict:
    def text(content: dict) -> str:
        return " ".join(f["value"] for f in content.values() if isinstance(f.get("value"), str))

    meta = replies(record, "meta_review")
    rebuttals = [_date(r, "cdate", "tcdate") for r in replies(record, "Rebuttal")]
    venueid = str(_value(record["content"], "venueid") or "")
    return {
        "number": record["number"],
        "url": config["url_forum"] + record["id"],
        "status": next((s for s in ("Withdrawn", "Desk_Rejected") if s in venueid), "active"),
        "findings_opt_in": _value(record["content"], config["field_findings_opt_in"]),
        "spcs": [
            person(record, m) for m in record["groups"].get(record["names"]["area_chairs"], [])
        ],
        "reviewers": [
            person(record, m) for m in record["groups"].get(record["names"]["reviewers"], [])
        ],
        "reviews": [
            {
                "reviewer": person(record, r["signatures"][0]),
                "rating": _score(_value(r["content"], config["field_rating"])),
                "confidence": _score(_value(r["content"], config["field_confidence"])),
                "words": _words(r["content"]),
                "created": _date(r, "cdate", "tcdate"),
                "modified": _date(r, "tmdate", "mdate", "cdate"),
                "fingerprint": fingerprint(text(r["content"])),
            }
            for r in replies(record, "review")
        ],
        "meta_review": bool(meta),
        "meta": {
            "words": _words(meta[0]["content"]),
            "proceedings": _value(meta[0]["content"], config["field_meta_proceedings"]),
            "findings": _value(meta[0]["content"], config["field_meta_findings"]),
        }
        if meta
        else None,
        "comments": len(replies(record, "Official_Comment")),
        "posts": [
            {
                "who": person(record, r["signatures"][0]),
                "role": _role(record, r["signatures"][0]),
                "date": _date(r, "cdate", "tcdate"),
            }
            for r in replies(record, "Official_Comment")
        ],
        "rebuttal": min((d for d in rebuttals if d), default=None),
    }


def snapshot(records: list[dict], config: dict) -> dict:
    return {
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "papers": [summarize(r, config) for r in records],
    }
