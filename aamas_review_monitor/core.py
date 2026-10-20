"""Services shared by the CLI and the TUI: data dir, config, sign-in, sync, and the current
issues. Nothing here prints; the front ends present the results."""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import threading
import time
from datetime import date, datetime, timezone
from collections.abc import Callable, Iterator
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
FILE_IGNORED = DIR_DATA / "ignored.json"  # issues the user chose to ignore: [number, code]


def load_config() -> dict:
    """The shipped settings with the user's overrides; ValueError on an override that is not a
    setting (a typo would be silently ignored), of the wrong type, or a malformed date."""
    config = json.loads(FILE_CONFIG.read_text(encoding="utf-8"))
    local = DIR_DATA / "config.json"  # optional overrides, e.g. updated deadlines
    overrides = json.loads(local.read_text(encoding="utf-8")) if local.is_file() else {}
    for key, value in overrides.items():
        default = config.get(key)
        if key not in config:
            raise ValueError(f"{local}: {key} is not a setting")
        number = (int, float)  # either way: 1 or 0.5 seconds
        kind = number if type(default) in number else type(default)
        if not isinstance(value, kind) or isinstance(value, bool) != isinstance(default, bool):
            raise ValueError(f"{local}: {key} should be like {default!r}, not {value!r}")
    config |= overrides
    dates = [v for k, v in config.items() if k.startswith("deadline_") or k == "discussion_start"]
    for day in [*dates, *config["reviews_milestones"]]:
        try:
            date.fromisoformat(day)
        except ValueError:
            raise ValueError(f"{local}: {day!r} is not a YYYY-MM-DD date") from None
    return config


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


class ThrottledAdapter(HTTPAdapter):
    """Spaces requests at least 1/`rate` seconds apart, across threads: a proactive brake, so
    bulk jobs stay under OpenReview's rate limits instead of only backing off once hit. The wait
    gives up if INTERRUPT is set."""

    def __init__(self, rate: float, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.interval = 1 / rate if rate > 0 else 0.0  # 0: no cap
        self.lock, self.slot = threading.Lock(), 0.0  # when the next request may start

    def send(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        with self.lock:
            now = time.monotonic()
            wait, self.slot = max(0.0, self.slot - now), max(now, self.slot) + self.interval
        if wait and INTERRUPT.wait(wait):
            raise Interrupted
        return super().send(request, *args, **kwargs)


def tune(client: Any, config: dict) -> Any:
    """Sets the client's request policy from `config`: at most `requests_per_second_max`
    requests per second, then exponential backoff with jitter on rate limits (429), server
    errors (5xx) and connection failures, honouring Retry-After. Only reads are retried: a
    message POST is never resent, so no email can go out twice."""
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
    adapter = ThrottledAdapter(
        config["requests_per_second_max"], max_retries=retry, pool_maxsize=128
    )
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
    ignored: set[tuple[int, str]]  # (number, code) of the issues the user ignores

    @property
    def active(self) -> list[Issue]:
        """The issues not ignored: the ones that count, and that emails and comments are about."""
        return [i for i in self.issues if (i.number, i.code) not in self.ignored]


def current(config: dict) -> State:
    latest, previous = load_snapshots()
    if latest is None:
        return State(None, None, [], [], set(), ignored())
    extra, inspected = documents.snapshot_issues(latest, config, DIR_PAPERS)
    return State(latest, previous, check(latest, config) + extra, extra, inspected, ignored())


def ignored() -> set[tuple[int, str]]:
    """(paper number, issue code) of the issues the user ignores. An issue stays ignored for as
    long as its check keeps flagging it, across syncs."""
    if not FILE_IGNORED.is_file():
        return set()
    return {(n, c) for n, c in json.loads(FILE_IGNORED.read_text(encoding="utf-8"))}


def ignore(keys: set[tuple[int, str]], undo: bool = False) -> set[tuple[int, str]]:
    """Ignores the issues (or, with `undo`, no longer ignores them); returns all ignored."""
    found = ignored() - keys if undo else ignored() | keys
    DIR_DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    FILE_IGNORED.touch(mode=0o600)
    FILE_IGNORED.write_text(json.dumps(sorted(found)), encoding="utf-8")
    return found


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
    hours = max(0, ((now or datetime.now(timezone.utc)) - taken).total_seconds() / 3600)  # skew
    age = f"{hours:.0f} h" if hours >= 1 else f"{hours * 60:.0f} min"
    line = f"Snapshot of {taken.astimezone():%Y-%m-%d %H:%M}, {age} old"
    limit = config["snapshot_stale_hours"]
    return f"⚠ {line}: older than {limit} h, sync first?" if hours > limit else line


def download_each(
    client: Any, records: list[dict], field: str
) -> Iterator[tuple[dict, Path | None, Exception | None]]:
    """Downloads `field` of each paper, keeping current cached copies. Yields (record, path or
    None if it has no such file, error): after the retries, one failure doesn't stop the rest."""
    for record in records:
        try:
            yield record, papers.download(client, record, field, DIR_PAPERS), None
        except Exception as e:
            yield record, None, e


def inspect_each(
    records: list[dict], config: dict, connect: Callable[[], Any]
) -> Iterator[tuple[dict, list, Exception | None]]:
    """Runs the document checks of each paper, downloading what is missing through `connect()`.
    Yields (record, [(code, Finding)], error): a missing tool or file stops only that paper."""
    for record in records:
        try:
            yield record, documents.inspect_paper(record, config, DIR_PAPERS, connect), None
        except (OSError, subprocess.CalledProcessError) as e:
            yield record, [], e
