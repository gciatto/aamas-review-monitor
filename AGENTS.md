# AGENTS.md

Notes for coding agents and contributors. User-facing documentation (features, checks,
installation, commands, configuration) lives in `README.md`; do not duplicate it here. When a
check, command or key changes, update the README's tables too.

## Layout

```
aamas_review_monitor/     the package, at the repo root (renamed by rename-template.sh)
  __init__.py     `__version__` and the package logger (logging is configured only in `__main__.py`)
  __main__.py     CLI: argument parsing and printing only
  core.py         shared by CLI and TUI: data dir, config, login (cached token), sync, snapshots
  collector.py    read-only OpenReview v2 -> per-paper records -> snapshot (process metadata only)
  checks.py       deterministic per-paper checks, SPC-grouped report, CSV
  papers.py       record cache, metadata/reviews text, attachment downloads, emails
  documents.py    on-request document checks (xpdf tools, zipfile), cached per PDF version
  markers.py      signs of generated text: fixed phrase and word lists (resources/ai_*.txt), no model
  outreach.py     email templates (resources/templates/*.txt) -> per-SPC / per-paper drafts
  tui.py          Textual app; network jobs run in worker threads behind a blocking Busy dialog
  screens.py      the TUI's screens and dialogs (details, attachment, legend, Busy, forms, Confirm)
  resources/      non-code files; `__init__.py` exposes `DIR_RESOURCES` and `FILE_*` paths
tests/            pytest unit tests: test_core.py covers the shared services without a front end;
                  test_tui.py drives the app, and waits for a job's visible effect (`done`),
                  never for a fixed time or a quiet spell
docs/             README screenshots (Textual SVGs of synthetic data only: never real papers)
scripts/          githooks.py: installs/removes local Git hooks (poe install-hooks)
.github/workflows/
  check.yml       static-checks + coverage, then tests on ubuntu/windows/macos x Python 3.10-3.13,
                  then deploy.yml
  deploy.yml      semantic-release to GitHub releases only, wheel kept as an artifact (dry run
                  off main/master and on the initial commit)
  init.yml        one-shot: renames the template in repos created from it, then deletes itself
```

## Commands

```bash
uv sync                               # env + dev tools
uv run poe test                       # pytest
uv run poe static-checks              # compileall, ruff format --check, ruff check, mypy
uv run poe static-fixes               # ruff --fix + ruff format
uv run poe coverage && uv run poe coverage-report
uv run poe install-hooks [HOOK...]    # local hooks in .git/hooks (default: all)
uv run poe uninstall-hooks [HOOK...]  # removes only hooks it installed
```

Hooks (`scripts/githooks.py`, never tracked): `pre-commit` runs static-checks,
`conventional-commits` rejects non-Conventional-Commit subjects, `no-ai-signature` rejects
AI assistants' signatures (Claude, Codex, Copilot, ... trailers or "Generated with" footers),
`pre-push` runs static-checks + tests. The two message checks share `.git/hooks/commit-msg`,
one tagged line each. Foreign hooks are never overwritten. `--no-verify` skips them once.

## Confidentiality (hard rule)

Never run `sync`/`report`, read `~/.aamas-review-monitor/` (or `$AAMAS_MONITOR_DATA`), or
otherwise touch real OpenReview data: AAMAS forbids exposing submissions to AI. Develop
against the synthetic fixtures in `tests/` (`FakeClient` mimics the openreview-py calls;
`conftest.py` makes any real `OpenReviewClient` fail and points every data path at a temporary
folder). Never send real emails or comments: sending must keep requiring a typed `SEND`, and
must keep recording each message in the history (`papers.deliver`, `papers.post_comments`). Keep
checks deterministic; never add LLM calls or scientific judgments (generated-text checks
stay string matching against the lists, and never report a probability).

## Conventions

- Checks are one function each: `@paper_check` in `checks.py` (run on snapshots, `(paper,
  Context)`), `@document_check` in `documents.py` (on request, `(Document)`). The function name
  is the issue code (keep names stable: the history diff keys on them). Docstring: first line =
  what holds when the paper passes ("SPC assigned"), no placeholders; then a blank line and
  what is flagged, with which severity, using `{config_key}` placeholders for thresholds. Both
  legends (`legend` command, `l` in the TUI) and the passed-checks lists come from these
  docstrings. New snapshot fields must be read with `.get`: old snapshots lack them.

- Commits follow Conventional Commits (`<type>[(scope)][!]: <description>`); semantic-release
  derives the next version from them, so pick the type carefully (`feat` = minor, `fix` =
  patch, `!` = major; `chore`/`docs`/`style`/`test`/`ci` don't release).
- No AI-assistant signatures in commit messages or PR descriptions.
- `static-checks` and tests must pass before committing.
- Ruff: line length 100, target py310. Code must run on Python 3.10 (the lowest version in
  the CI matrix and `requires-python`; keep the three in sync).
- Manage dependencies with `uv add` / `uv add --dev`, never by hand-editing `uv.lock`.
- Tests must not hit the network.
- Long strings (LLM prompts, templates, messages), configuration, icons and other assets go in
  files under `aamas_review_monitor/resources/`, never inline in code. Reference them through
  `Path` constants in `resources/__init__.py` (`FILE_CONFIG = DIR_RESOURCES / "config.json"`);
  everything in the package directory ships in the wheel.
- Names go from general to specific: general prefix, specific suffix (`DIR_DATA`,
  `FILE_CONFIG`, `URL_API_BASE`, not `DATA_DIR`, `CONFIG_FILE`, `API_BASE_URL`), so related
  identifiers sort and autocomplete together.

## Releases

Conventional Commits drive semantic-release (`release.config.mjs`), which runs
`uv version <next> && uv build` in its prepare step and attaches the wheel and sdist to a
GitHub release. Nothing goes to PyPI; `deploy.yml` also keeps `dist/` as a workflow artifact on
every run. `pyproject.toml` is the only version source; never bump it by hand.
`CHANGELOG.md` is generated.
