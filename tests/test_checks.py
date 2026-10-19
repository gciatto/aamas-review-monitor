from datetime import date

from aamas_review_monitor.checks import LABELS, RED, YELLOW, check_paper, passed

CONFIG = {
    "deadline_reviews": "2026-11-13",
    "deadline_meta_reviews": "2026-12-09",
    "reviewers_min": 3,
    "reviews_warning_days": 5,
    "reviews_critical_days": 2,
    "reviews_words_min": 150,
    "scores_spread_max": 3,
    "meta_reviews_warning_days": 2,
}


def paper(number=1, spcs=("~SPC_One1",), reviews=3, ratings=(6, 6, 7), words=400, **extra):
    return {
        "number": number,
        "url": f"https://openreview.net/forum?id=p{number}",
        "spcs": list(spcs),
        "reviewers": [f"~R_{i}1" for i in range(3)],
        "reviews": [
            {"reviewer": f"~R_{i}1", "rating": ratings[i], "confidence": 3, "words": words}
            for i in range(reviews)
        ],
        "meta_review": False,
        "comments": 0,
    } | extra


def issues(p, today):
    return {(i.severity, i.code) for i in check_paper(p, CONFIG, date.fromisoformat(today))}


def test_healthy_paper_has_no_issues():
    assert issues(paper(), "2026-10-19") == set()


def test_missing_reviews_escalate_towards_deadline():
    p = paper(reviews=1)
    assert issues(p, "2026-10-19") == set()
    assert issues(p, "2026-11-08") == {(YELLOW, "missing_reviews")}
    assert issues(p, "2026-11-11") == {(RED, "missing_reviews")}
    assert issues(p, "2026-11-20") == {(RED, "missing_reviews")}


def test_assignment_problems():
    assert issues(paper(spcs=[], reviewers=["~R_01"], reviews=1), "2026-10-19") == {
        (RED, "no_spc"),
        (RED, "few_reviewers"),
    }


def test_quality_signals():
    p = paper(ratings=(2, 6, 8), words=100)
    assert issues(p, "2026-10-19") == {
        (YELLOW, "disagreement"),
        *((YELLOW, f"short_review:~R_{i}1") for i in range(3)),
    }
    after = {(RED, "no_discussion")} | issues(p, "2026-10-19")
    assert issues(p, "2026-11-20") == after
    assert issues(p | {"comments": 2}, "2026-11-20") == after - {(RED, "no_discussion")}


def test_meta_review_deadline():
    assert issues(paper(), "2026-12-08") == {(RED, "missing_meta_review")}
    assert issues(paper(meta_review=True), "2026-12-20") == set()


def test_passed_lists_the_checks_without_issues():
    found = check_paper(paper(spcs=[], words=10), CONFIG, date(2026, 10, 19))
    labels = passed(found)
    assert "SPC assigned" not in labels and "reviews long enough" not in labels
    assert "enough reviewers assigned" in labels and len(labels) == len(LABELS) - 2
