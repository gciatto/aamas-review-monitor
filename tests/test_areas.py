import pytest

from aamas_review_monitor import __main__ as cli
from aamas_review_monitor import areas, core

URL = "https://example.org/call"
# The shape of the AAMAS call: a list of the areas, then per area a heading, the chairs, the
# topics (paragraphs inside list items) and the description (one area uses a <br> after its label)
PAGE = """<html><body><h2>Areas of Interest</h2>
<ul><li><p>Learning (LEARN)</p></li><li><p>Robots (ROBOT)</p></li></ul>
<h3>Learning (LEARN)</h3>
<p>Area Chairs: Ada Lovelace, Alan Turing</p>
<p>Topics:</p>
<ul><li dir="ltr"><p role="presentation">Supervised   learning</p></li>
<li><p>Multiagent learning</p></li></ul>
<p>Description:</p><p>Papers on learning.</p><p>Not on robots: see ROBOT.</p>
<h3>Robots (ROBOT)</h3>
<p>Topics:</p><ul><li><p>Swarms</p></li></ul>
<p>Description:<br>Papers on robots.</p><p></p>
<h3>Contact us</h3><p>Nothing to see here.</p>
</body></html>"""


def test_parse_keeps_topics_and_descriptions_of_each_area_but_not_chairs():
    learn, robot = areas.parse(PAGE, URL)
    assert learn["area"] == "Learning" and learn["code"] == "LEARN"
    assert learn["topics"] == ["Supervised learning", "Multiagent learning"]
    assert learn["description"] == "Papers on learning.\n\nNot on robots: see ROBOT."
    assert robot["topics"] == ["Swarms"] and robot["description"] == "Papers on robots."
    assert "Lovelace" not in areas.dump(learn)
    assert learn["source"]["url"] == URL and not areas.edited(learn)
    learn["topics"].append("Bandits")
    assert areas.edited(learn)


def test_dump_and_read_round_trip_and_problems_are_explained():
    (learn, _) = areas.parse(PAGE, URL)
    assert areas.read(areas.dump(learn), "LEARN") == learn
    with pytest.raises(ValueError, match="differs from the file name"):
        areas.read(areas.dump(learn), "ROBOT")
    with pytest.raises(ValueError, match="not valid YAML"):
        areas.read("area: [", None)
    assert areas.problems([]) == ["not a mapping of area, code, topics, ..."]
    assert areas.problems({k: v for k, v in learn.items() if k != "rules"} | {"x": 1}) == [
        "missing rules",
        "unknown key x",
    ]
    empty = learn | {"topics": [], "description": " ", "code": "learn", "exemplars": {}}
    assert areas.problems(empty) == [
        "code should be capital letters, e.g. LEARN",
        "topics and description are both empty: nothing describes the area",
        "exemplars should be a list of texts",
    ]


def test_the_acs_copy_replaces_the_shipped_rubric(tmp_path):
    shipped = areas.load(tmp_path / "none")
    assert len(shipped) == 11 and "LEARN" in shipped
    mine = shipped["LEARN"] | {"topics": ["Bandits"]}
    areas.save(mine, tmp_path)
    assert areas.load(tmp_path)["LEARN"]["topics"] == ["Bandits"]
    (tmp_path / "GTEP.yaml").write_text("area: [", encoding="utf-8")
    with pytest.raises(ValueError, match="GTEP.yaml: not valid YAML"):
        areas.load(tmp_path)


def test_rubrics_command_extracts_lists_shows_and_edits(monkeypatch, capsys):
    from tests.test_models import FakeEndpoint

    FakeEndpoint(monkeypatch)  # editing reports what the edit changed: topics get embedded
    monkeypatch.setattr(areas, "extract", lambda url: areas.parse(PAGE, url))
    cli.main(["rubrics", "extract"])
    assert "LEARN  saved" in capsys.readouterr().out
    cli.main(["rubrics", "extract"])
    assert "LEARN  kept your copy" in capsys.readouterr().out
    cli.main(["rubrics", "list"])
    out = capsys.readouterr().out
    assert "LEARN  Learning  (2 topics, 0 exemplars, 0 rules; yours)" in out
    assert "GTEP   Game Theory and Economic Paradigms  (17 topics" in out
    cli.main(["rubrics", "show", "ROBOT"])
    assert "- Swarms" in capsys.readouterr().out

    def editor(command, check):
        file = command[-1]
        text = open(file, encoding="utf-8").read().replace("- Swarms", "- Swarms\n- Drones")
        open(file, "w", encoding="utf-8").write(text)

    monkeypatch.setattr(cli.subprocess, "run", editor)
    cli.main(["rubrics", "edit", "ROBOT"])
    assert capsys.readouterr().out.startswith("Saved")
    assert areas.load(core.DIR_RUBRICS)["ROBOT"]["topics"] == ["Swarms", "Drones"]
    monkeypatch.setattr(cli.subprocess, "run", lambda command, check: None)
    cli.main(["rubrics", "edit", "SIM"])  # a shipped rubric: edits a copy
    assert (core.DIR_RUBRICS / "SIM.yaml").is_file()
    with pytest.raises(SystemExit, match="Which area"):
        cli.main(["rubrics", "show", "NOPE"])
