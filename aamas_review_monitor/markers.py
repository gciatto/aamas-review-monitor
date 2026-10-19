"""Deterministic hints of generated text: leftover chatbot phrases and the density of words
chatbots overuse. Plain string matching against fixed lists in resources/; no model involved.
They are hints for a person to read the text, never evidence or a probability."""

import re
from collections import Counter
from pathlib import Path

from aamas_review_monitor.resources import FILE_AI_PHRASES, FILE_AI_WORDS


def _entries(file: Path) -> list[str]:
    lines = file.read_text(encoding="utf-8").splitlines()
    return [line.strip().lower() for line in lines if line.strip() and not line.startswith("#")]


PHRASES = _entries(FILE_AI_PHRASES)
WORDS = frozenset(_entries(FILE_AI_WORDS))


def _normal(text: str) -> str:
    """Lowercase, words hyphenated across lines joined, straight quotes, single spaces."""
    text = text.replace("-\n", "").replace("’", "'").replace("‘", "'").lower()
    return re.sub(r"\s+", " ", text)


def phrases(text: str) -> list[str]:
    """The listed chatbot phrases the text contains."""
    normal = _normal(text)
    return [p for p in PHRASES if p in normal]


def words(text: str) -> tuple[dict[str, int], int]:
    """How often each listed marker word occurs, most frequent first, and the text's words."""
    found = re.findall(r"[a-z]+", _normal(text))
    return dict(Counter(w for w in found if w in WORDS).most_common()), len(found)


def dense(counts: dict[str, int], total: int, config: dict) -> str | None:
    """A description of the marker words if there are at least `ai_markers_min` of them and
    more than `ai_markers_per_1000_max` per 1000 words; else None."""
    count = sum(counts.values())
    rate = 1000 * count / max(total, 1)
    if count < config["ai_markers_min"] or rate <= config["ai_markers_per_1000_max"]:
        return None
    top = ", ".join(f"{w} ×{n}" for w, n in list(counts.items())[:4])
    return f"{rate:.1f} marker words per 1000 ({top})"
