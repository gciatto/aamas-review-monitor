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
from pathlib import Path
from typing import Any

import yaml

from aamas_review_monitor import rules
from aamas_review_monitor.areas import dump
from aamas_review_monitor.resources import FILE_REVIEW_RUBRIC_DEFAULT

KEYS = ("name", "sources", "criteria")
KEYS_CRITERION = ("key", "name", "weight", "advice", "meets", "short", "rules")
# alert: flags the review when missed; compare: "abstract"; presumed: met unless ruled out;
# margin: this criterion's own threshold, in place of reviews_margin_min (or, presumed,
# reviews_margin_alert; compared, reviews_abstract_min); 2 or more: its rules decide alone
KEYS_OPTIONAL = ("alert", "compare", "presumed", "margin")


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
