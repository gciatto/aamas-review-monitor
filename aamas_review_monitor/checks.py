"""Deterministic process checks over a snapshot. They flag review-process health, never quality."""

import csv
import inspect
from collections import Counter, defaultdict
from collections.abc import Callable, Collection
from datetime import date
from typing import IO, Any, NamedTuple, TypeVar

from aamas_review_monitor import markers

RED, YELLOW, GREEN = "RED", "YELLOW", "GREEN"
ICONS = {RED: "🔴", YELLOW: "🟡", GREEN: "🟢"}


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


class Context(NamedTuple):
    config: dict
    today: date
    papers: list[dict]  # every paper of the snapshot, for checks that look across papers


Check = Callable[[dict, Context], list[Finding]]
F = TypeVar("F", bound=Callable[..., list[Finding]])

# Checks, in display order. Convention for each one (see `registrar`):
# - the function name is the issue code (stable across days, used by the history diff);
# - the docstring's first line says what holds when the paper passes ("SPC assigned"), with no
#   placeholders (passed-check lists show it without a configuration at hand);
# - the rest says what is flagged and how severely, with {config_key} placeholders that the
#   legend fills in from the configuration.
CHECKS: list[Check] = []


def registrar(registry: list) -> Callable[[F], F]:
    """A decorator adding checks to `registry`; they must follow the docstring convention."""

    def register(function: F) -> F:
        doc = inspect.cleandoc(function.__doc__ or "")
        assert "\n\n" in doc, f"{function.__name__}: docstring needs a label and a description"
        registry.append(function)
        return function

    return register


paper_check = registrar(CHECKS)


def _days(ctx: Context, key: str) -> int:
    return (date.fromisoformat(ctx.config[key]) - ctx.today).days


def _deadline(missing: int, what: str, days: int, warning: int, critical: int) -> list[Finding]:
    if not missing or days > warning:
        return []
    if days < 0:
        return [Finding(RED, f"{missing} {what} missing, {-days} days overdue")]
    severity = RED if days <= critical else YELLOW
    return [Finding(severity, f"{missing} {what} missing, {days} days left")]


def _ratings(paper: dict) -> list[int]:
    return sorted(r["rating"] for r in paper["reviews"] if r["rating"] is not None)


def _disagree(paper: dict, ctx: Context) -> bool:
    ratings = _ratings(paper)
    return bool(ratings) and ratings[-1] - ratings[0] >= ctx.config["scores_spread_max"]


def _pending(paper: dict) -> list[str]:
    """Assigned reviewers without a review, when identities match (else none can be named)."""
    reviewed = {r["reviewer"] for r in paper["reviews"]}
    pending = [m for m in paper["reviewers"] if m not in reviewed]
    return pending if len(pending) == len(paper["reviewers"]) - len(paper["reviews"]) else []


def _posts(paper: dict, role: str | None = None) -> list[dict]:
    return [p for p in paper.get("posts", []) if role is None or p["role"] == role]


@paper_check
def active_submission(paper: dict, ctx: Context) -> list[Finding]:
    """Submission active

    YELLOW when the paper was withdrawn or desk rejected: it needs no further review action, and
    no other check runs on it.
    """
    status = paper.get("status", "active")
    return [] if status == "active" else [Finding(YELLOW, f"{status.replace('_', ' ').lower()}")]


@paper_check
def no_spc(paper: dict, ctx: Context) -> list[Finding]:
    """SPC assigned

    RED when the paper has no SPC (Area Chair) assigned.
    """
    return [] if paper["spcs"] else [Finding(RED, "no SPC assigned")]


@paper_check
def few_reviewers(paper: dict, ctx: Context) -> list[Finding]:
    """Enough reviewers assigned

    RED when fewer than {reviewers_min} reviewers are assigned.
    """
    count = len(paper["reviewers"])
    return (
        [Finding(RED, f"{count} reviewers assigned")] if count < ctx.config["reviewers_min"] else []
    )


@paper_check
def reviews_behind(paper: dict, ctx: Context) -> list[Finding]:
    """Reviews on track with the milestones

    YELLOW when, past a review milestone ({reviews_milestones}), fewer of the paper's reviews are
    in than that share, until the last {reviews_warning_days} days before the review deadline
    (then "Reviews on schedule" applies).
    """
    if _days(ctx, "deadline_reviews") <= ctx.config["reviews_warning_days"]:
        return []
    passed = [
        (d, share) for d, share in ctx.config["reviews_milestones"].items() if d <= str(ctx.today)
    ]
    if not passed or not paper["reviewers"]:
        return []
    when, share = max(passed)
    done, total = len(paper["reviews"]), len(paper["reviewers"])
    if done < share * total:
        return [Finding(YELLOW, f"{done} of {total} reviews in, {share:.0%} due by {when}")]
    return []


@paper_check
def missing_reviews(paper: dict, ctx: Context) -> list[Finding]:
    """Reviews on schedule

    Counts assigned reviewers without a submitted review. From {reviews_warning_days} days
    before the review deadline ({deadline_reviews}) it is YELLOW, from {reviews_critical_days}
    days before and once overdue RED.
    """
    return _deadline(
        max(len(paper["reviewers"]) - len(paper["reviews"]), 0),
        "reviews",
        _days(ctx, "deadline_reviews"),
        ctx.config["reviews_warning_days"],
        ctx.config["reviews_critical_days"],
    )


@paper_check
def late_reviewer(paper: dict, ctx: Context) -> list[Finding]:
    """No reviewer behind on several papers

    YELLOW for each reviewer of this paper who, past the first review milestone, still owes
    reviews on {reviewers_late_papers_min} or more of your papers: one reminder covers them all.
    """
    if not ctx.config["reviews_milestones"] or str(ctx.today) < min(
        ctx.config["reviews_milestones"]
    ):
        return []
    owed = Counter(
        m for p in ctx.papers if p.get("status", "active") == "active" for m in _pending(p)
    )
    return [
        Finding(YELLOW, f"{m} owes reviews on {owed[m]} of your papers", m)
        for m in _pending(paper)
        if owed[m] >= ctx.config["reviewers_late_papers_min"]
    ]


def _which(review: dict) -> str:
    """Which review, as the forum names it (" (Reviewer_aB3x)"); old snapshots lack it."""
    return f" ({review['name']})" if review.get("name") else ""


@paper_check
def short_review(paper: dict, ctx: Context) -> list[Finding]:
    """Reviews long enough

    YELLOW for each submitted review shorter than {reviews_words_min} words (all text fields
    counted together).
    """
    return [
        Finding(YELLOW, f"review of {r['words']} words{_which(r)}", r["reviewer"])
        for r in paper["reviews"]
        if r["words"] < ctx.config["reviews_words_min"]
    ]


@paper_check
def review_chatbot_phrases(paper: dict, ctx: Context) -> list[Finding]:
    """No leftover chatbot phrases in reviews

    YELLOW for each review containing a phrase chatbots produce and people rarely write, such
    as "as an AI language model" or "here is a revised version" (the list is in
    resources/ai_phrases.txt). A hint to read the review, not proof.
    """
    return [
        Finding(
            YELLOW,
            f"review with chatbot phrases: {'; '.join(r['phrases'][:3])}{_which(r)}",
            r["reviewer"],
        )
        for r in paper["reviews"]
        if r.get("phrases")
    ]


@paper_check
def review_marker_words(paper: dict, ctx: Context) -> list[Finding]:
    """No review dense with chatbot-favoured words

    YELLOW for each review with at least {ai_markers_min} words such as "delve", "intricate" or
    "showcase" (resources/ai_words.txt) and more than {ai_markers_per_1000_max} of them per
    1000 words. Many people write like this too: a weak hint, to be read before anything else.
    """
    found = []
    for r in paper["reviews"]:
        described = markers.dense(r.get("markers", {}), r["words"], ctx.config)
        if described:
            found.append(Finding(YELLOW, f"review with {described}{_which(r)}", r["reviewer"]))
    return found


def similarity(a: list[int], b: list[int]) -> float:
    """Estimated Jaccard similarity of two texts from their MinHash fingerprints."""
    return sum(x == y for x, y in zip(a, b)) / max(len(a), 1)


@paper_check
def recycled_review(paper: dict, ctx: Context) -> list[Finding]:
    """Reviews written for this paper

    YELLOW when a review shares {reviews_similarity_max:.0%} or more of its 5-word phrases
    (estimated from fingerprints, not text) with a review by the same reviewer on another of
    your papers.
    """
    found = []
    for review in paper["reviews"]:
        for other in ctx.papers:
            if other["number"] == paper["number"]:
                continue
            for twin in other["reviews"]:
                same = twin["reviewer"] == review["reviewer"] and review.get("fingerprint")
                score = (
                    similarity(review["fingerprint"], twin.get("fingerprint", [])) if same else 0
                )
                if score >= ctx.config["reviews_similarity_max"]:
                    message = (
                        f"review {score:.0%} similar to the same reviewer's on #{other['number']}"
                        f"{_which(review)}"
                    )
                    found.append(
                        Finding(YELLOW, message, f"{review['reviewer']}@{other['number']}")
                    )
    return found


@paper_check
def low_confidence(paper: dict, ctx: Context) -> list[Finding]:
    """Confident reviewers

    YELLOW when at least two reviews are in and every reviewer's confidence is
    {confidence_low_max} or lower, which may point to an expertise mismatch.
    """
    confidences = [r["confidence"] for r in paper["reviews"] if r["confidence"] is not None]
    if len(confidences) >= 2 and max(confidences) <= ctx.config["confidence_low_max"]:
        return [Finding(YELLOW, f"all confidences low: {sorted(confidences)}")]
    return []


@paper_check
def disagreement(paper: dict, ctx: Context) -> list[Finding]:
    """Ratings within the allowed spread

    YELLOW when the highest and lowest ratings differ by {scores_spread_max} or more.
    """
    return [Finding(YELLOW, f"ratings {_ratings(paper)}")] if _disagree(paper, ctx) else []


@paper_check
def no_discussion(paper: dict, ctx: Context) -> list[Finding]:
    """No undiscussed disagreement

    RED when, from the discussion start ({discussion_start}), ratings differ by
    {scores_spread_max} or more and no reviewer has posted a comment.
    """
    if not _disagree(paper, ctx) or _days(ctx, "discussion_start") > 0:
        return []
    discussed = _posts(paper, "reviewer") if "posts" in paper else paper["comments"]
    return [] if discussed else [Finding(RED, "reviewers disagree and none has commented")]


@paper_check
def long_discussion(paper: dict, ctx: Context) -> list[Finding]:
    """Discussion within the expected length

    YELLOW when there are more comments than one per reviewer plus one per SPC (meta-reviewer),
    which may mean a stuck discussion.
    """
    expected = len(paper["reviewers"]) + len(paper["spcs"])
    count = len(_posts(paper)) if "posts" in paper else paper["comments"]
    return [Finding(YELLOW, f"{count} comments, {expected} expected")] if count > expected else []


@paper_check
def missing_acknowledgement(paper: dict, ctx: Context) -> list[Finding]:
    """Rebuttal acknowledged

    Counts reviewers who, since the authors' rebuttal, neither updated their review nor
    commented. From {acknowledgements_warning_days} days before the acknowledgement deadline
    ({deadline_acknowledgements}) it is YELLOW, once overdue RED.
    """
    since = paper.get("rebuttal")
    if not since:
        return []
    active = {p["who"] for p in _posts(paper, "reviewer") if (p["date"] or "") > since}
    silent = [
        r
        for r in paper["reviews"]
        if (r.get("modified") or "") <= since and r["reviewer"] not in active
    ]
    warning = ctx.config["acknowledgements_warning_days"]
    days = _days(ctx, "deadline_acknowledgements")
    return _deadline(len(silent), "acknowledgements", days, warning, -1)


@paper_check
def inactive_spc(paper: dict, ctx: Context) -> list[Finding]:
    """SPC active in the discussion

    YELLOW, from {spcs_inactive_days} days after the discussion start ({discussion_start}), for
    each SPC of this paper who has posted no comment on any of your papers in the last
    {spcs_inactive_days} days.
    """
    quiet = ctx.config["spcs_inactive_days"]
    if -_days(ctx, "discussion_start") < quiet:
        return []
    found = []
    for spc in paper["spcs"]:
        dates = [
            p["date"] for q in ctx.papers for p in _posts(q, "spc") if p["who"] == spc and p["date"]
        ]
        last = max(dates, default=None)
        if last is None or (ctx.today - date.fromisoformat(last)).days >= quiet:
            found.append(Finding(YELLOW, f"{spc} silent since {last or 'the start'}", spc))
    return found


@paper_check
def missing_meta_review(paper: dict, ctx: Context) -> list[Finding]:
    """Meta-review on schedule

    RED when there is no meta-review from {meta_reviews_warning_days} days before its
    deadline ({deadline_meta_reviews}) on.
    """
    warning = ctx.config["meta_reviews_warning_days"]
    days = _days(ctx, "deadline_meta_reviews")
    return _deadline(0 if paper["meta_review"] else 1, "meta-review", days, warning, warning)


@paper_check
def short_meta_review(paper: dict, ctx: Context) -> list[Finding]:
    """Meta-review long enough

    YELLOW when the meta-review has fewer than {meta_reviews_words_min} words.
    """
    meta = paper.get("meta")
    if meta and meta["words"] < ctx.config["meta_reviews_words_min"]:
        return [Finding(YELLOW, f"meta-review of {meta['words']} words")]
    return []


@paper_check
def missing_recommendation(paper: dict, ctx: Context) -> list[Finding]:
    """Proceedings and Findings recommendations given

    YELLOW when the meta-review lacks the Proceedings ({field_meta_proceedings}) or the
    Findings ({field_meta_findings}) recommendation.
    """
    meta = paper.get("meta")
    missing = [kind for kind in ("proceedings", "findings") if meta and not meta[kind]]
    return [Finding(YELLOW, f"no {' or '.join(missing)} recommendation")] if missing else []


def _mean(paper: dict) -> float | None:
    ratings = _ratings(paper)
    return sum(ratings) / len(ratings) if ratings else None


@paper_check
def meta_vs_ratings(paper: dict, ctx: Context) -> list[Finding]:
    """Meta-review in line with the ratings

    YELLOW when the Proceedings recommendation is "Strong Accept" for a paper whose mean rating
    is in the bottom quarter of your papers, or "Reject" for one in the top quarter. Ranking
    within your papers needs no knowledge of the rating scale; it needs at least 8 rated papers.
    """
    recommendation, mean = str((paper.get("meta") or {}).get("proceedings") or ""), _mean(paper)
    means = sorted(m for p in ctx.papers if (m := _mean(p)) is not None)
    if mean is None or len(means) < 8 or recommendation not in ("Strong Accept", "Reject"):
        return []
    low, high = means[len(means) // 4], means[-(len(means) // 4) - 1]
    if recommendation == "Strong Accept" and mean < low:
        return [Finding(YELLOW, f"Strong Accept, but mean rating {mean:.1f} is in your bottom 25%")]
    if recommendation == "Reject" and mean > high:
        return [Finding(YELLOW, f"Reject, but mean rating {mean:.1f} is in your top 25%")]
    return []


@paper_check
def findings_consistency(paper: dict, ctx: Context) -> list[Finding]:
    """Findings recommendation respects the authors' choice

    YELLOW when the meta-review recommends accepting the paper in Findings although the authors
    opted out of Findings ({field_findings_opt_in} = No).
    """
    meta = paper.get("meta") or {}
    if paper.get("findings_opt_in") == "No" and str(meta.get("findings", "")).startswith("Accept"):
        return [Finding(YELLOW, "Findings accept, but the authors opted out of Findings")]
    return []


def run(checks: list, subject: Any, *args: Any) -> list[tuple[str, Finding]]:
    """(code, finding) pairs from running `checks` on `subject`; a check's name is its code."""
    found = []
    for function in checks:
        for f in function(subject, *args):
            found.append((function.__name__ + (f":{f.detail}" if f.detail else ""), f))
        if function is active_submission and found:
            break  # withdrawn or desk rejected: nothing else applies
    return found


def check_paper(paper: dict, ctx: Context) -> list[Issue]:
    spcs = tuple(paper["spcs"])
    return [
        Issue(paper["number"], f.severity, code, f.message, paper["url"], spcs)
        for code, f in run(CHECKS, paper, ctx)
    ]


def _doc(function: Callable) -> tuple[str, str]:
    label, _, description = inspect.cleandoc(function.__doc__ or "").partition("\n\n")
    return label, " ".join(description.split())


def legend(config: dict, checks: list | None = None) -> list[tuple[str, str, str]]:
    """(code, label, description) of every check, thresholds filled in from `config`."""
    milestones = config.get("reviews_milestones", {}).items()
    shown = config | {"reviews_milestones": ", ".join(f"{s:.0%} by {d}" for d, s in milestones)}
    return [
        (f.__name__, _doc(f)[0], _doc(f)[1].format_map(shown))
        for f in (CHECKS if checks is None else checks)
    ]


def passed(issues: list[Issue], checks: list | None = None) -> list[str]:
    """Labels of the checks a paper passes, given its issues."""
    failed = {i.code.split(":")[0] for i in issues}
    return [_doc(f)[0] for f in (CHECKS if checks is None else checks) if f.__name__ not in failed]


PHASES = (  # (the setting ending a phase, the phase, what happens then)
    ("deadline_reviews", "Reviewing", "reviews due"),
    ("discussion_start", "Rebuttal", "discussion starts"),
    ("deadline_acknowledgements", "Discussion", "acknowledgements due"),
    ("deadline_meta_reviews", "Meta-reviews", "meta-reviews due"),
)


def phase(config: dict, today: date) -> str:
    """Where the reviewing process stands on `today`, and its next date."""
    for key, name, then in PHASES:
        day = date.fromisoformat(config[key])
        if today <= day:
            days = (day - today).days
            when = {0: "today", 1: "tomorrow"}.get(days, f"in {days} days")
            return f"{name}: {then} {day.day} {day:%b}, {when}"
    return "Decisions: meta-reviews are past due"


def check(snapshot: dict, config: dict) -> list[Issue]:
    ctx = Context(config, date.fromisoformat(snapshot["taken_at"][:10]), snapshot["papers"])
    issues = [i for p in snapshot["papers"] for i in check_paper(p, ctx)]
    return sorted(issues, key=lambda i: (i.severity != RED, i.number, i.code))


def green_rows(snapshot: dict, issues: list[Issue]) -> list[Issue]:
    """One GREEN pseudo-issue per paper without issues, so listings can show every paper."""
    flagged = {i.number for i in issues}
    return [
        Issue(p["number"], GREEN, "ok", "all checks pass", p["url"], tuple(p["spcs"]))
        for p in snapshot["papers"]
        if p["number"] not in flagged
    ]


def matches(issue: Issue, needle: str) -> bool:
    """The filter of the CLI and the TUI: a case-insensitive substring of severity, paper
    number ("#7"), SPCs or message."""
    spcs = ", ".join(issue.spcs) or "(no SPC)"
    return needle.lower() in f"{issue.severity} #{issue.number} {spcs} {issue.message}".lower()


def _changes(snapshot: dict, config: dict, previous: dict) -> tuple[int, list[Issue]]:
    """How many paper-check issues are new since `previous`, and the ones resolved since."""
    now = {(i.number, i.code) for i in check(snapshot, config)}
    before = check(previous, config)
    then = {(i.number, i.code) for i in before}
    return len(now - then), [i for i in before if (i.number, i.code) not in now]


def summary(
    snapshot: dict,
    config: dict,
    previous: dict | None = None,
    extra: list[Issue] | None = None,
    ignored: Collection[tuple[int, str]] = (),
) -> list[str]:
    """Papers per status and, given `previous`, the changes since. `extra` issues (document
    checks) count in the status but not in the changes; `ignored` ones (number, code) don't."""
    status = {p["number"]: GREEN for p in snapshot["papers"]}
    for i in check(snapshot, config) + (extra or []):
        if (i.number, i.code) in ignored:
            continue
        status[i.number] = RED if RED in (status[i.number], i.severity) else YELLOW
    counts = {s: list(status.values()).count(s) for s in (RED, YELLOW, GREEN)}
    lines = [f"{len(status)} papers: " + ", ".join(f"{n} {s}" for s, n in counts.items())]
    if previous:
        new, resolved = _changes(snapshot, config, previous)
        lines.append(
            f"Since {previous['taken_at'][:16]}: {new} new issues, {len(resolved)} resolved"
        )
    return lines


def report(
    snapshot: dict,
    config: dict,
    previous: dict | None = None,
    extra: list[Issue] | None = None,
    needle: str = "",
    green: bool = False,
    ignored: Collection[tuple[int, str]] = (),
) -> str:
    """Summary, changes since `previous`, and issues grouped by SPC. `needle` filters the
    listing, `green` adds a row for each paper without issues; `ignored` issues are listed,
    marked, but not counted."""
    issues = sorted(
        check(snapshot, config) + (extra or []), key=lambda i: (i.severity != RED, i.number, i.code)
    )
    lines = summary(snapshot, config, previous, extra, ignored)
    resolved: dict[str, int] = defaultdict(int)
    for i in _changes(snapshot, config, previous)[1] if previous else []:
        for spc in i.spcs or ("(no SPC)",):
            resolved[spc] += 1

    by_spc: dict[str, list[Issue]] = defaultdict(list)
    for i in issues + (green_rows(snapshot, issues) if green else []):
        if matches(i, needle):
            for spc in i.spcs or ("(no SPC)",):
                by_spc[spc].append(i)
    for spc, mine in sorted(by_spc.items(), key=lambda kv: -sum(i.severity == RED for i in kv[1])):
        counted = [i for i in mine if (i.number, i.code) not in ignored]
        reds = sum(i.severity == RED for i in counted)
        open_ = sum(i.severity != GREEN for i in counted)
        lines.append(f"\n{spc}: {open_} open ({reds} RED), {resolved[spc]} resolved since")
        lines += [
            f"  {i.severity:6} #{i.number:<5} {i.message}"
            + ("  (ignored)" if (i.number, i.code) in ignored else "")
            + f"  {i.url}"
            for i in mine
        ]
    return "\n".join(lines)


def write_csv(
    issues: list[Issue], file: IO[str], ignored: Collection[tuple[int, str]] = ()
) -> None:
    writer = csv.writer(file)
    writer.writerow([*Issue._fields, "ignored"])
    writer.writerows(
        (*i[:5], ";".join(i.spcs), "yes" if (i.number, i.code) in ignored else "") for i in issues
    )
