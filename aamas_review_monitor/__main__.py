import argparse
import functools
import getpass
import json
import logging
import os
import subprocess
import sys
import textwrap
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from aamas_review_monitor import documents, papers
from aamas_review_monitor.checks import (
    Issue,
    check,
    green_rows,
    legend,
    matches,
    passed,
    report,
    write_csv,
)
from aamas_review_monitor.collector import fetch, snapshot
from aamas_review_monitor.resources import FILE_CONFIG

# Confidential data lives outside the repository, readable only by the user
DIR_DATA = Path(os.environ.get("AAMAS_MONITOR_DATA", Path.home() / ".aamas-review-monitor"))
DIR_SNAPSHOTS = DIR_DATA / "snapshots"
DIR_PAPERS = DIR_DATA / "papers"
FILE_TOKEN = DIR_DATA / "token"
LEGEND_STATUS = "RED: serious, needs you; YELLOW: needs SPC attention; GREEN: no process issue"


def load_config() -> dict:
    config = json.loads(FILE_CONFIG.read_text(encoding="utf-8"))
    local = DIR_DATA / "config.json"  # optional overrides, e.g. updated deadlines
    return config | (json.loads(local.read_text(encoding="utf-8")) if local.is_file() else {})


def tune(client: Any, config: dict) -> Any:
    """Sets the client's retry policy from `config`: exponential backoff with jitter on rate
    limits (429), server errors (5xx) and connection failures, honouring Retry-After. Only
    reads are retried: a message POST is never resent, so no email can go out twice."""
    retry = Retry(
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
    for prefix in ("https://", "http://"):
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


def main(argv: list[str] | None = None) -> None:
    # Only the application configures logging; importing the package leaves it alone.
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="aamas_review_monitor")
    retries = parser.add_argument_group("retries (OpenReview reads; defaults from the config)")
    retries.add_argument("--retries", type=int, help="retries after a failure (config: retries)")
    retries.add_argument(
        "--backoff", type=float, dest="backoff_seconds", help="first wait in seconds, then doubling"
    )
    retries.add_argument(
        "--backoff-max", type=float, dest="backoff_max_seconds", help="longest wait in seconds"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="fetch papers and a new snapshot from OpenReview (read-only)")
    report_cmd = commands.add_parser("report", help="action queue from the latest snapshot")
    report_cmd.add_argument("--csv", type=Path, help="also write the issues to this CSV file")
    report_cmd.add_argument("--filter", default="", help="only issues matching (SPC, #N, text)")
    report_cmd.add_argument("--green", action="store_true", help="also list papers without issues")
    browse_cmd = commands.add_parser("browse", help="open a paper on OpenReview in the browser")
    attachment_cmd = commands.add_parser(
        "attachment", help="a paper's PDF or supplementary: path, contents, open (downloads it)"
    )
    attachment_cmd.add_argument("--supplementary", action="store_true", help="instead of the PDF")
    attachment_cmd.add_argument(
        "--contents", action="store_true", help="print PDF text or zip files"
    )
    attachment_cmd.add_argument("--open", action="store_true", help="open with the default app")
    attachment_cmd.add_argument("--reveal", action="store_true", help="show in Finder/Explorer")
    commands.add_parser("tui", help="interactive terminal UI over the latest snapshot")
    commands.add_parser("legend", help="what each check verifies, with current thresholds")
    inspect_cmd = commands.add_parser("inspect", help="document checks of PDFs (downloads them)")
    show_cmd = commands.add_parser("show", help="metadata and issues of a paper")
    issues_cmd = commands.add_parser("issues", help="issues of a paper")
    reviews_cmd = commands.add_parser("reviews", help="reviews and meta-reviews of a paper")
    reviews_cmd.add_argument("--reveal", action="store_true", help="show reviewer identities")
    for cmd in (show_cmd, issues_cmd, reviews_cmd, browse_cmd, attachment_cmd):
        cmd.add_argument("number", type=int)
    download_cmd = commands.add_parser("download", help="download PDFs (cached)")
    download_cmd.add_argument("--supplementary", action="store_true", help="supplementary instead")
    email_cmd = commands.add_parser("email", help="email a role of some papers (asks to confirm)")
    email_cmd.add_argument("role", choices=papers.ROLES)
    email_cmd.add_argument("--subject", required=True)
    email_cmd.add_argument("--body", type=Path, required=True, help="text file; {{fullname}} works")
    for cmd in (download_cmd, email_cmd, inspect_cmd):
        cmd.add_argument("numbers", type=int, nargs="*", help="papers (default: all)")
    args = parser.parse_args(argv)

    overrides = ("retries", "backoff_seconds", "backoff_max_seconds")
    config = load_config() | {
        k: getattr(args, k) for k in overrides if getattr(args, k) is not None
    }
    if args.command == "sync":
        file, changes = sync(config)
        print("\n".join([*changes, f"Saved {file}"]))
    elif args.command == "legend":
        print(LEGEND_STATUS)
        sections = [
            ("Paper checks", None),
            ("Document checks (run with `inspect`)", documents.DOCUMENT_CHECKS),
        ]
        for title, checks in sections:
            print(f"\n== {title}")
            for code, label, text in legend(config, checks):
                print(
                    f"\n{label} ({code})\n"
                    + textwrap.fill(text, 96, initial_indent="    ", subsequent_indent="    ")
                )
    elif args.command == "tui":
        from aamas_review_monitor.tui import Monitor

        Monitor(config).run()
    elif args.command in ("report", "show", "issues"):
        latest, previous = load_snapshots()
        if latest is None:
            sys.exit(f"No snapshots in {DIR_SNAPSHOTS}: run `sync` first")
        if args.command == "report":
            extra, _ = documents.snapshot_issues(latest, config, DIR_PAPERS)
            print(report(latest, config, previous, extra, args.filter, args.green))
            if args.csv:
                issues = check(latest, config) + extra
                issues += green_rows(latest, issues) if args.green else []
                with args.csv.open("w", newline="", encoding="utf-8") as file:
                    write_csv([i for i in issues if matches(i, args.filter)], file)
            return
        if args.command == "show":
            print(papers.metadata(load_records(args.number)[0], config) + "\n")
        mine = [i for i in check(latest, config) if i.number == args.number]
        mine_documents = document_lines(args.number, config)
        print(
            "\n".join(
                [f"{i.severity:6} {i.message}" for i in mine]
                + [f"{'GREEN':6} {label}" for label in passed(mine)]
                + mine_documents
            )
        )
    elif args.command == "inspect":
        connect = functools.cache(lambda: login(config))  # logs in only to download
        for record in load_records(*args.numbers):
            try:
                found = documents.inspect_paper(record, config, DIR_PAPERS, connect)
            except (FileNotFoundError, subprocess.CalledProcessError) as e:
                print(f"#{record['number']}: not inspected ({e})")
                continue
            print(f"#{record['number']}: {len(found) or 'no'} document issues")
            print("\n".join(f"  {f.severity:6} {f.message}" for _, f in found))
    elif args.command == "browse":
        webbrowser.open(config["url_forum"] + load_records(args.number)[0]["id"])
    elif args.command == "attachment":
        (record,) = load_records(args.number)
        field = config["field_supplementary" if args.supplementary else "field_pdf"]
        path = papers.attachment(record, field, DIR_PAPERS)
        if path is None:
            sys.exit(f"#{args.number} has no {field}")
        if not path.is_file():
            papers.download(login(config), record, field, DIR_PAPERS)
        print(path)
        if args.contents:
            print(papers.contents(path))
        if args.open:
            papers.os_open(path)
        if args.reveal:
            papers.os_open(path, reveal=True)
    elif args.command == "reviews":
        print(papers.reviews(load_records(args.number)[0], args.reveal))
    elif args.command == "download":
        records, client = load_records(*args.numbers), login(config)
        field = config["field_supplementary" if args.supplementary else "field_pdf"]
        for count, record in enumerate(records, 1):
            try:  # after the retries, one failure must not stop the other downloads
                result = papers.download(client, record, field, DIR_PAPERS) or f"no {field}"
            except Exception as e:
                result = f"failed ({e})"
            print(f"[{count}/{len(records)}] #{record['number']}: {result}")
    elif args.command == "email":
        records = load_records(*args.numbers)
        body = args.body.read_text(encoding="utf-8")
        papers.email(login(config), records, args.role, args.subject, body)


def document_lines(number: int, config: dict) -> list[str]:
    """Cached document check results of a paper, as report lines."""
    try:
        (record,) = papers.load(DIR_PAPERS, [number])
    except FileNotFoundError:
        return []
    found = documents.inspection(record, config, DIR_PAPERS)
    if found is None:
        return [f"Document checks not run: `inspect {number}`"]
    issues = [Issue(number, f.severity, code, f.message, "", ()) for code, f in found]
    return [f"{i.severity:6} {i.message}" for i in issues] + [
        f"{'GREEN':6} {label}" for label in passed(issues, documents.DOCUMENT_CHECKS)
    ]


def load_records(*numbers: int) -> list[dict]:
    try:
        return papers.load(DIR_PAPERS, list(numbers))
    except FileNotFoundError as e:
        sys.exit(f"Not cached: {e.filename}. Is the paper yours? Run `sync` first")


if __name__ == "__main__":
    main()
