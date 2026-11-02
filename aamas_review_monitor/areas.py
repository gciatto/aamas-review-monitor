"""Areas of the call for papers as rubrics, one YAML file per area: extracted from the public
page, then edited by the AC. The AC's copies (in the data folder) replace the shipped ones."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import operator
import re
import statistics
from collections import Counter
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests
import yaml

from aamas_review_monitor import models, papers
from aamas_review_monitor.collector import replies
from aamas_review_monitor.resources import DIR_RUBRICS_DEFAULT

KEYS = ("area", "code", "source", "topics", "description", "exemplars", "rules")
PATTERN_AREA = re.compile(r"^(?P<area>.+?)\s*\((?P<code>[A-Z]+)\)$")  # "Robotics (ROBOT)"
LABELS = ("Topics", "Description", "Area Chairs")  # what precedes each part of an area


class _Blocks(HTMLParser):
    """Flattens a page into (tag, text) blocks: headings, paragraphs and list items (a paragraph
    inside a list item belongs to the item)."""

    TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"}

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[tuple[str, str]] = []
        self.tag: str | None = None
        self.text: list[str] = []

    def flush(self) -> None:
        text = " ".join("".join(self.text).split())
        if self.tag and text:
            self.blocks.append((self.tag, text))
        self.tag, self.text = None, []

    def _block(self, tag: str) -> bool:
        return tag in self.TAGS and not (tag == "p" and self.tag == "li")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.text.append(" ")
        elif self._block(tag):
            self.flush()
            self.tag = tag

    def handle_endtag(self, tag: str) -> None:
        if self._block(tag):
            self.flush()

    def handle_data(self, data: str) -> None:
        if self.tag:
            self.text.append(data)


def digest(rubric: dict) -> str:
    """Fingerprint of an area's text as the page states it (topics and description)."""
    text = json.dumps([rubric["topics"], rubric["description"]], ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def parse(html: str, url: str) -> list[dict]:
    """The areas of a call for papers: each a heading "Name (CODE)", then "Topics:" with a list
    and "Description:" with paragraphs. The area chairs' names are not kept."""
    parser = _Blocks()
    parser.feed(html)
    parser.close()
    parser.flush()
    rubrics: list[dict] = []
    rubric: dict | None = None
    section = None
    for tag, text in parser.blocks:
        if tag.startswith("h"):
            match = PATTERN_AREA.match(text)
            rubric = None
            if match:
                rubric = {"area": match["area"], "code": match["code"], "source": {"url": url}}
                rubric |= {"topics": [], "description": "", "exemplars": [], "rules": []}
                rubrics.append(rubric)
                section = None
            continue
        if rubric is None:
            continue
        label, _, rest = text.partition(":")
        if label in LABELS:
            section, text = label, rest.strip()
        if section == "Topics" and tag == "li":
            rubric["topics"].append(text)
        elif section == "Description" and tag == "p" and text:
            rubric["description"] = f"{rubric['description']}\n\n{text}".strip()
    for rubric in rubrics:
        rubric["source"]["sha256"] = digest(rubric)
    return rubrics


def extract(url: str) -> list[dict]:
    """The areas of the call for papers at `url` (a public page)."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return parse(response.text, url)


def edited(rubric: dict) -> bool:
    """Whether the topics or description differ from the page they were extracted from."""
    return rubric.get("source", {}).get("sha256") != digest(rubric)


def problems(rubric: Any, code: str | None = None) -> list[str]:
    """What makes a rubric unusable; `code` is the one its file name gives."""
    if not isinstance(rubric, dict):
        return ["not a mapping of area, code, topics, ..."]
    found = [f"missing {k}" for k in KEYS if k not in rubric]
    found += [f"unknown key {k}" for k in rubric if k not in KEYS]
    if found:
        return found
    if not isinstance(rubric["area"], str) or not rubric["area"].strip():
        found.append("area should be a name")
    if not isinstance(rubric["code"], str) or not re.fullmatch(r"[A-Z]+", rubric["code"]):
        found.append("code should be capital letters, e.g. LEARN")
    elif code is not None and rubric["code"] != code:
        found.append(f"code {rubric['code']} differs from the file name {code}.yaml")
    if not isinstance(rubric["source"], dict):
        found.append("source should be a mapping of url and sha256")
    topics = rubric["topics"]
    if not isinstance(topics, list) or not all(isinstance(t, str) and t.strip() for t in topics):
        found.append("topics should be a list of texts")
    if not isinstance(rubric["description"], str):
        found.append("description should be a text")
    elif not topics and not rubric["description"].strip():
        found.append("topics and description are both empty: nothing describes the area")
    exemplars = rubric["exemplars"]
    if not isinstance(exemplars, list) or not all(isinstance(e, str) for e in exemplars):
        found.append("exemplars should be a list of texts")
    if not isinstance(rubric["rules"], list):
        found.append("rules should be a list")
    return found


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(
    str,
    lambda dumper, text: dumper.represent_scalar(
        "tag:yaml.org,2002:str", text, style="|" if "\n" in text else None
    ),
)


def dump(rubric: dict) -> str:
    return yaml.dump(rubric, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)


def read(text: str, code: str | None = None) -> dict:
    """A rubric from its YAML; ValueError saying what is wrong with it."""
    try:
        rubric = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"not valid YAML: {e}") from None
    if found := problems(rubric, code):
        raise ValueError("; ".join(found))
    return rubric


def files(directory: Path) -> dict[str, Path]:
    """Rubric files by code: the shipped ones, each replaced by the AC's copy in `directory`."""
    found = {
        f.stem: f for folder in (DIR_RUBRICS_DEFAULT, directory) for f in folder.glob("*.yaml")
    }
    return dict(sorted(found.items()))


def load(directory: Path) -> dict[str, dict]:
    """Rubrics by code; ValueError naming the file of an unusable one."""
    rubrics = {}
    for code, file in files(directory).items():
        try:
            rubrics[code] = read(file.read_text(encoding="utf-8"), code)
        except ValueError as e:
            raise ValueError(f"{file}: {e}") from None
    return rubrics


def save(rubric: dict, directory: Path) -> Path:
    """Saves the AC's copy of a rubric."""
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / f"{rubric['code']}.yaml"
    file.write_text(dump(rubric), encoding="utf-8")
    return file


def texts(rubric: dict) -> list[str]:
    """What describes an area, embedded one vector each: its topics, its description and its
    exemplars (all public: rubrics never hold paper data)."""
    description = [rubric["description"]] if rubric["description"].strip() else []
    return [*rubric["topics"], *description, *rubric["exemplars"]]


def similarity(vector: list[float], vectors: list[list[float]], k: int) -> float:
    """Mean of the `k` highest cosine similarities (unit vectors), rounded so that float noise
    across machines cannot reorder results."""
    best = heapq.nlargest(k, (sum(map(operator.mul, vector, v)) for v in vectors))
    return round(sum(best) / len(best), 4) if best else 0.0


def nearest(scores: dict[str, float]) -> str:
    """The best-scoring area; ties go to the first code alphabetically."""
    return max(sorted(scores), key=scores.__getitem__)


def confusion(rubrics: dict[str, dict], vectors: dict[str, list[list[float]]], k: int) -> dict:
    """Where each area's topics land when left out of it: per area, how many of its topics are
    nearest to each area (its own, ideally). Shows which areas the rubrics fail to separate."""
    found: dict[str, Counter[str]] = {}
    for code, own in vectors.items():
        found[code] = Counter()
        for i in range(len(rubrics[code]["topics"])):
            scores = {
                other: similarity(
                    own[i], [v for j, v in enumerate(vs) if (other, j) != (code, i)], k
                )
                for other, vs in vectors.items()
            }
            found[code][nearest(scores)] += 1
    return found


INCLUDE = ("title", "keywords", "abstract", "text", "reviews", "meta-reviews")
WORDS_CHUNK = 300  # ponytail: words, not tokens; well within the models' contexts


def _value(content: dict, key: str) -> str:
    value = content.get(key, {}).get("value") if isinstance(content.get(key), dict) else None
    return ", ".join(map(str, value)) if isinstance(value, list) else str(value or "")


def _chunks(text: str) -> list[str]:
    words = text.split()
    return [" ".join(words[i : i + WORDS_CHUNK]) for i in range(0, len(words), WORDS_CHUNK)]


def parts(record: dict, include: tuple[str, ...], config: dict, directory: Path) -> list[list[str]]:
    """What of a paper gets embedded, as parts of chunks: title, keywords and abstract together,
    then the PDF's text (if downloaded; FileNotFoundError without pdftotext), the reviews, the
    meta-reviews. Each part counts the same in the paper's vector, however long."""
    head = [_value(record["content"], k) for k in INCLUDE[:3] if k in include]
    found = [_chunks("\n".join(head))]
    pdf = papers.attachment(record, config["field_pdf"], directory)
    if "text" in include and pdf is not None and pdf.is_file():
        found.append(_chunks("\n".join(papers.pdf_pages(pdf))))
    for kind, name in (("review", "reviews"), ("meta_review", "meta-reviews")):
        if name in include:
            found.append(
                _chunks(
                    "\n".join(
                        v for r in replies(record, kind) for _, v in papers.fields(r["content"])
                    )
                )
            )
    return [p for p in found if p]


def _mean(vectors: list[list[float]]) -> list[float]:
    return [sum(column) / len(vectors) for column in zip(*vectors)]


def shares(similarities: dict[str, float], temperature: float) -> dict[str, float]:
    """Each area's share of the paper (a softmax of the similarities: they sum to 1). A lower
    temperature makes the nearest area take more."""
    top = max(similarities.values())
    weights = {c: math.exp((s - top) / temperature) for c, s in similarities.items()}
    total = sum(weights.values())
    return {c: round(w / total, 4) for c, w in weights.items()}


def fingerprint(rubrics: dict[str, dict]) -> str:
    """Names the rubrics' version in results."""
    return hashlib.sha256("".join(map(dump, rubrics.values())).encode()).hexdigest()[:12]


def score(
    records: list[dict],
    rubrics: dict[str, dict],
    s: models.Settings,
    include: tuple[str, ...],
    config: dict,
    directories: tuple[Path, Path],
    cache_only: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[dict[int, dict], list[str]]:
    """Area scores of each paper: similarity (mean of the `areas_top_k` nearest of the area's
    vectors), share, and the nearest topics as evidence; plus why some papers have none. The
    papers' text only goes to local endpoints. `directories`: the papers', the embeddings'."""
    folder, cache = directories
    k, temperature = config["areas_top_k"], config["areas_temperature"]
    area_texts = {c: texts(r) for c, r in rubrics.items()}
    flat = [t for ts in area_texts.values() for t in ts]
    vectors = iter(models.embed(s, flat, cache, private=False, cache_only=cache_only))
    by_area = {c: [next(vectors) for _ in ts] for c, ts in area_texts.items()}
    results, failures = {}, []
    for count, record in enumerate(records, 1):
        if progress:
            progress(count - 1, len(records))
        try:
            chunks = parts(record, include, config, folder)
            if not chunks:
                raise LookupError(f"nothing to embed among {', '.join(include)}")
            found = iter(models.embed(s, sum(chunks, []), cache, True, cache_only))
            vector = models._unit(_mean([_mean([next(found) for _ in p]) for p in chunks]))
        except (LookupError, FileNotFoundError) as e:
            failures.append(f"#{record['number']}: {e}")
            continue
        similarities, nearest_ = {}, {}
        for code, vs in by_area.items():
            similarities[code] = similarity(vector, vs, k)
            near = heapq.nlargest(
                3, zip((round(sum(map(operator.mul, vector, v)), 4) for v in vs), area_texts[code])
            )
            nearest_[code] = [[cos, text] for cos, text in near]
        results[record["number"]] = {
            "similarities": similarities,
            "shares": shares(similarities, temperature),
            "nearest": nearest_,
        }
    if progress:
        progress(len(records), len(records))
    return results, failures


def metrics(paper: dict) -> dict:
    """The review figures of a snapshot's paper, for the view."""
    ratings = [r["rating"] for r in paper["reviews"] if isinstance(r.get("rating"), (int, float))]
    confidences = [
        r["confidence"] for r in paper["reviews"] if isinstance(r.get("confidence"), (int, float))
    ]
    meta = paper.get("meta") or {}
    recommendation = " / ".join(str(meta[k]) for k in ("proceedings", "findings") if meta.get(k))
    return {
        "reviews": len(paper["reviews"]),
        "reviewers": len(paper.get("reviewers", [])),
        "rating": round(float(statistics.mean(ratings)), 2) if ratings else None,
        "spread": round(float(statistics.pstdev(ratings)), 2) if ratings else None,
        "confidence": round(float(statistics.mean(confidences)), 2) if confidences else None,
        "meta": recommendation or ("yes" if paper.get("meta_review") else None),
    }


def rows(snapshot: dict, records: dict[int, dict], results: dict[int, dict]) -> list[dict]:
    """One row per active paper: number, title, each area's share, best area and its margin
    over the second, then the review figures. Missing values are None."""
    found = []
    for paper in snapshot["papers"]:
        if paper.get("status", "active") != "active":
            continue
        number, result = paper["number"], results.get(paper["number"])
        record = records.get(number)
        row = {"number": number, "title": _value(record["content"], "title") if record else None}
        if result:
            ranked = sorted(result["shares"].items(), key=lambda cs: (-cs[1], cs[0]))
            row |= result["shares"] | {"best": ranked[0][0]}
            row["margin"] = round(ranked[0][1] - ranked[1][1], 4) if len(ranked) > 1 else None
        found.append(row | metrics(paper))
    return found


def ordered(found: list[dict], spec: list[tuple[str, bool]]) -> list[dict]:
    """Rows sorted by each (column, descending) of `spec`, the first deciding most; rows
    missing a value go last."""
    for column, descending in reversed(spec):
        known = [r for r in found if r.get(column) is not None]
        unknown = [r for r in found if r.get(column) is None]
        found = sorted(known, key=lambda r: r[column], reverse=descending) + unknown
    return found


def sort_spec(text: str) -> list[tuple[str, bool]]:
    """ "LEARN,-rating" -> [("LEARN", False), ("rating", True)]: a minus sorts descending."""
    return [
        (c.strip().lstrip("-"), c.strip().startswith("-")) for c in text.split(",") if c.strip()
    ]
