import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "rubrics_benchmark", Path(__file__).parents[1] / "scripts" / "rubrics_benchmark.py"
)
assert _spec and _spec.loader
benchmark = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(benchmark)

CONTENTS = """<a name="K"></a>Keynotes <a href="../pdfs/KEY1.pdf"><strong>A Keynote</strong></a>
<a name="R" id="R"></a>Research Paper Track
<p><a href="../pdfs/ABCD1234.pdf" style="x"><font><strong>Learning   to
Coordinate</strong></font></a> (Page 4)</p>
<p><a href="../pdfs/EFGH5678.pdf"><strong>Fair Allocation</strong></a></p>
<a name="1"></a>Blue Sky <a href="../pdfs/BLUE1.pdf"><strong>An Idea</strong></a>"""

FRONT = """Learning to Coordinate
ABSTRACT
We study multi-
agent learning.
KEYWORDS
Reinforcement learning; Coordination, LEARN; GAAI
ACM Reference Format:
Someone. 2026."""


def test_research_papers_are_read_from_the_table_of_contents():
    assert benchmark.research_papers(CONTENTS) == [
        ("ABCD1234", "Learning to Coordinate"),
        ("EFGH5678", "Fair Allocation"),
    ]


def test_abstract_and_keywords_without_the_authors_area_codes():
    assert benchmark.front(FRONT) == (
        "We study multiagent learning.",
        ["Reinforcement learning", "Coordination"],
    )
    assert benchmark.front("No abstract here") is None


def test_labels_cover_both_splits_with_area_codes_only():
    labelled = json.loads(benchmark.FILE_LABELS.read_text())
    assert len(labelled["dev"]) == 161 and len(labelled["test"]) == 157
    assert not set(labelled["dev"]) & set(labelled["test"])
    codes = set(benchmark.CODES.strip(r"\b()").split("|"))
    assert set(labelled["dev"].values()) | set(labelled["test"].values()) <= codes
