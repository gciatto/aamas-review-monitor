"""On-request document checks of a paper's PDF and supplementary material.

Deterministic and local (xpdf's pdftotext/pdfinfo/pdffonts, zipfile): they produce flags for a
human to verify, never decisions. Results are cached next to the PDF, per attachment version.
"""

import json
import re
import shutil
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from aamas_review_monitor import papers
from aamas_review_monitor.checks import RED, YELLOW, Finding, Issue, registrar, run

FILE_INSPECTION = "inspection.json"
HEADING_REFERENCES = re.compile(r"^\s*(References|REFERENCES|Bibliography)\s*$", re.M)
# "Appendix", or a lettered section heading such as "A Proofs" alone on its line
HEADING_APPENDIX = re.compile(
    r"^\s*(Appendix|APPENDIX|Appendices|[A-Z]\s+[A-Z][a-z]+(\s+[A-Za-z-]+){0,6})\s*$", re.M
)
HEADING_ACKNOWLEDGEMENTS = re.compile(r"^\s*(Acknowledge?ments?|ACKNOWLEDGE?MENTS?)\s*$", re.M)
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


def _tool(name: str, *args: str) -> str:
    tool = shutil.which(name)
    if not tool:
        raise FileNotFoundError(f"{name} not found: install xpdf (`brew install xpdf`)")
    return subprocess.run([tool, *args], check=True, capture_output=True, text=True).stdout


def pdfinfo(pdf: Path) -> dict[str, str]:
    lines = _tool("pdfinfo", "-enc", "UTF-8", str(pdf)).splitlines()
    return {k.strip(): v.strip() for k, _, v in (line.partition(":") for line in lines) if v}


def pdffonts(pdf: Path) -> list[dict[str, str]]:
    """pdffonts' table, split along the dashes under its header."""
    lines = _tool("pdffonts", str(pdf)).splitlines()
    if len(lines) < 2:
        return []
    spans = [m.span() for m in re.finditer(r"-+", lines[1])]
    keys = ["name", "type", "emb"]
    return [{k: line[a:b].strip() for k, (a, b) in zip(keys, spans)} for line in lines[2:]]


def _main_pages(doc: Document) -> tuple[int, int] | None:
    """(main text pages, appendix pages after the references); None without a References heading."""
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
            return main, extra
    return None


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
    return [Finding(RED, f"main text on {parts[0]} pages")] if parts[0] > limit else []


@document_check
def appendix_in_paper(doc: Document) -> list[Finding]:
    """No appendix beyond the page limit

    RED when appendix sections after the references bring main text plus appendix beyond
    {pages_max} pages: AAMAS counts appendices in the paper toward the limit.
    """
    parts = _main_pages(doc)
    if parts and parts[1] and sum(parts) > doc.config["pages_max"]:
        return [Finding(RED, f"main text {parts[0]} pages + appendix {parts[1]} pages")]
    return []


@document_check
def too_short(doc: Document) -> list[Finding]:
    """Main text long enough

    YELLOW when the text before the References heading spans fewer than {pages_min} pages.
    """
    parts = _main_pages(doc)
    if parts and parts[0] < doc.config["pages_min"]:
        return [Finding(YELLOW, f"main text on {parts[0]} pages")]
    return []


@document_check
def page_size(doc: Document) -> list[Finding]:
    """US Letter pages

    RED when the pages are not US Letter (612 x 792 pt), the size of the AAMAS template.
    """
    size = re.match(r"([\d.]+) x ([\d.]+)", doc.info.get("Page size", ""))
    if size and (float(size[1]), float(size[2])) != LETTER:
        return [Finding(RED, f"page size {size[1]} x {size[2]} pt")]
    return []


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

    RED when the first page lacks the AAMAS 2027 copyright block of the template, e.g. because
    another or an older template was used.
    """
    first = " ".join(doc.pages[0].split()) if doc.pages else ""
    return [] if TEMPLATE_MARK in first else [Finding(RED, "no AAMAS 2027 copyright block")]


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
        found.append(Finding(YELLOW, "Acknowledgements section", "acknowledgements"))
    owners = sorted({m[1] for m in PATTERN_REPOSITORY.findall(text)})
    if owners:
        found.append(Finding(YELLOW, f"repository links: {', '.join(owners[:3])}", "repositories"))
    phrases = sorted({m.group(0) for m in PATTERN_SELF_REFERENCE.finditer(text)})
    if phrases:
        found.append(Finding(YELLOW, f"self-references: {'; '.join(phrases[:3])}", "phrases"))
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
        found.append(Finding(YELLOW, "OpenReview title not found in the PDF", "title"))
    words = _words(str(content.get("abstract", {}).get("value", "")))
    phrases = [" ".join(words[i : i + 3]) for i in range(len(words) - 2)]
    if phrases:
        share = sum(p in start_text for p in phrases) / len(phrases)
        if share < 0.8:
            found.append(
                Finding(YELLOW, f"{share:.0%} of the abstract found in the PDF", "abstract")
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
    found, homes, emails = [], set(), set()
    with zipfile.ZipFile(doc.supplementary) as archive:
        entries = _entries(archive)
        if any("/.git/" in f"/{e.filename}" for e in entries):
            found.append(Finding(RED, "contains a .git folder", "git"))
        for entry in entries:
            if Path(entry.filename).suffix.lower() in SUFFIXES_TEXT and not entry.is_dir():
                with archive.open(entry) as file:
                    text = file.read(1_000_000).decode("utf-8", errors="replace")
                homes |= {m[1] for m in PATTERN_HOME.findall(f"{entry.filename}\n{text}")}
                emails |= set(PATTERN_EMAIL.findall(text))
    if homes:
        found.append(Finding(YELLOW, f"home folders: {', '.join(sorted(homes)[:3])}", "homes"))
    if emails:
        found.append(Finding(YELLOW, f"emails: {', '.join(sorted(emails)[:3])}", "emails"))
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
    return [Finding(YELLOW, "experiments, but no code in the supplementary or linked")]


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
    pages = papers.pdf_text(pdf).split("\f")
    pages = pages[:-1] if pages and not pages[-1].strip() else pages
    doc = Document(record, config, pages, pdfinfo(pdf), pdffonts(pdf), supplementary)
    found = run(DOCUMENT_CHECKS, doc)
    result = {
        "versions": _versions(record, config, directory),
        "findings": [[c, *f] for c, f in found],
    }
    file = directory / str(record["number"]) / FILE_INSPECTION
    file.write_text(json.dumps(result, indent=1), encoding="utf-8")
    file.chmod(0o600)
    return found


def inspection(record: dict, config: dict, directory: Path) -> list[tuple[str, Finding]] | None:
    """Cached document check results for the current attachments; None if not (re)run yet."""
    file = directory / str(record["number"]) / FILE_INSPECTION
    if not file.is_file():
        return None
    result = json.loads(file.read_text(encoding="utf-8"))
    if result["versions"] != _versions(record, config, directory):
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
