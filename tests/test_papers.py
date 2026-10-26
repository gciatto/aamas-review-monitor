import copy

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


def test_pdfs_are_converted_page_by_page_as_pdfinfo_counts_them_once(tmp_path, monkeypatch):
    import subprocess

    calls: list[list[str]] = []

    def run(command, check, capture_output):
        calls.append(command)
        if command[0].endswith("pdfinfo"):
            out = "Title: x\nPages:          3\n"
        else:  # pdftotext -f N -l N: page 2 is blank, and each page ends with a form feed
            page = command[command.index("-f") + 1]
            out = "" if page == "2" else f"text of page {page}\n"
            out += "\f"
        return subprocess.CompletedProcess(command, 0, out.encode())

    monkeypatch.setattr(papers.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(papers.subprocess, "run", run)
    pdf = tmp_path / "pdf_v1.pdf"
    pages = ["text of page 1\n", "", "text of page 3\n"]
    assert papers.pdf_pages(pdf) == papers.pdf_pages(pdf) == pages
    assert len(calls) == 4  # pdfinfo, then 3 pages; the second time from the cache
    assert calls[1][-6:] == ["-f", "1", "-l", "1", str(pdf), "-"]
    text = papers.pdf_text(pdf)
    assert text.startswith("── page 1 of 3 ──\ntext of page 1") and "── page 3 of 3 ──" in text


def test_history_entries_mention_their_issues_or_older_ones_their_messages():
    entry = {"via": 7, "papers": [7], "body": "- 2 reviews late", "issues": [[7, "late"]]}
    assert papers.mentions(entry, 7, "late", "anything")
    assert not papers.mentions(entry, 7, "no_spc", "2 reviews late")
    older = {k: v for k, v in entry.items() if k != "issues"}
    assert papers.mentions(older, 7, "late", "2 reviews late")
    assert not papers.mentions(older, 8, "late", "2 reviews late")
