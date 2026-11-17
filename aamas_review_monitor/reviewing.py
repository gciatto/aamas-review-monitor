"""Review rubric: criteria a helpful review meets, to spot the reviews worth a second look.

One YAML file (shipped, or the AC's copy in the data folder) lists criteria, each with public
example sentences that meet it (`meets`) and that fall short of it (`short`), plus rules
(`rules.py`). A review meets a criterion when one of its sentences is nearer the `meets`
examples than the `short` ones by `reviews_margin_min`, or when its rules score above zero; a
negative rule score rules the criterion out. A criterion that `compare`s with the abstract is
met when a sentence is that near the paper's title and abstract (`reviews_abstract_min`). A
review is poor below `reviews_rubric_min` of the criteria (by weight), or when it misses one
marked `alert`. A `presumed` criterion (tone, say) is met unless a negative rule, or a
sentence nearer the `short` examples than the `meets` ones by `reviews_margin_alert`, rules it
out: then the margin and evidence are the worst sentence's. Reviews only go to local
embedding endpoints. It measures how a review is written, never the paper, and suggests no
decision."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from aamas_review_monitor import models, rules
from aamas_review_monitor.areas import dump, similarity
from aamas_review_monitor.collector import replies
from aamas_review_monitor.papers import fields
from aamas_review_monitor.resources import FILE_REVIEW_RUBRIC_DEFAULT

KEYS = ("name", "sources", "criteria")
KEYS_CRITERION = ("key", "name", "weight", "advice", "meets", "short", "rules")
# alert: flags the review when missed; compare: "abstract"; presumed: met unless ruled out;
# margin: this criterion's own threshold, in place of reviews_margin_min (or, presumed,
# reviews_margin_alert; compared, reviews_abstract_min); 2 or more: its rules decide alone
KEYS_OPTIONAL = ("alert", "compare", "presumed", "margin")
PATTERN_PIECES = re.compile(r"(?<=[.?!;])\s+|\n+")
WORDS_PIECE_MIN = 4  # shorter pieces join the next one


def _texts(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(t, str) and t.strip() for t in value)
    )


def problems(rubric: Any) -> list[str]:
    """What makes a review rubric unusable."""
    if not isinstance(rubric, dict):
        return ["not a mapping of name, sources, criteria"]
    found = [f"missing {k}" for k in KEYS if k not in rubric]
    found += [f"unknown key {k}" for k in rubric if k not in KEYS]
    if found:
        return found
    if not isinstance(rubric["criteria"], list) or not rubric["criteria"]:
        return ["criteria should be a non-empty list"]
    keys = set()
    for i, c in enumerate(rubric["criteria"], 1):
        if not isinstance(c, dict):
            found.append(f"criterion {i}: should be a mapping of {', '.join(KEYS_CRITERION)}")
            continue
        name = f"criterion {c.get('key', i)}"
        found += [f"{name}: missing {k}" for k in KEYS_CRITERION if k not in c]
        found += [f"{name}: unknown key {k}" for k in c if k not in KEYS_CRITERION + KEYS_OPTIONAL]
        if c.get("compare", "abstract") != "abstract":
            found.append(f"{name}: compare can only be abstract")
        margin = c.get("margin", 0)
        if not isinstance(margin, (int, float)) or isinstance(margin, bool):
            found.append(f"{name}: margin should be a number")
        for flag in ("alert", "presumed"):
            if not isinstance(c.get(flag, False), bool):
                found.append(f"{name}: {flag} should be true or false")
        if not isinstance(c.get("key"), str) or not re.fullmatch(r"[a-z_]+", c["key"]):
            found.append(f"{name}: key should be lower-case letters, e.g. weaknesses")
        elif c["key"] in keys:
            found.append(f"{name}: key used twice")
        keys.add(c.get("key"))
        weight = c.get("weight")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            found.append(f"{name}: weight should be a positive number")
        for k in ("meets", "short"):
            if not _texts(c.get(k)) and not ("compare" in c and c.get(k) == []):
                found.append(f"{name}: {k} should be a non-empty list of sentences")
        if not isinstance(c.get("rules"), list):
            found.append(f"{name}: rules should be a list")
        else:
            for j, rule in enumerate(c["rules"], 1):
                found += [f"{name}, rule {j}: {p}" for p in rules.problems(rule)]
    return found


def read(text: str) -> dict:
    """A review rubric from its YAML; ValueError saying what is wrong with it."""
    try:
        rubric = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"not valid YAML: {e}") from None
    if found := problems(rubric):
        raise ValueError("; ".join(found))
    return rubric


def file(mine: Path) -> Path:
    """The AC's copy if any, else the shipped rubric."""
    return mine if mine.is_file() else FILE_REVIEW_RUBRIC_DEFAULT


def load(mine: Path) -> dict:
    """The review rubric in use; ValueError naming its file if unusable."""
    found = file(mine)
    try:
        return read(found.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ValueError(f"{found}: {e}") from None


def save(rubric: dict, mine: Path) -> Path:
    mine.parent.mkdir(parents=True, exist_ok=True)
    mine.write_text(dump(rubric), encoding="utf-8")
    return mine


def fingerprint(rubric: dict) -> str:
    return hashlib.sha256(dump(rubric).encode()).hexdigest()[:12]


def text(review: dict, config: dict) -> str:
    """A review's written text: its fields but the rating, the confidence and short ones
    (checkboxes, yes/no)."""
    skip = (config["field_rating"], config["field_confidence"])
    return "\n".join(v for _, v in fields(review["content"], skip) if len(v.split()) > 2)


def pieces(written: str) -> list[str]:
    """Sentences and list items, each joined to the next while shorter than WORDS_PIECE_MIN."""
    found, pending = [], ""
    for part in PATTERN_PIECES.split(written):
        pending = f"{pending} {part}".strip()
        if len(pending.split()) >= WORDS_PIECE_MIN:
            found.append(pending)
            pending = ""
    if pending:
        found.append(pending)
    return found


def exemplar_vectors(
    rubric: dict, s: models.Settings, cache: Path, cache_only: bool = False
) -> dict[str, tuple[list[list[float]], list[list[float]]]]:
    """Each criterion's (meets, short) vectors: public text, any endpoint."""
    flat = [t for c in rubric["criteria"] for k in ("meets", "short") for t in c[k]]
    vectors = iter(models.embed(s, flat, cache, private=False, cache_only=cache_only))
    return {
        c["key"]: tuple([next(vectors) for _ in c[k]] for k in ("meets", "short"))  # type: ignore[misc]
        for c in rubric["criteria"]
    }


def judge(
    rubric: dict,
    exemplars: dict[str, tuple[list[list[float]], list[list[float]]]],
    parts: list[str],
    vectors: list[list[float]],
    config: dict,
    paper: list[float] | None = None,
) -> dict[str, dict]:
    """Each criterion's verdict on one review: met, the best sentence's margin (or, comparing
    with the abstract, its similarity to `paper`) and the sentence, the rules that held."""
    k, threshold = config["reviews_top_k"], config["reviews_margin_min"]
    whole = "\n".join(parts)
    found_texts = {f: rules._normal(whole) for f in rules.FIELDS} | {"raw": whole}
    verdicts = {}
    for c in rubric["criteria"]:
        meets, short = exemplars[c["key"]]
        if "compare" in c:  # no abstract: nothing to compare with, so no alert
            margins = [similarity(v, [paper], 1) for v in vectors] if paper else []
            minimum = c.get("margin", config["reviews_abstract_min"]) if paper else -1.0
        else:
            margins = [similarity(v, meets, k) - similarity(v, short, k) for v in vectors]
            minimum = c.get("margin", threshold)
        pick = min if c.get("presumed") else max
        best = pick(range(len(margins)), key=margins.__getitem__, default=None)
        margin = round(margins[best], 4) if best is not None else None
        value, held = rules.score(c["rules"], found_texts)
        if c.get("presumed"):
            alert = c.get("margin", config["reviews_margin_alert"])
            ruled_out = margin is not None and margin <= -alert
            met = value > 0 or (value == 0 and not ruled_out)
        else:
            met = value > 0 or (value == 0 and (margin if margin is not None else 0) >= minimum)
        verdicts[c["key"]] = {
            "met": met,
            "margin": margin,
            "evidence": parts[best] if best is not None else "",
            "rules": held,
            "rule": value,  # the rules' weighted score: above 0 meets, below 0 rules out
        }
    return verdicts


def score(
    records: list[dict],
    rubric: dict,
    s: models.Settings,
    config: dict,
    cache: Path,
    cache_only: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[dict], list[str]]:
    """One result per review of the cached papers: paper, its anonymous name and id, words,
    rating, the criteria's verdicts and the weighted share met; also the reviews not scored, and
    why. The reviews' sentences only go to local endpoints."""
    exemplars = exemplar_vectors(rubric, s, cache, cache_only)
    weights = {c["key"]: c["weight"] for c in rubric["criteria"]}
    found, failures = [], []
    reviews = [(r, v) for r in records for v in replies(r, "review")]
    for count, (record, review) in enumerate(reviews):
        if progress:
            progress(count, len(reviews))
        name = review["signatures"][0].removeprefix(record["prefix"])
        written = text(review, config)
        parts = pieces(written)
        if not parts:
            failures.append(f"#{record['number']} {name}: no written text")
            continue
        try:
            vectors = models.embed(s, parts, cache, True, cache_only)
        except models.NotEmbedded as e:
            failures.append(f"#{record['number']} {name}: {e}")
            continue
        abstract = " ".join(
            str((record["content"].get(k) or {}).get("value") or "") for k in ("title", "abstract")
        ).strip()
        paper = None
        if abstract and any("compare" in c for c in rubric["criteria"]):
            try:
                (paper,) = models.embed(s, [abstract], cache, True, cache_only)
            except models.NotEmbedded:
                pass
        verdicts = judge(rubric, exemplars, parts, vectors, config, paper)
        alerts = [
            c["key"] for c in rubric["criteria"] if c.get("alert") and not verdicts[c["key"]]["met"]
        ]
        met = sum(weights[k] for k, v in verdicts.items() if v["met"])
        rating = review["content"].get(config["field_rating"], {}).get("value")
        found.append(
            {
                "number": record["number"],
                "name": name,
                "id": review.get("id"),
                "words": len(written.split()),
                "rating": rating,
                "score": round(met / sum(weights.values()), 4),
                "alerts": alerts,
                "criteria": verdicts,
            }
        )
    if progress:
        progress(len(reviews), len(reviews))
    return found, failures


def poor(results: list[dict], config: dict) -> list[dict]:
    """The reviews below `reviews_rubric_min`, or missing an alert criterion; the lowest
    first."""
    low = [r for r in results if r["score"] < config["reviews_rubric_min"] or r.get("alerts")]
    return sorted(low, key=lambda r: (r["score"], r["number"], r["name"]))


def missing(result: dict, rubric: dict) -> list[str]:
    """The names of the criteria a review does not meet."""
    return [c["name"] for c in rubric["criteria"] if not result["criteria"][c["key"]]["met"]]


def check(
    rubric: dict, s: models.Settings, cache: Path, config: dict, cache_only: bool = False
) -> dict[str, tuple[int, int]]:
    """How well each criterion's examples separate: each example, left out, judged by the
    others (public text only). Per criterion: right, total."""
    exemplars = exemplar_vectors(rubric, s, cache, cache_only)
    k, found = config["reviews_top_k"], {}
    for key, (meets, short) in exemplars.items():
        if not meets or not short:  # compared with the abstract: no examples
            continue
        right = 0
        for i, v in enumerate(meets):
            others = meets[:i] + meets[i + 1 :]
            right += (
                similarity(v, others, k) - similarity(v, short, k) >= config["reviews_margin_min"]
            )
        for i, v in enumerate(short):
            others = short[:i] + short[i + 1 :]
            right += (
                similarity(v, meets, k) - similarity(v, others, k) < config["reviews_margin_min"]
            )
        found[key] = (right, len(meets) + len(short))
    return found
