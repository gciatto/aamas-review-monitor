"""Measures the area rubrics on published AAMAS 2026 papers (public proceedings, same 11 areas).

uv run poe rubrics-benchmark [--split dev|test|all] [--rubrics DIR] [--model M] [--weight W]

Downloads the proceedings' research-track PDFs once into --cache (~/.cache by default), takes
title, keywords and abstract from each first page, scores them as the app does (embeddings from
a local endpoint, rules on the PDFs) and compares the best area with the labels in
aamas2026_areas.json. Tune on dev, report test. --rubrics: a folder of rubric copies that
replace the shipped ones (as the AC's copies do). Nothing here touches the app's data folder.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path

import requests

URL_PROCEEDINGS = "https://ifaamas.org/Proceedings/aamas2026/"
FILE_LABELS = Path(__file__).with_name("aamas2026_areas.json")
CODES = r"\b(LEARN|GAAI|GTEP|COINE|SOPS|RR|EMAS|SIM|HAI|ROBOT|IASI)\b"


def research_papers(contents: str) -> list[tuple[str, str]]:
    """(PDF id, title) of the research-track papers in the proceedings' table of contents."""
    section = contents[contents.find('name="R"') : contents.find('name="1"')]
    found = re.findall(
        r'href="\.\./pdfs/([A-Z0-9]+)\.pdf"[^>]*>.*?<strong>(.*?)</strong>', section, re.S
    )
    return [(pdf, " ".join(title.split())) for pdf, title in found]


def front(text: str) -> tuple[str, list[str]] | None:
    """Abstract and keywords from a paper's first pages (ACM layout), without area codes some
    authors put among their keywords; None if there is no abstract."""
    found = re.search(
        r"\bABSTRACT\b(.*?)(?:\bKEYWORDS\b|\bCCS CONCEPTS\b|ACM Reference Format)", text, re.S
    )
    if not found:
        return None
    abstract = " ".join(found.group(1).replace("-\n", "").split())
    keys = re.search(r"\bKEYWORDS\b(.*?)ACM Reference Format", text, re.S)
    keywords = [" ".join(k.split()) for k in keys.group(1).split(";")] if keys else []
    keywords = [re.sub(rf"\s*[,;]?\s*{CODES}\s*[,;]?", " ", k).strip(" ,") for k in keywords]
    return abstract, [k for k in keywords if k]


def fetch(url: str, file: Path) -> Path:
    if not file.is_file():
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        file.write_bytes(response.content)
        time.sleep(0.3)  # politely
    return file


def records(cache: Path, wanted: set[str]) -> list[dict]:
    """The labelled papers as the app caches them: record.json and the PDF, numbered as listed."""
    (cache / "pdfs").mkdir(parents=True, exist_ok=True)
    contents = fetch(URL_PROCEEDINGS + "forms/contents.htm", cache / "contents.htm")
    found = []
    for number, (pdf, title) in enumerate(
        research_papers(contents.read_text("utf-8", "replace")), 1
    ):
        if pdf not in wanted:
            continue
        source = fetch(f"{URL_PROCEEDINGS}pdfs/{pdf}.pdf", cache / "pdfs" / f"{pdf}.pdf")
        run = subprocess.run(
            ["pdftotext", "-q", "-f", "1", "-l", "2", str(source), "-"], capture_output=True
        )
        if (parts := front(run.stdout.decode("utf-8", "replace"))) is None:
            continue
        content = {
            "title": title,
            "abstract": parts[0],
            "keywords": parts[1],
            "pdf": f"/pdf/{pdf}.pdf",
        }
        folder = cache / "papers" / str(number)
        folder.mkdir(parents=True, exist_ok=True)
        if not (folder / f"pdf_{pdf}.pdf").is_file():
            shutil.copy(source, folder / f"pdf_{pdf}.pdf")
        found.append(
            {
                "number": number,
                "id": pdf,
                "prefix": f"AAMAS2026/Submission{number}/",
                "names": {"review": "Official_Review", "meta_review": "Meta_Review"},
                "groups": {},
                "content": {k: {"value": v} for k, v in content.items()},
                "replies": [],
            }
        )
    return found


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--rubrics", type=Path, help="rubric copies replacing the shipped ones")
    parser.add_argument("--model", help="embedding model (default: as the app's settings)")
    parser.add_argument("--weight", type=float, help="areas_weight_rules")
    parser.add_argument(
        "--cache", type=Path, default=Path.home() / ".cache" / "aamas-rubrics-benchmark"
    )
    args = parser.parse_args()

    from aamas_review_monitor import areas, models
    from aamas_review_monitor.resources import FILE_CONFIG

    labelled = json.loads(FILE_LABELS.read_text())
    splits = ("dev", "test") if args.split == "all" else (args.split,)
    by_id = {pdf: code for s in splits for pdf, code in labelled[s].items()}
    found = records(args.cache, set(by_id))
    labels = {r["number"]: by_id[r["id"]] for r in found}
    config = json.loads(FILE_CONFIG.read_text())  # the shipped settings, not the user's
    if args.weight is not None:
        config["areas_weight_rules"] = args.weight
    rubrics = areas.load(args.rubrics or args.cache / "no-copies")
    s = models.settings(config, **({"model": args.model} if args.model else {}))
    include = ("title", "keywords", "abstract")
    results, failures = areas.score(
        found, rubrics, s, include, config, (args.cache / "papers", args.cache / "embeddings")
    )
    top1, top3, total = areas.accuracy(results, labels)
    print(f"{s.model}, rubrics {areas.fingerprint(rubrics)}, {args.split}: {total} papers")
    print(
        f"  best area {len(top1)}/{total} = {len(top1) / total:.0%}, top 3 {len(top3) / total:.0%}"
    )
    for channel in ("embeddings", "rules"):
        c1, c3, n = areas.accuracy(results, labels, channel)
        if n:
            print(f"  {channel} alone: {len(c1) / n:.0%}, top 3 {len(c3) / n:.0%} ({n} papers)")
    hits, per_area = Counter(labels[n] for n in top1), Counter(labels.values())
    print("  per area: " + "  ".join(f"{c} {hits[c]}/{per_area[c]}" for c in sorted(per_area)))
    confused = Counter(
        (labels[n], areas.ranking(results[n])[0]) for n in labels if n in results and n not in top1
    )
    print("  confused: " + ", ".join(f"{a}->{b} {k}" for (a, b), k in confused.most_common(6)))
    if failures:
        print(f"  not scored: {len(failures)} ({failures[0]})")


if __name__ == "__main__":
    main()
