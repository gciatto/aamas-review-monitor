"""Services shared by the CLI and the TUI: data dir, config, sign-in, sync, and the current
issues. Nothing here prints; the front ends present the results."""

from __future__ import annotations

import getpass
import json
import os
import threading
from datetime import datetime, timezone
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any, NamedTuple

from requests.adapters import HTTPAdapter
from urllib3.connectionpool import ConnectionPool
from urllib3.response import BaseHTTPResponse
from urllib3.util.retry import Retry

from aamas_review_monitor import documents, logger, papers
from aamas_review_monitor.checks import Issue, check
from aamas_review_monitor.collector import fetch, snapshot
from aamas_review_monitor.resources import FILE_CONFIG

# Confidential data lives outside the repository, readable only by the user
DIR_DATA = Path(os.environ.get("AAMAS_MONITOR_DATA", Path.home() / ".aamas-review-monitor"))
DIR_SNAPSHOTS = DIR_DATA / "snapshots"
DIR_PAPERS = DIR_DATA / "papers"
FILE_TOKEN = DIR_DATA / "token"
FILE_HISTORY = DIR_DATA / "history.jsonl"  # what the app sent: emails and comments


def load_config() -> dict:
    config = json.loads(FILE_CONFIG.read_text(encoding="utf-8"))
    local = DIR_DATA / "config.json"  # optional overrides, e.g. updated deadlines
    return config | (json.loads(local.read_text(encoding="utf-8")) if local.is_file() else {})


class Interrupted(BaseException):
    """The user stopped a running job. A BaseException, so per-paper `except Exception`
    handlers let it through instead of recording it as one more failure."""


# ponytail: one job runs at a time (the TUI blocks while it does), so one flag is enough
INTERRUPT = threading.Event()


class LoggedRetry(Retry):
    """Retry that logs each retry and its wait, and gives up the wait if INTERRUPT is set."""

    def increment(
        self,
        method: str | None = None,
        url: str | None = None,
        response: BaseHTTPResponse | None = None,
        error: Exception | None = None,
        _pool: ConnectionPool | None = None,
        _stacktrace: TracebackType | None = None,
    ) -> LoggedRetry:
        retry = super().increment(method, url, response, error, _pool, _stacktrace)
        reason = f"HTTP {response.status}" if response is not None else type(error).__name__
        done = len(retry.history)  # urllib3 counts `total` down, so the budget is done + left
        budget = done + retry.total if isinstance(retry.total, int) else "∞"
        logger.warning("%s on %s %s: retry %d of %s", reason, method, url, done, budget)
        return retry

    def sleep(self, response: Any = None) -> None:
        after = (
            self.get_retry_after(response) if response and self.respect_retry_after_header else None
        )
        wait = after if after is not None else self.get_backoff_time()
        if wait > 0:
            logger.warning(
                "waiting %.0f s before retrying%s", wait, " (Retry-After)" if after else ""
            )
        if INTERRUPT.wait(wait):
            raise Interrupted


def tune(client: Any, config: dict) -> Any:
    """Sets the client's retry policy from `config`: exponential backoff with jitter on rate
    limits (429), server errors (5xx) and connection failures, honouring Retry-After. Only
    reads are retried: a message POST is never resent, so no email can go out twice."""
    retry = LoggedRetry(
        total=config["retries"],
        connect=config["retries"],
        backoff_factor=config["backoff_seconds"],
        backoff_max=config["backoff_max_seconds"],
        backoff_jitter=1,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=128)
    # openreview-py retries POSTs to its edit endpoints: a retried new comment could be posted
    # twice, so those get this policy too (requests picks the longest matching prefix)
    edits = [getattr(client, f"{kind}_edits_url", None) for kind in ("note", "invitation", "group")]
    for prefix in ("https://", "http://", *filter(None, edits)):
        client.session.mount(prefix, adapter)
    return client


def resume(config: dict) -> Any | None:
    """A client from the cached session token; None if there is none or it expired."""
    import openreview  # type: ignore[import-untyped]

    if not FILE_TOKEN.is_file():
        return None
    client = openreview.api.OpenReviewClient(
        baseurl=config["url_api"], token=FILE_TOKEN.read_text(encoding="utf-8").strip()
    )
    return tune(client, config) if client.profile is not None else None  # expired: no profile


def login(config: dict, username: str | None = None, password: str | None = None) -> Any:
    """A signed-in client: cached token, else the given, environment or prompted credentials."""
    import openreview

    if client := resume(config):
        return client
    client = openreview.api.OpenReviewClient(
        baseurl=config["url_api"],
        username=username
        or os.environ.get("OPENREVIEW_USERNAME")
        or input("OpenReview username: "),
        password=password or os.environ.get("OPENREVIEW_PASSWORD") or getpass.getpass("Password: "),
        tokenExpiresIn=7 * 24 * 3600,  # the longest OpenReview allows
    )
    DIR_DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    FILE_TOKEN.touch(mode=0o600)
    FILE_TOKEN.write_text(client.token, encoding="utf-8")
    return tune(client, config)


def sync(
    config: dict, client: Any = None, progress: Callable[[int, int], None] | None = None
) -> tuple[Path, list[str]]:
    """Fetches and caches the papers, saves a snapshot; returns it and the updated attachments."""
    records = fetch(client or login(config), config, progress)
    fields = [config["field_pdf"], config["field_supplementary"]]
    changes = papers.save(records, DIR_PAPERS, fields)
    snap = snapshot(records, config)
    DIR_SNAPSHOTS.mkdir(parents=True, exist_ok=True, mode=0o700)
    file = DIR_SNAPSHOTS / (snap["taken_at"][:19].replace(":", "") + ".json")
    file.write_text(json.dumps(snap, indent=1), encoding="utf-8")
    file.chmod(0o600)
    return file, changes


def load_snapshots() -> tuple[dict | None, dict | None]:
    """The latest snapshot and the one before it, either None if missing."""
    files = sorted(DIR_SNAPSHOTS.glob("*.json"))[-2:][::-1]
    latest, previous, *_ = [json.loads(f.read_text(encoding="utf-8")) for f in files] + [None] * 2
    return latest, previous


class State(NamedTuple):
    """What the front ends work on: the latest snapshot and the one before it, its open issues
    (paper and cached document checks), and the papers whose current PDF was inspected."""

    latest: dict | None
    previous: dict | None
    issues: list[Issue]
    documents: list[Issue]  # the document checks' issues, also in `issues`
    inspected: set[int]


def current(config: dict) -> State:
    latest, previous = load_snapshots()
    if latest is None:
        return State(None, None, [], [], set())
    extra, inspected = documents.snapshot_issues(latest, config, DIR_PAPERS)
    return State(latest, previous, check(latest, config) + extra, extra, inspected)


def records(*numbers: int) -> list[dict]:
    """Cached records of the papers (all if none given); FileNotFoundError if one is missing."""
    if not numbers and not DIR_PAPERS.is_dir():
        return []
    return papers.load(DIR_PAPERS, list(numbers))


def freshness(latest: dict | None, config: dict, now: datetime | None = None) -> str:
    """How old the snapshot is, with a warning past `snapshot_stale_hours`: what is sent from an
    old snapshot may be about issues already resolved."""
    if latest is None:
        return "⚠ No snapshot: sync first"
    taken = datetime.fromisoformat(latest["taken_at"])
    taken = taken if taken.tzinfo else taken.replace(tzinfo=timezone.utc)
    hours = ((now or datetime.now(timezone.utc)) - taken).total_seconds() / 3600
    age = f"{hours:.0f} h" if hours >= 1 else f"{hours * 60:.0f} min"
    line = f"Snapshot of {taken.astimezone():%Y-%m-%d %H:%M}, {age} old"
    limit = config["snapshot_stale_hours"]
    return f"⚠ {line}: older than {limit} h, sync first?" if hours > limit else line
