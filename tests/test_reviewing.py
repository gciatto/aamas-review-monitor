import copy

import pytest

from aamas_review_monitor import core, reviewing
from aamas_review_monitor.resources import FILE_REVIEW_RUBRIC_DEFAULT


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
