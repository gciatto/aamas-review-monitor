"""On-request document checks of a paper's PDF and supplementary material.

Deterministic and local (xpdf's pdftotext/pdfinfo/pdffonts, zipfile): they produce flags for a
human to verify, never decisions. Results are cached next to the PDF, per attachment version.
"""

import hashlib
import json
import re
import zipfile
from functools import partial
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from aamas_review_monitor import markers, papers
from aamas_review_monitor.checks import RED, YELLOW, Finding, Issue, registrar, run

FILE_INSPECTION = "inspection.json"


def _heading(*words: str) -> re.Pattern[str]:
    """A line that is only one of `words`, in any case, maybe numbered ("7 References"), and
    maybe spaced out, as pdftotext extracts the template's small-caps headings ("R EFERENCES")."""
    spaced = "|".join("[ \t]*".join(map(re.escape, word)) for word in words)
    return re.compile(rf"^[ \t]*(\d+\.?[ \t]+)?({spaced})[ \t]*$", re.M | re.I)


HEADING_REFERENCES = _heading("References", "Bibliography")
# "Appendix", or a lettered section heading such as "A Proofs" alone on its line
HEADING_APPENDIX = re.compile(
    r"^\s*(Appendix|APPENDIX|Appendices|[A-Z]\s+[A-Z][a-z]+(\s+[A-Za-z-]+){0,6})\s*$", re.M
)
HEADING_ACKNOWLEDGEMENTS = _heading(
    "Acknowledgements", "Acknowledgments", "Acknowledgement", "Acknowledgment"
)
PATTERN_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PATTERN_HOME = re.compile(r"(/Users/|/home/|C:\\\\Users\\\\)([A-Za-z][\w.-]+)")
PATTERN_REPOSITORY = re.compile(r"(github\.com|gitlab\.com|bitbucket\.org)/([\w.-]+)", re.I)
PATTERN_CODE_LINK = re.compile(
    r"github\.com|gitlab\.com|bitbucket\.org|anonymous\.4open\.science|zenodo\.org|osf\.io|"
    r"figshare\.com|huggingface\.co",
    re.I,
)
PATTERN_SELF_REFERENCE = re.compile(
    r"\b(our|my) (previous|prior|earlier|recent) (work|paper|study|approach)|"
    r"\bwe (have )?(previously|earlier) (proposed|presented|introduced|showed|shown)",
    re.I,
)
PATTERN_EXPERIMENTS = re.compile(r"\b(experiments?|experimental|empirical|benchmarks?)\b", re.I)
SUFFIXES_CODE = {
    ".py", ".ipynb", ".java", ".kt", ".scala", ".c", ".cc", ".cpp", ".h", ".hpp", ".rs", ".go",
    ".js", ".ts", ".jl", ".r", ".m", ".sh", ".pl", ".lp", ".asp", ".pddl", ".netlogo", ".nlogo",
}  # fmt: skip
SUFFIXES_TEXT = SUFFIXES_CODE | {".txt", ".md", ".json", ".yaml", ".yml", ".cfg", ".ini", ".toml"}
TEMPLATE_MARK = "Autonomous Agents and Multiagent Systems (AAMAS 2027)"
LETTER = (612.0, 792.0)  # points


class Document(NamedTuple):
    record: dict
    config: dict
    pages: list[str]  # PDF text per page, from pdftotext in reading order
    info: dict[str, str]  # pdfinfo's fields
    fonts: list[dict[str, str]]  # pdffonts' rows: name, type, emb
    supplementary: Path | None  # the downloaded supplementary file, if any


# Same convention as the paper checks in `checks.py`: name = code, docstring = label + description
DOCUMENT_CHECKS: list = []
document_check = registrar(DOCUMENT_CHECKS)


def pdfinfo(pdf: Path) -> dict[str, str]:
    """pdfinfo's fields, with each page's size ("Page    3 size": "612 x 792 pts (letter)")."""
    lines = papers.tool(
        "pdfinfo", "-enc", "UTF-8", "-f", "1", "-l", "100000", str(pdf)
    ).splitlines()
    return {k.strip(): v.strip() for k, _, v in (line.partition(":") for line in lines) if v}


def pdffonts(pdf: Path) -> list[dict[str, str]]:
    return parse_pdffonts(papers.tool("pdffonts", str(pdf)))


def parse_pdffonts(output: str) -> list[dict[str, str]]:
    """pdffonts' table as dicts keyed by its header (name, type, emb, ...), split along the
    dashes under the header: works for xpdf and for poppler, which adds an encoding column."""
    lines = output.splitlines()
    if len(lines) < 2:
        return []
    spans = [m.span() for m in re.finditer(r"-+", lines[1])]
    keys = [lines[0][a:b].strip() for a, b in spans]
    return [{k: line[a:b].strip() for k, (a, b) in zip(keys, spans)} for line in lines[2:]]


class Parts(NamedTuple):
    main: int  # pages of main text
    appendix: int  # pages of appendix after the references
    references: int  # the page (from 1) with the References heading


def _main_pages(doc: Document) -> Parts | None:
    """How the PDF splits into main text and appendix; None without a References heading."""
    for index, page in enumerate(doc.pages):
        heading = HEADING_REFERENCES.search(page)
        if heading:
            # running headers put some text above a heading at the top of a page
            main = index + (len(page[: heading.start()].strip()) > 300)
            after = "\f".join([page[heading.end() :], *doc.pages[index + 1 :]])
            appendix = HEADING_APPENDIX.search(after)
            extra = (
                len(doc.pages) - index - after[: appendix.start()].count("\f") if appendix else 0
            )
            return Parts(main, extra, index + 1)
    return None


def _on(doc: Document, found: Callable[[str], object]) -> str:
    """The pages where `found(page text)` holds, e.g. " (p. 3, 5)"; empty if none (a match
    may straddle two pages)."""
    numbers = [n for n, page in enumerate(doc.pages, 1) if found(page)]
    return f" ({_listed(numbers, len(doc.pages))})" if numbers else ""


def _listed(numbers: list[int], total: int) -> str:
    """Page numbers, briefly: "p. 3, 5", "p. 1, 2, 3, 4, 5, …", or "all pages"."""
    if total > 1 and len(numbers) == total:
        return "all pages"
    return "p. " + ", ".join(map(str, numbers[:5])) + (", …" if len(numbers) > 5 else "")


def _where(doc: Document, parts: Parts) -> str:
    return f"References heading on page {parts.references} of {len(doc.pages)}"


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("-\n", ""))


@document_check
def page_limit(doc: Document) -> list[Finding]:
    """Main text within the page limit

    RED when the text before the References heading runs beyond {pages_max} pages; YELLOW when
    no References heading is found and the PDF has more than {pages_max} pages.
    """
    limit, parts = doc.config["pages_max"], _main_pages(doc)
    if parts is None:
        if len(doc.pages) > limit:
            return [Finding(YELLOW, f"{len(doc.pages)} pages, no References heading found")]
        return []
    if parts.main > limit:
        return [Finding(RED, f"main text on {parts.main} pages ({_where(doc, parts)})")]
    return []


@document_check
def appendix_in_paper(doc: Document) -> list[Finding]:
    """No appendix beyond the page limit

    RED when appendix sections after the references bring main text plus appendix beyond
    {pages_max} pages: AAMAS counts appendices in the paper toward the limit.
    """
    parts = _main_pages(doc)
    if parts and parts.appendix and parts.main + parts.appendix > doc.config["pages_max"]:
        message = f"main text {parts.main} pages + appendix {parts.appendix} pages"
        return [Finding(RED, f"{message} ({_where(doc, parts)})")]
    return []


@document_check
def too_short(doc: Document) -> list[Finding]:
    """Main text long enough

    YELLOW when the text before the References heading spans fewer than {pages_min} pages.
    """
    parts = _main_pages(doc)
    if parts and parts.main < doc.config["pages_min"]:
        return [Finding(YELLOW, f"main text on {parts.main} pages ({_where(doc, parts)})")]
    return []


@document_check
def page_size(doc: Document) -> list[Finding]:
    """US Letter pages

    RED when pages are not US Letter (612 x 792 pt), the size of the AAMAS template, saying
    which ones.
    """
    sizes = {
        int(m[1]): value
        for key, value in doc.info.items()
        if (m := re.fullmatch(r"Page\s+(\d+) size", key))
    } or {1: doc.info.get("Page size", "")}  # older pdfinfo output: the first page's only
    wrong: dict[str, list[int]] = {}
    for number, value in sorted(sizes.items()):
        size = re.match(r"([\d.]+) x ([\d.]+)", value)
        if size and (float(size[1]), float(size[2])) != LETTER:
            wrong.setdefault(f"{size[1]} x {size[2]} pt", []).append(number)
    return [
        Finding(RED, f"page size {size} ({_listed(numbers, len(doc.pages))})")
        for size, numbers in wrong.items()
    ]


@document_check
def fonts(doc: Document) -> list[Finding]:
    """Template fonts, all embedded

    YELLOW when a font is not embedded, or when no Libertine font (the template's typeface)
    is used.
    """
    found = []
    missing = sorted({f["name"] for f in doc.fonts if f.get("emb") == "no"})
    if missing:
        found.append(Finding(YELLOW, f"fonts not embedded: {', '.join(missing[:5])}", "embedded"))
    if doc.fonts and not any("Libertine" in f["name"] for f in doc.fonts):
        found.append(Finding(YELLOW, "no Libertine font: not the template's typeface", "typeface"))
    return found


@document_check
def template(doc: Document) -> list[Finding]:
    """AAMAS 2027 template

    YELLOW when the first page lacks the AAMAS 2027 copyright block of the template, e.g. because
    another or an older template was used, or the text extraction missed it.
    """
    first = " ".join(doc.pages[0].split()) if doc.pages else ""
    missing = Finding(YELLOW, "no AAMAS 2027 copyright block on page 1")
    return [] if TEMPLATE_MARK in first else [missing]


@document_check
def anonymous_mode(doc: Document) -> list[Finding]:
    """Anonymous submission mode

    RED when the first page lacks "Anonymous Author(s)" (the template's anonymous mode), or the
    PDF's Author metadata names someone.
    """
    found = []
    if doc.pages and "Anonymous Author" not in doc.pages[0]:
        found.append(Finding(RED, "first page not in anonymous mode", "mode"))
    author = doc.info.get("Author", "")
    if author and "anonymous" not in author.lower():
        found.append(Finding(RED, f"PDF metadata Author: {author}", "metadata"))
    return found


@document_check
def identifying_text(doc: Document) -> list[Finding]:
    """No identifying text

    YELLOW for email addresses on the first page, an Acknowledgements section, links to
    personal code repositories (anonymous.4open.science is fine), or self-revealing phrases
    such as "our previous work".
    """
    text, found = "\f".join(doc.pages), []
    emails = PATTERN_EMAIL.findall(doc.pages[0]) if doc.pages else []
    if emails:
        found.append(Finding(YELLOW, f"emails on page 1: {', '.join(emails[:3])}", "emails"))
    if HEADING_ACKNOWLEDGEMENTS.search(text):
        where = _on(doc, HEADING_ACKNOWLEDGEMENTS.search)
        found.append(Finding(YELLOW, f"Acknowledgements section{where}", "acknowledgements"))
    owners = sorted({m[1] for m in PATTERN_REPOSITORY.findall(text)})
    if owners:
        where = _on(doc, PATTERN_REPOSITORY.search)
        message = f"repository links: {', '.join(owners[:3])}{where}"
        found.append(Finding(YELLOW, message, "repositories"))
    phrases = sorted({m.group(0) for m in PATTERN_SELF_REFERENCE.finditer(text)})
    if phrases:
        where = _on(doc, PATTERN_SELF_REFERENCE.search)
        found.append(
            Finding(YELLOW, f"self-references: {'; '.join(phrases[:3])}{where}", "phrases")
        )
    return found


@document_check
def metadata_match(doc: Document) -> list[Finding]:
    """OpenReview metadata matches the PDF

    YELLOW when fewer than 80% of the OpenReview title's words, or of the abstract's 3-word
    phrases, appear in the PDF's first two pages: maybe a wrong PDF or a changed title.
    """
    found, start = [], set(_words(" ".join(doc.pages[:2])))
    start_text = " ".join(_words(" ".join(doc.pages[:2])))
    content = doc.record["content"]
    title = _words(str(content.get("title", {}).get("value", "")))
    if title and sum(w in start for w in title) < 0.8 * len(title):
        found.append(
            Finding(YELLOW, "OpenReview title not found in the PDF's first 2 pages", "title")
        )
    words = _words(str(content.get("abstract", {}).get("value", "")))
    phrases = [" ".join(words[i : i + 3]) for i in range(len(words) - 2)]
    if phrases:
        share = sum(p in start_text for p in phrases) / len(phrases)
        if share < 0.8:
            found.append(
                Finding(
                    YELLOW,
                    f"{share:.0%} of the abstract found in the PDF's first 2 pages",
                    "abstract",
                )
            )
    return found


def _entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    return archive.infolist()[:5000]  # ponytail: caps huge archives, read lazily if ever needed


@document_check
def supplementary_format(doc: Document) -> list[Finding]:
    """Supplementary material is one small zip

    YELLOW when the supplementary material is not a zip file or exceeds
    {supplementary_mb_max} MB.
    """
    if doc.supplementary is None:
        return []
    found, size = [], doc.supplementary.stat().st_size / 2**20
    if not zipfile.is_zipfile(doc.supplementary):
        found.append(Finding(YELLOW, f"not a zip file: {doc.supplementary.suffix}", "zip"))
    if size > doc.config["supplementary_mb_max"]:
        found.append(Finding(YELLOW, f"{size:.1f} MB", "size"))
    return found


@document_check
def supplementary_anonymous(doc: Document) -> list[Finding]:
    """Anonymous supplementary material

    RED when the zip contains a .git folder (its history names the authors); YELLOW for home
    folder paths (/Users/<name>, /home/<name>) or email addresses in its text files.
    """
    if doc.supplementary is None or not zipfile.is_zipfile(doc.supplementary):
        return []
    found: list[Finding] = []
    homes: dict[str, set[str]] = {}  # name -> the files it was found in
    emails: dict[str, set[str]] = {}
    with zipfile.ZipFile(doc.supplementary) as archive:
        entries = _entries(archive)
        gits = sorted(
            {e.filename.split(".git/")[0] for e in entries if "/.git/" in f"/{e.filename}"}
        )
        if gits:
            found.append(Finding(RED, f"contains a .git folder: {gits[0]}.git/", "git"))
        for entry in entries:
            if Path(entry.filename).suffix.lower() in SUFFIXES_TEXT and not entry.is_dir():
                with archive.open(entry) as file:
                    text = file.read(1_000_000).decode("utf-8", errors="replace")
                for m in PATTERN_HOME.findall(f"{entry.filename}\n{text}"):
                    homes.setdefault(m[1], set()).add(entry.filename)
                for email in PATTERN_EMAIL.findall(text):
                    emails.setdefault(email, set()).add(entry.filename)
    for what, code, by in (("home folders", "homes", homes), ("emails", "emails", emails)):
        if by:
            files = sorted(set().union(*by.values()))
            where = ", ".join(files[:3]) + (", …" if len(files) > 3 else "")
            found.append(Finding(YELLOW, f"{what}: {', '.join(sorted(by)[:3])} (in {where})", code))
    return found


@document_check
def code_available(doc: Document) -> list[Finding]:
    """Code available for the experiments

    YELLOW when the paper reports experiments but the supplementary material holds no source
    code and the paper links no code repository or archive.
    """
    text = "\f".join(doc.pages)
    if len(PATTERN_EXPERIMENTS.findall(text)) < 3 or PATTERN_CODE_LINK.search(text):
        return []
    if doc.supplementary and zipfile.is_zipfile(doc.supplementary):
        with zipfile.ZipFile(doc.supplementary) as archive:
            if any(Path(e.filename).suffix.lower() in SUFFIXES_CODE for e in _entries(archive)):
                return []
    where = _on(doc, PATTERN_EXPERIMENTS.search)
    return [Finding(YELLOW, f"experiments{where}, but no code in the supplementary or linked")]


def _has_phrase(phrase: str, page: str) -> bool:
    return phrase in markers.phrases(page)


@document_check
def chatbot_phrases(doc: Document) -> list[Finding]:
    """No leftover chatbot phrases

    YELLOW when the PDF contains a phrase chatbots produce and people rarely write, such as "as
    an AI language model", "Certainly! Here is" or "[insert" (the list is in
    resources/ai_phrases.txt). A hint to read the passage, not proof.
    """
    found = markers.phrases("\f".join(doc.pages))
    located = [f"{p}{_on(doc, partial(_has_phrase, p))}" for p in found[:3]]
    return [Finding(YELLOW, f"chatbot phrases: {'; '.join(located)}")] if found else []


@document_check
def marker_words(doc: Document) -> list[Finding]:
    """Not dense with chatbot-favoured words

    YELLOW when the PDF has at least {ai_markers_min} words such as "delve", "intricate" or
    "showcase" (resources/ai_words.txt) and more than {ai_markers_per_1000_max} of them per
    1000 words. Many people write like this too: a weak hint, to be read before anything else.
    """
    described = markers.dense(*markers.words("\f".join(doc.pages)), doc.config)
    if not described:
        return []
    counts = [sum(markers.words(page)[0].values()) for page in doc.pages]
    densest = sorted((n for n in range(len(counts)) if counts[n]), key=lambda n: -counts[n])
    where = ", ".join(str(n + 1) for n in densest[:3])
    return [Finding(YELLOW, f"{described}, most on p. {where}")]


def _checks_version() -> str:
    """Changes whenever the document checks' code or marker lists change, so that results
    cached by an older version of the checks count as not run."""
    files = [Path(__file__), Path(markers.__file__), markers.FILE_AI_PHRASES, markers.FILE_AI_WORDS]
    return hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest()[:16]


def _versions(record: dict, config: dict, directory: Path) -> dict[str, str | None]:
    files = {
        key: papers.attachment(record, config[key], directory)
        for key in ("field_pdf", "field_supplementary")
    }
    return {key: path.name if path else None for key, path in files.items()}


def inspect_paper(
    record: dict, config: dict, directory: Path, connect: Callable[[], Any] | None = None
) -> list[tuple[str, Finding]]:
    """Runs the document checks and caches the results; `connect()` gives a client to download
    missing attachments with (without it, they must already be downloaded)."""
    for key in ("field_pdf", "field_supplementary"):
        path = papers.attachment(record, config[key], directory)
        if connect and path and not path.is_file():
            papers.download(connect(), record, config[key], directory)
    pdf = papers.attachment(record, config["field_pdf"], directory)
    if pdf is None or not pdf.is_file():
        raise FileNotFoundError(f"#{record['number']}: PDF not downloaded")
    supplementary = papers.attachment(record, config["field_supplementary"], directory)
    if supplementary is not None and not supplementary.is_file():
        raise FileNotFoundError(f"#{record['number']}: supplementary material not downloaded")
    pages = papers.pdf_pages(pdf)
    doc = Document(record, config, pages, pdfinfo(pdf), pdffonts(pdf), supplementary)
    found = run(DOCUMENT_CHECKS, doc)
    result = {
        "versions": _versions(record, config, directory),
        "checks": _checks_version(),
        "findings": [[c, *f] for c, f in found],
    }
    file = directory / str(record["number"]) / FILE_INSPECTION
    file.write_text(json.dumps(result, indent=1), encoding="utf-8")
    file.chmod(0o600)
    return found


def inspection(record: dict, config: dict, directory: Path) -> list[tuple[str, Finding]] | None:
    """Cached document check results for the current attachments; None if not (re)run yet, or
    run by another version of the checks."""
    file = directory / str(record["number"]) / FILE_INSPECTION
    if not file.is_file():
        return None
    result = json.loads(file.read_text(encoding="utf-8"))
    if result["versions"] != _versions(record, config, directory):
        return None
    if result.get("checks") != _checks_version():
        return None
    return [
        (code, Finding(severity, message, detail))
        for code, severity, message, detail in result["findings"]
    ]


def downloaded(record: dict, config: dict, directory: Path) -> bool:
    """Whether every attachment the paper has is in the cache (no client needed to inspect)."""
    files = [
        papers.attachment(record, config[k], directory)
        for k in ("field_pdf", "field_supplementary")
    ]
    return all(f is None or f.is_file() for f in files)


def snapshot_issues(snapshot: dict, config: dict, directory: Path) -> tuple[list[Issue], set[int]]:
    """Cached document check results of the snapshot's papers (current attachments only), and
    the numbers of the papers they cover."""
    found, inspected, by_number = [], set(), {p["number"]: p for p in snapshot["papers"]}
    for record in papers.load(directory) if directory.is_dir() else []:
        paper, results = by_number.get(record["number"]), inspection(record, config, directory)
        if paper is None or results is None:
            continue
        inspected.add(paper["number"])
        spcs = tuple(paper["spcs"])
        found += [
            Issue(paper["number"], f.severity, c, f.message, paper["url"], spcs) for c, f in results
        ]
    return found, inspected
