# AAMAS Review Monitor

**The review process of a hundred papers, on one screen.**

AAMAS Review Monitor is a command-line and terminal tool for Senior Area Chairs of
[AAMAS 2027](https://warwick.ac.uk/fac/sci/dcs/aamas2027/). It reads, from OpenReview, the papers
you supervise, then runs a few dozen checks on how their reviewing is going. Out comes a short,
prioritised list of what needs you today, grouped by the SPC (Area Chair) who can act on it.
Papers where everything is on track stay out of your way.

![The action queue: every paper, one row per issue, worst first](docs/tui-queue.svg)

- **Every paper, every day, in seconds.** Assignments, missing and late reviews, short or
  recycled reviews, disagreements nobody is discussing, unacknowledged rebuttals, quiet SPCs,
  missing or inconsistent meta-reviews. The checks follow the AAMAS 2027 calendar.
- **Know whom to nudge.** Issues are grouped by SPC, and a reviewer late on several of your papers
  shows up once, so one reminder covers them all. Each sync also tells you what got resolved
  since the last one.
- **Submission policy at scale.** On request, it inspects PDFs and supplementary zips for the
  page limit (appendices included), the AAMAS 2027 template, anonymity leaks, missing code, and
  OpenReview metadata that doesn't match the PDF.
- **Everything at hand.** A paper's metadata, checks and reviews (reviewers kept anonymous), its
  PDF text and its supplementary file tree, without leaving the terminal.
- **Reminders without the clicking.** Email a paper's reviewers, only its late reviewers, or its
  SPCs, for one paper or many at once, through OpenReview's own messaging.

![Paper details: metadata, every check, reviews](docs/tui-details.svg)

## Automatic, deterministic, and on your machine

AAMAS 2027 forbids sharing submissions with AI systems and using AI to evaluate them. This
tool is built around that rule:

- **Every check is plain Python.** No language model, no randomness: the same data always gives
  the same flags, and each flag comes with the rule that raised it (`legend`).
- **Nothing is sent anywhere.** Data goes from OpenReview to `~/.aamas-review-monitor/` on your
  disk (mode 0700) and nowhere else. No telemetry.
- **It reads with your own OpenReview permissions** and never changes anything there. The one
  exception is email, and nothing is sent until you type `SEND`.
- **Flags are for people to verify.** The colors describe the health of the reviewing process,
  never the quality of a paper.
  - 🔴 needs you
  - 🟡 needs the SPC's attention
  - 🟢 nothing to do

## Checks

`legend` (or `l` in the terminal UI) prints this list with the thresholds currently in use.
Defaults follow the AAMAS 2027 timeline: 50% of reviews by 26 Oct, all by 13 Nov, rebuttal
20–24 Nov, discussion from 25 Nov, acknowledgement by 3 Dec, meta-reviews by 9 Dec.

### Paper checks: automatic, on every sync

| Check | Flags |
|---|---|
| Submission active | 🟡 withdrawn or desk-rejected papers (and skips all other checks for them) |
| SPC assigned | 🔴 no SPC |
| Enough reviewers assigned | 🔴 fewer than 3 reviewers |
| Reviews on track with the milestones | 🟡 fewer than 50% of the reviews in after 26 Oct |
| Reviews on schedule | 🟡 reviews missing in the last 5 days before the deadline; 🔴 in the last 2 days and once overdue |
| No reviewer behind on several papers | 🟡 a reviewer who owes reviews on 2 or more of your papers |
| Reviews long enough | 🟡 a review under 150 words |
| Reviews written for this paper | 🟡 a review that shares 60% or more of its phrases with the same reviewer's review of another paper |
| Confident reviewers | 🟡 every reviewer's confidence is 2 or lower |
| Ratings within the allowed spread | 🟡 ratings 3 or more points apart |
| No undiscussed disagreement | 🔴 ratings 3 or more apart and no reviewer has commented, from 25 Nov |
| Discussion within the expected length | 🟡 more comments than one per reviewer plus one per SPC |
| Rebuttal acknowledged | 🟡 reviewers who neither updated their review nor commented since the rebuttal, from 2 days before 3 Dec; 🔴 after |
| SPC active in the discussion | 🟡 an SPC silent on all of your papers for 7 days during the discussion |
| Meta-review on schedule | 🔴 no meta-review in the last 2 days before 9 Dec, and after |
| Meta-review long enough | 🟡 a meta-review under 80 words |
| Proceedings and Findings recommendations given | 🟡 either recommendation missing |
| Meta-review in line with the ratings | 🟡 "Strong Accept" for a paper in your bottom quarter by mean rating, "Reject" for one in your top quarter |
| Findings recommendation respects the authors' choice | 🟡 Findings acceptance recommended although the authors opted out |

### Document checks: on request (`inspect`, or `i` / `I`)

These use the PDF's text and properties and the supplementary zip's contents. Missing files
are downloaded first. Results are cached per uploaded version, and a new upload makes them
stale.

| Check | Flags |
|---|---|
| Main text within the page limit | 🔴 text before the references beyond 8 pages; 🟡 more than 8 pages and no References heading found |
| No appendix beyond the page limit | 🔴 an appendix after the references that takes main text plus appendix beyond 8 pages |
| Main text long enough | 🟡 main text under 6 pages |
| US Letter pages | 🔴 any other page size |
| Template fonts, all embedded | 🟡 fonts not embedded, or no Libertine (the template's typeface) |
| AAMAS 2027 template | 🔴 no AAMAS 2027 copyright block on page 1 |
| Anonymous submission mode | 🔴 no "Anonymous Author(s)" on page 1, or a name in the PDF's Author metadata |
| No identifying text | 🟡 emails on page 1, an Acknowledgements section, personal repository links, phrases like "our previous work" |
| OpenReview metadata matches the PDF | 🟡 the OpenReview title or abstract largely missing from the PDF's first pages |
| Supplementary material is one small zip | 🟡 not a zip, or over 25 MB |
| Anonymous supplementary material | 🔴 a `.git` folder; 🟡 home folder paths or emails in its files |
| Code available for the experiments | 🟡 experiments, but no code in the supplementary material and no code link |

Every threshold and date can be changed (see [Configuration](#configuration)). Adding a check
takes one documented function; see [`AGENTS.md`](AGENTS.md).

## Installation

You need Python 3.10 or newer. The document checks also need xpdf's or poppler's command-line
tools (`pdftotext`, `pdfinfo`, `pdffonts`): `brew install xpdf` on macOS, or
`apt install poppler-utils` on Debian and Ubuntu.

```bash
pip install "git+https://github.com/gciatto/amas-review-monitor.git"
```

To install a fixed release, use its tag, or the wheel attached to the release on
[GitHub](https://github.com/gciatto/amas-review-monitor/releases) (replace `X.Y.Z`):

```bash
pip install "git+https://github.com/gciatto/amas-review-monitor.git@vX.Y.Z"
pip install https://github.com/gciatto/amas-review-monitor/releases/download/vX.Y.Z/aamas_review_monitor-X.Y.Z-py3-none-any.whl
```

`pipx install …` or `uv tool install …` with the same URLs keeps it in an environment of its
own. The command is `aamas_review_monitor` (also `python -m aamas_review_monitor`).

## Getting started

```bash
aamas_review_monitor sync     # sign in, fetch your papers, take a snapshot
aamas_review_monitor tui      # browse the action queue
aamas_review_monitor report   # or print it
```

The first `sync` asks for your OpenReview credentials, or reads `OPENREVIEW_USERNAME` and
`OPENREVIEW_PASSWORD`. Only the resulting session token is kept, for one week
(`~/.aamas-review-monitor/token`; delete it to sign out). Run `sync` daily. Each run adds a
snapshot, and the report tells you what is new and what got resolved since the previous one.

## Command line

Paper lists (`N ...`) default to all your papers.

| Command | What it does |
|---|---|
| `sync` | Fetch your papers, their reviews and attachments' versions; save a snapshot; report updated PDFs and supplementary material |
| `report [--filter TEXT] [--green] [--csv FILE]` | The action queue by SPC, with changes since the last sync; filter by SPC, `#N`, issue or color; `--green` lists papers without issues too |
| `tui` | The interactive terminal UI |
| `legend` | What each check verifies, with the current thresholds |
| `show N` / `issues N` | A paper's metadata and issues / only its issues (passed checks included) |
| `reviews N [--reveal]` | Reviews and meta-reviews; reviewers stay anonymous unless `--reveal` |
| `browse N` | Open the paper on OpenReview |
| `download [N ...] [--supplementary]` | Download PDFs or supplementary material, skipping current copies |
| `attachment N [--supplementary] [--contents] [--open] [--reveal]` | A paper's PDF or zip, downloaded if needed: its path, its text or file list, open it, or show it in Finder/Explorer |
| `inspect [N ...]` | Run the document checks, downloading what is missing |
| `email ROLE [N ...] --subject S --body FILE` | Email `reviewers`, `late-reviewers` or `spcs`, one message per paper, after you type `SEND` |

Options that come before the command apply to every OpenReview read:
`--retries`, `--backoff` and `--backoff-max`. They set exponential backoff with jitter on rate
limits, server errors and connection failures, and honour `Retry-After`. The defaults are 8
retries, a first wait of 1 s and a longest wait of 120 s. Email is never retried, so no message
goes out twice.

## Terminal UI

`tui` shows every paper: one row per issue, and a 🟢 row for each paper without issues. Every
action is also in the command palette (`ctrl+p`). In each pair below, the lowercase key acts on
the selected paper and the uppercase one on all papers shown.

| Key | Action |
|---|---|
| `f` | Filter by SPC, `#N`, issue text or color |
| `g` | Show or hide 🟢 papers |
| Enter, `d` | Paper details: metadata, every check with its outcome, anonymous reviews |
| `o` | Open the paper on OpenReview |
| `p` / `P` | PDF: a dialog with its path and text, or download all; in the dialog, `c` shows it in Finder/Explorer, `v` opens it, `y` copies the path |
| `u` / `U` | Supplementary material: the same dialog, with the zip's file tree |
| `i` / `I` | Run the document checks, downloading what is missing |
| `e` / `E` | Email reviewers, late reviewers or SPCs, with a `SEND` confirmation |
| `s` | Sync with OpenReview |
| `l` | Legend of all checks |
| `r` / `q` | Reload / quit |

Syncing, downloading, inspecting and sending run in the background behind a progress bar, and
the rest of the interface waits meanwhile. An expired session brings up a sign-in dialog.

## Email

`email` (or `e`/`E`) writes through each paper's OpenReview message invitation, signed as that
paper's Senior Area Chairs. Messages can go to its reviewers, to its late reviewers (assigned,
no review yet), or to its SPCs. `{{fullname}}` in the body becomes each recipient's name. Before
anything is sent, you see every recipient group and the full message, and you confirm by typing
`SEND`. OpenReview doesn't let SACs email authors.

## Configuration

Defaults are in
[`aamas_review_monitor/resources/config.json`](aamas_review_monitor/resources/config.json): the
venue, OpenReview field names, the AAMAS 2027 dates, every threshold, and the retry policy.
Override any of them in `~/.aamas-review-monitor/config.json`, for example
`{"reviews_words_min": 200, "deadline_meta_reviews": "2026-12-10"}`. Use `AAMAS_MONITOR_DATA` to
keep the data folder elsewhere.

## Data and confidentiality

- Snapshots keep only process metadata: assignments, ratings, word counts, comment dates, and
  MinHash fingerprints of reviews (comparable, but the text can't be recovered from them).
- Paper content, reviews, PDFs, extracted text and document check results are cached in
  `~/.aamas-review-monitor/papers/`.
- **Run it in your own terminal, not through an AI coding assistant.** Its output and its cache
  hold submissions, reviews and the identities of reviewers and SPCs.
- The project is developed and tested only on synthetic data. The screenshots above are
  synthetic too.

## Development

```bash
uv sync                    # environment and development tools
uv run poe test            # tests (synthetic data, no network)
uv run poe static-checks   # compile, ruff format/lint, mypy
uv run poe install-hooks   # optional local Git hooks
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/), from which
semantic-release derives versions. Releases are GitHub releases only: the wheel and sdist are
attached to each release and kept as workflow artifacts, and nothing is published to PyPI.
Contributor and agent notes, including how to add a check, are in [`AGENTS.md`](AGENTS.md).

## License

See [LICENSE](LICENSE).
