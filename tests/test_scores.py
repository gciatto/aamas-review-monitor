"""Area scores of papers: synthetic papers and rubrics, the fake embedding endpoint."""

import csv
import json

import pytest

from aamas_review_monitor import __main__ as cli
from aamas_review_monitor import areas, core, models, papers
from tests.test_areas import PAGE
from tests.test_checks import CONFIG as CHECKS_CONFIG
from tests.test_checks import paper
from tests.test_models import CONFIG as MODELS_CONFIG
from tests.test_models import FakeEndpoint, resolves_to

CONFIG = CHECKS_CONFIG | MODELS_CONFIG | {"areas_top_k": 1, "areas_temperature": 0.05}
CONFIG |= {"areas_include": ["title", "keywords", "abstract"], "field_pdf": "pdf"}


def record(number, title, abstract, review=None):
    reply = {
        "invitations": [f"V/Submission{number}/-/Official_Review"],
        "signatures": [f"V/Submission{number}/Reviewer_x"],
        "content": {"review": {"value": review}},
    }
    return {
        "number": number,
        "id": f"p{number}",
        "prefix": f"V/Submission{number}/",
        "names": {"review": "Official_Review", "meta_review": "Meta_Review"},
        "groups": {},
        "content": {"title": {"value": title}, "abstract": {"value": abstract}},
        "replies": [reply] if review else [],
    }


RECORDS = [
    record(1, "Multiagent learning", "Supervised learning for multiagent teams."),
    record(2, "Swarms", "Robots in swarms.", review="This is about robots and swarms."),
]


@pytest.fixture
def rubrics(monkeypatch):
    monkeypatch.setattr(areas, "DIR_RUBRICS_DEFAULT", core.DIR_DATA / "none")
    for rubric in areas.parse(PAGE, "https://example.org/call"):
        areas.save(rubric, core.DIR_RUBRICS)
    return areas.load(core.DIR_RUBRICS)


def scored(include=("title", "abstract"), cache_only=False):
    s = models.settings(CONFIG)
    directories = (core.DIR_PAPERS, core.DIR_EMBEDDINGS)
    return areas.score(
        RECORDS, areas.load(core.DIR_RUBRICS), s, include, CONFIG, directories, cache_only
    )


def test_papers_score_highest_on_their_area_with_the_nearest_topics_as_evidence(
    monkeypatch, rubrics
):
    FakeEndpoint(monkeypatch)
    resolves_to(monkeypatch, "127.0.0.1")
    results, failures = scored()
    assert failures == []
    first, second = results[1], results[2]
    assert first["shares"]["LEARN"] > 0.9 > first["shares"]["ROBOT"]
    assert second["shares"]["ROBOT"] > second["shares"]["LEARN"]
    assert abs(sum(first["shares"].values()) - 1) < 1e-3
    assert first["nearest"]["LEARN"][0][1] == "Multiagent learning"
    assert first["similarities"]["LEARN"] == first["nearest"]["LEARN"][0][0]  # top 1


def test_included_data_decides_what_is_embedded(monkeypatch, rubrics):
    endpoint = FakeEndpoint(monkeypatch)
    resolves_to(monkeypatch, "127.0.0.1")
    assert areas.parts(RECORDS[1], ("title",), CONFIG, core.DIR_PAPERS) == [["Swarms"]]
    with_reviews = ("title", "reviews", "text")  # no PDF downloaded: no text
    assert areas.parts(RECORDS[1], with_reviews, CONFIG, core.DIR_PAPERS) == [
        ["Swarms"],
        ["This is about robots and swarms."],
    ]
    assert areas.parts(RECORDS[0], ("reviews",), CONFIG, core.DIR_PAPERS) == []
    results, failures = scored(("reviews",))
    assert list(results) == [2] and failures == ["#1: nothing to embed among reviews"]
    sent = [t for r in endpoint.requests for t in r["input"]]
    assert "This is about robots and swarms." in sent and "Robots in swarms." not in sent
    long = record(3, " ".join(["word"] * (areas.WORDS_CHUNK + 1)), "")
    assert [len(c.split()) for c in areas.parts(long, ("title",), CONFIG, core.DIR_PAPERS)[0]] == [
        areas.WORDS_CHUNK,
        1,
    ]


def test_paper_data_never_reaches_a_remote_endpoint(monkeypatch, rubrics):
    endpoint = FakeEndpoint(monkeypatch)
    resolves_to(monkeypatch, "203.0.113.9")
    with pytest.raises(PermissionError):
        scored()
    assert all("Robots in swarms." not in r["input"] for r in endpoint.requests)  # topics only


def test_cache_only_scores_what_was_embedded_before(monkeypatch, rubrics):
    FakeEndpoint(monkeypatch)
    resolves_to(monkeypatch, "127.0.0.1")
    scored(("title",))
    results, failures = scored(("title", "abstract"), cache_only=True)
    assert results == {} and len(failures) == 2 and "cache only" in failures[0]
    assert scored(("title",), cache_only=True)[1] == []


def test_rows_carry_review_figures_and_sort_on_several_columns():
    snapshot = {
        "papers": [
            paper(1, ratings=(4, 6, 8)),
            paper(2, reviews=0),
            paper(3, ratings=(7, 7, 7), meta={"proceedings": "Accept", "findings": None}),
            paper(4, status="Withdrawn"),
        ]
    }
    results = {n: {"shares": {"LEARN": s, "ROBOT": 1 - s}} for n, s in ((1, 0.7), (3, 0.2))}
    found = areas.rows(snapshot, {1: RECORDS[0]}, results)
    assert [r["number"] for r in found] == [1, 2, 3]
    first, second, third = found
    assert first["title"] == "Multiagent learning" and first["best"] == "LEARN"
    assert first["margin"] == 0.4 and first["rating"] == 6 and first["spread"] == 1.63
    assert second["rating"] is None and "best" not in second and second["reviews"] == 0
    assert third["meta"] == "Accept" and third["best"] == "ROBOT"
    by_learn = areas.ordered(found, areas.sort_spec("-LEARN"))
    assert [r["number"] for r in by_learn] == [1, 3, 2]  # unscored last
    by_rating = areas.ordered(found, areas.sort_spec("-rating, ROBOT"))
    assert [r["number"] for r in by_rating] == [3, 1, 2]
    assert areas.sort_spec("best,-margin") == [("best", False), ("margin", True)]


def test_areas_command_prints_the_table_and_writes_csv(monkeypatch, rubrics, tmp_path, capsys):
    FakeEndpoint(monkeypatch)
    resolves_to(monkeypatch, "127.0.0.1")
    monkeypatch.setattr(core, "load_config", lambda: CONFIG)
    papers.save(RECORDS, core.DIR_PAPERS, [])
    core.DIR_SNAPSHOTS.mkdir(parents=True)
    snapshot = {"taken_at": "2026-11-11T08:00:00", "papers": [paper(1), paper(2, reviews=1)]}
    (core.DIR_SNAPSHOTS / "2026-11-11T080000.json").write_text(json.dumps(snapshot))
    out_csv = tmp_path / "areas.csv"
    cli.main(["areas", "--sort=-ROBOT", "--csv", str(out_csv)])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("bge-m3, title+keywords+abstract; rubrics ")
    assert out[1].split() == ["#", "LEARN", "ROBOT", "best", "margin", "reviews", "rating", "±"] + [
        "conf.",
        "meta",
        "title",
    ]
    assert out[2].split()[:4] == ["2", "0", "100", "ROBOT"] and out[2].endswith("Swarms")
    assert out[3].split()[0] == "1" and "LEARN" in out[3]
    rows = list(csv.DictReader(out_csv.open(encoding="utf-8")))
    assert [r["number"] for r in rows] == ["2", "1"] and rows[0]["best"] == "ROBOT"
    core.save_areas_view({"hidden": ["LEARN"], "sort": [("number", False)]})
    cli.main(["--cache-only", "areas", "2"])
    out = capsys.readouterr().out.splitlines()
    assert "LEARN" not in out[1] and len(out) == 3
    with pytest.raises(SystemExit, match="Cannot include pdf"):
        cli.main(["areas", "--include", "title,pdf"])
