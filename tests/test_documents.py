import zipfile

from aamas_review_monitor import documents
from aamas_review_monitor.checks import RED, YELLOW, run
from aamas_review_monitor.documents import DOCUMENT_CHECKS, Document
from tests.test_checks import CONFIG

HEADER = "Research Paper Track\n\nAAMAS 2027, 3–7 May 2027, Hanoi, Vietnam\n"
FIRST = (
    f"{HEADER}A Study of Agents\nAnonymous Author(s) Submission Id: 7\n\nAbstract\n"
    "We study agents that negotiate under uncertainty.\n"
    "Proc. of the 26th International Conference on Autonomous Agents and Multiagent Systems "
    "(AAMAS 2027), Hanoi, Vietnam.\n"
)
BODY = HEADER + "Some text. " * 100
RECORD = {
    "number": 7,
    "content": {
        "title": {"value": "A Study of Agents"},
        "abstract": {"value": "We study agents that negotiate under uncertainty."},
    },
}
FONTS = [{"name": "ABCDEF+LinLibertineT", "type": "Type 1", "emb": "yes"}]
INFO = {"Author": "Anonymous Author(s)", "Page size": "612 x 792 pts (letter)"}


def doc(pages, info=INFO, fonts=FONTS, supplementary=None, record=RECORD):
    return Document(record, CONFIG, pages, info, fonts, supplementary)


def codes(d):
    return {(f.severity, code) for code, f in run(DOCUMENT_CHECKS, d)}


def paper(main_pages, after=""):
    """Pages: main text, then References at the top of the next page, then `after`."""
    return (
        [FIRST] + [BODY] * (main_pages - 1) + [f"{HEADER}References\n[1] A. Smith. 2020.\n{after}"]
    )


def test_a_compliant_paper_passes():
    assert codes(doc(paper(8))) == set()


def test_page_limits_and_appendix():
    assert codes(doc(paper(9))) == {(RED, "page_limit")}
    assert codes(doc(paper(5))) == {(YELLOW, "too_short")}
    with_appendix = paper(8) + [f"{HEADER}A Proofs\nTheorem 1 holds.\n"]
    assert codes(doc(with_appendix)) == {(RED, "appendix_in_paper")}
    assert codes(doc(paper(6) + [f"{HEADER}A Proofs\n"])) == set()  # 6 + 1 pages fit
    wrapped = paper(8, "A Survey of Multiagent Systems. In Proc. AAMAS, 2019.\n")
    assert codes(doc(wrapped + [BODY])) == set()  # a wrapped reference is no appendix
    no_heading = [FIRST] + [BODY] * 9
    assert codes(doc(no_heading)) == {(YELLOW, "page_limit")}


def test_format():
    a4 = INFO | {"Page size": "595.276 x 841.89 pts (A4)"}
    other = [{"name": "Times-Roman", "type": "Type 1", "emb": "no"}]
    assert codes(doc(paper(8), a4, other)) == {
        (RED, "page_size"),
        (YELLOW, "fonts:embedded"),
        (YELLOW, "fonts:typeface"),
    }
    old = [FIRST.replace("AAMAS 2027)", "AAMAS 2026)")] + paper(8)[1:]
    assert codes(doc(old)) == {(RED, "template")}


def test_anonymity():
    named = [FIRST.replace("Anonymous Author(s)", "Ada Lovelace, ada@uni.edu")] + paper(8)[1:]
    assert codes(doc(named, INFO | {"Author": "Ada Lovelace"})) == {
        (RED, "anonymous_mode:mode"),
        (RED, "anonymous_mode:metadata"),
        (YELLOW, "identifying_text:emails"),
    }
    revealing = paper(8)
    revealing[2] += "As in our previous work, code is at github.com/adalove/agents.\n"
    revealing[3] += "\nAcknowledgments\nWe thank our funders.\n"
    assert codes(doc(revealing)) == {
        (YELLOW, "identifying_text:acknowledgements"),
        (YELLOW, "identifying_text:repositories"),
        (YELLOW, "identifying_text:phrases"),
    }


def test_metadata_mismatch():
    other = RECORD | {
        "content": {"title": {"value": "Robots on Mars"}, "abstract": RECORD["content"]["abstract"]}
    }
    assert codes(doc(paper(8), record=other)) == {(YELLOW, "metadata_match:title")}
    changed = RECORD | {
        "content": RECORD["content"] | {"abstract": {"value": "Totally different words here now."}}
    }
    assert codes(doc(paper(8), record=changed)) == {(YELLOW, "metadata_match:abstract")}


def test_supplementary_material(tmp_path):
    experiments = paper(8)
    experiments[3] += "Our experiments and the experimental benchmark show gains.\n"
    assert codes(doc(experiments)) == {(YELLOW, "code_available")}
    linked = (
        experiments[:3] + [experiments[3] + "See anonymous.4open.science/r/x.\n"] + experiments[4:]
    )
    assert codes(doc(linked)) == set()

    archive = tmp_path / "supplementary_material_s.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("code/main.py", "DATA = '/Users/adalove/data'\n# ada@uni.edu\n")
        z.writestr("code/.git/HEAD", "ref: refs/heads/main")
    assert codes(doc(experiments, supplementary=archive)) == {
        (RED, "supplementary_anonymous:git"),
        (YELLOW, "supplementary_anonymous:homes"),
        (YELLOW, "supplementary_anonymous:emails"),
    }
    loose = tmp_path / "supplementary_material_s.pdf"
    loose.write_bytes(b"%PDF")
    assert codes(doc(paper(8), supplementary=loose)) == {(YELLOW, "supplementary_format:zip")}


def test_inspection_is_cached_per_attachment_version(tmp_path, monkeypatch):
    record = RECORD | {"content": RECORD["content"] | {"pdf": {"value": "/pdf/v1.pdf"}}}
    (tmp_path / "7").mkdir()
    (tmp_path / "7" / "pdf_v1.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(documents.papers, "pdf_text", lambda pdf: "\f".join(paper(9)) + "\f")
    monkeypatch.setattr(documents, "pdfinfo", lambda pdf: INFO)
    monkeypatch.setattr(documents, "pdffonts", lambda pdf: FONTS)
    found = documents.inspect_paper(record, CONFIG, tmp_path)
    assert [code for code, _ in found] == ["page_limit"]
    assert documents.inspection(record, CONFIG, tmp_path) == found
    cache = tmp_path / "7" / documents.FILE_INSPECTION
    cache.write_text(cache.read_text().replace('"checks"', '"older checks"'))
    assert documents.inspection(record, CONFIG, tmp_path) is None  # run before new checks
    documents.inspect_paper(record, CONFIG, tmp_path)
    record["content"]["pdf"]["value"] = "/pdf/v2.pdf"  # a new upload makes the results stale
    assert documents.inspection(record, CONFIG, tmp_path) is None


def test_chatbot_phrases_and_marker_words_in_the_pdf():
    leftover = BODY + "Certainly! Here is the related work section you asked for.\n"
    assert (YELLOW, "chatbot_phrases") in codes(doc([FIRST, leftover] + paper(7)[1:]))
    dense = BODY + "We delve into the intricate realm and showcase pivotal results. " * 4
    assert (YELLOW, "marker_words") in codes(doc([FIRST, dense] + paper(7)[1:]))
    assert not {c for _, c in codes(doc(paper(8)))} & {"chatbot_phrases", "marker_words"}


def test_pdffonts_output_of_xpdf_and_poppler():
    xpdf = """name                                 type              emb sub uni prob object ID
------------------------------------ ----------------- --- --- --- ---- ---------
NPWNPS+LinLibertineT                 Type 1            yes yes yes          51  0
Helvetica                            Type 1            no  no  no            7  0
"""
    poppler = """name                                 type              encoding         emb sub uni object ID
------------------------------------ ----------------- ---------------- --- --- --- ---------
NPWNPS+LinLibertineT                 Type 1            Custom           yes yes yes     51  0
Helvetica                            Type 1            WinAnsi          no  no  no       7  0
"""
    for output in (xpdf, poppler):
        fonts = documents.parse_pdffonts(output)
        assert [(f["name"], f["emb"]) for f in fonts] == [
            ("NPWNPS+LinLibertineT", "yes"),
            ("Helvetica", "no"),
        ]
