# AAMAS Review Monitor

Monitor for an AAMAS 2027 Senior Area Chair: it pulls the review-process state of the papers
assigned to you from OpenReview and prints an action queue grouped by SPC (Area Chair), with
each paper GREEN/YELLOW/RED. Colors describe process health, never scientific quality. It also
shows each paper's metadata and reviews, downloads PDFs, and emails reviewers or SPCs.

## Usage

```bash
uv sync
uv run aamas_review_monitor sync                 # fetch papers and a snapshot (asks for credentials)
uv run aamas_review_monitor report [--csv FILE]  # action queue, diff vs previous snapshot
uv run aamas_review_monitor tui                  # the same, as an interactive table
uv run aamas_review_monitor show N               # metadata and issues of paper N
uv run aamas_review_monitor issues N             # issues of paper N
uv run aamas_review_monitor reviews N [--reveal] # reviews and meta-reviews, reviewers anonymous
uv run aamas_review_monitor download [N ...] [--supplementary]  # PDFs, or supplementary material
uv run aamas_review_monitor email ROLE [N ...] --subject S --body FILE
```

Paper lists default to all your papers. `sync` caches each paper (content, reviews, groups) in
`~/.aamas-review-monitor/papers/N/` and reports PDFs or supplementary material updated since the
last sync; `download` fetches only what is missing or outdated, into the same folder.

`email` sends one message per paper, signed as that paper's SACs, to `reviewers`,
`late-reviewers` (assigned but no review yet) or `spcs`. It prints the recipients, subject and
body and sends nothing unless you type `SEND`. `{{fullname}}` in the body becomes each
recipient's name. Authors cannot be emailed: OpenReview only lets Program Chairs do that.

In the TUI every paper is listed: one row per issue, one GREEN row per paper without issues. `f`
filters (SPC, paper number, issue), `g` hides or shows GREEN rows, clicking a header sorts, `s`
syncs, `r` reloads, `q` quits. On the selected paper: Enter or `d` shows its metadata, failed and
passed checks, and anonymous reviews, `o` opens it on OpenReview, `e` opens an email form, and
`p`/`u` open its PDF/supplementary material in a dialog, downloading it first if needed. The
dialog shows the local path and the contents (PDF text, or the file tree of a zip); there `c`
shows the file in Finder/Explorer, `v` opens it with the default app, `y` copies the path.
`P`, `U` and `E` download or email for every paper shown. Downloads, logins and the email `SEND`
confirmation run in the plain terminal, then the TUI comes back.

PDF text comes from xpdf's `pdftotext` (`brew install xpdf`), in reading order so the two AAMAS
columns come out one after the other; it is cached next to the PDF as `<pdf>.txt`.

Run `sync` daily: each run adds a snapshot, and `report` shows what is new or resolved per SPC
since the previous one. Credentials come from `OPENREVIEW_USERNAME`/`OPENREVIEW_PASSWORD` or a
prompt and are never stored; the resulting 1-week session token is kept in
`~/.aamas-review-monitor/token` (mode 0600), so you log in about once a week. Delete that file
to log out.

Checks: missing SPC, fewer than `reviewers_min` reviewers, missing reviews near/after the review
deadline, reviews under `reviews_words_min` words, rating spread of `scores_spread_max` or more,
disagreement with no comments after the deadline, missing meta-review near/after its deadline.
Thresholds, deadlines and field names are in
[`resources/config.json`](aamas_review_monitor/resources/config.json); override any of them in
`~/.aamas-review-monitor/config.json`. Verify `deadline_*`, `field_rating` and
`field_confidence` against the venue before relying on the report.

## Confidentiality

AAMAS 2027 forbids sharing submission content with AI systems. Hence:

- everything is deterministic Python; no LLM, no telemetry; only `email` writes to OpenReview,
  after you type `SEND`;
- snapshots keep only process metadata (assignments, scores, word counts, comment counts); paper
  content, reviews and PDFs are cached separately under `papers/`;
- data lives in `~/.aamas-review-monitor/` (override with `AAMAS_MONITOR_DATA`), mode 0700,
  outside the repository;
- **run every command in your own terminal, not through a coding agent**: their output and the
  cache carry submissions, reviews and the identities of reviewers and SPCs.

Development uses synthetic fixtures only (`tests/`).

## Project Structure

```bash
<root directory>
├── aamas_review_monitor/                     # main package (renamed into your project name)
│   ├── __init__.py                   # package version and logger
│   ├── __main__.py                   # CLI (also `python -m aamas_review_monitor`)
│   ├── collector.py                  # read-only OpenReview v2 collector
│   ├── checks.py                     # deterministic checks and report
│   ├── papers.py                     # paper cache: metadata, reviews, downloads, emails
│   ├── tui.py                        # Textual interface over the same checks
│   └── resources/                    # non-code files shipped with the package
│       ├── __init__.py               # paths to the resource files (DIR_RESOURCES, FILE_*)
│       └── config.json               # venue, deadlines, thresholds
├── tests/                            # pytest suite, synthetic data only
│   ├── test_githooks.py              # tests for scripts/githooks.py
│   ├── test_checks.py                # checks
│   ├── conftest.py                   # blocks real OpenReview clients in every test
│   ├── test_collector.py             # collector against a fake OpenReview client
│   ├── test_papers.py                # cache, downloads, emails (fake client)
│   ├── test_tui.py                   # TUI driven headlessly
│   └── test_main_package.py          # CLI report end to end
├── scripts/
│   └── githooks.py                   # installs/removes local Git hooks
├── .github/                          # configuration of GitHub Actions
│   └── workflows/
│       ├── check.yml                 # runs checks and tests on multiple OSs and Python versions
│       ├── deploy.yml                # releases to PyPI/TestPyPI with semantic-release
│       └── init.yml                  # initializes repositories created from this template
├── AGENTS.md                         # notes for coding agents and contributors
├── CHANGELOG.md                      # generated release changelog
├── LICENSE                           # license file
├── package.json                      # Node.js dependencies for semantic-release
├── pyproject.toml                    # Python project configuration, dependencies, and tasks
├── renovate.json                     # configuration of Renovate bot for dependency updates
├── release.config.mjs                # semantic-release configuration
├── rename-template.sh                # CI helper script used by init.yml to rename the project
└── uv.lock                           # locked Python dependency versions
```

## Requirements

- Only [uv](https://docs.astral.sh/uv/getting-started/installation/) and
    - Node.js and npm, for semantic-release and package publishing.

You can install uv following the instructions in the [documentation](https://docs.astral.sh/uv/getting-started/installation/).

## Python Installation

You can install and handle Python versions with uv:

```bash
uv python install 3.12
uv python pin 3.12
uv python list
```

## Creating a Project from this Template

1. Create a new repository from this template on GitHub.

2. Let the initialization workflow run.

   The `.github/workflows/init.yml` workflow runs automatically on `main` or
   `master` when the repository is neither marked as a template nor a fork. It calls
   `rename-template.sh` to replace the template placeholders with the repository
   name, removes the initialization workflow, and commits the result.

3. Install dependencies:

    ```bash
    uv sync
    ```

4. Run the checks:

    ```bash
    uv run poe static-checks
    uv run poe test
    ```

5. Start building your project in `aamas_review_monitor/` and add tests under `tests/`.

## Main Commands

### Running the Application
`uv run aamas_review_monitor` (or `uv run python -m aamas_review_monitor`) to run the application entry point defined in `pyproject.toml`.


### Dependency Management

| Command | Description |
| --- | --- |
| `uv sync` | Create or update the local environment from `pyproject.toml` and `uv.lock`. |
| `uv run aamas_review_monitor` | Run the application entry point. |
| `uv add <package>` | Add a runtime dependency. |
| `uv add --dev <package>` | Add a development dependency. |
| `uv remove <package>` | Remove a dependency. | 
| `uv lock` | Update the lock file after dependency changes. |
| `uv sync --locked` | Sync the environment strictly to the locked versions. |

### Configured Tasks

Project task aliases are defined in [pyproject.toml](pyproject.toml) under `[tool.poe.tasks]` and
can be run through uv.

| Command | Description |
| --- | --- |
| `uv run poe test` | Run the pytest test suite. |
| `uv run poe coverage` | Run tests through coverage. |
| `uv run poe coverage-report` | Print a terminal coverage report with missing lines. |
| `uv run poe coverage-html` | Generate an HTML coverage report in `htmlcov/`. |
| `uv run poe ruff-check` | Lint: report code problems (unused imports, undefined names, risky patterns, ...). |
| `uv run poe ruff-fix` | Lint and apply the automatic fixes Ruff knows for those problems. |
| `uv run poe format-check` | Report files whose layout (quotes, wrapping, spacing) differs from Ruff's style. |
| `uv run poe format` | Rewrite files into Ruff's style. |
| `uv run poe mypy` | Type-check `aamas_review_monitor/`, `tests/` and `scripts/` with Mypy. |
| `uv run poe compile` | Compile `aamas_review_monitor/`, `tests/` and `scripts/` to catch syntax errors. |
| `uv run poe static-checks` | Run `compile`, `format-check`, `ruff-check` and `mypy` (what CI runs); changes nothing. |
| `uv run poe static-fixes` | Run `ruff-fix`, then `format`; fixes most `static-checks` failures except type errors. |
| `uv run poe install-hooks [HOOK...]` | Install local Git hooks (see [Git Hooks](#git-hooks); default: all). |
| `uv run poe uninstall-hooks [HOOK...]` | Remove the hooks installed by `install-hooks`. |

Linting (`ruff-*`) and formatting (`format*`) are separate Ruff tools: the linter finds code
problems but ignores layout, the formatter fixes layout but never changes what the code does.
A file can pass one and fail the other, so both run in `static-checks`.

Contributor/agent notes (layout, conventions) are in [`AGENTS.md`](AGENTS.md).

### Git Hooks

Optional and local: they live in `.git/hooks/`, so each clone opts in with
`uv run poe install-hooks [HOOK...]`. They catch locally what CI would otherwise reject later.
`git commit/push --no-verify` skips them once. Existing hooks not installed by this script are
never overwritten.

| Hook | Runs on | Blocks when | Cost | Install it if |
| --- | --- | --- | --- | --- |
| `pre-commit` | every `git commit` | `static-checks` fails | a few seconds per commit | you want every commit to be clean |
| `conventional-commits` | every commit message | the subject is not `<type>[(scope)][!]: <description>` | none | you push to `main`/`master` (releases depend on it) |
| `no-ai-signature` | every commit message | it has an AI-assistant trailer or "Generated with" footer | none | you use coding assistants |
| `pre-push` | every `git push` | `static-checks` or tests fail | the whole test suite per push | you'd rather wait locally than for CI to fail |

`pre-commit` and `pre-push` overlap. For small, frequent commits, `pre-push` alone is usually
enough.


## Release a new version on PyPi

New versions are automatically released on PyPi via GitHub Actions, when a push is made on the `main` or `master` branch.

The version number is updated automatically by the `semantic-release` tool, which uses the commit messages to infer the type of the release (major, minor, patch).

It is paramount that the commit messages follow the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification,
in order for `semantic-release` to compute version numbers correctly.


For successfully publishing, configure these repository secrets as needed:

- `PYPI_TOKEN`: token for publishing to PyPI.
- `TEST_PYPI_TOKEN`: token for publishing to TestPyPI.
- `RELEASE_TOKEN`: GitHub token used by semantic-release.

The workflow dry-runs releases outside `main` or `master`, and also dry-runs the
initial commit.

## Automatic updates of dependencies (via Renovate)

The project is configured to use [Renovate](https://docs.renovatebot.com/) to automatically open pull-requests
to update dependencies declared in `pyproject.toml`.

By default, Renovate will assign such pull-requests to the user who created the repository from this template.

If the project has tests (which is the case for this template), Renovate will only merge such pull-requests
if all tests pass.

When some test fails, Renovate will leave a comment on the pull-request, so that you can fix the issue manually.

To make Renovate work, you need to enable it for your repository.
To do so, please follow the instruction at <https://docs.renovatebot.com/getting-started/installing-onboarding/#hosted-githubcom-app>

Finally, please remember to enable PR auto-merging in your repository settings, otherwise Renovate will not be able to merge
the pull-requests it opens, even if all tests pass.
To do so, please follow the instructions available [here](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-auto-merge-for-pull-requests-in-your-repository#managing-auto-merge).

> Notice that the combination between Renovate, and Semantic Release may lead to a number of releases being created automatically.


## License

This template is distributed under the license included in [LICENSE](LICENSE).
