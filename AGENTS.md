# AGENTS.md

Notes for coding agents and contributors. User-facing usage (setup, commands, release
secrets, Renovate) lives in `README.md`; do not duplicate it here.

## Layout

```
aamas_review_monitor/     the package, at the repo root (renamed by rename-template.sh)
  __init__.py     `__version__` and the package logger (logging is configured only in `__main__.py`)
  __main__.py     CLI, login (cached token), data dir and snapshot storage
  collector.py    read-only OpenReview v2 -> per-paper records -> snapshot (process metadata only)
  checks.py       deterministic per-paper checks, SPC-grouped report, CSV
  papers.py       record cache, metadata/reviews text, attachment downloads, emails
  tui.py          Textual app over `checks` (sync runs suspended, so prompts work)
  resources/      non-code files; `__init__.py` exposes `DIR_RESOURCES` and `FILE_*` paths
tests/            pytest unit tests
scripts/          githooks.py: installs/removes local Git hooks (poe install-hooks)
.github/workflows/
  check.yml       static-checks + coverage, then tests on ubuntu/windows/macos x Python 3.10-3.13,
                  then deploy.yml
  deploy.yml      semantic-release (dry run off main/master and on the initial commit)
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
`conftest.py` makes any real `OpenReviewClient` fail). Never send real emails: `email` must
keep requiring a typed `SEND`. Keep
checks deterministic; never add LLM calls or scientific judgments.

## Conventions

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
`uv version <next> && uv build && uv publish` (to TestPyPI while the repo name contains
`template`) in its prepare step, before the release commit and tag: a failed upload leaves
neither. `pyproject.toml` is the only version source; never bump it by hand.
`CHANGELOG.md` is generated.
