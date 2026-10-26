from datetime import date

from aamas_review_monitor import outreach
from aamas_review_monitor.checks import RED, YELLOW, Issue
from aamas_review_monitor.collector import fetch
from aamas_review_monitor.papers import deliver
from tests.test_checks import CONFIG
from tests.test_collector import SUB, FakeClient

TODAY = date(2026, 11, 11)
URL = "https://openreview.net/forum?id=abc"
ISSUES = [
    Issue(7, RED, "missing_reviews", "2 reviews missing, 2 days left", URL, ("~Spc_One1",)),
    Issue(7, YELLOW, "disagreement", "ratings [3, 6]", URL, ("~Spc_One1",)),
    Issue(9, RED, "missing_meta_review", "1 meta-review missing", "u9", ("~Spc_Two1",)),
]


def by_key():
    return {t.key: t for t in outreach.templates()}


def test_shipped_templates_parse():
    templates = by_key()
    assert set(templates) >= {"spc-digest", "spc-late", "spc-deadline", "reviewers-late"}
    assert all(t.subject and "{{fullname}}" in t.body for t in templates.values())


def test_spc_digest_lists_every_issue_of_the_spc_and_goes_through_their_paper():
    records = fetch(FakeClient(), CONFIG)
    drafts, unreachable = outreach.compose(by_key()["spc-digest"], ISSUES, records, CONFIG, TODAY)
    assert unreachable == ["~Spc_Two1: none of their papers is cached"]  # paper 9 isn't cached
    (draft,) = drafts
    assert draft.to == "~Spc_One1" and draft.members == [f"{SUB}7/Area_Chair_9jqi"]
    assert draft.invitation == f"{SUB}7/Area_Chairs/-/Message"
    assert draft.subject == "AAMAS 2027: status of your papers (#7)"
    assert f"- #7 ({URL}): 2 reviews missing, 2 days left\n    Reviews on schedule: " in draft.body
    assert f"- #7 ({URL}): ratings [3, 6]\n    Ratings within the allowed spread: " in draft.body
    assert draft.body.startswith("Dear {{fullname}},")  # OpenReview fills the name in


def test_reviewer_reminder_goes_to_the_late_reviewers_of_each_paper():
    records = fetch(FakeClient(), CONFIG)
    template = by_key()["reviewers-deadline"]
    drafts, _ = outreach.compose(template, ISSUES, records, CONFIG, TODAY)
    (draft,) = drafts  # the disagreement and the uncached #9 are not about late reviews
    assert draft.members == ["~Rev_B1", "~Rev_C1"] and draft.invitation == f"{SUB}7/-/Message"
    assert draft.subject == "AAMAS 2027: review of paper #7 due 13 November 2026"
    assert "is due on\n13 November 2026, in 2 days." in draft.body


def test_compose_can_target_some_spcs_or_papers_and_previews_everything():
    records = fetch(FakeClient(), CONFIG)
    digest = by_key()["spc-digest"]
    assert outreach.compose(digest, ISSUES, records, CONFIG, TODAY, spcs={"~Nobody1"}) == ([], [])
    assert outreach.compose(digest, ISSUES, records, CONFIG, TODAY, numbers={9})[0] == []
    drafts, unreachable = outreach.compose(digest, ISSUES, records, CONFIG, TODAY)
    text = outreach.preview(drafts, unreachable)
    assert text.startswith("1 messages\nNot reachable: ~Spc_Two1")
    assert "=== To ~Spc_One1, via #7 ===\nSubject: AAMAS 2027: status of your papers (#7)" in text


def test_delivered_drafts_are_signed_as_the_papers_sacs():
    records, client = fetch(FakeClient(), CONFIG), FakeClient()
    drafts, _ = outreach.compose(by_key()["spc-late"], ISSUES, records, CONFIG, TODAY)
    assert drafts == []  # the late-SPC template is about SPC work, none pending on #7
    drafts, _ = outreach.compose(by_key()["spc-digest"], ISSUES, records, CONFIG, TODAY)
    assert deliver(client, drafts) == []
    ((args, kwargs),) = client.messages
    assert args[1] == [f"{SUB}7/Area_Chair_9jqi"]
    assert kwargs["signature"] == f"{SUB}7/Senior_Area_Chairs"


def test_previews_warn_when_the_same_message_already_went_out(tmp_path):
    from aamas_review_monitor import papers

    records, history = fetch(FakeClient(), CONFIG), tmp_path / "history.jsonl"
    drafts, _ = outreach.compose(by_key()["spc-digest"], ISSUES, records, CONFIG, TODAY)
    assert "⚠" not in outreach.preview(drafts, [], papers.history(history))
    deliver(FakeClient(), drafts, history_file=history)
    sent = papers.history(history)
    text = outreach.preview(drafts, [], sent, ["Snapshot of today"])
    assert text.startswith("1 messages\nSnapshot of today\n⚠ 1 of 1 went out before: see below\n")
    assert "via #7 ===\n⚠ Already sent 20" in text
    other, _ = outreach.direct(records, "spcs", "Something else", "Hi")  # not a repeat
    assert "⚠" not in outreach.preview(other, [], sent)

    found, _ = outreach.comments(ISSUES, records, {7}, False, CONFIG)
    assert "⚠" not in outreach.preview_comments(found, [], sent)  # emails are not comments
    papers.post_comments(FakeClient(), found, history_file=history)
    text = outreach.preview_comments(found, [], papers.history(history))
    assert "⚠ 1 of 1 papers were commented on before" in text


def test_each_failed_check_is_explained_once_per_paper_for_spcs_but_not_reviewers():
    records = fetch(FakeClient(), CONFIG)
    short = [
        Issue(7, YELLOW, f"short_review:~R{n}", "review of 60 words", URL, ("~Spc_One1",))
        for n in (1, 2)
    ]
    (draft,), _ = outreach.compose(by_key()["spc-digest"], ISSUES + short, records, CONFIG, TODAY)
    assert draft.body.count("Reviews long enough: ") == 1
    assert "shorter than 150 words" in draft.body
    (comment,), _ = outreach.comments(ISSUES + short, records, {7}, True, CONFIG)
    assert comment.text.count("Reviews long enough: ") == 1
    (reminder,), _ = outreach.compose(
        by_key()["reviewers-deadline"], ISSUES, records, CONFIG, TODAY
    )
    assert "Reviews on schedule: " not in reminder.body


def test_comments_drop_the_explanations_when_too_long_for_openreview(monkeypatch):
    records = fetch(FakeClient(), CONFIG)
    (explained,), _ = outreach.comments(ISSUES, records, {7}, True, CONFIG)
    monkeypatch.setattr(outreach, "COMMENT_CHARS_MAX", len(explained.text) - 1)
    (bare,), _ = outreach.comments(ISSUES, records, {7}, True, CONFIG)
    assert "Reviews on schedule: " not in bare.text and "- 🔴 2 reviews missing" in bare.text
    monkeypatch.setattr(outreach, "COMMENT_CHARS_MAX", 100)
    found, skipped = outreach.comments(ISSUES, records, {7}, True, CONFIG)
    assert found == [] and skipped[0].endswith("OpenReview allows 100")


def test_late_reviews_alone_get_their_own_comment_and_suggested_spc_template():
    records = fetch(FakeClient(), CONFIG)
    late, other = ISSUES[:1], ISSUES[:2]
    (comment,), _ = outreach.comments(late, records, {7}, True, CONFIG)
    assert comment.title == "Process check: reviews late" and "responsibility" in comment.text
    (comment,), _ = outreach.comments(other, records, {7}, True, CONFIG)
    assert comment.title == "Process check: points needing attention"
    choices = outreach.templates()
    assert outreach.suggest(choices, late).key == "spc-late-reviews"
    assert outreach.suggest(choices, other) is None  # disagreement: no narrower template
