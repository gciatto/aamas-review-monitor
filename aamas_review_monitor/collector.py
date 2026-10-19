"""Read-only OpenReview (API v2) collector.

`fetch` returns one record per paper the signed-in SAC supervises (content, replies, groups): it
is cached locally, never put in snapshots. `summarize` turns a record into snapshot metadata
(assignments, scores, word counts, reply counts): no titles, abstracts, PDFs or review text.
"""

import re
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


def fetch(client: Any, config: dict) -> list[dict]:
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
    records = []
    for note in sorted((n for n in notes if n.number in numbers), key=lambda n: n.number):
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


def summarize(record: dict, config: dict) -> dict:
    def field(content: dict, key: str) -> int | None:
        return _score(content.get(config[key], {}).get("value"))

    return {
        "number": record["number"],
        "url": config["url_forum"] + record["id"],
        "spcs": [
            person(record, m) for m in record["groups"].get(record["names"]["area_chairs"], [])
        ],
        "reviewers": [
            person(record, m) for m in record["groups"].get(record["names"]["reviewers"], [])
        ],
        "reviews": [
            {
                "reviewer": person(record, r["signatures"][0]),
                "rating": field(r["content"], "field_rating"),
                "confidence": field(r["content"], "field_confidence"),
                "words": _words(r["content"]),
            }
            for r in replies(record, "review")
        ],
        "meta_review": bool(replies(record, "meta_review")),
        "comments": len(replies(record, "Official_Comment")),
    }


def snapshot(records: list[dict], config: dict) -> dict:
    return {
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "papers": [summarize(r, config) for r in records],
    }
