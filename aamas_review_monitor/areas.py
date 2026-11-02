"""Areas of the call for papers as rubrics, one YAML file per area: extracted from the public
page, then edited by the AC. The AC's copies (in the data folder) replace the shipped ones."""

from __future__ import annotations

import hashlib
import heapq
import json
import operator
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests
import yaml

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
