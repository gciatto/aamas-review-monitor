"""Read-only OpenReview (API v2) collector: turns what the signed-in SAC can see into a snapshot.

The snapshot keeps only process metadata (assignments, scores, word counts, reply counts):
no titles, abstracts, PDFs or review text.
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


def collect(client: Any, config: dict) -> dict:
    venue_id = config["venue_id"]
    venue = client.get_group(venue_id).content or {}

    def name(key: str, default: str) -> str:
        return venue.get(key, {}).get("value", default)

    submission = name("submission_name", "Submission")
    sacs = name("senior_area_chairs_name", "Senior_Area_Chairs")
    spcs = name("area_chairs_name", "Area_Chairs")
    reviewers = name("reviewers_name", "Reviewers")
    review = name("review_name", "Official_Review")
    meta_review = name("meta_review_name", "Meta_Review")

    prefix = f"{venue_id}/{submission}"
    mine = client.get_all_groups(member=client.profile.id, prefix=prefix)
    pattern = re.compile(rf"{re.escape(prefix)}(\d+)/{re.escape(sacs)}")
    numbers = {int(m.group(1)) for g in mine if (m := pattern.fullmatch(g.id))}
    logger.info("%d papers assigned to %s", len(numbers), client.profile.id)

    notes = client.get_all_notes(invitation=f"{venue_id}/-/{submission}", details="replies")
    papers = []
    for note in sorted((n for n in notes if n.number in numbers), key=lambda n: n.number):
        paper = f"{prefix}{note.number}/"
        groups = {g.id.removeprefix(paper): g.members for g in client.get_all_groups(prefix=paper)}

        def person(member: str, groups: dict = groups, paper: str = paper) -> str:
            # Role groups and signatures use anonymous groups (".../Area_Chair_9jqi"): resolve
            # them to profiles when their members are visible, else keep the anonymous id
            return (groups.get(member.removeprefix(paper)) or [member])[0]

        replies = (note.details or {}).get("replies", [])

        def of(kind: str, replies: list = replies) -> list:
            return [r for r in replies if any(i.endswith(f"/-/{kind}") for i in r["invitations"])]

        papers.append(
            {
                "number": note.number,
                "url": config["url_forum"] + note.id,
                "spcs": [person(m) for m in groups.get(spcs, [])],
                "reviewers": [person(m) for m in groups.get(reviewers, [])],
                "reviews": [
                    {
                        "reviewer": person(sig),
                        "rating": _score(r["content"].get(config["field_rating"], {}).get("value")),
                        "confidence": _score(
                            r["content"].get(config["field_confidence"], {}).get("value")
                        ),
                        "words": _words(r["content"]),
                    }
                    for r in of(review)
                    for sig in r["signatures"][:1]
                ],
                "meta_review": bool(of(meta_review)),
                "comments": len(of("Official_Comment")),
            }
        )
    return {"taken_at": datetime.now(timezone.utc).isoformat(), "papers": papers}
