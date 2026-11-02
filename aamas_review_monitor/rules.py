"""Rubric rules: deterministic string matching on a paper's local text, no model involved.

    {any: [MARL, multi-agent reinforcement learning], in: [title, abstract], weight: 2}
    {all: [equilibrium, learning], near: 10, none: [argumentation]}
    {count: '\\bTheorem\\b', at_least: 3}
    {cites: [NeurIPS, ICML]}          # in the references section

A rule's value is 0 if it does not hold, else saturates with its matches: 1 - 1/2^matches."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from aamas_review_monitor import papers
from aamas_review_monitor.collector import replies

KINDS = ("any", "all", "count", "cites")
FIELDS = ("title", "keywords", "abstract", "text", "references", "reviews", "meta-reviews")
FIELDS_DEFAULT = ("title", "keywords", "abstract", "text")  # the paper itself
KEYS = {"in", "none", "near", "at_least", "weight", *KINDS}
PATTERN_REFERENCES = re.compile(r"\n\s*(references|bibliography)\s*\n", re.I)


def _terms(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(t, str) and t.strip() for t in value)
    )


def problems(rule: Any) -> list[str]:
    """What makes a rule unusable."""
    if not isinstance(rule, dict):
        return ["a rule should be a mapping, e.g. {any: [MARL], weight: 2}"]
    kinds = [k for k in KINDS if k in rule]
    found = [f"unknown key {k}" for k in rule if k not in KEYS]
    if len(kinds) != 1:
        return found + [f"a rule needs exactly one of {', '.join(KINDS)}"]
    kind = kinds[0]
    if kind == "count":
        try:
            re.compile(rule["count"])
        except (re.error, TypeError) as e:
            found.append(f"count should be a regular expression ({e})")
        if not isinstance(rule.get("at_least", 1), int):
            found.append("at_least should be a whole number")
    elif not _terms(rule[kind]):
        found.append(f"{kind} should be a list of terms")
    if "none" in rule and not _terms(rule["none"]):
        found.append("none should be a list of terms")
    if "near" in rule and (kind != "all" or not isinstance(rule["near"], int) or rule["near"] < 1):
        found.append("near goes with all, as a number of words")
    fields = rule.get("in", [])
    if not isinstance(fields, list) or not all(isinstance(f, str) and f in FIELDS for f in fields):
        found.append(f"in should list some of {', '.join(FIELDS)}")
    weight = rule.get("weight", 1)
    if not isinstance(weight, (int, float)) or isinstance(weight, bool):
        found.append("weight should be a number (negative: evidence against the area)")
    return found


def _normal(text: str) -> str:
    return " ".join(text.lower().split())


def texts(record: dict, config: dict, directory: Path) -> dict[str, str]:
    """A paper's text by field, lower-cased, from the cache: the PDF's text and references only
    if downloaded (and readable with pdftotext)."""

    def value(key: str) -> str:
        v = record["content"].get(key, {}).get("value")
        return " ".join(map(str, v)) if isinstance(v, list) else str(v or "")

    found = {k: value(k) for k in ("title", "keywords", "abstract")}
    pdf = papers.attachment(record, config["field_pdf"], directory)
    try:
        text = "\n".join(papers.pdf_pages(pdf)) if pdf is not None and pdf.is_file() else ""
    except FileNotFoundError:  # no pdftotext
        text = ""
    *_, references = PATTERN_REFERENCES.split(text) if PATTERN_REFERENCES.search(text) else [""]
    found |= {"text": text, "references": references}
    for kind, name in (("review", "reviews"), ("meta_review", "meta-reviews")):
        found[name] = "\n".join(
            v for r in replies(record, kind) for _, v in papers.fields(r["content"])
        )
    return {k: _normal(v) for k, v in found.items()} | {"raw": text}


def _positions(term: str, text: str) -> list[int]:
    """Where a phrase occurs, as word positions (whole words, any case)."""
    pattern = re.compile(rf"(?<!\w){re.escape(_normal(term))}(?!\w)")
    return [
        text.count(" ", 0, m.start()) + text.count("\n", 0, m.start())
        for m in pattern.finditer(text)
    ]


def evaluate(rule: dict, found: dict[str, str]) -> tuple[float, str]:
    """The rule's value on a paper's texts, and what matched (empty if nothing)."""
    fields = ["references"] if "cites" in rule else rule.get("in", FIELDS_DEFAULT)
    text = "\n".join(found[f] for f in fields)
    if any(_positions(t, text) for t in rule.get("none", [])):
        return 0.0, ""
    if "count" in rule:
        matches = len(re.findall(rule["count"], found["raw"] if "in" not in rule else text))
        holds = matches >= rule.get("at_least", 1)
        return (1.0, f"{rule['count']} ×{matches}") if holds else (0.0, "")
    terms = rule.get("any") or rule.get("cites") or rule["all"]
    hits = {t: _positions(t, text) for t in terms}
    if "all" in rule:
        if not all(hits.values()):
            return 0.0, ""
        first, *others = hits.values()
        near = rule.get("near")
        matches = sum(
            all(any(abs(p - q) <= near for q in positions) for positions in others) if near else 1
            for p in first
        )
    else:
        matches = sum(map(len, hits.values()))
    if not matches:
        return 0.0, ""
    return 1 - 0.5**matches, ", ".join(f"{t} ×{len(p)}" for t, p in hits.items() if p)


def score(rubric_rules: list[dict], found: dict[str, str]) -> tuple[float, list[str]]:
    """An area's rule score, the weighted mean of its rules' values (-1..1), and the rules that
    held, as evidence."""
    total = sum(abs(r.get("weight", 1)) for r in rubric_rules)
    value, held = 0.0, []
    for rule in rubric_rules:
        v, matched = evaluate(rule, found)
        if v:
            value += rule.get("weight", 1) * v
            held.append(f"{matched} ({rule.get('weight', 1):+g})")
    return (round(value / total, 4) if total else 0.0), held
