import pytest

from aamas_review_monitor import areas, core, models, papers, rules
from tests.test_models import FakeEndpoint, resolves_to
from tests.test_scores import CONFIG, RECORDS, record
from tests.test_scores import rubrics  # noqa: F401 (fixture)

PAPER = {
    "title": "multi-agent reinforcement learning (marl) for teams",
    "keywords": "",
    "abstract": "we study equilibrium selection; learning converges to an equilibrium.",
    "text": "",
    "references": "smith. proc. neurips 2020. jones. icml 2021. lee. neurips 2023.",
    "reviews": "out of scope for this track",
    "meta-reviews": "",
    "raw": "Theorem 1. ... Theorem 2. ... Lemma 3.",
}


def value(rule):
    return rules.evaluate(rule, PAPER)


def test_rules_are_checked_when_rubrics_are_read():
    assert rules.problems({"any": ["MARL"], "weight": 2}) == []
    assert rules.problems({"any": ["a"], "all": ["b"]}) == [
        "a rule needs exactly one of any, all, count, cites"
    ]
    assert rules.problems({"any": [], "near": 3, "in": ["pdf"], "weight": "x", "w": 1}) == [
        "unknown key w",
        "any should be a list of terms",
        "near goes with all, as a number of words",
        "in should list some of title, keywords, abstract, text, references, reviews, meta-reviews",
        "weight should be a number (negative: evidence against the area)",
    ]
    assert "regular expression" in rules.problems({"count": "("})[0]
    assert rules.problems("MARL") == ["a rule should be a mapping, e.g. {any: [MARL], weight: 2}"]
    rubric = {
        "area": "A",
        "code": "A",
        "source": {},
        "topics": ["t"],
        "description": "",
        "exemplars": [],
        "rules": [{"any": ["x"]}, {"cites": "NeurIPS"}],
    }
    assert areas.problems(rubric) == ["rule 2: cites should be a list of terms"]


def test_any_all_near_none_count_and_cites():
    assert value({"any": ["MARL", "multi-agent reinforcement learning"]}) == (
        0.75,
        "MARL ×1, multi-agent reinforcement learning ×1",
    )
    assert value({"any": ["learn"]}) == (0.0, "")  # whole words only
    assert value({"any": ["equilibrium"], "in": ["title"]}) == (0.0, "")
    assert value({"all": ["equilibrium", "learning"]})[0] == 0.75  # one hit per `equilibrium`
    assert value({"all": ["equilibrium", "learning"], "near": 2})[0] == 0.5  # only the second
    assert value({"all": ["equilibrium", "bandit"]}) == (0.0, "")
    assert value({"any": ["marl"], "none": ["scope"], "in": ["title", "reviews"]}) == (0.0, "")
    assert value({"count": r"\b(Theorem|Lemma)\b", "at_least": 3}) == (
        1.0,
        r"\b(Theorem|Lemma)\b ×3",
    )
    assert value({"count": r"\bTheorem\b", "at_least": 3}) == (0.0, "")
    assert value({"cites": ["NeurIPS", "AAMAS"]}) == (0.75, "NeurIPS ×2")
    assert rules.score([{"any": ["marl"], "weight": 3}, {"any": ["bandit"]}], PAPER) == (
        0.375,
        ["marl ×1 (+3)"],
    )
    assert rules.score([{"cites": ["icml"], "weight": -1}], PAPER) == (-0.5, ["icml ×1 (-1)"])
    assert rules.score([], PAPER) == (0.0, [])


def test_texts_come_from_the_cache_with_the_references_apart(monkeypatch):
    paper = record(9, "A Title", "An abstract.", review="Fine work.") | {"id": "p9"}
    paper["content"]["pdf"] = {"value": "/pdf/v1.pdf"}
    assert rules.texts(paper, CONFIG, core.DIR_PAPERS)["text"] == ""  # not downloaded
    pdf = papers.attachment(paper, "pdf", core.DIR_PAPERS)
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")
    pages = ["Intro\nWe use MARL.", "More text.\nReferences\nNeurIPS 2020."]
    monkeypatch.setattr(papers, "pdf_pages", lambda path: pages)
    found = rules.texts(paper, CONFIG, core.DIR_PAPERS)
    assert found["title"] == "a title" and found["reviews"] == "fine work."
    assert found["references"] == "neurips 2020." and "we use marl." in found["text"]
    assert found["raw"].startswith("Intro\nWe use MARL.")

    def missing(path):
        raise FileNotFoundError("pdftotext not found")

    monkeypatch.setattr(papers, "pdf_pages", missing)
    assert rules.texts(paper, CONFIG, core.DIR_PAPERS)["text"] == ""


def test_rules_mix_with_embeddings_and_are_measured_apart(monkeypatch, rubrics):  # noqa: F811
    FakeEndpoint(monkeypatch)
    resolves_to(monkeypatch, "127.0.0.1")
    s, directories = models.settings(CONFIG), (core.DIR_PAPERS, core.DIR_EMBEDDINGS)
    include, labels = ("title", "abstract"), {1: "ROBOT", 2: "ROBOT"}
    config = CONFIG | {"areas_weight_rules": 0.6, "areas_temperature_rules": 0.1}
    plain, _ = areas.score(RECORDS, rubrics, s, include, config, directories, labels=labels)
    assert "rules" not in plain[1]["channels"] and areas.ranking(plain[1]) == ["LEARN", "ROBOT"]
    robot = rubrics["ROBOT"] | {"rules": [{"any": ["teams"], "weight": 2}]}
    ruled = rubrics | {"ROBOT": robot}
    results, _ = areas.score(RECORDS, ruled, s, include, config, directories, labels=labels)
    assert results[1]["rules"] == {"LEARN": [], "ROBOT": ["teams ×1 (+2)"]}
    assert areas.ranking(results[1], "embeddings")[0] == "LEARN"
    assert areas.ranking(results[1], "rules")[0] == areas.ranking(results[1])[0] == "ROBOT"
    assert areas.agreement(results, labels) == (
        "labels: best area 2/2 (embeddings alone 1/2, rules alone 1/1), top 3 2/2"
    )
    lines, _ = areas.revise(rubrics, ruled, RECORDS, labels, s, include, config, directories)
    assert lines[-2:] == [
        "Fixed: #1; broken: none",
        "Best area by each channel alone: embeddings 1/2 -> 1/2; rules 0/0 -> 1/1",
    ]
    with pytest.raises(ValueError, match="rule 1: any should be a list of terms"):
        areas.read(areas.dump(robot | {"rules": [{"any": "teams"}]}), "ROBOT")
