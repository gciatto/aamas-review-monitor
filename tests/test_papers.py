import copy
from pathlib import Path

from aamas_review_monitor import papers
from aamas_review_monitor.collector import fetch
from tests.test_collector import CONFIG, SUB, FakeClient

CONFIG = CONFIG | {"field_pdf": "pdf", "field_supplementary": "supplementary_material"}


def record():
    return fetch(FakeClient(), CONFIG)[0]


def test_cache_spots_updated_attachments(tmp_path):
    fields = ["pdf", "supplementary_material"]
    assert papers.save([record()], tmp_path, fields) == []
    newer = copy.deepcopy(record())
    newer["content"]["pdf"]["value"] = "/pdf/v2.pdf"
    assert papers.save([newer], tmp_path, fields) == ["#7: pdf updated"]
    assert papers.load(tmp_path) == papers.load(tmp_path, [7]) == [newer]


def test_download_reuses_current_copy(tmp_path):
    client, rec = FakeClient(), record()
    first = papers.download(client, rec, "pdf", tmp_path)
    assert first and first.read_bytes() == b"%PDF"
    assert papers.download(client, rec, "pdf", tmp_path) == first
    assert len(client.downloads) == 1
    rec["content"]["pdf"]["value"] = "/pdf/v2.pdf"
    second = papers.download(client, rec, "pdf", tmp_path)
    assert len(client.downloads) == 2 and not first.exists() and second and second.exists()
    assert papers.download(client, rec, "supplementary_material", tmp_path) is None


def test_metadata_and_reviews_keep_reviewers_anonymous():
    rec = record()
    assert papers.metadata(rec, CONFIG) == (
        "#7  https://openreview.net/forum?id=abc\ntitle: A Paper\nfindings_of_AAMAS_2027: No"
    )
    anonymous = papers.reviews(rec)
    assert "== Official_Review by Reviewer_aB3x" in anonymous and "~Rev_A1" not in anonymous
    assert "== Meta_Review by Area_Chair_9jqi\nmetareview: fine" in anonymous
    assert "== Official_Review by ~Rev_A1" in papers.reviews(rec, reveal=True)


def test_email_late_reviewers_through_paper_invitation():
    from aamas_review_monitor.outreach import direct

    client = FakeClient()
    drafts, unreachable = direct([record()], "late-reviewers", "Hi", "Body")
    assert unreachable == [] and papers.deliver(client, drafts) == []
    assert client.messages == [
        (
            ("Hi", ["~Rev_B1", "~Rev_C1"], "Body"),
            {
                "invitation": f"{SUB}7/-/Message",
                "signature": f"{SUB}7/Senior_Area_Chairs",
                "parentGroup": f"{SUB}7/Reviewers",
            },
        )
    ]


def test_pdf_text_is_converted_once(tmp_path, monkeypatch):
    calls = []

    def pdftotext(command, check):
        calls.append(command)
        Path(command[-1]).write_text("text")

    monkeypatch.setattr(papers.shutil, "which", lambda name: "/bin/pdftotext")
    monkeypatch.setattr(papers.subprocess, "run", pdftotext)
    pdf = tmp_path / "pdf_v1.pdf"
    assert papers.pdf_text(pdf) == papers.pdf_text(pdf) == "text"
    assert calls == [["/bin/pdftotext", "-enc", "UTF-8", "-q", str(pdf), str(pdf) + ".txt"]]
