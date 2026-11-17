"""Measures the review rubric on public peer reviews: ICLR 2017, from PeerRead (AllenAI).

uv run poe reviews-benchmark [--split dev|test|all] [--rubric FILE] [--model M]
                             [--margin-min X] [--margin-alert X] [--abstract-min X]

Downloads PeerRead's ICLR 2017 dev and test reviews once into --cache (~/.cache by default),
keeps the official reviews (those with a recommendation), scores them as the app does (rules,
and a local embedding endpoint), and prints:
- how often each criterion is met, the share of poor reviews and the most common alerts;
- agreement with the hand labels in iclr2017_review_labels.json, per criterion;
- the summary check: each review against its own paper's abstract and against another paper's,
  with the accuracy of `reviews_abstract_min` and the best threshold on this data.
Public data only; nothing here touches the app's data folder.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parents[1]))

from aamas_review_monitor import core, models, reviewing  # noqa: E402
from aamas_review_monitor.resources import FILE_REVIEW_RUBRIC_DEFAULT  # noqa: E402

URL_LIST = "https://api.github.com/repos/allenai/PeerRead/contents/data/iclr_2017/{}/reviews"
URL_RAW = "https://raw.githubusercontent.com/allenai/PeerRead/master/data/iclr_2017/{}/reviews/{}"
FILE_LABELS = Path(__file__).with_name("iclr2017_review_labels.json")
SPLITS = ("dev", "test")
WORDS_MIN = 30  # shorter entries are notes, not reviews


def download(split: str, cache: Path) -> list[Path]:
    """The split's paper files, fetched once."""
    folder = cache / split
    if not folder.is_dir():
        listing = requests.get(URL_LIST.format(split), timeout=60)
        listing.raise_for_status()
        folder.mkdir(parents=True)
        for item in listing.json():
            response = requests.get(URL_RAW.format(split, item["name"]), timeout=60)
            response.raise_for_status()
            (folder / item["name"]).write_bytes(response.content)
    return sorted(folder.glob("*.json"), key=lambda f: int(f.stem))


def record(paper: dict, split: str, number: int) -> dict:
    """A paper and its official reviews (with a recommendation; deduplicated), shaped like the
    app's cached records."""
    prefix = f"ICLR2017/{split}/Paper{number}/"
    seen: set[str] = set()
    replies: list[dict] = []
    for review in paper["reviews"]:
        text = (review.get("comments") or "").strip()
        if review.get("IS_META_REVIEW") or "RECOMMENDATION" not in review or text in seen:
            continue
        if len(text.split()) < WORDS_MIN:
            continue
        seen.add(text)
        k = len(replies) + 1
        replies.append(
            {
                "id": f"{split}-{paper['id']}-{k}",
                "invitations": [f"{prefix}-/Official_Review"],
                "signatures": [f"{prefix}Reviewer_{k}"],
                "content": {
                    "review": {"value": text},
                    "rating": {"value": review["RECOMMENDATION"]},
                    "confidence": {"value": review.get("REVIEWER_CONFIDENCE")},
                },
            }
        )
    return {
        "id": f"{split}-{paper['id']}",
        "number": number,
        "prefix": prefix,
        "names": {"review": "Official_Review"},
        "content": {
            "title": {"value": paper.get("title") or ""},
            "abstract": {"value": paper.get("abstract") or ""},
        },
        "replies": replies,
    }


def records(splits: tuple[str, ...], cache: Path) -> list[dict]:
    found = []
    for split in splits:
        for f in download(split, cache):
            r = record(json.loads(f.read_text(encoding="utf-8")), split, int(f.stem))
            if r["replies"]:
                found.append(r)
    return found


def swapped(found: list[dict]) -> list[dict]:
    """Each paper's reviews under the next paper's title and abstract."""
    return [r | {"content": found[(i + 1) % len(found)]["content"]} for i, r in enumerate(found)]


def agreement(results: list[dict], labels: dict[str, dict[str, int]]) -> dict[str, list[int]]:
    """Per criterion: [agree, total, labelled missing, flagged missing and labelled so]."""
    found: dict[str, list[int]] = {}
    for r in results:
        theirs = labels.get(r["id"])
        if not theirs:
            continue
        for key, verdict in r["criteria"].items():
            if key not in theirs:
                continue
            counts = found.setdefault(key, [0, 0, 0, 0])
            counts[0] += int(verdict["met"]) == theirs[key]
            counts[1] += 1
            counts[2] += theirs[key] == 0
            counts[3] += theirs[key] == 0 and not verdict["met"]
    return found


def best_threshold(own: list[float], other: list[float]) -> tuple[float, float]:
    """The cut that best tells own abstracts (above) from others' (below), and its accuracy."""
    cuts = sorted(set(own + other))
    scored = [
        ((sum(v >= c for v in own) + sum(v < c for v in other)) / (len(own) + len(other)), c)
        for c in cuts
    ]
    accuracy, cut = max(scored)
    return round(cut, 3), accuracy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=(*SPLITS, "all"), default="all")
    parser.add_argument("--rubric", type=Path, default=FILE_REVIEW_RUBRIC_DEFAULT)
    parser.add_argument("--model", help="embedding model (default: the app's)")
    parser.add_argument("--margin-min", type=float)
    parser.add_argument("--margin-alert", type=float)
    parser.add_argument("--abstract-min", type=float)
    parser.add_argument(
        "--cache", type=Path, default=Path.home() / ".cache" / "aamas-reviews-benchmark"
    )
    args = parser.parse_args()

    config = json.loads((Path(core.__file__).parent / "resources" / "config.json").read_text())
    config |= {"field_rating": "rating", "field_confidence": "confidence"}
    for key in ("margin_min", "margin_alert", "abstract_min"):
        if getattr(args, key) is not None:
            config[f"reviews_{key}"] = getattr(args, key)
    rubric = reviewing.read(args.rubric.read_text(encoding="utf-8"))
    s = models.settings(config, model=args.model)
    embeddings = args.cache / "embeddings"

    found = records(SPLITS if args.split == "all" else (args.split,), args.cache)
    results, failures = reviewing.score(found, rubric, s, config, embeddings)

    poor = reviewing.poor(results, config)
    print(
        f"{s.model}; rubric {reviewing.fingerprint(rubric)}; {len(found)} papers, "
        f"{len(results)} reviews ({args.split}); margin_min {config['reviews_margin_min']}, "
        f"margin_alert {config['reviews_margin_alert']}, abstract_min "
        f"{config['reviews_abstract_min']}"
    )
    scores = [r["score"] for r in results]
    print(
        f"Scores: median {statistics.median(scores):.0%}, quartiles "
        + ", ".join(f"{q:.0%}" for q in statistics.quantiles(scores, n=4))
        + f"; poor: {len(poor)} ({len(poor) / len(results):.0%})"
    )
    alerts = Counter(a for r in results for a in r["alerts"])
    print("Alerts: " + (", ".join(f"{k} {n}" for k, n in alerts.most_common()) or "none"))

    labels = json.loads(FILE_LABELS.read_text(encoding="utf-8")) if FILE_LABELS.is_file() else {}
    labelled = agreement(results, labels)
    print("\nCriterion       met   labels: agree  missing found")
    for c in rubric["criteria"]:
        key = c["key"]
        met = sum(r["criteria"][key]["met"] for r in results) / len(results)
        line = f"{key:15} {met:4.0%}"
        if key in labelled:
            agree, total, missing, caught = labelled[key]
            line += f"   {agree:>3}/{total:<3} {agree / total:4.0%}  {caught}/{missing}"
        print(line)

    if any("compare" in c for c in rubric["criteria"]):
        key = next(c["key"] for c in rubric["criteria"] if "compare" in c)
        others, _ = reviewing.score(swapped(found), rubric, s, config, embeddings)
        own = [r["criteria"][key]["margin"] for r in results if r["criteria"][key]["margin"]]
        other = [r["criteria"][key]["margin"] for r in others if r["criteria"][key]["margin"]]
        flagged = sum(not r["criteria"][key]["met"] for r in others) / len(others)
        kept = sum(r["criteria"][key]["met"] for r in results) / len(results)
        cut, accuracy = best_threshold(own, other)
        print(
            f"\nSummary check ({key}): similarity to the own abstract median "
            f"{statistics.median(own):.3f}, to another paper's {statistics.median(other):.3f}; "
            f"at {config['reviews_abstract_min']}: own met {kept:.0%}, others flagged "
            f"{flagged:.0%}; best threshold {cut} ({accuracy:.0%})"
        )
    if failures:
        print(f"\nNot scored: {len(failures)}, e.g. {failures[0]}")


if __name__ == "__main__":
    main()
