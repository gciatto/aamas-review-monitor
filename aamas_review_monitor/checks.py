"""Deterministic process checks over a snapshot. They flag review-process health, never quality."""

import csv
from collections import defaultdict
from datetime import date
from typing import IO, NamedTuple

RED, YELLOW, GREEN = "RED", "YELLOW", "GREEN"


class Issue(NamedTuple):
    number: int
    severity: str
    code: str  # stable across days, so history can tell new issues from resolved ones
    message: str
    url: str
    spcs: tuple[str, ...]


def _deadline(
    missing: int, what: str, days: int, warning: int, critical: int
) -> tuple[str, str] | None:
    if not missing or days > warning:
        return None
    if days < 0:
        return RED, f"{missing} {what} missing, {-days} days overdue"
    return (RED if days <= critical else YELLOW), f"{missing} {what} missing, {days} days left"


def check_paper(paper: dict, config: dict, today: date) -> list[Issue]:
    found: list[tuple[str, str, str]] = []
    reviews, reviewers = paper["reviews"], paper["reviewers"]
    days_reviews = (date.fromisoformat(config["deadline_reviews"]) - today).days
    days_meta = (date.fromisoformat(config["deadline_meta_reviews"]) - today).days

    if not paper["spcs"]:
        found.append((RED, "no_spc", "no SPC assigned"))
    if len(reviewers) < config["reviewers_min"]:
        found.append((RED, "few_reviewers", f"{len(reviewers)} reviewers assigned"))
    late = _deadline(
        max(len(reviewers) - len(reviews), 0),
        "reviews",
        days_reviews,
        config["reviews_warning_days"],
        config["reviews_critical_days"],
    )
    if late:
        found.append((late[0], "missing_reviews", late[1]))
    for r in reviews:
        if r["words"] < config["reviews_words_min"]:
            found.append((YELLOW, f"short_review:{r['reviewer']}", f"review of {r['words']} words"))
    ratings = [r["rating"] for r in reviews if r["rating"] is not None]
    if ratings and max(ratings) - min(ratings) >= config["scores_spread_max"]:
        found.append((YELLOW, "disagreement", f"ratings {sorted(ratings)}"))
        if days_reviews < 0 and not paper["comments"]:
            found.append((RED, "no_discussion", "reviewers disagree and nobody has commented"))
    late = _deadline(
        0 if paper["meta_review"] else 1,
        "meta-review",
        days_meta,
        config["meta_reviews_warning_days"],
        config["meta_reviews_warning_days"],
    )
    if late:
        found.append((late[0], "missing_meta_review", late[1]))
    spcs = tuple(paper["spcs"])
    return [Issue(paper["number"], s, c, m, paper["url"], spcs) for s, c, m in found]


def check(snapshot: dict, config: dict) -> list[Issue]:
    today = date.fromisoformat(snapshot["taken_at"][:10])
    issues = [i for p in snapshot["papers"] for i in check_paper(p, config, today)]
    return sorted(issues, key=lambda i: (i.severity != RED, i.number, i.code))


def report(snapshot: dict, config: dict, previous: dict | None = None) -> str:
    issues = check(snapshot, config)
    status = {p["number"]: GREEN for p in snapshot["papers"]}
    for i in issues:
        status[i.number] = RED if RED in (status[i.number], i.severity) else YELLOW
    counts = {s: list(status.values()).count(s) for s in (RED, YELLOW, GREEN)}
    lines = [f"{len(status)} papers: " + ", ".join(f"{n} {s}" for s, n in counts.items())]

    resolved: dict[str, int] = defaultdict(int)
    if previous:
        now = {(i.number, i.code) for i in issues}
        before = check(previous, config)
        for i in before:
            if (i.number, i.code) not in now:
                for spc in i.spcs or ("(no SPC)",):
                    resolved[spc] += 1
        then = {(i.number, i.code) for i in before}
        lines.append(
            f"Since {previous['taken_at'][:16]}: {len(now - then)} new issues, "
            f"{len(then - now)} resolved"
        )

    by_spc: dict[str, list[Issue]] = defaultdict(list)
    for i in issues:
        for spc in i.spcs or ("(no SPC)",):
            by_spc[spc].append(i)
    for spc, mine in sorted(by_spc.items(), key=lambda kv: -sum(i.severity == RED for i in kv[1])):
        reds = sum(i.severity == RED for i in mine)
        lines.append(f"\n{spc}: {len(mine)} open ({reds} RED), {resolved[spc]} resolved since")
        lines += [f"  {i.severity:6} #{i.number:<5} {i.message}  {i.url}" for i in mine]
    return "\n".join(lines)


def write_csv(issues: list[Issue], file: IO[str]) -> None:
    writer = csv.writer(file)
    writer.writerow(Issue._fields)
    writer.writerows((*i[:5], ";".join(i.spcs)) for i in issues)
