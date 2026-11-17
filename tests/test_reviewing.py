import copy
import json

import pytest

from aamas_review_monitor import __main__ as cli
from aamas_review_monitor import core, models, outreach, papers, reviewing
from aamas_review_monitor.collector import fetch, replies
from aamas_review_monitor.resources import FILE_REVIEW_RUBRIC_DEFAULT
from tests.test_checks import CONFIG, paper
from tests.test_collector import FakeClient
from tests.test_models import CONFIG as EMBEDDINGS, FakeEndpoint

GOOD = """The paper proposes a decentralised auction protocol for task allocation among robots
and proves that it converges within a factor of two of the optimum.
A strength is the clean reduction in Section 4, which makes the proof easy to verify.
The convergence proof of Theorem 2 assumes a fixed number of agents, yet the experiments in
Section 5 vary it, so the guarantee does not cover the reported results.
I suggest reporting means and standard deviations over at least five seeds.
How does the algorithm behave when agents join or leave during the auction?
The bidding scheme is close to Zlot and Stentz (2006), which the paper does not cite.
The flaw in the proof is the main reason for my score; the other issues are minor.
The main weakness is the proof, though the modelling is a strength. The paper is clearly written,
fits AAMAS, and the proofs are otherwise correct, but the code and hyperparameters are missing,
and the references omit recent work."""
POOR = "I read it all. This is nonsense, a waste of time. Reject it, then."


def records_with(*texts):
    records = fetch(FakeClient(), CONFIG)
    reviews = replies(records[0], "review")
    for i, (review, text) in enumerate(zip(reviews, texts)):
        review["id"] = f"r{i}"
        review["content"]["summary"] = {"value": text}
    return records


def rubric():
    return reviewing.read(FILE_REVIEW_RUBRIC_DEFAULT.read_text(encoding="utf-8"))


def test_shipped_rubric_parses_and_broken_ones_say_why():
    shipped = rubric()
    assert len(shipped["criteria"]) >= 8 and reviewing.problems(shipped) == []
    broken = copy.deepcopy(shipped)
    broken["criteria"][1]["key"] = broken["criteria"][0]["key"]
    broken["criteria"][2]["weight"] = 0
    broken["criteria"][3]["short"] = []
    broken["criteria"][4]["alert"] = "yes"
    broken["criteria"][5]["compare"] = "title"
    found = reviewing.problems(broken)
    assert any("key used twice" in p for p in found)
    assert any("weight should be a positive number" in p for p in found)
    assert any("short should be a non-empty list" in p for p in found)
    assert any("alert should be true or false" in p for p in found)
    assert any("compare can only be abstract" in p for p in found)
    with pytest.raises(ValueError, match="not valid YAML"):
        reviewing.read("criteria: [")


def test_your_copy_of_the_rubric_replaces_the_shipped_one():
    assert reviewing.file(core.FILE_REVIEW_RUBRIC) == FILE_REVIEW_RUBRIC_DEFAULT
    mine = rubric() | {"name": "Mine"}
    reviewing.save(mine, core.FILE_REVIEW_RUBRIC)
    assert reviewing.load(core.FILE_REVIEW_RUBRIC)["name"] == "Mine"
    assert reviewing.fingerprint(mine) != reviewing.fingerprint(rubric())
    core.FILE_REVIEW_RUBRIC.write_text("name: x\n")
    with pytest.raises(ValueError, match="review-rubric.yaml: missing sources"):
        reviewing.load(core.FILE_REVIEW_RUBRIC)


def test_pieces_are_sentences_and_items_of_some_words():
    found = reviewing.pieces("Good. Why is it so?\n- item one is here\nTheorem 2 fails for n=3.")
    assert found == ["Good. Why is it so?", "- item one is here", "Theorem 2 fails for n=3."]


def test_a_thin_review_scores_below_a_specific_one_and_only_goes_to_local_endpoints(
    monkeypatch, tmp_path
):
    endpoint = FakeEndpoint(monkeypatch)
    s = models.settings(EMBEDDINGS)
    records = records_with(GOOD, POOR)
    config = CONFIG | {
        "reviews_margin_min": 9,
        "reviews_abstract_min": -1,
        "reviews_margin_alert": 9,
    }  # the fake vectors can't judge: rules decide
    results, failures = reviewing.score(records, rubric(), s, config, tmp_path)
    assert failures == []
    good, poor = results
    assert good["name"] == "Reviewer_aB3x" and good["id"] == "r0" and good["score"] > 0.9
    assert good["criteria"]["grounded"]["met"] and good["criteria"]["questions"]["rules"]
    assert good["alerts"] == []  # tone, balance: presumed, nothing rules them out
    assert {"strengths", "weaknesses", "constructive"} <= set(poor["alerts"])  # "nonsense"
    assert poor["score"] < 0.4 and reviewing.poor(results, config) == [poor]
    assert reviewing.poor([poor | {"score": 1.0}], config) != []  # alerts, whatever the score
    review_requests = [r for r in endpoint.requests if "I read it all." in r["input"]]
    assert review_requests and not any(r["proxies from the environment"] for r in review_requests)
    # cached: scoring again asks nothing
    endpoint.requests.clear()
    assert reviewing.score(records, rubric(), s, config, tmp_path, cache_only=True)[0] == results
    assert endpoint.requests == []


def embeddings_alone(*keys):
    """The shipped rubric, with these criteria left to the embeddings (no rules, no margin)."""
    found = rubric()
    for c in found["criteria"]:
        if c["key"] in keys:
            c["rules"] = []
            c.pop("margin", None)
    return found


def test_a_sentence_like_the_examples_meeting_a_criterion_meets_it(monkeypatch, tmp_path):
    FakeEndpoint(monkeypatch)
    plain = embeddings_alone("strengths", "constructive")
    nice = "Interesting paper."  # verbatim among the examples falling short of strengths
    records = records_with(nice + "\nThe paper is well written.")
    s, config = models.settings(EMBEDDINGS), CONFIG | {"reviews_margin_min": 0.0}
    (result, *_), _ = reviewing.score(records, plain, s, config, tmp_path)
    verdict = result["criteria"]["strengths"]
    assert not verdict["met"] and verdict["margin"] < 0
    nice = "The user study is well designed, with a preregistered hypothesis and a sample."
    records = records_with(nice)
    (result, *_), _ = reviewing.score(records, plain, s, config, tmp_path)
    verdict = result["criteria"]["strengths"]
    assert verdict["met"] and verdict["margin"] > 0 and verdict["evidence"] == nice
    # presumed: a sentence like the harsh examples rules tone out, as the worst sentence
    harsh = "The authors clearly do not understand the field."
    records = records_with(f"{harsh}\nThe proof in Section 2 is fine.")
    config |= {"reviews_margin_alert": 0.01}
    (result, *_), _ = reviewing.score(records, plain, s, config, tmp_path)
    tone = result["criteria"]["constructive"]
    assert not tone["met"] and tone["evidence"] == harsh and "constructive" in result["alerts"]
    # with the shipped margin (2), only the rules can rule tone out
    (result, *_), _ = reviewing.score(records, rubric(), s, config, tmp_path)
    assert result["criteria"]["constructive"]["met"]


def test_bare_citation_requests_and_a_summary_far_from_the_abstract_raise_alerts(
    monkeypatch, tmp_path
):
    FakeEndpoint(monkeypatch)
    cites = "The authors should cite the following papers. Smith 2020 and Jones 2021."
    on_topic = "Auction protocols for robot task allocation converge near the optimum."
    records = records_with(cites, on_topic)
    records[0]["content"]["abstract"] = {"value": on_topic}
    config = CONFIG | {
        "reviews_margin_min": 9,
        "reviews_abstract_min": 0.9,
        "reviews_margin_alert": 9,
    }
    s = models.settings(EMBEDDINGS)
    (requests_only, about), _ = reviewing.score(records, rubric(), s, config, tmp_path)
    assert {"citations", "about_paper"} <= set(requests_only["alerts"])
    assert requests_only["criteria"]["citations"]["rules"]  # what matched, as evidence
    assert about["criteria"]["about_paper"]["met"] and about["criteria"]["citations"]["met"]
    assert about["criteria"]["about_paper"]["margin"] > 0.9


def test_poor_reviews_get_a_reply_their_reviewer_reads_or_a_comment_to_the_spc(
    monkeypatch, tmp_path
):
    FakeEndpoint(monkeypatch)
    records = records_with(POOR, POOR)
    config = CONFIG | {
        "reviews_margin_min": 9,
        "reviews_abstract_min": -1,
        "reviews_margin_alert": 9,
    }
    results, _ = reviewing.score(records, rubric(), models.settings(EMBEDDINGS), config, tmp_path)
    issues = reviewing.issues(results, rubric(), records, None, config)
    assert issues[0].code == "poor_review:Reviewer_aB3x" and "missing: " in issues[0].message
    templates = {t.key: t for t in outreach.comment_templates()}
    direct, spc = templates["reviewers-poor-review"], templates["spc-poor-reviews"]
    found, skipped = outreach.comments(issues, records, {7}, direct.readers, config, None, direct)
    assert skipped == [] and [c.replyto for c in found] == ["r0", "r1"]
    assert found[0].readers == ("Area_Chairs", "Reviewer_aB3x")
    assert found[0].text.startswith("Dear Reviewer_aB3x,")
    header, items = outreach.review_comments(found, skipped)
    assert items[0].heading.startswith("Comment on #7 replying to Reviewer_aB3x, readable by")
    client = FakeClient()
    papers.post_comments(client, found[:1])
    ((_, _, note),) = client.comments
    assert note.replyto == "r0" and note.forum == "abc"
    (comment,), _ = outreach.comments(issues, records, {7}, spc.readers, config, None, spc)
    assert comment.replyto == "" and comment.text.count("poor") == 0  # one per paper, listed
    assert comment.text.count("review by Reviewer_") == 2


def test_cli_comments_on_the_poor_reviews_from_their_cached_scores(monkeypatch, capsys):
    FakeEndpoint(monkeypatch)
    records = records_with(GOOD, POOR)
    papers.save(records, core.DIR_PAPERS, [])
    config = CONFIG | {
        "reviews_margin_min": 9,
        "reviews_margin_alert": 9,
        "reviews_abstract_min": -1,
    }
    monkeypatch.setattr(core, "load_config", lambda: config)
    snapshot = {"taken_at": "2026-11-11T08:00:00", "papers": [paper(7)]}
    core.DIR_SNAPSHOTS.mkdir(parents=True)
    (core.DIR_SNAPSHOTS / "a.json").write_text(json.dumps(snapshot))
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")
    cli.main(["comment", "7", "--template", "spc-poor-reviews"])
    out = capsys.readouterr().out
    assert "review by Reviewer_hidden meets" in out and "review by Reviewer_aB3x" not in out
    assert out.rstrip().endswith("Nothing posted")


def test_cli_lists_reviews_and_shows_and_checks_the_rubric(monkeypatch, tmp_path, capsys):
    FakeEndpoint(monkeypatch)
    records = records_with(GOOD, POOR)
    papers.save(records, core.DIR_PAPERS, [])
    monkeypatch.setattr(
        core,
        "load_config",
        lambda: (
            CONFIG
            | {"reviews_margin_min": 9, "reviews_abstract_min": -1, "reviews_margin_alert": 9}
        ),
    )
    cli.main(["--cache-only", "review-scores"])
    assert "judged by the rules alone" in capsys.readouterr().out
    cli.main(["review-scores", "--poor"])
    out = capsys.readouterr().out
    assert "judged by the rules alone" not in out
    assert "Reviewer_hidden" in out and "!constructive" in out and "Reviewer_aB3x" not in out
    cli.main(["rubrics", "show", "reviews"])
    assert capsys.readouterr().out == FILE_REVIEW_RUBRIC_DEFAULT.read_text(encoding="utf-8")
    cli.main(["rubrics", "check", "reviews"])
    assert "weaknesses" in capsys.readouterr().out
    cli.main(["rubrics", "list"])
    assert "reviews 17 criteria (shipped)" in capsys.readouterr().out


def test_reviews_not_embedded_yet_are_judged_by_the_rules_alone(monkeypatch, tmp_path):
    endpoint = FakeEndpoint(monkeypatch)
    records = records_with(GOOD, POOR)
    s = models.settings(EMBEDDINGS)
    (good, poor), failures = reviewing.score(records, rubric(), s, CONFIG, tmp_path, True)
    assert endpoint.requests == [] and failures == []
    assert not good["embedded"] and good["criteria"]["questions"]["met"]  # a "?" rule
    assert good["criteria"]["about_paper"]["met"]  # compared: unknown, so no alert
    assert not poor["criteria"]["constructive"]["met"]  # "nonsense": the rules rule it out
    assert poor["criteria"]["weaknesses"]["margin"] is None
