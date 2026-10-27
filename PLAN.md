# Plan: Reorganize the repository, then the Notrios import follow-ups

Status: **opened 2026-10-26.** L0 (opening) and **L1 to L7 are complete**
(L4 ran before L3), **L8** is published and **H1** is complete. The next
slice is **D1**, not yet authorized. The user
confirmed this plan's assignments for the session on 2026-10-26; see
[Coding-agent assignments](#coding-agent-assignments-and-session-confirmation).

How this plan, [`ROADMAP.md`](ROADMAP.md) and the archive in [`plans/`](plans/)
are kept current, and when this plan is archived, is in `AGENTS.md` under
[Plans, the roadmap and the archive](AGENTS.md#plans-the-roadmap-and-the-archive).

## Goal

The Notrios import plan is complete, and the repository root has grown to 25
Markdown documents, a JSON ledger and ten test modules beside the scripts.
This plan:

1. removes the account name from every committed path;
2. archives the finished plans under `plans/` by version, and releases 3.37;
3. adds `ROADMAP.md` for the deferred Notrios features, and the rules in
   `AGENTS.md` for how `PLAN.md`, `ROADMAP.md` and the archive are used;
4. moves the test modules into `tests/`, the remaining development tools into
   `scripts/` and the documentation into `docs/`, updating every reference to a
   moved file;
5. documents how to keep private data out of a Notrios publication, what
   tagging cannot catch, and how to publish more than 100,000 notes;
6. checks that every documented example is either executable, and executed,
   or recorded with the reason it is not;
7. rewrites the old paths in the Git history;
8. then carries the four proposed Notrios follow-ups (H1, D1, R1 and R2), each
   still needing its own authorization.

The layout follows the Notrios repository's conventions
(`~/projects/notrios/plans`, `docs/` and `scripts/`), at the scale this
standard-library-only Python repository needs.

## Decisions (user, 2026-10-26)

The request: rewrite local paths holding the account name as `~/…` and
`$USER`; update the `AGENTS.md` test command; declutter the root; add
`ROADMAP.md` for the deferred items (packed publications, multiple handoffs and
merges, full or subset archives); explain in `AGENTS.md` how `PLAN.md` and
`ROADMAP.md` are used and archived; name the active plan `PLAN.md`; archive
`PLAN.md`, `plans/v3.36/000-ledger-migration-plan.md` and `plans/v3.37/000-notrios-import-plan.md` under
`plans/` by version; put documentation in `docs/` and test scripts in
`scripts/`; check that documented examples are executable; document the
100,000-note workaround, Notrios's private marking, and the limits of tagging,
recommending dedicated PII software
([Presidio](https://github.com/data-privacy-stack/presidio),
[hawk-eye](https://github.com/rohitcoder/hawk-eye)); and update the paths in
every file that refers to a moved one.

Answers to the four questions asked before writing this plan:

| Question | Answer |
|---|---|
| Archive versions | **3.34 / 3.36 / 3.37**: the old `PLAN.md` (refocus, steps 1–19, last shipped as 3.34) goes to `plans/v3.34/`, `plans/v3.36/000-ledger-migration-plan.md` to `plans/v3.36/`, and `plans/v3.37/000-notrios-import-plan.md` with its ledger and renderer to `plans/v3.37/`. The CHANGELOG's "Unreleased changes" becomes "Changes in 3.37", and the changed scripts' `__version__` values go to 3.37. |
| H1, R1, R2, D1 | **New `PLAN.md`**, after the reorganization, each still needing authorization. `ROADMAP.md` holds only deferred features. |
| Notrios evidence documents | **Archived with their plan** in `plans/v3.37/`. Reference documents go to `docs/`: the static-site and deployment guides, the performance review, the implementation review, and the Notrios import contract and design. |
| Test directory (asked after L2) | **`tests/`**, holding the eleven `test_*.py` modules; `notrios_c7c.py` goes to `scripts/`; L4 runs before L3. The user first asked for a `unittest` directory, then: "Pick a different name if `unittest` would cause problems." It would: `python3 -m unittest unittest/test_x.py` looks for a module `unittest.test_x` inside the standard library and fails, and an `unittest/__init__.py` would shadow the standard library's `unittest` so that no test could start. `tests/` has neither problem. |
| Documented examples | **A registry, and run what can run.** Every fence in `README.md` and `docs/` is registered with its hash; an edited or unregistered fence fails the gate. Python-only examples run in the unit gate against `sample/` and synthetic fixtures in a temporary home. Examples needing Hugo, Go, `notriosctl` or the network run in a separate `--with-tools` check, which names any missing tool and does not count those examples as passed. Every other fence records why it is not run. |

## Coding-agent assignments and session confirmation

Every slice is planned for the Claude Code parent, called **Main** in the
table. No worker or subagent is planned; spawning one needs an explicit user
request and a plan amendment first. At the start of each implementation
session, follow
[Mandatory planned delegation](AGENTS.md#mandatory-planned-delegation): show
the active coding agent, this plan's model and effort assignments (marking
which are runtime-reported and which configured), and the billing route or
`not exposed`, then ask whether they are current, and wait for the answer
before implementing. Plan and provenance edits and read-only inspection may
proceed while confirmation is pending. A new session, coding agent, model or
billing route invalidates the confirmation; compaction alone does not.

The table below is generated from the ledger, [`docs/plan/ledger.json`](docs/plan/ledger.json),
which is authoritative for assignments, confirmation and execution records.
Update the ledger first, then regenerate and check:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/render_plan_ledger.py
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/render_plan_ledger.py --check
```

<!-- PLAN-ASSIGNMENTS:START -->
Session confirmation: **confirmed**.

2026-10-27 user, in a new session: answered Current to whether the assignments are current for this session, after being shown the Claude Code parent (Main) with no worker, runtime-reported model claude-opus-5-5, and reasoning effort and billing route not exposed. Applies to this unchanged session; each slice still needs its own authorization. Earlier: 2026-10-26 user: The assignments are current for this session (the previous session).

| Coding agent | Execution owner | Configured model | Reasoning effort | Availability | Billing route |
|---|---|---|---|---|---|
| claude | parent | not exposed; runtime reports claude-opus-5-5 | not exposed | Main for every slice; no workers planned | not exposed; assignments confirmed by user for this session |

Runtime-reported parent family: **Claude Opus 5.5 (runtime-reported model ID claude-opus-5-5)**. Product/client version: not exposed; model provider: Anthropic (runtime-reported).

- Every slice is planned for the Claude Code parent, called Main in the slice table. No worker or subagent is planned.
- Spawning a worker or subagent requires an explicit user request and a recorded plan amendment first.
- Main runs long data-heavy commands as harness-tracked background commands, is re-invoked once when they exit, and does not poll.
- The runtime-reported model ID is not a configured alias. Reasoning effort, client version and billing route are not exposed.
<!-- PLAN-ASSIGNMENTS:END -->

Next slice: **D1 — clearer output refusals**, assigned to Main; not yet
authorized.

## Execution rules

- One slice at a time. Commit each slice, then ask before starting the next and
  wait for the answer. No push without permission.
- A moved file moves with `git mv`, and every reference to it, in any tracked
  file, changes in the same commit. From L2 on, `scripts/check_doc_links.py`
  proves it.
- Keep `.zvec-grep/` out of commits; `git ls-files .zvec-grep` prints nothing.
  After each slice run `zg index` and `zg status --check-ready`.
- The regression gate runs with `PYTHONDONTWRITEBYTECODE=1` and `-B`. It is the
  required modules (six, and seven from L2 with `test_docs.py`), plus the four
  other harness modules for a full gate; from L4 on, both run from `tests/`.
- Private data stays out of Git: aggregate evidence only, no note content.
- When a slice finds something that needs fixing, add it to this plan rather
  than only reporting it.

## Slices

| Slice | Work | Depends on | Acceptance |
|---|---|---|---|
| L0 / Main | *Complete 2026-10-26.* Open this plan: archive the old `PLAN.md` to `plans/v3.34/000-refocus-plan.md`, write this plan and its ledger, and turn `render_notrios_execution.py` into `scripts/render_plan_ledger.py`, which takes `--ledger` and serves both ledgers. | — | Both ledgers render and `--check` passes; the README and `requirements.txt` point at the archived plan. |
| L1 / Main | *Complete 2026-10-26.* Remove the account name from committed paths; update the `AGENTS.md` test command. See [L1](#l1--remove-the-account-name-from-committed-paths). | L0 | No tracked file holds a path with the account name; both ledgers check; the full gate passes. |
| L2 / Main | *Complete 2026-10-26.* Release 3.37 and archive the finished plans, with a link checker. See [L2](#l2--release-337-and-archive-the-finished-plans). | L1 | Every relative link and anchor in every tracked Markdown file resolves; the archived ledger checks in place; the full gate passes. |
| L4 / Main | *Complete 2026-10-26.* Move the test modules into `tests/` and `notrios_c7c.py` into `scripts/`. See [L4](#l4--tests-in-tests-and-tools-in-scripts). | L2 | The same 321 and 43 tests, by name, pass from `tests/`, run from the repository root; no `test_*.py` or `notrios_c7c.py` at the root. |
| L3 / Main | *Complete 2026-10-26.* Add `ROADMAP.md`, and the plan, roadmap and archive rules in `AGENTS.md`. See [L3](#l3--roadmapmd-and-the-rules-for-plans). | L4 | Each deferred feature has its scope, why it is deferred and what it needs; `AGENTS.md` states the rules; links resolve. |
| L5 / Main | *Complete 2026-10-26.* Move the documentation into `docs/`, and split the README's usage sections into pages there. See [L5](#l5--documentation-in-docs). | L3 | Root holds only the files listed in L5; every old README paragraph exists in exactly one page; links resolve. |
| L6 / Main | *Complete 2026-10-26.* Document private data and publications over 100,000 notes. See [L6](#l6--private-data-and-large-publications). | L5 | Each documented command was run on a synthetic library and behaved as written. |
| L7 / Main | Check that documented examples are executable. See [L7](#l7--executable-documentation). | L6 | Every fence is registered; Python-only examples pass in the gate; the `--with-tools` run passes here; an edited fence fails. |
| L8 / Main | *Added 2026-10-26 at the user's request; needs authorization, and separate permission to force-push.* Rewrite the old paths in the Git history. See [L8](#l8--rewrite-the-old-paths-in-the-git-history). | L7 | No commit on any branch holds a path with the account name; the tip's tree is unchanged by the rewrite; every reference to a rewritten commit is mapped. |
| H1 / Main | *Proposed 2026-10-24 (C7d); not authorized.* Make HTML images render after export. See [H1](#h1--html-images-after-export). | L7 | As in H1. |
| D1 / Main | *Proposed 2026-10-26 (7d); not authorized.* Clearer `notrios2sql.py` refusals for an unusable `--output`. See [D1](#d1--clearer-output-refusals). | L7 | As in D1. |
| R1 / Main | *Proposed 2026-10-25 at the user's request; not authorized.* Report links a web reader cannot reach. See [R1](#r1--the-link-report). | L7 | As in R1. |
| R2 / Main | *Proposed 2026-10-25; option (a) chosen by the user; not authorized.* Keep non-internal destinations on the Notrios route. See [R2](#r2--non-internal-destinations-on-the-notrios-route). | R1 | As in R2. |

### L1 — Remove the account name from committed paths

In every tracked file, rewrite a path under the home directory
(`/home/<account>/…`) as `~/…`, and the account name as a segment of any other
path as `$USER`, as V1 does for export records:
`/run/media/<account>/HD2/…` becomes `/run/media/$USER/HD2/…`, and
`/media/<account>/…` becomes `/media/$USER/…`. About 70 occurrences, in the
Notrios plan and ledger, five Notrios evidence documents, the site acceptance
report and `testdata/notrios/README.md`. A path inside a shell command must
keep working as written: `~` stays outside quotes, and `$USER` is inside double
quotes or unquoted. Edit the ledger's JSON, then regenerate the plan. Git
history keeps the old text; L8 rewrites it.

`AGENTS.md`'s Tests section gives the six required modules
(`test_movenotes.py`, `test_image_resources.py`, `test_obsidian2sql.py`,
`test_obsidian2site.py`, `test_notrios2sql.py`, `test_notrios_7c.py`), and the
four harness modules (`test_notrios_c7c.py`, `test_notrios_p7a.py`,
`test_notrios_p7b.py`, `test_notrios_p7c.py`) for a full gate.

*Acceptance:* `git grep -n -E "/home/$USER/|/media/$USER/"`, with the shell
expanding `$USER`, prints nothing; both ledgers check; the full gate passes.

### L2 — Release 3.37 and archive the finished plans

*Release.* The CHANGELOG's "Unreleased changes" becomes "Changes in 3.37".
`__version__` goes to 3.37 in the scripts changed since 3.36 that carry the
3.x line: `obsidian2site.py`, `obsidian2sql.py`, `sql2obsidian.py` and
`sql2joplin.py`. `cleanres.py` changed too (S43c); its own 2.x line (2.10)
is synced with the rest of the project at 3.37 (user, 2026-10-26).
`notrios2sql.py` gains `--version`, printing `notrios2sql 3.37` in the same
form as the other scripts (user, 2026-10-26), with a test; the README's
`notrios2sql.py` rules mention it.

*Archive*, in the Notrios layout `plans/v<major>.<minor>/<NNN>-<slug>.md`, with
`plans/README.md` describing it:

- `plans/v3.36/000-ledger-migration-plan.md` ← `plans/v3.36/000-ledger-migration-plan.md`;
- `plans/v3.37/000-notrios-import-plan.md` ← `plans/v3.37/000-notrios-import-plan.md`, with
  its ledger beside it as `plans/v3.37/notrios-import-ledger.json`;
- the plan's working records, numbered in the order their slices ran:
  `001-verifier-audit.md`, `002-tag-review.md`, `003-resource-review.md`,
  `004-site-acceptance.md`, `005-compatibility-review.md`,
  `006-c7c-evidence.md`, `007-performance-evidence.md`, `008-p7b-evidence.md`,
  `009-p7c-evidence.md` and `010-corpus-trials.md`.

In the archived Notrios ledger, H1, D1, R1 and R2 are marked moved to this
plan; their records continue here. Every reference to a moved file changes in
the same commit: the README, the CHANGELOG, `AGENTS.md`, the code comments in
`obsidian2site.py` and `site_server/search/service_test.go`, and the archived
documents' own links (relative links from `plans/v3.37/` gain `../../`).

*Link checker.* `scripts/check_doc_links.py` reads every tracked Markdown file
and refuses a relative link whose file does not exist, or whose `#anchor`
names no heading in it (GitHub's slug rules). Anything under `http(s)://` is
not checked. A unit test runs it in the gate.

*Acceptance:* the checker passes; a deliberately broken link and anchor each
fail it; `scripts/render_plan_ledger.py --ledger plans/v3.37/notrios-import-ledger.json --check`
passes; the full gate passes.

### L4 — Tests in tests/ and tools in scripts/

`git mv` the eleven `test_*.py` modules into `tests/`, and `notrios_c7c.py`,
the corpus comparison the 7c harness drives, into `scripts/` beside that
harness. `tests/` gets no `__init__.py`; the runner needs none.

- The test modules find the repository root as
  `Path(__file__).resolve().parent.parent` instead of their own directory, and
  run each script, fixture and tool from there.
- `notrios_c7c.py` puts the repository root on `sys.path` for the shared
  modules it imports. The 7c harness runs it from `scripts/`, and
  `consumer_hashes` hashes it there. Its source changes, so a later rerun of
  7c's comparison stage reruns rather than reusing the checkpoint.
- The gate is run from the root by path, as now:
  `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests/test_movenotes.py …`.
  `AGENTS.md`, the README's script table and Testing section, this plan, and
  `scripts/notrios_p7b_long_batch.py`'s suite command change with it, and so
  does every other reference to a moved file, the archived plans' included.
- The Go module's tests stay in `site_server/`.

*Acceptance:* the sorted list of test IDs is the same before and after, and
all 321 required and 43 harness tests pass from `tests/`; no `test_*.py` and no
`notrios_c7c.py` remain at the root; `scripts/notrios_c7c.py --help` and the 7c
harness's `--help` run; the link checker passes; nothing writes `__pycache__`.

### L3 — ROADMAP.md and the rules for plans

`ROADMAP.md` is the inventory of deferred features, each with its scope, why
it is deferred, what it would need, and what it depends on:

- **Packed publications.** The importer refuses `objects.pack.v1` archives and
  pack locations; reading them needs bounded, authenticated pack reading with
  the same per-object size and digest checks as loose objects.
- **Multiple handoffs and merges.** An import goes only into a new directory.
  Importing several publications into one library, or a newer publication of
  the same selection over an older import, needs rules for identity, updates,
  deletions and collisions. It is also what would let a library over the
  publish path's 100,000-note cap be published in parts and merged.
- **Full and subset archives.** Only the `publication_handoff` target is read.
  `full_archive` and `subset_transfer` carry history, provenance, source
  bundles and saved searches; importing them losslessly needs a mapping for
  each.

`AGENTS.md` gains the rules, adapted from the Notrios repository's
"Keeping the plan current", "Keeping the roadmap current" and "Plan archival":
`PLAN.md` is the active plan and its journal; what is left is in its ledger
(`docs/plan/ledger.json`), rendered by `scripts/render_plan_ledger.py`;
`ROADMAP.md` says what a version will mean and carries no per-slice status;
new work enters the roadmap when it enters the plan; a finished plan is
archived as `plans/v<major>.<minor>/000-<slug>-plan.md`, with its ledger and
working records beside it; a new `PLAN.md` is then written from `ROADMAP.md`,
with the assignment section, a fresh ledger and a pointer back to these rules,
and the user is asked before it starts. The reading list's entries for
`PLAN.md` and the migration plan are replaced.

*Acceptance:* links resolve; the roadmap carries no slice status.

### L5 — Documentation in docs

`git mv` the reference documents into `docs/`, renamed in lowercase as the
Notrios repository does: `static-site.md`, `deploy-vercel.md`,
`deploy-github-pages.md`, `performance-review.md`, `implementation-review.md`
(a dated snapshot), `notrios-import-contract.md` and `notrios-import-design.md`.
`docs/index.md` lists every page.

The README keeps what movenotes is, the script list, setup, one short example
per workflow, and links. Its usage sections move unchanged into pages:
`docs/joplin.md` (Joplin RAW import and export, duplicates, cleanup),
`docs/twitter.md`, `docs/obsidian.md` (import, export, the preservation bundle,
a damaged bundle, round trips), `docs/images.md` (localizing images,
quarantine), `docs/notrios.md` (import and the publishing recipe),
`docs/quartz.md`, `docs/testing.md` and `docs/schema.md`. The site section
merges into `docs/static-site.md` where it does not repeat it.

The root then holds: `README.md`, `CHANGELOG.md`, `LICENSE.md`, `AGENTS.md`,
`PLAN.md`, `ROADMAP.md`, `requirements.txt`, the scripts and their shared
modules, `movenotes-images.example.ini` (named by the README's image usage),
and the directories `docs/`, `plans/`, `scripts/`, `tests/`, `sample/`, `testdata/`,
`site_server/` and `experiments/`.

*Acceptance:* a script compares the paragraphs of the old README with the new
README and pages, and finds each old paragraph in exactly one place, except
the quick-start examples the README repeats from each page, and the site
section's summary paragraphs, each of which `docs/static-site.md` already
covers (the mapping is in the L5 record); the link checker passes.

### L6 — Private data and large publications

In `docs/notrios.md`:

- **Keeping a note out of a publication.** Tag it `private`, `draft` or
  `confidential` (`notriosctl tags add --tag private --document <id>`); those
  are excluded by default, along with read-only notebooks and the Trash.
  `--exclude-tags` replaces the default list, so a profile that sets it must
  name the defaults it still wants. Review the plan's list of notes before
  publishing. *(Corrected in L6 by reading and measuring `v1.0.0`:
  `--exclude-tags` adds tags; it is `--private-tags` that replaces the three
  defaults.)*
- **What tagging cannot catch.** Neither Notrios nor movenotes reads a note
  for personal data. A phone number, address or account number written in a
  sentence, in a code block, in a table, in a title or file name, or in a
  link's URL is published as written; `tel:` and `mailto:` are only the forms a
  link happens to take. Attachments are copied byte for byte, so an image
  publishes whatever it shows and whatever metadata it carries, such as a
  photo's location. Anyone concerned about private data should scan the
  publication or the exported vault with software built for it before building
  or deploying the site: [Presidio](https://github.com/data-privacy-stack/presidio)
  ([site](https://presidio.dataprivacystack.org)) detects, redacts, masks and
  anonymizes personal data in text, images and structured data;
  [hawk-eye](https://github.com/rohitcoder/hawk-eye) scans filesystems and
  storage for it.
- **Publications over 100,000 notes.** The cap and why; the workaround 7c used
  (`export archive-v2 --target publication_handoff` over the root notebooks
  with `--max-documents`), how to find the root notebooks, what to do about
  notes in no notebook (file them first), and what the export does not do that
  `publish` does (no profile, no reviewed plan). Whether the export applies
  the private-tag defaults is measured on a synthetic library, not assumed,
  and documented as found. Splitting a library into several publications
  under the cap gives several sites, since publications cannot yet be merged
  (see `ROADMAP.md`).

*Acceptance:* every command in these sections was run on a synthetic library
with the pinned `v1.0.0` binary and behaved as documented, including a
`private`-tagged note on both the publish and the export path.

### L7 — Executable documentation

`scripts/check_doc_examples.py` finds every fenced block in `README.md` and
`docs/**/*.md`, and `docs/examples.json` registers each one: its page, heading,
ordinal, language, SHA-256, and a state:

- `executed`: run in the unit gate. A page's executed examples run in order in
  one temporary home, so a later example can use what an earlier one wrote.
  The home is seeded from `sample/` and `testdata/` as the registry says (for
  example `~/joplin_raw_export` from `sample/source1`), and a placeholder such
  as `<the reviewed plan's manifest_sha256>` is replaced by a value the
  registry names.
- `tools`: needs Hugo, Go, `notriosctl` (from `$NOTRIOSCTL`) or the network.
  Run by `--with-tools`, which reports each missing tool and does not count
  those examples as passed.
- `unverified`, with a reason: a synopsis, recorded output, a fragment, or
  a command that changes something outside the temporary home.

`tests/test_doc_examples.py` fails on an unregistered or changed fence and
on a stale registry entry, then runs the executed examples. `AGENTS.md`
describes the process: an edited example is re-run and re-registered in the
commit that edits it.

*Acceptance:* every fence is registered; the executed examples pass in the
gate; `--with-tools` passes on this machine with Hugo `v0.164.0`, Go 1.27.0 and
`notriosctl` `v1.0.0`; an edited fence and an unregistered one each fail.

*As built (2026-10-26).* The tools are Hugo, Go, `npx`, `notriosctl` and the
Ledger theme (`$LEDGER_THEME`, else `~/projects/hugo-theme-ledger`). No
registered example needs the network: Go and `npx` use the machine's module
and package caches. Running the examples needed four registry features the
specification did not name:

- **`homes`.** A page can have more than one temporary home, because
  `notrios2sql.py` writes only into a new directory. The README's Notrios
  import, and the export route in `docs/notrios.md`, each run in their own home.
- **`cwd`.** It starts an example where the previous one `cd`'d.
- **`{port}`.** A free port is substituted, because port 8080 is in use on
  this machine.
- **`serves`.** It waits for a server to answer, then stops it.

The first run found six examples that failed as written: every converter
needs its `--output` directory to exist, and the README's and
`docs/twitter.md`'s Twitter/X import, `docs/obsidian.md`'s subset export and
both round trips, and `docs/quartz.md`'s export did not create it. The pages
are fixed.

### L8 — Rewrite the old paths in the Git history

L1 removed the account name from every committed file, but Git history still
holds it: 8 commits change how many home-directory paths the tree holds and 15
how many `/media` paths, the first being `bc4a911` (Step 20). `origin/develop` is at `659aa41`, so pushed commits
are affected and publishing the result needs a force-push of `develop`.
`origin/main` (`0b15260`, the initial commit) holds no such path and is not
rewritten.

*Found on 2026-10-27, before the rewrite.* That `origin/main` was a stale
local ref. GitHub's `main` is at `cb7ddc0`, the merges of pull requests 1 to 3
from `develop`, and 39 of its commits hold a path with the account name, so
`main` is rewritten too; the user chose that scope. `main` is protected:
changes reach it by a pull request from `develop`, which is then merged back
into `develop`, so publishing the rewritten `main` needs the user to allow a
force-push on it. The repository is public, with no forks, and GitHub keeps
`refs/pull/1/head`, `refs/pull/2/head` and `refs/pull/3/head`, which cannot be
pushed to and each hold 33 to 36 such commits. They and the pull-request pages
keep the old text until GitHub Support removes them, which only the user can
request. The only clone is this checkout.

*Before:* a mirror clone of the repository as a backup, outside the working
tree, kept until the user says it can go. The working tree is clean and every
other clone of the repository is known to the user, because each one has to be
re-cloned afterwards.

*Rewrite* every commit on every branch with the same replacements as L1 (home
paths to `~/`, the account segment of `/media` and `/run/media` paths to
`$USER`, scratchpad paths, `<name>-backup`), applied to every blob and to commit
messages. Use `git filter-repo --replace-text` if the user approves installing
it, since it also rewrites abbreviated commit hashes in commit messages and
writes an old-to-new commit map; otherwise `git filter-branch` with an index
filter, plus a recorded map. Author names and email addresses are not paths
and are left alone unless the user asks.

*Commit references.* Every commit from `bc4a911` on gets a new hash, and the
plans, ledgers, evidence documents and CHANGELOG cite many of them (`7e85d13`,
`2bd2de0`, …). A follow-up commit rewrites each reference in the tip's files
through the map. Only hashes that name a commit in this repository's old
history are rewritten: Notrios (`2aab9a8`, `7662fdd`) and Ledger (`85ac1b0`)
hashes belong to other repositories and stay.

*Verification:* `git log --all -p` and every commit message hold no path with
the account name; the rewritten tip's tree is byte-identical to the old tip's,
since L1 already cleaned it; for every commit, the old and new trees differ
only by the replacements; every hexadecimal token of seven or more characters
in the tip's files that was an old commit hash is mapped; the full gate passes.

*Publishing* is a separate step, with the user's explicit permission: force-push
`develop` with `--force-with-lease` against `659aa41`. GitHub can keep the old
commits reachable by their hashes for a while, and purging them from GitHub's
caches needs GitHub support; the plan records this rather than claiming the
old text is gone.

*Rewritten locally (2026-10-27).* A mirror backup of every branch and
remote-tracking ref is kept outside the working tree until the user says it
can go. `git filter-repo` rewrote `develop` and `main` (from GitHub's
`cb7ddc0`, since the local `main` was only stale) in a separate mirror. It
applied four rules to blobs and messages: scratchpad paths, `/home/<account>/`,
`/media/<account>/` (which covers `/run/media`), and `<account>-backup`. It
pruned nothing. Then:

- **Nothing left.** An inventory of every blob and message on both rewritten
  branches finds the account name nowhere, except as part of the GitHub user
  name, which is not a path.
- **Same tip.** `develop`'s tip tree is unchanged (`b59b5ba`).
- **Only the replacements.** All 124 commits keep their paths, modes, parents,
  authors, committers and dates. Every changed blob, 577 entries, equals the
  old one with the four rules applied. Seven messages changed, each only where
  filter-repo mapped an old hash. Messages held no account name.
- **New hashes.** Only the initial commit keeps its hash. The three GitHub merge
  commits on `main` lose GitHub's signature, because their content changed.
- **References mapped.** 210 citations of rewritten commits, in nine files
  (mostly the archived Notrios plan and ledger), now name the new commits, and
  every mapped hash resolves to one. Hashes from other repositories, dates and
  digests are unchanged. This section and the log keep the old hashes, because
  they describe the history before the rewrite and GitHub's current state,
  which the force-push leases are taken against. The full map is
  [`docs/plan/l8-commit-map.txt`](docs/plan/l8-commit-map.txt).

*Publishing, as authorized on 2026-10-27; steps 1 and 2 are done:*

1. The user temporarily enables "Allow force pushes" on `main`. `develop` is
   not protected.
2. Push `develop` with `--force-with-lease=develop:659aa41`, and the rewritten
   `main` with `--force-with-lease=main:cb7ddc0`.
3. The user turns force pushes off again.
4. The user asks GitHub Support to remove `refs/pull/1/head` to
   `refs/pull/3/head` and the cached views.
5. The usual pull request from `develop` to `main`, then the merge back into
   `develop`, brings `main` up to date.
6. Once the user agrees, delete the backup, and the local reflogs that still
   reach the old commits.

### H1 — HTML images after export

Carried from the Notrios import plan, proposed 2026-10-24 during C7d. A Joplin
note can hold `<img src=":/id">` (80 tags in 38 notes of the Joplin corpus).
`sql2obsidian.py` copies the resource, but `rewrite_resource_links` rewrites
only Markdown links, so the vault keeps `src=":/id"`, which neither Obsidian nor
the site resolves. Notrios-generated notes do the same since C7d, on purpose.
Rewrite the `src` value to the attachment's path relative to the note in both
export paths, keeping every other byte of the tag, and decide with the user
whether an exported image stays HTML or becomes an embed. Owns
`sql2obsidian.py`, `notrios_links.py` (`rewrite_projected_links`) and tests.

*Acceptance:* a note with HTML images exports with each `src` pointing at its
copied attachment, on both paths, byte-identical elsewhere; the vault reimports
to the same database except for the rewritten bytes; the site shows the image.

*Decided 2026-10-27.* Asked whether an exported image stays HTML or becomes an
embed, the user chose **stay HTML**: only the `src` value changes, to the
attachment's path relative to the note, and every other byte of the tag stays.
Today `obsidian2site.py` copies HTML tags verbatim, so the site cannot resolve
a vault path. `obsidian2sql.py` maps Markdown and wiki attachment links back to
`:/id`, but not `src`. With the user's agreement, H1 also owns:

- `obsidian2site.py`: resolving an `<img>` `src` that names a vault attachment
  to the site's asset URL;
- `obsidian2sql.py`: mapping such a `src` back to `:/id`, so a native reimport
  returns the original tag.

### D1 — Clearer output refusals

Carried from the Notrios import plan, proposed 2026-10-26 during 7d.
`notrios2sql.py` refuses each of these correctly (exit 1, nothing written), but
blames the archive, which verified: a missing output parent gives
`error [io]: cannot read archive directory` before verification; an existing
regular file gives the same message, and an existing directory that is not a
completed import gives `error [io]: cannot read regular archive object`, both
only after the whole archive is verified. Check the destination first: a
missing parent, or an existing path that is not a completed import, refuses as
`destination` with a message naming the problem. A completed import of another
publication keeps `completion receipt or shape differs`. The existing checks
stay, so a destination that appears during verification is still refused.
Owns `notrios2sql.py`, its tests and the `notrios2sql.py` rules in the docs.

*Acceptance:* each case has a subprocess test for exit 1, the exact error, no
`verify` phase reported and nothing written beside the output; existing
refusal, rerun and recovery tests pass unchanged.

### R1 — The link report

Carried from the Notrios import plan, proposed 2026-10-25 at the user's
request; the full specification is in
the [archived plan's R1 row](plans/v3.37/000-notrios-import-plan.md#producer-link-syntax-prerequisites--titles-in-projected-bodies). In short: during site
generation, write one CSV per run listing every link a web reader cannot reach
(`file:`, drive and UNC paths, browser and app schemes, unresolved relative
and wiki links, internal forms left unresolved), every malformed HTTP(S)
destination, every insecure `http:` link, and, for information, `tel:` and
`mailto:`; never fail generation for a link; keep the report out of everything
published, uploaded or deployed; print per-category counts.

*Acceptance:* as in the archived R1 row, including the three 7c libraries'
per-category counts in aggregate only.

### R2 — Non-internal destinations on the Notrios route

Carried from the Notrios import plan, proposed 2026-10-25; the user chose
option (a). With `plain_text`, Notrios `v1.0.0` replaces every unresolved or
ambiguous link with its label (2,318 links in the Joplin library: `file:`,
`tel:`, `data:`, relative and others), so they never reach movenotes. Export
the handoff with `--link-action retain` and have movenotes admit unresolved and
ambiguous records whose destination names no internal target, as text that R1
reports, while doing itself what `plain_text` does for a link to a withheld
note. A bounded probe of what `retain` emits for a withheld-note link comes
first; if it leaks withheld identities in a way the import cannot contain, fall
back to option (b), a producer change. The full specification is in the
[archived plan's R2 row](plans/v3.37/000-notrios-import-plan.md#producer-link-syntax-prerequisites--titles-in-projected-bodies).

*Acceptance:* every non-internal destination in a publication reaches the
vault and site byte-identical to the source note and appears in R1's report;
a link to a withheld note never carries that note's identity.

## Execution provenance

Generated from [`docs/plan/ledger.json`](docs/plan/ledger.json).

<!-- PLAN-EXECUTION:START -->
<details><summary>L0 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Plan and provenance edits, allowed while confirmation is pending (AGENTS.md). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent (Main) |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | Read the Notrios repository's plans/, docs/ and scripts/ layout and its AGENTS.md plan, roadmap and archival rules; asked the four layout questions; archived the old PLAN.md as plans/v3.34/000-refocus-plan.md; wrote PLAN.md and docs/plan/ledger.json; moved render_notrios_execution.py to scripts/render_plan_ledger.py with --ledger and per-ledger markers, and repointed the Notrios plan's commands; pointed the README and requirements.txt at the archived plan. |
| Validation | scripts/render_plan_ledger.py --check passes for docs/plan/ledger.json and for plans/v3.37/notrios-import-ledger.json; documentation and tooling only. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User request, 2026-10-26 (repository reorganization), and the four answers recorded under Decisions in PLAN.md. |
| Execution evidence | User request and answers, 2026-10-26 |
| Commit | Git commit containing this record: docs: open the reorganization plan and archive the refocus plan (L0) |

</details>

<details><summary>L1 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-26; L1 authorized by the user on 2026-10-26 (Start L1). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent (Main) |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | Rewrote every tracked path holding the account name: home-directory paths as ~/..., the account segment of /media and /run/media paths as $USER, scratchpad paths as /tmp/claude-$UID/-home-$USER-projects-movenotes-v3/<session>/scratchpad/..., and V1's example segment as <name>-backup; 70 lines across 11 files, the Notrios ledger's JSON included, with its plan regenerated. Two Markdown links to review files outside the repository became code spans, since a ~/ link cannot resolve. AGENTS.md's Tests section now gives the six required modules and the four harness modules for a full gate. |
| Validation | git grep for the account name in a path (home, media, run/media, scratchpad forms) prints nothing; no rewritten ~ sits inside quotes, and the one shell assignment (notrios_repo=~/...) expands in bash; both ledgers pass --check; 318 required tests passed in 188.794 s and 43 harness tests in 19.431 s, no __pycache__ written. Git history still holds the old text; rewriting it is out of scope. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User request, 2026-10-26 (repository reorganization), and the four answers recorded under Decisions in PLAN.md. |
| Execution evidence | User: Start L1; Private scratchpad l1/required.log and l1/harness.log |
| Commit | Git commit containing this record: docs: remove the account name from committed paths (L1) |

</details>

<details><summary>L2 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-26; L2 authorized by the user on 2026-10-26 (Start L2). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent (Main) |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | Release: CHANGELOG heading Changes in 3.37; __version__ 3.37 in obsidian2site.py, obsidian2sql.py, sql2obsidian.py, sql2joplin.py and cleanres.py (from 2.10, user decision); notrios2sql.py --version printing 'notrios2sql 3.37', with a test. Archive: git mv of LEDGER_MIGRATION_PLAN.md to plans/v3.36/000-ledger-migration-plan.md and of the Notrios plan, its ledger and ten working records to plans/v3.37/ (000 to 010 and notrios-import-ledger.json); plans/README.md. A one-off scratchpad mover re-relativized every Markdown link from each file's new location (a ledger's links from its plan's), rewrote bare mentions to repository-relative paths, and left fixture data untouched. The 26 links into a sibling ../notrios checkout became GitHub links at the commit each document cites (bdecfeda for the contract and the plan's original-pin section, 7662fdd for its schema-28 section, the only pin holding 0028_fts_rowid_map.sql). H1, D1, R1 and R2 are marked moved to PLAN.md in the archived plan and ledger. Added scripts/check_doc_links.py and test_docs.py (seventh required module); fixed one anchor that was already broken (2026-102223 for 2026-10-2223). |
| Validation | check_doc_links.py: 30 documents, 0 broken links; its test refuses a missing file, a missing anchor, a link leaving the repository and a site-absolute link, and ignores code spans, fences, schemes and fixture notes. Both ledgers pass --check, the archived one in place. 321 required tests (seven modules) passed in 184.423 s and 43 harness tests in 17.912 s, no __pycache__ written. All six scripts print 3.37 for --version. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User request, 2026-10-26 (repository reorganization), and the four answers recorded under Decisions in PLAN.md. |
| Execution evidence | User: Start L2; User: Sync version number for cleanres.py with rest of project; Add --version support to notrios2sql.py; Private scratchpad move_docs.py, l2-moves.json, l2/required.log, l2/harness.log |
| Commit | Git commit containing this record: chore: release 3.37 and archive the finished plans (L2) |

</details>

<details><summary>L4 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-26; L4 authorized by the user on 2026-10-26 (do L4 next). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent (Main) |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | Tested a unittest/ directory first: python3 -m unittest unittest/test_x.py fails and an __init__.py there shadows the standard library, so the user's fallback applied and tests/ was used (path form works, no __init__.py needed). git mv of the eleven test_*.py modules into tests/ and of notrios_c7c.py into scripts/. Test modules now take the repository root as Path(__file__).resolve().parent.parent (test_notrios2sql.py: one PROJECT_DIR for 22 uses); test_notrios_c7c.py puts scripts/ on sys.path before importing notrios_c7c. notrios_c7c.py puts the root on sys.path, and its dependency code inventory hashes the root's *.py files plus itself (as scripts/notrios_c7c.py). The 7c harness runs scripts/notrios_c7c.py, and its consumer-hash probe searches the root and scripts/. References rewritten everywhere except the active plan and its ledger (which quote the user and describe the move): paths to tests/..., dotted test names to tests.test_x.Class, scripts/notrios_p7b_long_batch.py's suite command, and the archived plans' records. |
| Validation | The sorted list of 364 test IDs is identical before and after the move, with no import failures; 321 required tests (seven modules) passed in 167.794 s and 43 harness tests in 15.788 s from tests/, no __pycache__ written; the dotted form tests.test_notrios2sql.NotriosV1TitledTest runs (4 tests OK); scripts/notrios_c7c.py, scripts/notrios_7c_trials.py and scripts/notrios_c7c_pair_smoke.py --help run, and consumer_hashes(('notrios_c7c',)) finds scripts/notrios_c7c.py; no test_*.py or notrios_c7c.py remains at the root; check_doc_links.py: 31 documents, 0 broken links. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User, 2026-10-26: Add a unittest directory for those files ... do L4 next, including notrios_c7c.py, then L3; Pick a different name if unittest would cause problems. |
| Execution evidence | User: Add a unittest directory for those files and update any necessary files in the plan for L4. Then, do L4 next, including notrios_c7c.py, then L3.; User: Pick a different name if unittest would cause problems.; Private scratchpad l4/ids-before.txt, l4/ids-after.txt, l4/required.log, l4/harness.log |
| Commit | Git commit containing this record: refactor: move the tests to tests/ and notrios_c7c.py to scripts/ (L4) |

</details>

<details><summary>L3 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-26; L3 authorized by the user on 2026-10-26 (do L4 next ... then L3). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent (Main) |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | Wrote ROADMAP.md: the 3.38 release the active plan is for (no slice status) and the three deferred features, packed publications, multiple handoffs and merges, and full and subset archives, each with what it is, why it waits (from the importer's actual refusals in notrios_archive.py and notrios2sql.py), what it needs and what it depends on. AGENTS.md: a new 'Plans, the roadmap and the archive' section adapted from the Notrios repository's plan, roadmap and archival rules (homes table, keeping the plan and roadmap current, the archive layout and verbatim rule, starting the next plan); a 'Repository layout and moved files' section (root scripts, tests/ without __init__.py and why not unittest/, scripts/, docs/, plans/, fixture data never rewritten, git mv plus references in the same commit, the link checker); the reading list now starts with PLAN.md and ROADMAP.md, describes the migration plan as archived, and names the Notrios modules. PLAN.md, the README and plans/README.md point back to the new section. |
| Validation | check_doc_links.py: 32 documents, 0 broken links (ROADMAP.md and the new AGENTS.md anchors included); tests/test_docs.py passes; ROADMAP.md holds no slice status. Documentation only; no code changed. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User request, 2026-10-26 (repository reorganization), and the four answers recorded under Decisions in PLAN.md. |
| Execution evidence | User: do L4 next, including notrios_c7c.py, then L3; ~/projects/notrios/AGENTS.md (Keeping the plan current, Keeping the roadmap current, Plan archival) |
| Commit | Git commit containing this record: docs: add ROADMAP.md and the rules for plans (L3) |

</details>

<details><summary>L5 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-26; L5 authorized by the user on 2026-10-26 (Start L5). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent (Main) |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | git mv of STATIC_SITE.md, DEPLOY_VERCEL.md, DEPLOY_GITHUB_PAGES.md, PERFORMANCE_REVIEW.md, IMPLEMENTATION_REVIEW.md, NOTRIOS_IMPORT_CONTRACT.md and NOTRIOS_IMPORT_DESIGN.md to lowercase names in docs/, with every reference rewritten by the one-off mover (archived plans and ledger included; the active plan excluded). Split the README's usage sections, verbatim apart from heading levels and re-based links, into docs/joplin.md (with the orphaned PDF OCR section), twitter.md, obsidian.md (with the round trips), images.md, notrios.md, quartz.md, testing.md (with the test-module rows of the script table) and schema.md; wrote docs/index.md. The README keeps About, the script table (tests/ and scripts/ as one row each), Setup, a quick start repeating each page's first example, a short Testing pointer, the development plan, history and licence. The site section's opening paragraph and example stay in the README; its prose-tags paragraph moved into docs/static-site.md's conversion section; its other summary paragraphs were dropped as covered there: server start and logging (section 3, lines 162-175), search syntax and newest-first ordering (Search syntax), link search (Searching for a link), the three ways in and two tag populations (intro, Two kinds of tag), canonical URLs (section 2), the JSONL stream and Pagefind commands (Search backends, section 4), --search-backend both and the built-backend check (Search backends, Confirm which backend is active), converter features (Obsidian Markdown conversion), deployment links (Deploying). AGENTS.md's reading list points at docs/ for usage; the Notrios page's 'previous section' link now names the static-site guide. |
| Validation | verify_split.py: 187 blocks of the pre-split README; every block has exactly one home except the seven quick-start examples and the Testing heading the README repeats, and 15 intended changes (two table rows reworded or replaced by the scripts/ row, the site heading, ten site summary blocks covered in docs/static-site.md as mapped, one link label, one link wording). check_doc_links.py: 41 documents, 0 broken links; tests/test_docs.py passes. Root holds only the files the plan lists (plus an ignored __pycache__ from earlier runs). Documentation only; no code changed. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User request, 2026-10-26 (repository reorganization), and the four answers recorded under Decisions in PLAN.md. |
| Execution evidence | User: Start L5; Private scratchpad split_readme.py, compose_readme.py, verify_split.py, readme-presplit.md, l5-moves.json |
| Commit | Git commit containing this record: docs: move the documentation into docs/ and split the README (L5) |

</details>

<details><summary>L6 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-26; L6 authorized by the user on 2026-10-26 (Start L6). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent (Main) |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | Read Notrios v1.0.0's selection policy (internal/store/sqlite_selection.go: defaultSelectionPolicy, the ExcludeTags/PrivateTags union, MaxSelectionSelectors) and found the plan's assumption wrong: --exclude-tags adds to the withheld tags, --private-tags replaces the three defaults. Measured on a synthetic library imported from testdata/notrios/vault-titled-v1 with the pinned binary: default plan withholds a private-tagged note; --exclude-tags internal withholds both; --private-tags secret publishes the private-tagged note; export archive-v2 withholds it and its selection digest equals the default plan's for the same notebook; both routes over every root notebook select 3 and exclude 1; a note in a notebook named Private is published unless tagged; tags add --query ... --apply tags a notebook; notes move files a note. docs/notrios.md: new sections 'Keeping notes out of a publication', 'What tagging cannot catch' (prose, code, titles, file names, URLs, attachments and their metadata; Presidio and hawk-eye; fix findings in Notrios, not the vault) and 'Publications over 100,000 notes' (export over root notebooks found with notebooks list --json, what the export route does and does not do, the 100-selector and unfiled-note limits, or splitting into separate sites until merges exist), replacing the recipe's short paragraph. CHANGELOG gains an Unreleased section for L2 to L6's user-visible changes. |
| Validation | The three new fences ran as written in a fresh scratch library: search found the note IDs, tags add tagged it (plan 4 selected/0 excluded to 3/1), the query dry run and --apply ran, the export over every root notebook selected 3 and excluded 1 with skipped_rewrites 0, withheld the tagged note, verified, and imported with notrios2sql.py. The --exclude-tags and --private-tags behaviour was measured in a separate probe. check_doc_links.py: 41 documents, 0 broken links. Documentation only; no code changed. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User request, 2026-10-26 (repository reorganization), and the four answers recorded under Decisions in PLAN.md. |
| Execution evidence | User: Start L6; ~/projects/notrios at v1.0.0: internal/store/sqlite_selection.go, cmd/notriosctl/publish.go; Private scratchpad l6/probe.sh, l6/probe2.sh, l6/doc-fences.sh |
| Commit | Git commit containing this record: docs: document private data and publications over 100,000 notes (L6) |

</details>

<details><summary>L7 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-26; L7 authorized by the user on 2026-10-26 (Start L7.). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent (Main) |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | Added scripts/check_doc_examples.py: finds every fenced block in README.md and docs/ (tracked or untracked, not ignored), refuses unregistered, changed (heading, language or SHA-256) and stale entries before running anything, then runs each page's runnable examples in page order from the repository root with bash -euo pipefail, in temporary homes (HOME and XDG inside) seeded from sample/ and testdata/ with optional setup commands; registry features substitute, {port}, cwd and serves; --with-tools adds Hugo, Go, npx, notriosctl ($NOTRIOSCTL) and the Ledger theme ($LEDGER_THEME), reports a missing tool as skipped and fails the run; --list and --page. Wrote docs/examples.json for all 66 fences: 22 executed, 16 tools, 28 unverified with reasons. Fixed six examples that failed as written because the --output directory did not exist (README and docs/twitter.md Twitter/X import, docs/obsidian.md subset export and both round trips, docs/quartz.md export). Added tests/test_doc_examples.py (eighth required module: the repository's examples, fence parsing, refused registry problems, shared and separate homes, a failure, a missing tool and an after-skip, a server); AGENTS.md section Documentation examples and the eight-module gate; docs/testing.md, README script table and CHANGELOG. |
| Validation | check_doc_examples.py: 66 fences in 13 pages, 0 registry problems, 22 executed examples pass in about 15 s; --with-tools with Hugo v0.164.0, Go 1.27.0, notriosctl v1.0.0 (the pinned binary) and the Ledger theme: 38 examples, 38 passed, 0 failed, 0 skipped. Editing a real fence (docs/joplin.md example 2) made the check fail with one changed-entry problem; the synthetic test refuses a changed, an unregistered and two stale entries. Required gate: 325 tests (eight modules) passed in 205.728 s; harness gate 43 tests in 15.999 s; no __pycache__ written. The repository, the theme checkout and /tmp were left unchanged by the runs. check_doc_links.py: 41 documents, 0 broken links. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User request, 2026-10-26 (repository reorganization), and the four answers recorded under Decisions in PLAN.md. |
| Execution evidence | User: Start L7.; Private scratchpad l7/build_registry.py, l7/tools1.log, l7/tools2.log, l7/required.log, l7/harness.log |
| Commit | Git commit containing this record: test: register and run the documentation examples (L7) |

</details>

<details><summary>L8 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-27 (new session); L8 authorized on 2026-10-27 (I installed git filter-repo. gh is also available. Start L8.), with the scope Rewrite develop and main; force-pushing needs separate permission. Force-push authorized 2026-10-27: I enabled force pushes on main; Force-push when ready. |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent (Main) |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | Read-only check found GitHub's main at cb7ddc0 (merges of pull requests 1 to 3) holding the old paths, three unwritable refs/pull/N/head refs, a public repository with no forks, and classic protection on main (force pushes off). Made a mirror backup outside the working tree. Rewrote develop and main with git filter-repo in a separate mirror: four rules (scratchpad paths, home paths, /media and /run/media account segments, <account>-backup) on blobs and messages, --prune-empty never, --prune-degenerate never. Moved this checkout onto the rewritten branches (identical tree). Mapped 210 citations of rewritten commits in nine files through the commit map, keeping PLAN.md's L8 text on the old hashes it describes; committed the map as docs/plan/l8-commit-map.txt. Published: checked force pushes enabled on main and GitHub still at 659aa41 and cb7ddc0, then pushed develop (659aa41 to 547b289) and main (cb7ddc0 to 526c073), each with --force-with-lease against those hashes. |
| Validation | Inventory of every blob and message on both rewritten branches: no account name outside the GitHub user name. develop's tip tree unchanged (b59b5ba). All 124 commits: same paths and modes; 577 changed blob entries each equal the old blob with the rules applied; parents mapped, authors, committers and dates equal; 7 messages changed only by filter-repo's hash mapping. The 14 hashes filter-repo left unmapped name no object here (Notrios, theme, a number). Every mapped short hash resolves to a commit; the archived Notrios ledger passes --check in place; 41 documents, 0 broken links. On the rewritten tip with the references mapped: 325 required tests passed in 207.345 s and 43 harness tests in 16.272 s, no __pycache__ written. After the push, a fresh mirror clone of GitHub has develop 547b289 and main 526c073, and no blob or message on them holds the account name; refs/pull/1/head to refs/pull/3/head still serve the old commits, as expected. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User, 2026-10-26: Update the plan to rewrite the old paths in the Git history. |
| Execution evidence | User: I installed git filter-repo. gh is also available. Start L8.; User answers 2026-10-27: Current; Rewrite develop and main (Recommended); Only this checkout; User: main is protected on GitHub; changes are merged by pull request into main, then merged back into develop; docs/plan/l8-commit-map.txt; Private scratchpad l8/inventory.py, l8/verify.py, l8/refs.py, l8/expressions.txt; User: I enabled force pushes on main; Force-push when ready. |
| Commit | Git commit containing this record: docs: record the published history rewrite (L8) |

</details>

<details><summary>H1 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-27; H1 authorized on 2026-10-27 (Then, start H1.), with the user's choices: the image stays HTML, and H1 also owns obsidian2site.py's src resolution and obsidian2sql.py's mapping back to :/id. |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent (Main) |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | Asked the user to choose HTML or embed and the scope (stay HTML; H1 also owns the site and reimport). common.py: HTML_IMAGE_SRC_RE (double-, single- or unquoted src after whitespace, so not data-src) and replace_html_image_sources, which changes only the value's bytes and takes an optional span predicate. sql2obsidian.rewrite_resource_links rewrites an <img> src of a known :/id to the attachment's path relative to the note. notrios_links.rewrite_projected_links does the same for projected notes, still refusing an HTML image without a mapped resource. obsidian2site.py resolves an <img> src naming a vault attachment to its asset URL in one pass over the whole note, so a tag spanning lines works, leaving tags with any byte in code, external sources and non-attachments unchanged; notes without <img skip it. obsidian2sql.rewrite_obsidian_links maps such a src back to :/id (percent-encoding and entities decoded). Tests: unit cases for each direction, the site, and the Notrios projection (renamed from keep_their_mapped_source), and one end-to-end Joplin RAW to vault, bundle and native reimport, and site test. Docs: obsidian.md, notrios.md, static-site.md, notrios-import-design.md, testing.md count; CHANGELOG. |
| Validation | New tests pass: the vault tag keeps every byte but src, which opens the copied attachment (same bytes as the resource); the bundled reimport returns the note byte for byte; the native reimport returns the tag with src=:/id of the reimported resource; the site's src resolves to the static asset, as the Markdown image's URL does, for quoted, single-quoted and multi-line unquoted tags, with external, missing and code forms unchanged; the Notrios projection rewrites src and refuses as before. A real Hugo v0.164.0 build with the Ledger theme: the built page's img src resolves to a file in public/. Required gate 329 tests passed in 229.222 s, harness 43 tests in 15.336 s, no __pycache__ written; 41 documents, 0 broken links; 66 fences, 0 registry problems. |
| Delegation failure or reassignment | Moved 2026-10-26 from the Notrios import plan (status pending there, never started) at the user's direction; the original record stays in the archived ledger. |
| Planned assignment evidence | C7d finding, 2026-10-24; moved from the Notrios import plan 2026-10-26. |
| Execution evidence | User: Then, start H1.; User answers 2026-10-27: Stay HTML (Recommended); Yes, both (Recommended); Private scratchpad h1/required.log, h1/harness.log, h1/site/build.log |
| Commit | Git commit containing this record: feat: keep exported HTML images as HTML pointing at their attachment (H1) |

</details>

<details><summary>D1 — pending; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-26; slice implementation requires user authorization. |
| Actual worker | pending |
| Child thread | pending |
| Actual model | pending |
| Reasoning effort | pending |
| Worker contribution | pending |
| Parent | pending |
| Parent underlying model family | pending |
| Parent reasoning effort | pending |
| Parent contribution | pending |
| Validation | pending |
| Delegation failure or reassignment | Moved 2026-10-26 from the Notrios import plan (status pending there, never started) at the user's direction; the original record stays in the archived ledger. |
| Planned assignment evidence | 7d finding, 2026-10-26; moved from the Notrios import plan 2026-10-26. |
| Execution evidence | none |
| Commit | pending |

</details>

<details><summary>R1 — pending; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-26; slice implementation requires user authorization. |
| Actual worker | pending |
| Child thread | pending |
| Actual model | pending |
| Reasoning effort | pending |
| Worker contribution | pending |
| Parent | pending |
| Parent underlying model family | pending |
| Parent reasoning effort | pending |
| Parent contribution | pending |
| Validation | pending |
| Delegation failure or reassignment | Moved 2026-10-26 from the Notrios import plan (status pending there, never started) at the user's direction; the original record stays in the archived ledger. |
| Planned assignment evidence | User request 2026-10-25; moved from the Notrios import plan 2026-10-26. |
| Execution evidence | none |
| Commit | pending |

</details>

<details><summary>R2 — pending; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-26; slice implementation requires user authorization. |
| Actual worker | pending |
| Child thread | pending |
| Actual model | pending |
| Reasoning effort | pending |
| Worker contribution | pending |
| Parent | pending |
| Parent underlying model family | pending |
| Parent reasoning effort | pending |
| Parent contribution | pending |
| Validation | pending |
| Delegation failure or reassignment | Moved 2026-10-26 from the Notrios import plan (status pending there, never started) at the user's direction; the original record stays in the archived ledger. |
| Planned assignment evidence | User chose option (a) 2026-10-25; moved from the Notrios import plan 2026-10-26. |
| Execution evidence | none |
| Commit | pending |

</details>
<!-- PLAN-EXECUTION:END -->

## Progress log

| Date | Event | Summary |
|---|---|---|
| 2026-10-26 | Plan opened | At the user's request, after 7e completed the Notrios import plan. The user's four answers are under Decisions. L0: the old `PLAN.md` is archived as `plans/v3.34/000-refocus-plan.md`, this plan and its ledger are written, and `scripts/render_plan_ledger.py` replaces `render_notrios_execution.py` for both ledgers. Documentation and provenance only. Next: confirm this plan's assignments, then ask to proceed to L1. |
| 2026-10-26 | Confirmed; L1 authorized | The user: "The assignments are current for this session; Sync version number for cleanres.py with rest of project; Add --version support to notrios2sql.py; Start L1." L2's release text now syncs `cleanres.py` at 3.37 and adds `notrios2sql.py --version`. |
| 2026-10-26 | L1 complete | Every committed path with the account name now uses `~/`, `$USER` or a `<session>` placeholder: 70 lines in 11 files. Two links to files outside the repository became code spans. `AGENTS.md` gives the six-module gate and the four harness modules. 318 and 43 tests pass. Next: ask to proceed to L2. |
| 2026-10-26 | L8 added; L2 authorized | The user: "Update the plan to rewrite the old paths in the Git history. Start L2." L8, after L7, rewrites every commit with L1's replacements, maps the rewritten commit hashes cited in the tip's files, and needs its own authorization plus separate permission to force-push `develop`. |
| 2026-10-26 | L2 complete | Released 3.37: CHANGELOG heading, five scripts at 3.37 (`cleanres.py` from 2.10), `notrios2sql.py --version`. Archived the migration plan to `plans/v3.36/` and the Notrios plan, ledger and ten records to `plans/v3.37/`, with every reference updated; 26 links into a sibling Notrios checkout now go to GitHub at the cited commit. `scripts/check_doc_links.py` and `test_docs.py` check every link and anchor, and found one already broken, now fixed. 321 and 43 tests pass. Next: ask to proceed to L3. |
| 2026-10-26 | L4 revised and moved before L3 | The user: "Add a `unittest` directory for those files and update any necessary files in the plan for L4. Then, do L4 next, including notrios_c7c.py, then L3." and then "Pick a different name if `unittest` would cause problems." A directory named `unittest` breaks `python3 -m unittest unittest/test_x.py`, and with an `__init__.py` would shadow the standard library, so the tests go to `tests/`; `notrios_c7c.py` goes to `scripts/`. Order: L4, then L3, then L5. |
| 2026-10-26 | L4 complete | The eleven test modules are in `tests/` and `notrios_c7c.py` in `scripts/`; every reference outside the active plan was rewritten, dotted test names included. The same 364 test IDs load; 321 and 43 pass from `tests/`. Next: L3, already authorized. |
| 2026-10-26 | L3 complete | `ROADMAP.md` gives the 3.38 release this plan is for and the three deferred Notrios features. `AGENTS.md` gains the rules for plans, the roadmap and the archive, and for the repository layout and moving files; its reading list starts with `PLAN.md` and `ROADMAP.md`. Documentation only. Next: ask to proceed to L5. |
| 2026-10-26 | L5 complete | Seven reference documents moved into `docs/` in lowercase, with every reference updated. The README's usage sections are eight pages in `docs/`, listed by `docs/index.md`; the README keeps what movenotes is, the script table, setup and a short example per workflow, and is 197 lines instead of 863. Every old paragraph has one home, apart from the repeated examples and the site summary that `docs/static-site.md` already covered. Next: ask to proceed to L6. |
| 2026-10-26 | Caches removed; L6 authorized | The user: "Remove unused __pycache__/ directories; there is another __pycache__/ directory in the scripts/ directory. Start L6." Both held only compiled files and nothing tracked; one, `scripts/__pycache__/check_doc_links.cpython-314.pyc`, came from a check run without `-B` during L2. Both removed. |
| 2026-10-26 | L6 complete | `docs/notrios.md` documents keeping notes out of a publication, what tagging cannot catch (with Presidio and hawk-eye), and publishing over 100,000 notes. Found while reading Notrios `v1.0.0`'s selection code, and confirmed by measurement: `--exclude-tags` adds tags, and `--private-tags` replaces the defaults, so it can publish a `private` note; the plan's L6 text said otherwise and is corrected. Every new command ran as written. Next: ask to proceed to L7. |
| 2026-10-26 | L7 complete | Every one of the 66 fences in the README and `docs/` is registered in `docs/examples.json`: 22 run in the gate, 16 with `--with-tools`, and 28 record why they are not run. The first run found six examples that failed as written because their `--output` directory did not exist; the pages are fixed. The registry needed `homes`, `cwd`, `{port}` (8080 is taken on this machine) and `serves` beyond the specification. 325 required tests (eight modules) and 43 harness tests pass, and all 38 examples pass with the tools. Next: ask to proceed to L8. |
| 2026-10-27 | New session; L8 authorized | The user re-confirmed the assignments for the new session, and: "I installed `git filter-repo`. `gh` is also available. Start L8." A read-only check found GitHub's `main` at `cb7ddc0` with the old paths, and pull-request refs that cannot be rewritten; the user chose to rewrite `develop` and `main`, and said `main` is protected and is updated by merging a pull request, then merging back into `develop`. Publishing needs separate permission. |
| 2026-10-27 | L8 rewritten locally | `git filter-repo` rewrote `develop` and `main` after a mirror backup. No blob or message on either branch holds the account name, the tip tree is unchanged, and every commit differs from its original only by L1's replacements. 210 references to rewritten commits are mapped, and the map is committed. Nothing is pushed: publishing needs the user's permission, and force pushes enabled on `main`. |
| 2026-10-27 | L8 complete | The user: "I enabled force pushes on `main`; Force-push when ready." `develop` (`659aa41` to `547b289`) and `main` (`cb7ddc0` to `526c073`) were pushed with leases against their old tips. A fresh clone of GitHub holds the account name in no blob or message. Left to the user: turning force pushes off on `main`, asking GitHub Support to remove `refs/pull/1-3/head` and the cached views, and saying when the backup can go. The next pull request from `develop` brings `main` up to date. Next: ask to proceed to H1. |
| 2026-10-27 | Branches synced; H1 authorized | The user turned force pushes off on `main` and asked to push `develop`, open a pull request to `main`, merge back into `develop`, then start H1. Pull request #4 merged as `5970504`, and `develop` fast-forwarded to it. For H1 the user chose that an exported HTML image stays HTML with only its `src` rewritten, and that H1 also owns the site's `src` resolution and the reimport's mapping back to `:/id`. |
| 2026-10-27 | H1 complete | An exported HTML image keeps its tag, with only `src` changed to the attachment's path relative to the note, on both the Joplin and the Notrios paths. The site resolves it to the asset URL, including a tag that spans lines, which the line-at-a-time conversion would have missed. A native reimport maps it back to `:/id`, and a bundled one returns the note byte for byte. A real Hugo build shows the image. 329 required and 43 harness tests pass. Next: ask to proceed to D1. |
