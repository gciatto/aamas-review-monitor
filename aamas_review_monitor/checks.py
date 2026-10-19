"""Deterministic process checks over a snapshot. They flag review-process health, never quality."""

import csv
import inspect
from collections import defaultdict
from collections.abc import Callable
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


class Finding(NamedTuple):
    severity: str
    message: str
    detail: str = ""  # tells apart several findings of one check, e.g. one per reviewer


Check = Callable[[dict, dict, date], list[Finding]]

# Paper checks, in display order. Convention for each one (see `paper_check`):
# - the function name is the issue code (stable across days, used by the history diff);
# - the docstring's first line says what holds when the paper passes ("SPC assigned");
# - the rest says what is flagged and how severely, with {config_key} placeholders that the
#   legend fills in from the configuration.
CHECKS: list[Check] = []


def paper_check(function: Check) -> Check:
    """Registers a paper check; it must follow the docstring convention above."""
    assert function.__doc__ and "\n\n" in inspect.cleandoc(function.__doc__), function.__name__
    CHECKS.append(function)
    return function


def _days(config: dict, key: str, today: date) -> int:
    return (date.fromisoformat(config[key]) - today).days


def _deadline(missing: int, what: str, days: int, warning: int, critical: int) -> list[Finding]:
    if not missing or days > warning:
        return []
    if days < 0:
        return [Finding(RED, f"{missing} {what} missing, {-days} days overdue")]
    severity = RED if days <= critical else YELLOW
    return [Finding(severity, f"{missing} {what} missing, {days} days left")]


def _spread(paper: dict) -> list[int]:
    return sorted(r["rating"] for r in paper["reviews"] if r["rating"] is not None)


@paper_check
def no_spc(paper: dict, config: dict, today: date) -> list[Finding]:
    """SPC assigned

    RED when the paper has no SPC (Area Chair) assigned.
    """
    return [] if paper["spcs"] else [Finding(RED, "no SPC assigned")]


@paper_check
def few_reviewers(paper: dict, config: dict, today: date) -> list[Finding]:
    """Enough reviewers assigned

    RED when fewer than {reviewers_min} reviewers are assigned.
    """
    count = len(paper["reviewers"])
    return [Finding(RED, f"{count} reviewers assigned")] if count < config["reviewers_min"] else []


@paper_check
def missing_reviews(paper: dict, config: dict, today: date) -> list[Finding]:
    """Reviews on schedule

    Counts assigned reviewers without a submitted review. From {reviews_warning_days} days
    before the review deadline ({deadline_reviews}) it is YELLOW, from {reviews_critical_days}
    days before and once overdue RED.
    """
    return _deadline(
        max(len(paper["reviewers"]) - len(paper["reviews"]), 0),
        "reviews",
        _days(config, "deadline_reviews", today),
        config["reviews_warning_days"],
        config["reviews_critical_days"],
    )


@paper_check
def short_review(paper: dict, config: dict, today: date) -> list[Finding]:
    """Reviews long enough

    YELLOW for each submitted review shorter than {reviews_words_min} words (all text fields
    counted together).
    """
    return [
        Finding(YELLOW, f"review of {r['words']} words", r["reviewer"])
        for r in paper["reviews"]
        if r["words"] < config["reviews_words_min"]
    ]


@paper_check
def disagreement(paper: dict, config: dict, today: date) -> list[Finding]:
    """Ratings within the allowed spread

    YELLOW when the highest and lowest ratings differ by {scores_spread_max} or more.
    """
    ratings = _spread(paper)
    if ratings and ratings[-1] - ratings[0] >= config["scores_spread_max"]:
        return [Finding(YELLOW, f"ratings {ratings}")]
    return []


@paper_check
def no_discussion(paper: dict, config: dict, today: date) -> list[Finding]:
    """No undiscussed disagreement

    RED when, after the review deadline ({deadline_reviews}), ratings differ by
    {scores_spread_max} or more and nobody has posted a comment.
    """
    ratings = _spread(paper)
    disagree = ratings and ratings[-1] - ratings[0] >= config["scores_spread_max"]
    if disagree and _days(config, "deadline_reviews", today) < 0 and not paper["comments"]:
        return [Finding(RED, "reviewers disagree and nobody has commented")]
    return []


@paper_check
def missing_meta_review(paper: dict, config: dict, today: date) -> list[Finding]:
    """Meta-review on schedule

    RED when there is no meta-review from {meta_reviews_warning_days} days before its
    deadline ({deadline_meta_reviews}) on.
    """
    days, warning = (
        _days(config, "deadline_meta_reviews", today),
        config["meta_reviews_warning_days"],
    )
    return _deadline(0 if paper["meta_review"] else 1, "meta-review", days, warning, warning)


def check_paper(paper: dict, config: dict, today: date) -> list[Issue]:
    issues = []
    for function in CHECKS:
        for f in function(paper, config, today):
            code = function.__name__ + (f":{f.detail}" if f.detail else "")
            issues.append(
                Issue(
                    paper["number"], f.severity, code, f.message, paper["url"], tuple(paper["spcs"])
                )
            )
    return issues


def _doc(function: Check) -> tuple[str, str]:
    label, _, description = inspect.cleandoc(function.__doc__ or "").partition("\n\n")
    return label, " ".join(description.split())


def legend(config: dict) -> list[tuple[str, str, str]]:
    """(code, label, description) of every check, thresholds filled in from `config`."""
    return [(f.__name__, _doc(f)[0], _doc(f)[1].format_map(config)) for f in CHECKS]


def passed(issues: list[Issue]) -> list[str]:
    """Labels of the checks a paper passes, given its issues."""
    failed = {i.code.split(":")[0] for i in issues}
    return [_doc(f)[0] for f in CHECKS if f.__name__ not in failed]


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
