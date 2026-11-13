from __future__ import annotations

import argparse
import csv
import functools
import logging
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
import webbrowser
from datetime import date
from pathlib import Path

from aamas_review_monitor import areas, core, documents, models, outreach, papers
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
    embeddings = parser.add_argument_group(
        "embeddings (area scores; defaults from AAMAS_MONITOR_EMBEDDINGS_<NAME>, then the config)"
    )
    embeddings.add_argument("--embeddings-vendor", help="preset: ollama or openai")
    embeddings.add_argument("--embeddings-url", help="base URL of the OpenAI-compatible API")
    embeddings.add_argument("--embeddings-model", help="model name, e.g. nomic-embed-text")
    embeddings.add_argument("--embeddings-api-key", help="API key, if the endpoint wants one")
    embeddings.add_argument(
        "--embeddings-networks", help="IP ranges paper data may go to, e.g. 127.0.0.0/8,10.0.0.0/8"
    )
    embeddings.add_argument("--embeddings-retries", type=int, help="retries after a failure")
    embeddings.add_argument(
        "--embeddings-backoff", type=float, dest="embeddings_backoff_seconds", help="first wait (s)"
    )
    embeddings.add_argument(
        "--embeddings-backoff-max",
        type=float,
        dest="embeddings_backoff_max_seconds",
        help="longest wait (s)",
    )
    embeddings.add_argument(
        "--cache-only", action="store_true", help="never ask the endpoint: cached embeddings only"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="fetch papers and a new snapshot from OpenReview (read-only)")
    report_cmd = commands.add_parser("report", help="action queue from the latest snapshot")
    report_cmd.add_argument("--csv", type=Path, help="also write the issues to this CSV file")
    report_cmd.add_argument("--filter", default="", help="only issues matching (SPC, #N, text)")
    report_cmd.add_argument("--green", action="store_true", help="also list papers without issues")
    browse_cmd = commands.add_parser("browse", help="open a paper on OpenReview in the browser")
    folder_cmd = commands.add_parser(
        "folder", help="print and open the local folder of a paper's data (PDF, text, results)"
    )
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
    legend_cmd = commands.add_parser(
        "legend", help="what each check verifies, with current thresholds"
    )
    legend_cmd.add_argument("filter", nargs="?", default="", help="only checks mentioning this")
    inspect_cmd = commands.add_parser("inspect", help="document checks of PDFs (downloads them)")
    show_cmd = commands.add_parser("show", help="metadata and issues of a paper")
    issues_cmd = commands.add_parser("issues", help="issues of a paper")
    reviews_cmd = commands.add_parser("reviews", help="reviews and meta-reviews of a paper")
    reviews_cmd.add_argument("--reveal", action="store_true", help="show reviewer identities")
    for cmd in (show_cmd, issues_cmd, reviews_cmd, browse_cmd, attachment_cmd, folder_cmd):
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
    ignore_cmd = commands.add_parser(
        "ignore", help="ignore issues of a paper (codes from `issues`); no arguments: list them"
    )
    ignore_cmd.add_argument("number", type=int, nargs="?")
    ignore_cmd.add_argument("codes", nargs="*", help="issue codes, e.g. disagreement")
    ignore_cmd.add_argument("--undo", action="store_true", help="count them again")
    history_cmd = commands.add_parser("history", help="emails and comments sent from the app")
    history_cmd.add_argument("--full", action="store_true", help="print the bodies too")
    outreach_cmd = commands.add_parser(
        "outreach", help="templated emails to SPCs or late reviewers: preview, then SEND"
    )
    outreach_cmd.add_argument("template", help="a template key, from `templates`")
    outreach_cmd.add_argument("--spc", action="append", help="only this SPC (repeatable)")
    rubrics_cmd = commands.add_parser(
        "rubrics", help="area rubrics: list, show, edit, check them, or extract them from the call"
    )
    rubrics_cmd.add_argument("action", choices=("list", "show", "edit", "check", "extract"))
    rubrics_cmd.add_argument("code", nargs="?", help="area code, e.g. LEARN (show, edit)")
    rubrics_cmd.add_argument("--url", help="page of the areas (extract; config: url_areas)")
    rubrics_cmd.add_argument(
        "--force", action="store_true", help="extract: replace your edited copies too"
    )
    areas_cmd = commands.add_parser(
        "areas", help="each paper's share of each area, with its reviews (embeds what is missing)"
    )
    areas_cmd.add_argument(
        "--include", help=f"what to embed, of {','.join(areas.INCLUDE)} (config: areas_include)"
    )
    areas_cmd.add_argument("--show", help="only these areas, e.g. LEARN,GTEP (default: not hidden)")
    areas_cmd.add_argument(
        "--sort",
        help="columns, the first deciding most, minus for descending: --sort=LEARN,-rating",
    )
    areas_cmd.add_argument("--csv", type=Path, help="also write every column to this CSV file")
    label_cmd = commands.add_parser(
        "label", help="give a paper the area you judge right (no arguments: list the labels)"
    )
    label_cmd.add_argument("number", type=int, nargs="?")
    label_cmd.add_argument("code", nargs="?", help="area code, e.g. LEARN")
    label_cmd.add_argument("--undo", action="store_true", help="remove the paper's label")
    for cmd in (email_cmd, outreach_cmd, comment_cmd):
        cmd.add_argument(
            "--edit", action="store_true", help="edit each message in $EDITOR before the preview"
        )
    numbered_cmds = (download_cmd, email_cmd, inspect_cmd, outreach_cmd, comment_cmd, history_cmd)
    for cmd in (*numbered_cmds, areas_cmd):
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
            for code, label, text in legend(config, checks, args.filter):
                print(
                    f"\n{label} ({code})\n"
                    + textwrap.fill(text, 96, initial_indent="    ", subsequent_indent="    ")
                )
    elif args.command == "tui":
        from aamas_review_monitor.tui import Monitor

        Monitor(config, embeddings_given(args), args.cache_only).run()
    elif args.command in ("report", "show", "issues"):
        state = core.current(config)
        if (latest := state.latest) is None:
            sys.exit(f"No snapshots in {core.DIR_SNAPSHOTS}: run `sync` first")
        if args.command == "report":
            print(
                report(
                    latest,
                    config,
                    state.previous,
                    state.documents,
                    args.filter,
                    args.green,
                    state.ignored,
                )
            )
            if args.csv:
                issues = state.issues + (green_rows(latest, state.issues) if args.green else [])
                with args.csv.open("w", newline="", encoding="utf-8") as file:
                    write_csv([i for i in issues if matches(i, args.filter)], file, state.ignored)
            return
        if args.command == "show":
            print(papers.metadata(load_records(args.number)[0], config) + "\n")
        mine = [i for i in check(latest, config) if i.number == args.number]
        mine_documents = document_lines(args.number, config, state.ignored)
        print(
            "\n".join(
                [issue_line(i, state.ignored) for i in mine]
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
    elif args.command == "folder":
        folder = core.DIR_PAPERS / str(args.number)
        if not folder.is_dir():
            sys.exit(f"#{args.number} is not cached. Is the paper yours? Run `sync` first")
        print(folder)
        papers.os_open(folder)
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
            state.active,
            core.records(),
            config,
            today,
            set(args.spc) if args.spc else None,
            set(args.numbers) if args.numbers else None,
        )
        send(config, drafts, unreachable, state.latest, args.edit)
    elif args.command == "comment":
        state = core.current(config)
        if state.latest is None:
            sys.exit("Run `sync` first")
        records = load_records(*args.numbers)
        to_post, skipped = outreach.comments(
            state.active,
            records,
            {r["number"] for r in records},
            args.spcs,
            config,
            date.fromisoformat(state.latest["taken_at"][:10]),
        )
        if args.text:
            text = args.text.read_text(encoding="utf-8")
            to_post = [c._replace(text=text) for c in to_post]
        sent, notes = papers.history(core.FILE_HISTORY), [core.freshness(state.latest, config)]
        header, items = outreach.review_comments(to_post, skipped, sent, notes)
        if args.edit:
            items = edit(items, "Title")
            to_post = [c._replace(title=i.title, text=i.text) for c, i in zip(to_post, items)]
        if problems := outreach.problems(items, outreach.COMMENT_LIMITS):
            sys.exit("\n".join([*problems, "Nothing posted"]))
        preview = outreach.render(header, items, "Title")
        if confirmed(preview, len(to_post), f"post {len(to_post)} comments"):
            failures = papers.post_comments(
                core.login(config), to_post, history_file=core.FILE_HISTORY
            )
            print(
                "\n".join([*failures, f"Posted {len(to_post) - len(failures)} of {len(to_post)}"])
            )
        else:
            print("Nothing posted")
    elif args.command == "ignore":
        if args.number is not None:
            if not args.codes:
                sys.exit("Which issues? Their codes are in `issues N`, in brackets")
            core.ignore({(args.number, c) for c in args.codes}, args.undo)
        listed = sorted(core.ignored())
        print("\n".join(f"#{n}  {c}" for n, c in listed) or "No issue is ignored")
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
    elif args.command == "rubrics":
        rubrics(args, config)
    elif args.command == "areas":
        areas_table(args, config)
    elif args.command == "label":
        if args.number is not None:
            codes = list(areas.files(core.DIR_RUBRICS))
            if not args.undo and args.code not in codes:
                sys.exit(f"Which area? One of {', '.join(codes)}")
            core.label(args.number, None if args.undo else args.code)
        print("\n".join(f"#{n}  {c}" for n, c in core.labels().items()) or "No paper is labelled")
    elif args.command == "email":
        body = args.body.read_text(encoding="utf-8")
        drafts, unreachable = outreach.direct(
            load_records(*args.numbers), args.role, args.subject, body
        )
        send(config, drafts, unreachable, core.load_snapshots()[0], args.edit)


def confirmed(preview: str, count: int, what: str) -> bool:
    """Shows everything about to go out; True only if there is something and the user types
    SEND."""
    print(preview)
    return count > 0 and input(f"Type SEND to {what}: ").strip() == "SEND"


def rubrics(args: argparse.Namespace, config: dict) -> None:
    broken = None  # an unusable copy: `edit` can still repair it, `extract --force` replace it
    try:
        loaded = areas.load(core.DIR_RUBRICS)
    except ValueError as e:
        if args.action not in ("edit", "extract"):
            sys.exit(f"{e}. Repair it with `rubrics edit CODE` or `rubrics extract --force`")
        loaded, broken = {}, e
    if args.action == "extract":
        url = args.url or config["url_areas"]
        for rubric in areas.extract(url):
            mine = core.DIR_RUBRICS / f"{rubric['code']}.yaml"
            if mine.is_file() and not args.force:
                print(f"{rubric['code']:6} kept your copy {mine} (--force replaces it)")
            else:
                print(f"{rubric['code']:6} saved {areas.save(rubric, core.DIR_RUBRICS)}")
        return
    if args.action == "list":
        yours = {f.stem for f in core.DIR_RUBRICS.glob("*.yaml")}
        for code, r in loaded.items():
            notes = ["yours" if code in yours else "shipped"] + ["edited"] * areas.edited(r)
            counts = f"{len(r['topics'])} topics, {len(r['exemplars'])} exemplars"
            counts += f", {len(r['rules'])} rules"
            print(f"{code:6} {r['area']}  ({counts}; {', '.join(notes)})")
        return
    if args.action == "check":
        texts = {code: areas.texts(r) for code, r in loaded.items()}
        try:
            vectors = embedded(args, config, sum(texts.values(), []), private=False)
        except (models.NotEmbedded, PermissionError, ValueError, OSError) as e:
            sys.exit(f"Embeddings: {e}")
        by_area = {code: [vectors.pop(0) for _ in t] for code, t in texts.items()}
        print(
            f"Where each area's topics land when left out of it ({config['areas_top_k']} nearest):"
        )
        for code, counts in areas.confusion(loaded, by_area, config["areas_top_k"]).items():
            others = ", ".join(f"{c} {n}" for c, n in counts.most_common() if c != code)
            total = len(loaded[code]["topics"])
            print(f"{code:6} {counts[code]}/{total} own" + (f"; {others}" if others else ""))
        return
    files = areas.files(core.DIR_RUBRICS)
    if args.code not in files:
        sys.exit(f"Which area? One of {', '.join(files)}")
    if args.action == "show":
        print(areas.dump(loaded[args.code]), end="")
        return
    file = core.DIR_RUBRICS / f"{args.code}.yaml"
    if not file.is_file():  # a copy of the shipped one
        core.DIR_RUBRICS.mkdir(parents=True, exist_ok=True)
        shutil.copy(files[args.code], file)
    subprocess.run([*editor(), str(file)], check=True)
    try:
        after = loaded | {args.code: areas.read(file.read_text(encoding="utf-8"), args.code)}
    except ValueError as e:
        sys.exit(f"{file}: {e}. Fix it with `rubrics edit {args.code}`")
    print(f"Saved {file}")
    if broken:  # nothing valid to compare with
        try:
            areas.load(core.DIR_RUBRICS)
        except ValueError as e:
            sys.exit(f"Still unusable: {e}")
        return
    if after == loaded:
        return
    try:
        s = models.settings(config, **embeddings_given(args))
        lines, _ = areas.revise(
            loaded,
            after,
            core.records(),
            core.labels(),
            s,
            tuple(config["areas_include"]),
            config,
            (core.DIR_PAPERS, core.DIR_EMBEDDINGS),
            args.cache_only,
        )
    except (models.NotEmbedded, PermissionError, ValueError, OSError) as e:
        sys.exit(f"No feedback on the edit: {e}")
    print("\n".join(lines))


def embeddings_given(args: argparse.Namespace) -> dict:
    """The --embeddings-* options given on the command line, by setting name."""
    given = {k: v for k, v in vars(args).items() if k.startswith("embeddings_") and v is not None}
    return {k.removeprefix("embeddings_"): v for k, v in given.items()}


def embedded(
    args: argparse.Namespace, config: dict, texts: list[str], private: bool
) -> list[list[float]]:
    """Embeddings with the settings from the command line, environment and config."""
    s = models.settings(config, **embeddings_given(args))
    return models.embed(s, texts, core.DIR_EMBEDDINGS, private, args.cache_only)


def cell(value: object, width: int, digits: int = 1) -> str:
    text = (
        "—" if value is None else f"{value:.{digits}f}" if isinstance(value, float) else str(value)
    )
    return f"{text:>{width}}"


def areas_table(args: argparse.Namespace, config: dict) -> None:
    """Each paper's share of each area (%), best area and margin, and review figures."""
    latest = core.load_snapshots()[0]
    if latest is None:
        sys.exit(f"No snapshots in {core.DIR_SNAPSHOTS}: run `sync` first")
    include = tuple(args.include.split(",")) if args.include else tuple(config["areas_include"])
    if unknown := set(include) - set(areas.INCLUDE):
        sys.exit(
            f"Cannot include {', '.join(sorted(unknown))}: choose among {', '.join(areas.INCLUDE)}"
        )
    view = core.areas_view()
    records, labels = load_records(), core.labels()
    # the papers asked for, plus the labelled ones: they join their areas' vectors
    scored = [r for r in records if not args.numbers or r["number"] in {*args.numbers, *labels}]
    try:
        rubrics = areas.load(core.DIR_RUBRICS)
        s = models.settings(config, **embeddings_given(args))
        directories = (core.DIR_PAPERS, core.DIR_EMBEDDINGS)
        results, failures = areas.score(
            scored, rubrics, s, include, config, directories, args.cache_only, labels=labels
        )
    except (models.NotEmbedded, PermissionError, ValueError, OSError) as e:
        sys.exit(f"Area scores: {e}")
    shown = args.show.split(",") if args.show else [c for c in rubrics if c not in view["hidden"]]
    numbers = set(args.numbers) or {r["number"] for r in records}
    found = [
        r
        for r in areas.rows(latest, {r["number"]: r for r in records}, results, labels)
        if r["number"] in numbers
    ]
    found = areas.ordered(found, areas.sort_spec(args.sort) if args.sort else view["sort"])
    print(
        f"{s.model}, {'+'.join(include)}; rubrics {areas.fingerprint(rubrics)}; nearest "
        f"{config['areas_top_k']}, temperature {config['areas_temperature']}; shares in %; "
        + areas.agreement(results, labels)
    )
    head = [
        "#",
        *shown,
        "best",
        "margin",
        "label",
        "reviews",
        "rating",
        "±",
        "conf.",
        "meta",
        "title",
    ]
    widths = [5] + [max(len(c), 3) for c in shown] + [6, 6, 6, 7, 6, 4, 5, 12, 0]
    print(" ".join(f"{h:>{w}}" for h, w in zip(head, widths)).rstrip())
    for r in found:
        values = [cell(r["number"], 5)] + [
            cell(round(r[c] * 100) if c in r else None, w) for c, w in zip(shown, widths[1:])
        ]
        values += [
            cell(r.get("best"), 6),
            cell(round(r["margin"] * 100) if r.get("margin") is not None else None, 6),
            cell(r["label"], 6),
            cell(f"{r['reviews']}/{r['reviewers']}", 7),
            cell(r["rating"], 6),
            cell(r["spread"], 4),
            cell(r["confidence"], 5),
            f"{(r['meta'] or '—')[:12]:>12}",
            (r["title"] or "")[:60],
        ]
        print(" ".join(values))
    failures = [f for f in failures if int(f[1:].split(":")[0]) in numbers]
    if failures:
        print("\n".join(f"Not scored: {f}" for f in failures))
    if args.csv:
        columns = ["number", "title", *rubrics, "best", "margin", "label"]
        columns += list(areas.metrics({"reviews": []}))
        with args.csv.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(found)


def editor() -> list[str]:
    """The command of $VISUAL or $EDITOR, or of the system's default editor."""
    default = "notepad" if sys.platform == "win32" else "vi"
    return shlex.split(
        os.environ.get("VISUAL") or os.environ.get("EDITOR") or default, posix=os.name != "nt"
    )


def edit(items: list[outreach.Item], field: str) -> list[outreach.Item]:
    """Opens each item in $VISUAL or $EDITOR, its first line holding the subject (or title).
    The file lives in the private data folder, as the text is confidential, and is removed."""
    editor_ = editor()
    file, edited = core.DIR_DATA / "draft.txt", []
    core.DIR_DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        for item in items:
            file.touch(mode=0o600)
            file.write_text(f"{field}: {item.title}\n\n{item.text}", encoding="utf-8")
            subprocess.run([*editor_, str(file)], check=True)
            first, _, text = file.read_text(encoding="utf-8").partition("\n")
            title = first.removeprefix(f"{field}:").strip()
            edited.append(item._replace(title=title, text=text.lstrip("\n")))
    finally:
        file.unlink(missing_ok=True)
    return edited


def send(
    config: dict,
    drafts: list[papers.Draft],
    unreachable: list[str],
    latest: dict | None,
    editing: bool = False,
) -> None:
    """Previews the drafts (after editing them, if `editing`), warning on repeats and on an old
    snapshot, and sends them after a typed SEND, recording them in the history."""
    sent, notes = papers.history(core.FILE_HISTORY), [core.freshness(latest, config)]
    header, items = outreach.review(drafts, unreachable, sent, notes)
    if editing:
        items = edit(items, "Subject")
        drafts = [d._replace(subject=i.title, body=i.text) for d, i in zip(drafts, items)]
    if problems := outreach.problems(items, None):
        sys.exit("\n".join([*problems, "Nothing sent"]))
    preview = outreach.render(header, items)
    if confirmed(preview, len(drafts), f"send {len(drafts)} messages"):
        failures = papers.deliver(core.login(config), drafts, history_file=core.FILE_HISTORY)
        print("\n".join([*failures, f"Sent {len(drafts) - len(failures)} of {len(drafts)}"]))
    else:
        print("Nothing sent")


def issue_line(issue: Issue, ignored: set[tuple[int, str]]) -> str:
    """An issue with its code (for `ignore`), marked when ignored."""
    mark = "  (ignored)" if (issue.number, issue.code) in ignored else ""
    return f"{issue.severity:6} {issue.message}  [{issue.code}]{mark}"


def document_lines(number: int, config: dict, ignored: set[tuple[int, str]]) -> list[str]:
    """Cached document check results of a paper, as report lines."""
    try:
        (record,) = core.records(number)
    except FileNotFoundError:
        return []
    found = documents.inspection(record, config, core.DIR_PAPERS)
    if found is None:
        return [f"Document checks not run: `inspect {number}`"]
    issues = [Issue(number, f.severity, code, f.message, "", ()) for code, f in found]
    return [issue_line(i, ignored) for i in issues] + [
        f"{'GREEN':6} {label}" for label in passed(issues, documents.DOCUMENT_CHECKS)
    ]


def load_records(*numbers: int) -> list[dict]:
    try:
        return core.records(*numbers)
    except FileNotFoundError as e:
        sys.exit(f"Not cached: {e.filename}. Is the paper yours? Run `sync` first")


if __name__ == "__main__":
    main()
