import argparse
import getpass
import json
import logging
import os
import sys
from pathlib import Path

from aamas_review_monitor.checks import check, report, write_csv
from aamas_review_monitor.resources import FILE_CONFIG

# Confidential data lives outside the repository, readable only by the user
DIR_DATA = Path(os.environ.get("AAMAS_MONITOR_DATA", Path.home() / ".aamas-review-monitor"))
DIR_SNAPSHOTS = DIR_DATA / "snapshots"
FILE_TOKEN = DIR_DATA / "token"


def load_config() -> dict:
    config = json.loads(FILE_CONFIG.read_text(encoding="utf-8"))
    local = DIR_DATA / "config.json"  # optional overrides, e.g. updated deadlines
    return config | (json.loads(local.read_text(encoding="utf-8")) if local.is_file() else {})


def sync(config: dict) -> Path:
    import openreview  # type: ignore[import-untyped]

    from aamas_review_monitor.collector import collect

    DIR_SNAPSHOTS.mkdir(parents=True, exist_ok=True, mode=0o700)
    client = None
    if FILE_TOKEN.is_file():  # an expired token leaves the client without a profile
        client = openreview.api.OpenReviewClient(
            baseurl=config["url_api"], token=FILE_TOKEN.read_text(encoding="utf-8").strip()
        )
    if client is None or client.profile is None:
        client = openreview.api.OpenReviewClient(
            baseurl=config["url_api"],
            username=os.environ.get("OPENREVIEW_USERNAME") or input("OpenReview username: "),
            password=os.environ.get("OPENREVIEW_PASSWORD") or getpass.getpass("Password: "),
            tokenExpiresIn=7 * 24 * 3600,  # the longest OpenReview allows
        )
        FILE_TOKEN.touch(mode=0o600)
        FILE_TOKEN.write_text(client.token, encoding="utf-8")
    snapshot = collect(client, config)
    file = DIR_SNAPSHOTS / (snapshot["taken_at"][:19].replace(":", "") + ".json")
    file.write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
    file.chmod(0o600)
    return file


def main(argv: list[str] | None = None) -> None:
    # Only the application configures logging; importing the package leaves it alone.
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="aamas_review_monitor")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="fetch a new snapshot from OpenReview (read-only)")
    report_cmd = commands.add_parser("report", help="action queue from the latest snapshot")
    report_cmd.add_argument("--csv", type=Path, help="also write the issues to this CSV file")
    args = parser.parse_args(argv)

    config = load_config()
    if args.command == "sync":
        print(f"Saved {sync(config)}")
        return
    snapshots = sorted(DIR_SNAPSHOTS.glob("*.json"))
    if not snapshots:
        sys.exit(f"No snapshots in {DIR_SNAPSHOTS}: run `sync` first")
    latest, *older = [json.loads(f.read_text(encoding="utf-8")) for f in snapshots[-2:][::-1]]
    print(report(latest, config, older[0] if older else None))
    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as file:
            write_csv(check(latest, config), file)


if __name__ == "__main__":
    main()
