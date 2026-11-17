import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "reviews_benchmark", Path(__file__).parents[1] / "scripts" / "reviews_benchmark.py"
)
assert _spec and _spec.loader
benchmark = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(benchmark)

LONG = "This paper proposes a method. " * 10


def paper(id, *reviews):
    return {"id": id, "title": f"Paper {id}", "abstract": f"About {id}.", "reviews": list(reviews)}


def test_records_keep_official_reviews_once_and_shape_them_like_the_app():
    official = {"comments": LONG, "RECOMMENDATION": 6, "REVIEWER_CONFIDENCE": 3}
    found = benchmark.record(
        paper(
            330,
            official,
            dict(official),  # PeerRead repeats entries
            {"comments": LONG + "Thanks!"},  # an author's note: no recommendation
            {"comments": "Too short.", "RECOMMENDATION": 4},
            {"comments": LONG, "RECOMMENDATION": 5, "IS_META_REVIEW": True},
        ),
        "dev",
        330,
    )
    ((review),) = found["replies"]
    assert review["id"] == "dev-330-1" and review["content"]["rating"]["value"] == 6
    assert review["signatures"] == ["ICLR2017/dev/Paper330/Reviewer_1"]
    assert found["content"]["abstract"]["value"] == "About 330."
    from aamas_review_monitor.collector import replies

    assert replies(found, "review") == [review]


def test_swapped_abstracts_agreement_and_threshold():
    a, b = ({"number": n, "content": {"abstract": n}} for n in (1, 2))
    assert [r["content"] for r in benchmark.swapped([a, b])] == [{"abstract": 2}, {"abstract": 1}]
    results = [{"id": "x", "criteria": {"summary": {"met": True}, "questions": {"met": False}}}]
    labels = {"x": {"summary": 1, "questions": 0}}
    assert benchmark.agreement(results, labels) == {
        "summary": [1, 1, 0, 0],
        "questions": [1, 1, 1, 1],
    }
    assert benchmark.best_threshold([0.8, 0.7, 0.4], [0.3, 0.5]) == (0.7, 0.8)
