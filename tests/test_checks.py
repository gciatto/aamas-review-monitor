import json
from datetime import date

from aamas_review_monitor.checks import (
    CHECKS,
    RED,
    YELLOW,
    Context,
    check_paper,
    legend,
    passed,
)
from aamas_review_monitor.collector import fingerprint
from aamas_review_monitor.resources import FILE_CONFIG

CONFIG = json.loads(FILE_CONFIG.read_text(encoding="utf-8"))


def paper(number=1, spcs=("~SPC_One1",), reviews=3, ratings=(6, 6, 7), words=400, **extra):
    return {
        "number": number,
        "url": f"https://openreview.net/forum?id=p{number}",
        "spcs": list(spcs),
        "reviewers": [f"~R_{i}1" for i in range(3)],
        "reviews": [
            {
                "reviewer": f"~R_{i}1",
                "rating": ratings[i],
                "confidence": 3,
                "words": words,
                "modified": "2026-11-10",
                "fingerprint": fingerprint(f"paper {number} review {i} " * 20),
            }
            for i in range(reviews)
        ],
        "meta_review": False,
        "comments": 0,
    } | extra


def ctx(today, *papers):
    return Context(CONFIG, date.fromisoformat(today), list(papers))


def issues(p, today, *others):
    return {(i.severity, i.code) for i in check_paper(p, ctx(today, p, *others))}


def post(role, who, day):
    return {"role": role, "who": who, "date": day}


def test_healthy_paper_has_no_issues():
    assert issues(paper(), "2026-10-19") == set()


def test_withdrawn_paper_needs_nothing_else():
    assert issues(paper(spcs=[], status="Withdrawn"), "2026-11-20") == {
        (YELLOW, "active_submission")
    }


def test_missing_reviews_escalate_towards_deadline():
    p = paper(reviews=1)
    assert issues(p, "2026-10-19") == set()
    assert issues(p, "2026-10-27") == {(YELLOW, "reviews_behind")}  # 50% due by 26 Oct
    assert issues(paper(reviews=2), "2026-10-27") == set()
    assert issues(p, "2026-11-08") == {(YELLOW, "missing_reviews")}
    assert issues(p, "2026-11-11") == {(RED, "missing_reviews")}
    assert issues(p, "2026-11-20") == {(RED, "missing_reviews")}


def test_reviewer_late_on_several_papers():
    one, two = paper(1, reviews=2), paper(2, reviews=2)
    assert (YELLOW, "late_reviewer:~R_21") in issues(one, "2026-10-27", two)
    assert (YELLOW, "late_reviewer:~R_21") not in issues(one, "2026-10-20", two)
    assert not any(code.startswith("late") for _, code in issues(one, "2026-10-27"))


def test_assignment_problems():
    assert issues(paper(spcs=[], reviewers=["~R_01"], reviews=1), "2026-10-19") == {
        (RED, "no_spc"),
        (RED, "few_reviewers"),
    }


def test_quality_signals():
    p = paper(ratings=(2, 6, 8), words=100)
    before = {(YELLOW, "disagreement"), *((YELLOW, f"short_review:~R_{i}1") for i in range(3))}
    assert issues(p, "2026-10-19") == before
    assert issues(p, "2026-11-26") == before | {(RED, "no_discussion")}
    discussed = p | {"posts": [post("spc", "~SPC_One1", "2026-11-26")]}
    assert (RED, "no_discussion") in issues(discussed, "2026-11-26")  # SPC comments don't count
    discussed["posts"].append(post("reviewer", "~R_01", "2026-11-26"))
    assert issues(discussed, "2026-11-26") == before


def test_recycled_reviews_and_low_confidence():
    one, two = paper(1), paper(2)
    two["reviews"][0]["fingerprint"] = one["reviews"][0]["fingerprint"]
    assert issues(one, "2026-10-19", two) == {(YELLOW, "recycled_review:~R_01@2")}
    for r in one["reviews"]:
        r["confidence"] = 2
    assert (YELLOW, "low_confidence") in issues(one, "2026-10-19")


def test_long_discussion():
    posts = [post("reviewer", "~R_01", "2026-11-26")] * 5  # 3 reviewers + 1 SPC expected
    assert issues(paper(posts=posts[:4]), "2026-11-26") == set()
    assert issues(paper(posts=posts), "2026-11-26") == {(YELLOW, "long_discussion")}


def test_rebuttal_acknowledgement():
    p = paper(rebuttal="2026-11-24", posts=[post("reviewer", "~R_01", "2026-11-26")])
    p["reviews"][1]["modified"] = "2026-11-27"
    late = [i for i in check_paper(p, ctx("2026-12-02", p)) if i.code.startswith("missing_ack")]
    assert [(i.severity, i.message) for i in late] == [
        (YELLOW, "1 acknowledgements missing, 1 days left")
    ]
    assert (RED, "missing_acknowledgement") in issues(p, "2026-12-04")
    assert not any("ack" in code for _, code in issues(paper(), "2026-12-04"))  # no rebuttal


def test_inactive_spc():
    quiet = paper(posts=[post("spc", "~SPC_One1", "2026-11-26")])
    assert (YELLOW, "inactive_spc:~SPC_One1") in issues(quiet, "2026-12-05")
    busy = paper(2, posts=[post("spc", "~SPC_One1", "2026-12-03")])
    assert (YELLOW, "inactive_spc:~SPC_One1") not in issues(quiet, "2026-12-05", busy)


def test_meta_review_checks():
    active = [post("spc", "~SPC_One1", "2026-12-07")]
    assert issues(paper(posts=active), "2026-12-08") == {(RED, "missing_meta_review")}
    meta = {"words": 20, "proceedings": "Reject", "findings": None}
    done = paper(meta_review=True, meta=meta, posts=active)
    assert issues(done, "2026-12-08") == {
        (YELLOW, "short_meta_review"),
        (YELLOW, "missing_recommendation"),
    }
    opted_out = done | {
        "findings_opt_in": "No",
        "meta": meta | {"words": 200, "findings": "Accept"},
    }
    assert issues(opted_out, "2026-12-08") == {(YELLOW, "findings_consistency")}


def test_meta_review_against_the_ratings_of_your_papers():
    others = [paper(n, ratings=(n, n, n)) for n in range(2, 10)]  # means 2..9
    meta = {"words": 200, "proceedings": "Strong Accept", "findings": "Accept"}
    weak = paper(1, ratings=(1, 1, 2), meta_review=True, meta=meta)
    assert (YELLOW, "meta_vs_ratings") in issues(weak, "2026-10-19", *others)
    assert (YELLOW, "meta_vs_ratings") not in issues(weak, "2026-10-19", *others[:5])  # too few
    strong = paper(1, ratings=(9, 9, 9), meta_review=True, meta=meta | {"proceedings": "Reject"})
    assert (YELLOW, "meta_vs_ratings") in issues(strong, "2026-10-19", *others)
    fair = paper(1, ratings=(5, 6, 6), meta_review=True, meta=meta)
    assert (YELLOW, "meta_vs_ratings") not in issues(fair, "2026-10-19", *others)


def test_passed_lists_the_checks_without_issues():
    found = check_paper(paper(spcs=[], words=10), ctx("2026-10-19"))
    labels = passed(found)
    assert "SPC assigned" not in labels and "Reviews long enough" not in labels
    assert "Enough reviewers assigned" in labels and len(labels) == len(CHECKS) - 2


def test_legend_comes_from_the_check_docstrings():
    entries = {code: (label, text) for code, label, text in legend(CONFIG)}
    assert list(entries) == [f.__name__ for f in CHECKS]
    assert entries["few_reviewers"] == (
        "Enough reviewers assigned",
        "RED when fewer than 3 reviewers are assigned.",
    )
    assert "deadline (2026-11-13) it is YELLOW" in entries["missing_reviews"][1]
    assert all(
        label and text and "{" not in text.replace("{'", "") for label, text in entries.values()
    )


def test_phase_names_the_next_date():
    from aamas_review_monitor.checks import phase

    assert phase(CONFIG, date(2026, 10, 19)) == "Reviewing: reviews due 13 Nov, in 25 days"
    assert phase(CONFIG, date(2026, 11, 24)) == "Rebuttal: discussion starts 25 Nov, tomorrow"
    assert phase(CONFIG, date(2026, 12, 9)) == "Meta-reviews: meta-reviews due 9 Dec, today"
    assert phase(CONFIG, date(2026, 12, 10)).startswith("Decisions")
