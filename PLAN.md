# Plan: Reorganize the repository, then the Notrios import follow-ups

Status: **opened 2026-10-26.** L0 (opening) and **L1 are complete**; the next
slice, **L2**, is authorized and in progress. The user confirmed this plan's assignments for the session
on 2026-10-26; see
[Coding-agent assignments](#coding-agent-assignments-and-session-confirmation).

## Goal

The Notrios import plan is complete, and the repository root has grown to 25
Markdown documents, a JSON ledger and ten test modules beside the scripts.
This plan:

1. removes the account name from every committed path;
2. archives the finished plans under `plans/` by version, and releases 3.37;
3. adds `ROADMAP.md` for the deferred Notrios features, and the rules in
   `AGENTS.md` for how `PLAN.md`, `ROADMAP.md` and the archive are used;
4. moves the test modules and tools into `scripts/` and the documentation into
   `docs/`, updating every reference to a moved file;
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
`PLAN.md`, `LEDGER_MIGRATION_PLAN.md` and `NOTRIOS_IMPORT_PLAN.md` under
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
| Archive versions | **3.34 / 3.36 / 3.37**: the old `PLAN.md` (refocus, steps 1–19, last shipped as 3.34) goes to `plans/v3.34/`, `LEDGER_MIGRATION_PLAN.md` to `plans/v3.36/`, and `NOTRIOS_IMPORT_PLAN.md` with its ledger and renderer to `plans/v3.37/`. The CHANGELOG's "Unreleased changes" becomes "Changes in 3.37", and the changed scripts' `__version__` values go to 3.37. |
| H1, R1, R2, D1 | **New `PLAN.md`**, after the reorganization, each still needing authorization. `ROADMAP.md` holds only deferred features. |
| Notrios evidence documents | **Archived with their plan** in `plans/v3.37/`. Reference documents go to `docs/`: the static-site and deployment guides, the performance review, the implementation review, and the Notrios import contract and design. |
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

2026-10-26 user: The assignments are current for this session. Answered after being shown the Claude Code parent (Main) as the only owner of every slice, runtime-reported model claude-opus-5-5, and configured alias, reasoning effort, client version and billing route not exposed. Applies to this unchanged session; each slice still needs its own authorization.

| Coding agent | Execution owner | Configured model | Reasoning effort | Availability | Billing route |
|---|---|---|---|---|---|
| claude | parent | not exposed; runtime reports claude-opus-5-5 | not exposed | Main for every slice; no workers planned | not exposed; assignments confirmed by user for this session |

Runtime-reported parent family: **Claude Opus 5.5 (runtime-reported model ID claude-opus-5-5)**. Product/client version: not exposed; model provider: Anthropic (runtime-reported).

- Every slice is planned for the Claude Code parent, called Main in the slice table. No worker or subagent is planned.
- Spawning a worker or subagent requires an explicit user request and a recorded plan amendment first.
- Main runs long data-heavy commands as harness-tracked background commands, is re-invoked once when they exit, and does not poll.
- The runtime-reported model ID is not a configured alias. Reasoning effort, client version and billing route are not exposed.
<!-- PLAN-ASSIGNMENTS:END -->

Current slice: **L2 — release 3.37 and archive the finished plans**, assigned
to Main; authorized 2026-10-26.

## Execution rules

- One slice at a time. Commit each slice, then ask before starting the next and
  wait for the answer. No push without permission.
- A moved file moves with `git mv`, and every reference to it, in any tracked
  file, changes in the same commit. From L2 on, `scripts/check_doc_links.py`
  proves it.
- Keep `.zvec-grep/` out of commits; `git ls-files .zvec-grep` prints nothing.
  After each slice run `zg index` and `zg status --check-ready`.
- The regression gate runs with `PYTHONDONTWRITEBYTECODE=1` and `-B`. It is the
  six required modules, plus the four other harness modules for a full gate;
  from L4 on, both run from `scripts/`.
- Private data stays out of Git: aggregate evidence only, no note content.
- When a slice finds something that needs fixing, add it to this plan rather
  than only reporting it.

## Slices

| Slice | Work | Depends on | Acceptance |
|---|---|---|---|
| L0 / Main | *Complete 2026-10-26.* Open this plan: archive the old `PLAN.md` to `plans/v3.34/000-refocus-plan.md`, write this plan and its ledger, and turn `render_notrios_execution.py` into `scripts/render_plan_ledger.py`, which takes `--ledger` and serves both ledgers. | — | Both ledgers render and `--check` passes; the README and `requirements.txt` point at the archived plan. |
| L1 / Main | *Complete 2026-10-26.* Remove the account name from committed paths; update the `AGENTS.md` test command. See [L1](#l1--remove-the-account-name-from-committed-paths). | L0 | No tracked file holds a path with the account name; both ledgers check; the full gate passes. |
| L2 / Main | Release 3.37 and archive the finished plans, with a link checker. See [L2](#l2--release-337-and-archive-the-finished-plans). | L1 | Every relative link and anchor in every tracked Markdown file resolves; the archived ledger checks in place; the full gate passes. |
| L3 / Main | Add `ROADMAP.md`, and the plan, roadmap and archive rules in `AGENTS.md`. See [L3](#l3--roadmapmd-and-the-rules-for-plans). | L2 | Each deferred feature has its scope, why it is deferred and what it needs; `AGENTS.md` states the rules; links resolve. |
| L4 / Main | Move the test modules and tools into `scripts/`. See [L4](#l4--tests-and-tools-in-scripts). | L3 | The same 318 and 43 tests pass from `scripts/`, run from the repository root; no test or script at the root. |
| L5 / Main | Move the documentation into `docs/`, and split the README's usage sections into pages there. See [L5](#l5--documentation-in-docs). | L4 | Root holds only the files listed in L5; every old README paragraph exists in exactly one page; links resolve. |
| L6 / Main | Document private data and publications over 100,000 notes. See [L6](#l6--private-data-and-large-publications). | L5 | Each documented command was run on a synthetic library and behaved as written. |
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
`notrios2sql.py` gains `--version`, printing `notrios2sql.py 3.37` like the
other scripts (user, 2026-10-26); its help test and the documented CLI rules
change with it.

*Archive*, in the Notrios layout `plans/v<major>.<minor>/<NNN>-<slug>.md`, with
`plans/README.md` describing it:

- `plans/v3.36/000-ledger-migration-plan.md` ← `LEDGER_MIGRATION_PLAN.md`;
- `plans/v3.37/000-notrios-import-plan.md` ← `NOTRIOS_IMPORT_PLAN.md`, with
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

### L4 — Tests and tools in scripts

`git mv` every `test_*.py` and the remaining root tools into `scripts/`. The
modules find the repository root as `Path(__file__).resolve().parent.parent`
instead of their own directory, and run each script from there. The gate
becomes `python3 -B -m unittest scripts/test_movenotes.py …`, run from the
root. `AGENTS.md`, the README's Testing section and this plan change with it.
The Go module's tests stay in `site_server/`.

*Acceptance:* the same 318 and 43 tests, by name, pass from `scripts/`; no
`test_*.py` remains at the root; nothing writes `__pycache__`.

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
and the directories `docs/`, `plans/`, `scripts/`, `sample/`, `testdata/`,
`site_server/` and `experiments/`.

*Acceptance:* a script compares the paragraphs of the old README with the new
README and pages, and finds each old paragraph in exactly one place; the link
checker passes.

### L6 — Private data and large publications

In `docs/notrios.md`:

- **Keeping a note out of a publication.** Tag it `private`, `draft` or
  `confidential` (`notriosctl tags add --tag private --document <id>`); those
  are excluded by default, along with read-only notebooks and the Trash.
  `--exclude-tags` replaces the default list, so a profile that sets it must
  name the defaults it still wants. Review the plan's list of notes before
  publishing.
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

`scripts/test_doc_examples.py` fails on an unregistered or changed fence and
on a stale registry entry, then runs the executed examples. `AGENTS.md`
describes the process: an edited example is re-run and re-registered in the
commit that edits it.

*Acceptance:* every fence is registered; the executed examples pass in the
gate; `--with-tools` passes on this machine with Hugo `v0.164.0`, Go 1.27.0 and
`notriosctl` `v1.0.0`; an edited fence and an unregistered one each fail.

### L8 — Rewrite the old paths in the Git history

L1 removed the account name from every committed file, but Git history still
holds it: 8 commits change how many home-directory paths the tree holds and 15
how many `/media` paths, the first being `bc4a911` (Step 20). `origin/develop` is at `659aa41`, so pushed commits
are affected and publishing the result needs a force-push of `develop`.
`origin/main` (`0b15260`, the initial commit) holds no such path and is not
rewritten.

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
the archived plan's R1 row (`NOTRIOS_IMPORT_PLAN.md` until L2 archives it). In short: during site
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
archived plan's R2 row.

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
| Validation | scripts/render_plan_ledger.py --check passes for docs/plan/ledger.json and for NOTRIOS_IMPORT_EXECUTION.json; documentation and tooling only. |
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

<details><summary>L2 — pending; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-26; L2 authorized by the user on 2026-10-26 (Start L2). |
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
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User request, 2026-10-26 (repository reorganization), and the four answers recorded under Decisions in PLAN.md. |
| Execution evidence | none |
| Commit | pending |

</details>

<details><summary>L3 — pending; planned parent</summary>

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
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User request, 2026-10-26 (repository reorganization), and the four answers recorded under Decisions in PLAN.md. |
| Execution evidence | none |
| Commit | pending |

</details>

<details><summary>L4 — pending; planned parent</summary>

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
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User request, 2026-10-26 (repository reorganization), and the four answers recorded under Decisions in PLAN.md. |
| Execution evidence | none |
| Commit | pending |

</details>

<details><summary>L5 — pending; planned parent</summary>

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
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User request, 2026-10-26 (repository reorganization), and the four answers recorded under Decisions in PLAN.md. |
| Execution evidence | none |
| Commit | pending |

</details>

<details><summary>L6 — pending; planned parent</summary>

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
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User request, 2026-10-26 (repository reorganization), and the four answers recorded under Decisions in PLAN.md. |
| Execution evidence | none |
| Commit | pending |

</details>

<details><summary>L7 — pending; planned parent</summary>

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
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User request, 2026-10-26 (repository reorganization), and the four answers recorded under Decisions in PLAN.md. |
| Execution evidence | none |
| Commit | pending |

</details>

<details><summary>L8 — pending; planned parent</summary>

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
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | User, 2026-10-26: Update the plan to rewrite the old paths in the Git history. |
| Execution evidence | none |
| Commit | pending |

</details>

<details><summary>H1 — pending; planned parent</summary>

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
| Planned assignment evidence | C7d finding, 2026-10-24; moved from the Notrios import plan 2026-10-26. |
| Execution evidence | none |
| Commit | pending |

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
