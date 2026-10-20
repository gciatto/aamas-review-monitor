from __future__ import annotations

import argparse
import functools
import logging
import sys
import textwrap
import webbrowser
from datetime import date
from pathlib import Path

from aamas_review_monitor import core, documents, outreach, papers
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

LEGEND_STATUS = "RED: serious, needs you; YELLOW: needs SPC attention; GREEN: no process issue"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="aamas_review_monitor")
    retries = parser.add_argument_group(
        "pace and retries (OpenReview requests; defaults from the config)"
    )
    retries.add_argument(
        "--rate",
        type=float,
        dest="requests_per_second_max",
        help="most requests per second (0: no cap)",
    )
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
    commands.add_parser("templates", help="list the email templates")
    comment_cmd = commands.add_parser(
        "comment", help="post each paper's open issues as a forum comment: preview, then SEND"
    )
    comment_cmd.add_argument("--spcs", action="store_true", help="let the papers' SPCs read it")
    comment_cmd.add_argument("--text", type=Path, help="post this file's text instead")
    history_cmd = commands.add_parser("history", help="emails and comments sent from the app")
    history_cmd.add_argument("--full", action="store_true", help="print the bodies too")
    outreach_cmd = commands.add_parser(
        "outreach", help="templated emails to SPCs or late reviewers: preview, then SEND"
    )
    outreach_cmd.add_argument("template", help="a template key, from `templates`")
    outreach_cmd.add_argument("--spc", action="append", help="only this SPC (repeatable)")
    for cmd in (download_cmd, email_cmd, inspect_cmd, outreach_cmd, comment_cmd, history_cmd):
        cmd.add_argument("numbers", type=int, nargs="*", help="papers (default: all)")
    args = parser.parse_args(argv)
    # Only the application configures logging; importing the package leaves it alone. The TUI
    # shows records in its job dialog, so nothing may write to the terminal under it.
    handlers = [logging.NullHandler()] if args.command == "tui" else None
    logging.basicConfig(level=logging.INFO, handlers=handlers)

    overrides = ("requests_per_second_max", "retries", "backoff_seconds", "backoff_max_seconds")
    try:
        config = core.load_config()
    except ValueError as e:
        sys.exit(f"Configuration error: {e}")
    config |= {k: getattr(args, k) for k in overrides if getattr(args, k) is not None}
    if args.command == "sync":
        file, changes = core.sync(config)
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
        state = core.current(config)
        if (latest := state.latest) is None:
            sys.exit(f"No snapshots in {core.DIR_SNAPSHOTS}: run `sync` first")
        if args.command == "report":
            print(report(latest, config, state.previous, state.documents, args.filter, args.green))
            if args.csv:
                issues = state.issues + (green_rows(latest, state.issues) if args.green else [])
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
        connect = functools.cache(lambda: core.login(config))  # logs in only to download
        for record, found, error in core.inspect_each(load_records(*args.numbers), config, connect):
            if error:
                print(f"#{record['number']}: not inspected ({error})")
                continue
            print(f"#{record['number']}: {len(found) or 'no'} document issues")
            print("\n".join(f"  {f.severity:6} {f.message}" for _, f in found))
    elif args.command == "browse":
        webbrowser.open(config["url_forum"] + load_records(args.number)[0]["id"])
    elif args.command == "attachment":
        (record,) = load_records(args.number)
        field = config["field_supplementary" if args.supplementary else "field_pdf"]
        path = papers.attachment(record, field, core.DIR_PAPERS)
        if path is None:
            sys.exit(f"#{args.number} has no {field}")
        if not path.is_file():
            papers.download(core.login(config), record, field, core.DIR_PAPERS)
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
        records, client = load_records(*args.numbers), core.login(config)
        field = config["field_supplementary" if args.supplementary else "field_pdf"]
        downloads = core.download_each(client, records, field)
        for count, (record, path, error) in enumerate(downloads, 1):
            result = f"failed ({error})" if error else path or f"no {field}"
            print(f"[{count}/{len(records)}] #{record['number']}: {result}")
    elif args.command == "templates":
        for t in outreach.templates():
            print(f"{t.key:20} {t.name} (to {t.audience}): {t.description}")
    elif args.command == "outreach":
        chosen = {t.key: t for t in outreach.templates()}.get(args.template)
        state = core.current(config)
        if chosen is None or state.latest is None:
            sys.exit("Unknown template: see `templates`" if chosen is None else "Run `sync` first")
        today = date.fromisoformat(state.latest["taken_at"][:10])
        drafts, unreachable = outreach.compose(
            chosen,
            state.issues,
            core.records(),
            config,
            today,
            set(args.spc) if args.spc else None,
            set(args.numbers) if args.numbers else None,
        )
        send(config, drafts, unreachable, state.latest)
    elif args.command == "comment":
        state = core.current(config)
        if state.latest is None:
            sys.exit("Run `sync` first")
        records = load_records(*args.numbers)
        to_post, skipped = outreach.comments(
            state.issues, records, {r["number"] for r in records}, args.spcs, config
        )
        if args.text:
            text = args.text.read_text(encoding="utf-8")
            to_post = [c._replace(text=text) for c in to_post]
        sent, notes = papers.history(core.FILE_HISTORY), [core.freshness(state.latest, config)]
        preview = outreach.preview_comments(to_post, skipped, sent, notes)
        if confirmed(preview, len(to_post), f"post {len(to_post)} comments"):
            failures = papers.post_comments(
                core.login(config), to_post, history_file=core.FILE_HISTORY
            )
            print(
                "\n".join([*failures, f"Posted {len(to_post) - len(failures)} of {len(to_post)}"])
            )
        else:
            print("Nothing posted")
    elif args.command == "history":
        entries = papers.history(core.FILE_HISTORY)
        if args.numbers:
            entries = [x for x in entries if any(papers.about(x, n) for n in args.numbers)]
        for entry in entries:
            papers_ = ", ".join(f"#{n}" for n in entry.get("papers", []))
            print(
                f"{entry['at'][:16]}  {entry['kind']:7}  via #{entry['via']}  {entry['status']:6}  to {entry['to']}"
            )
            print(
                f"    {entry['subject']}  [{papers_}]"
                + (f"  ({entry['template']})" if entry["template"] else "")
            )
            if args.full:
                print("    " + entry["body"].replace("\n", "\n    ").rstrip())
        print(
            f"{len(entries)} entries in {core.FILE_HISTORY}"
            if entries
            else "Nothing sent from the app yet"
        )
    elif args.command == "email":
        body = args.body.read_text(encoding="utf-8")
        drafts, unreachable = outreach.direct(
            load_records(*args.numbers), args.role, args.subject, body
        )
        send(config, drafts, unreachable, core.load_snapshots()[0])


def confirmed(preview: str, count: int, what: str) -> bool:
    """Shows everything about to go out; True only if there is something and the user types
    SEND."""
    print(preview)
    return count > 0 and input(f"Type SEND to {what}: ").strip() == "SEND"


def send(
    config: dict, drafts: list[papers.Draft], unreachable: list[str], latest: dict | None
) -> None:
    """Previews the drafts, warning on repeats and on an old snapshot, and sends them after a
    typed SEND, recording them in the history."""
    sent, notes = papers.history(core.FILE_HISTORY), [core.freshness(latest, config)]
    preview = outreach.preview(drafts, unreachable, sent, notes)
    if confirmed(preview, len(drafts), f"send {len(drafts)} messages"):
        failures = papers.deliver(core.login(config), drafts, history_file=core.FILE_HISTORY)
        print("\n".join([*failures, f"Sent {len(drafts) - len(failures)} of {len(drafts)}"]))
    else:
        print("Nothing sent")


def document_lines(number: int, config: dict) -> list[str]:
    """Cached document check results of a paper, as report lines."""
    try:
        (record,) = core.records(number)
    except FileNotFoundError:
        return []
    found = documents.inspection(record, config, core.DIR_PAPERS)
    if found is None:
        return [f"Document checks not run: `inspect {number}`"]
    issues = [Issue(number, f.severity, code, f.message, "", ()) for code, f in found]
    return [f"{i.severity:6} {i.message}" for i in issues] + [
        f"{'GREEN':6} {label}" for label in passed(issues, documents.DOCUMENT_CHECKS)
    ]


def load_records(*numbers: int) -> list[dict]:
    try:
        return core.records(*numbers)
    except FileNotFoundError as e:
        sys.exit(f"Not cached: {e.filename}. Is the paper yours? Run `sync` first")


if __name__ == "__main__":
    main()
