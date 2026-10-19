import argparse
import getpass
import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aamas_review_monitor import papers
from aamas_review_monitor.checks import check, passed, report, write_csv
from aamas_review_monitor.collector import fetch, snapshot
from aamas_review_monitor.resources import FILE_CONFIG

# Confidential data lives outside the repository, readable only by the user
DIR_DATA = Path(os.environ.get("AAMAS_MONITOR_DATA", Path.home() / ".aamas-review-monitor"))
DIR_SNAPSHOTS = DIR_DATA / "snapshots"
DIR_PAPERS = DIR_DATA / "papers"
FILE_TOKEN = DIR_DATA / "token"


def load_config() -> dict:
    config = json.loads(FILE_CONFIG.read_text(encoding="utf-8"))
    local = DIR_DATA / "config.json"  # optional overrides, e.g. updated deadlines
    return config | (json.loads(local.read_text(encoding="utf-8")) if local.is_file() else {})


def resume(config: dict) -> Any | None:
    """A client from the cached session token; None if there is none or it expired."""
    import openreview  # type: ignore[import-untyped]

    if not FILE_TOKEN.is_file():
        return None
    client = openreview.api.OpenReviewClient(
        baseurl=config["url_api"], token=FILE_TOKEN.read_text(encoding="utf-8").strip()
    )
    return client if client.profile is not None else None  # expired: no profile


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
    return client


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
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="fetch papers and a new snapshot from OpenReview (read-only)")
    report_cmd = commands.add_parser("report", help="action queue from the latest snapshot")
    report_cmd.add_argument("--csv", type=Path, help="also write the issues to this CSV file")
    commands.add_parser("tui", help="interactive terminal UI over the latest snapshot")
    show_cmd = commands.add_parser("show", help="metadata and issues of a paper")
    issues_cmd = commands.add_parser("issues", help="issues of a paper")
    reviews_cmd = commands.add_parser("reviews", help="reviews and meta-reviews of a paper")
    reviews_cmd.add_argument("--reveal", action="store_true", help="show reviewer identities")
    for cmd in (show_cmd, issues_cmd, reviews_cmd):
        cmd.add_argument("number", type=int)
    download_cmd = commands.add_parser("download", help="download PDFs (cached)")
    download_cmd.add_argument("--supplementary", action="store_true", help="supplementary instead")
    email_cmd = commands.add_parser("email", help="email a role of some papers (asks to confirm)")
    email_cmd.add_argument("role", choices=papers.ROLES)
    email_cmd.add_argument("--subject", required=True)
    email_cmd.add_argument("--body", type=Path, required=True, help="text file; {{fullname}} works")
    for cmd in (download_cmd, email_cmd):
        cmd.add_argument("numbers", type=int, nargs="*", help="papers (default: all)")
    args = parser.parse_args(argv)

    config = load_config()
    if args.command == "sync":
        file, changes = sync(config)
        print("\n".join([*changes, f"Saved {file}"]))
    elif args.command == "tui":
        from aamas_review_monitor.tui import Monitor

        Monitor(config).run()
    elif args.command in ("report", "show", "issues"):
        latest, previous = load_snapshots()
        if latest is None:
            sys.exit(f"No snapshots in {DIR_SNAPSHOTS}: run `sync` first")
        if args.command == "report":
            print(report(latest, config, previous))
            if args.csv:
                with args.csv.open("w", newline="", encoding="utf-8") as file:
                    write_csv(check(latest, config), file)
            return
        if args.command == "show":
            print(papers.metadata(load_records(args.number)[0], config) + "\n")
        mine = [i for i in check(latest, config) if i.number == args.number]
        print(
            "\n".join(
                [f"{i.severity:6} {i.message}" for i in mine]
                + [f"{'GREEN':6} {label}" for label in passed(mine)]
            )
        )
    elif args.command == "reviews":
        print(papers.reviews(load_records(args.number)[0], args.reveal))
    elif args.command == "download":
        records, client = load_records(*args.numbers), login(config)
        field = config["field_supplementary" if args.supplementary else "field_pdf"]
        for record in records:
            print(f"#{record['number']}: {papers.download(client, record, field, DIR_PAPERS)}")
    elif args.command == "email":
        records = load_records(*args.numbers)
        body = args.body.read_text(encoding="utf-8")
        papers.email(login(config), records, args.role, args.subject, body)


def load_records(*numbers: int) -> list[dict]:
    try:
        return papers.load(DIR_PAPERS, list(numbers))
    except FileNotFoundError as e:
        sys.exit(f"Not cached: {e.filename}. Is the paper yours? Run `sync` first")


if __name__ == "__main__":
    main()
