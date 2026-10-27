# AGENTS.md

## Repository orientation

`movenotes` is a dependency-free Python toolkit using `notesdb.sqlite` as the
intermediate representation between Joplin RAW, Obsidian vaults, Twitter/X
archives and Notrios publications.

Read these files first:

1. `PLAN.md` and `ROADMAP.md` — the plan being implemented and its next slice,
   and what releases are meant to do. How they are kept, and when a plan is
   archived to `plans/`, is under
   [Plans, the roadmap and the archive](#plans-the-roadmap-and-the-archive).
2. `README.md` — supported workflows, lossless guarantees, and command usage.
3. `notesdb.py` — schema, migrations, indexes, Joplin property serialization,
   exact-source checks, and batch insert helpers.
4. `joplin2sql.py` / `sql2joplin.py` — authoritative Joplin RAW parsing and
   serialization behavior.
5. `obsidian2sql.py` / `sql2obsidian.py` / `obsidianmeta.py` — native Obsidian
   snapshots, preservation bundles, path restoration, attachment mappings, and
   metadata carried through `application_data`.
6. `obsidian2site.py`, `site_server/`, and `STATIC_SITE.md` — scalable
   Hugo/Ledger generation, canonical note URLs, disk-backed tags, server-side
   Bluge search, and the Pagefind static fallback. The migration from the
   Relearn theme is complete and archived as
   `plans/v3.36/000-ledger-migration-plan.md`; its decisions (M2, M3 and the
   rest) still explain several invariants below.
   `DEPLOY_VERCEL.md` and `DEPLOY_GITHUB_PAGES.md` document deployment, and
   carry the measured platform limits that decide which archives can be deployed
   where — do not restate those numbers elsewhere from memory.
7. `image_resources.py`, `images2resources.py`, and `quarantinelinks.py` —
   Markdown image parsing, network safety, reports, resources, and quarantine.
8. `notrios2sql.py` and `notrios_archive.py`, `notrios_links.py`,
   `notrios_mapping.py`, `notrios_receipt.py`, with `NOTRIOS_IMPORT_CONTRACT.md`
   and `NOTRIOS_IMPORT_DESIGN.md` — Notrios publication verification, link
   projection, row mapping and receipts. The plan that built them, and its
   evidence, is archived in `plans/v3.37/`.
9. `CHANGELOG.md` and `PERFORMANCE_REVIEW.md` — revision history and complexity
   decisions.

## Invariants

- Never discard unknown Joplin properties; `note_source_properties` is ordered
  and `note_source_raw` is authoritative when unchanged.
- Never use `str.splitlines()` to parse Joplin RAW property blocks; OCR metadata
  may contain control characters that Python treats as line separators.
- Native Obsidian exact bytes belong in `note_obsidian_*` columns and the
  namespaced `application_data` envelope, not in reconstructed YAML.
- Resource and item-ID collisions with different bytes are errors.
- Keep large-library paths batched, indexed, streaming, or bounded-memory.
- Static-site note titles must never be enumerated in the sidebar, or in
  `hugo.toml`. The Ledger sidebar is `partialCached` with no variant key, so it
  renders once per build; anything page-specific in it makes the build O(pages)
  in sidebar work.
- Every surface that can hold the whole archive must be bounded before
  `.Paginate`, not after: home and section pagers via `params.scale`, over-limit
  taxonomy terms via `taxonomyPageLimit`. Hugo generates a page for every pager
  it is handed, so capping only the links changes nothing.
- Generated word tags never become Hugo taxonomy terms. Explicit tags may; the
  count that reaches the taxonomy is capped. See decisions M2 and M3 in
  `plans/v3.36/000-ledger-migration-plan.md`.
- Generated word tags never reach `search-source.jsonl` either. `tag:` matches
  the tags written in a note, so it returns the same count as the tag archive
  and as Pagefind's filter — one query, one answer, on all three. They stay
  reachable as words and through the posting index. Step 46; putting them back
  in `tags` silently reintroduces a three-way disagreement no test outside
  `test_tag_searches_agree_with_the_tag_archive` would catch.
- Search query clauses are generated in exactly one place per side: the theme's
  `_partials/search-clause.html`, and its Python equivalent here. The grammar
  tokenises on whitespace, so a value containing a space must be quoted.
- Site-absolute URLs in generated templates go through the theme's
  `_partials/site-url.html`, never `relURL` directly: `relURL` drops the
  baseURL's path when its argument starts with a slash, which breaks every asset
  and link on a project site published under a subpath. URLs stored in the
  exact-tag index are site-root-relative and must be resolved against
  `config.siteRoot`.
- Bluge-only generated sites must not emit any browser search runtime. Keep
  `_validate_built_search_backend` and its regression together. It reads every
  built page, because the guarantee is that *none* references a browser index —
  so it is the one step whose cost scales with the whole site, and it must keep
  saying what it is doing. It reads bytes behind a substring test rather than
  decoding UTF-8 for two regexes, which is easy to undo by reaching for
  `read_text`. Worth 1.81× on a 177,682-page archive.
- Do not override theme layouts or partials to inject site CSS/JS: the theme
  reads `params.extraCSS` and `params.extraJS`. Overriding a theme partial
  duplicates code that will drift.
- Twitter-origin note detection controls article-heading/date suppression; do
  not infer it from the folder name. Use `movenotes-original-format` or Joplin
  source metadata.
- Canonical note URLs are generated by `obsidian2site.py` and must be reused in
  Hugo frontmatter, exact-tag documents, Pagefind results, and Bluge source rows.
  `_build_path_maps` and `_unique_output_path` decide them, so a change there is
  a change to every URL on the site: whatever it is for, prove the maps come out
  identical over a real vault before keeping it. `_slug_site_segment`,
  `_safe_segment` and `_safe_filename` are the rules those two apply, and their
  results are cached per directory — the cache must stay keyed by everything the
  result depends on.
- Bluge builds from `server/search-source.jsonl`; never parse or depend on
  Pagefind's private index format. Pagefind must run after Hugo and remains the
  static-hosting fallback. Exact generated-tag results come from the hashed
  posting index under `static/movenotes/`.
- Keep Python scripts standard-library-only. The generated optional site server is a separate Go module using Bluge.

## Keeping the search index current

The workspace search index lives in `.zvec-grep/`. It is generated local state,
not repository content. Keep `.zvec-grep/` in `.gitignore`, never force-add it,
and check `git ls-files .zvec-grep` before committing; it must return no paths.

Index discovery respects ignore rules by default, along with the stored file
selection and supported-file limits. Keep private notes, exports, databases and
generated output ignored where appropriate; merely leaving them uncommitted
does not exclude them from indexing. Preserve the existing selection and
embedding settings during routine refreshes.

After source or documentation changes, a branch switch, rebase, or substantial
generated-file changes, refresh the existing index from the repository root:

```bash
zg index
zg status --check-ready
```

`zg index` updates an existing index incrementally using its stored settings.
Routine incremental refreshes are part of keeping this workspace current.
`zg status` reports coverage, pending work and failures; `--check-ready` also
returns a nonzero exit status when the index is not ready. Do not assume a
background daemon has caught up after an inactive session.

For an individual query that must await refresh, use
`zg query "your question" --refresh wait`. For ordinary MCP searches, inspect
the returned `freshness` and `background_refresh` fields instead of adding a
status preflight to every search. Use sufficient current-index results while
a background refresh runs, as directed by the retrieval rules.

Creating a missing index, rebuilding with `--rebuild`, dropping with `--drop`,
or changing the embedding model or stored selection requires explicit user
authorization. Do not use those operations to handle an ordinary stale index.
See the [zg CLI guide](https://github.com/zvec-ai/zvec-grep/blob/main/docs/02-cli.md)
and [index maintenance guide](https://github.com/zvec-ai/zvec-grep/blob/main/docs/04-pipeline.md);
check `zg help index` for the installed version's options.

## Tests

The required gate is seven modules:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests/test_movenotes.py tests/test_image_resources.py \
  tests/test_obsidian2sql.py tests/test_obsidian2site.py tests/test_notrios2sql.py tests/test_notrios_7c.py tests/test_docs.py
```

A full gate adds the four modules that test the performance and comparison
harnesses in `scripts/`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests/test_notrios_c7c.py tests/test_notrios_p7a.py \
  tests/test_notrios_p7b.py tests/test_notrios_p7c.py
```

Run both before a release, and before completing a plan slice that changes
code. `tests/test_docs.py` runs `scripts/check_doc_links.py`, which refuses a relative
link in any document whose file or `#anchor` does not exist; a file moved
without updating the links to it fails there. `tests/test_notrios2sql.py` needs no Notrios binary: it reads the committed
publications under `testdata/notrios/`.

The scripts change often and the tests run them as subprocesses, so a
`__pycache__` left by an earlier run can shadow the edit under test — which
fails in a way that looks like a bug in the change rather than a stale
byte-code file. `.gitignore` keeps it out of commits; this keeps it from being
written at all.

**Both are needed, and `-B` alone is not enough.** `-B` is a command-line flag,
so it applies to the test process and not to the interpreters it spawns —
running the suite with `-B` still writes a `__pycache__`, of `common`,
`notesdb`, `constants` and the rest, imported by the scripts under test.
`PYTHONDONTWRITEBYTECODE` is an environment variable, so the subprocesses
inherit it.

Some environments intermittently stall when all subprocess-heavy notebook
filtering tests share one process; running test classes independently is an
accepted diagnostic, but every class and method must pass before release.

## Plans, the roadmap and the archive

Three places hold planning, and each holds one kind of fact:

| Place | The home for | Not here |
|---|---|---|
| `PLAN.md` | the plan being implemented: what each slice is for, its acceptance, and a dated log of what happened | what is left, in prose; that is generated from its ledger |
| `ROADMAP.md` | what each release is meant to do, and the deferred features with why they wait | per-slice status; that is the plan's |
| `plans/` | finished plans, verbatim, with their ledgers and working records | anything still being worked on |

**Keeping the plan current.** `PLAN.md` is a journal, and its ledger,
`docs/plan/ledger.json`, is authoritative for each slice's status, assignment and
execution record (see [Mandatory planned delegation](#mandatory-planned-delegation)).
When a slice starts or finishes, update the ledger first, then regenerate and
check the plan's generated sections, and commit them with the work:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/render_plan_ledger.py
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/render_plan_ledger.py --check
```

The slice's own section keeps its specification, and the dated log says what
happened and why. A finding that needs fixing becomes a slice in the plan,
rather than a note that it exists.

**Keeping the roadmap current.** The roadmap says what a release *means*, and
the plan says how far along it is. Keep that line, or the roadmap goes on
claiming work is next long after it finished.

- The roadmap carries no slice status. It names the release the active plan is
  for and points to `PLAN.md`.
- New work enters the roadmap when it enters the plan, under the release it is
  planned for. A deferred feature stays listed when it is planned, and moves
  under that release.
- Scope that moves between releases says where it came from and why, in the
  release it moved to.

**Archiving a plan.** When every slice of `PLAN.md` is complete, or moved on
with the user's agreement, archive it under the release it shipped in:

```text
plans/v<major>.<minor>/000-<slug>-plan.md
plans/v<major>.<minor>/<slug>-ledger.json
plans/v<major>.<minor>/<NNN>-<slug>.md
```

The plan is `000`, its ledger sits beside it with its `plan` field pointing at
the archived plan, and its working records (evidence, reviews, trial reports)
follow as `001`, `002`, … in the order their slices ran. Archive verbatim:
update only the paths to files that moved, so every link still resolves, and
`--check` still passes in place
(`scripts/render_plan_ledger.py --ledger plans/v<major>.<minor>/<slug>-ledger.json --check`).
Add the plan to `plans/README.md`, and release the version in `CHANGELOG.md`.

**Starting the next plan.** Write a new `PLAN.md` from `ROADMAP.md` and ask the
user before starting it. It needs the coding-agent assignment section and a
fresh `docs/plan/ledger.json` seeded with its slices, and it must point back to
this section, because these rules outlive any one plan.

## Repository layout and moved files

- Scripts and the modules they share are at the root, so `python3 -B
  joplin2sql.py` works from a checkout.
- `tests/` holds the `unittest` modules. They are run from the root by path
  (`python3 -B -m unittest tests/test_movenotes.py`), or by dotted name
  (`tests.test_notrios2sql.NotriosV1TitledTest`). The directory needs no
  `__init__.py`. Do not name it, or any directory at the root, after a
  standard-library module: a `unittest/` directory breaks the runner.
- `scripts/` holds development tools: trial harnesses, the ledger renderer, the
  link checker.
- `docs/` holds documentation.
- `plans/` holds finished plans.
- `testdata/` and `sample/` hold fixtures. Their notes are data whose bytes the
  tests pin. Never rewrite one to fix a link.

Move a file with `git mv`, and change every reference to it in the same commit:
Markdown links relative to each file's location, and bare mentions by their
repository-relative path. Archived plans included. `tests/test_docs.py` runs
`scripts/check_doc_links.py`, which refuses any relative link whose file or
`#anchor` does not exist. It also refuses a link that leaves the repository; link
to another repository on GitHub at a pinned commit instead.

## Mandatory planned delegation

### Coding-agent-specific assignments and session confirmation

Every current and future implementation plan MUST include a **Coding-agent
assignments and session confirmation** section and a structured execution
provenance ledger. Assignments are scoped to a coding agent such as `codex`,
`claude`, or `opencode`; worker names and model aliases are not portable across
those products. Record the coding agent, planned parent/worker, configured model,
reasoning effort, known availability constraints and billing route for each
assignment. Record unavailable metadata as `not exposed`, never infer it.

At the beginning of every implementation session, before changing implementation
files or spawning workers, the parent MUST:

1. Read the plan's assignments and compare them with this runtime's available
   worker roles, models and fixed/configurable effort levels.
2. Tell the user which coding agent is active, show the plan's parent/worker
   model and effort assignments, identify differences or unavailable roles, and
   distinguish configured values from runtime-reported metadata.
3. State the known subscription/API billing route, or say it is not exposed.
   A similarly named model in another coding agent may be unavailable or incur
   substantially different API costs; availability does not authorize that cost.
4. Ask whether those assignments and effort levels are current for this coding
   agent and session, or whether the plan must be updated first. Wait for an
   explicit answer before implementation or delegation. Record the answer and
   its scope; do not repeat this check within an unchanged, confirmed session.

A new session, coding-agent change, model/worker configuration change or billing
route change invalidates that confirmation. Conversation compaction alone does
not. A prior instruction to proceed with a slice does not confirm newly surfaced
assignment, effort or billing differences. Read-only inspection and requested
plan/AGENTS.md/provenance edits may proceed while confirmation is pending.
Do not silently substitute another worker, model, effort, API provider or parent
implementation. Propose the revised assignment, update the plan on approval,
and retain the previous assignment in its history.

The plan's section must contain the assignment table, pending/confirmed session
status and confirmation evidence, mismatch/billing notes, next-slice assignment,
and the location and regeneration/check commands for its provenance ledger.

Worker assignments in an approved implementation plan are binding execution
instructions, not suggestions.

If a plan assigns a slice or task to a named subagent such as `luna_worker`
or `terra_worker`, that assignment counts as an explicit instruction to use
subagent delegation.

Before performing implementation work for that slice, the parent agent MUST
spawn the assigned worker using the native collaboration tools.

The parent agent MUST NOT silently perform implementation assigned to a worker.

If the assigned worker cannot be spawned, is unavailable, or fails:
- stop implementation of that slice;
- report the delegation failure;
- update the plan with the failure or reassignment;
- do not fall back to parent-agent implementation unless explicitly instructed.

The parent agent may:
- decompose and clarify the task;
- provide context and acceptance criteria;
- review worker output;
- integrate results;
- perform final validation;
- update the plan.

Before marking a delegated slice complete, record:
- planned worker;
- actual worker;
- child thread ID;
- actual model;
- reasoning effort;
- work performed by the worker;
- work performed by the parent;
- validation performed;
- any delegation failure or reassignment.

When reporting session metadata for a slice, state:

- Product role (eg. Codex, Claude, Opencode, etc.)
- Underlying model family: the model family identified by the runtime, if available (eg. GPT-5)
- Model provider: only when the runtime identifies it (eg. openai)
- Product/client version: report only when explicitly exposed (eg. OpenAI Codex (v0.154.0))
- Configured model alias: report only when explicitly exposed (eg. gpt-5.6-luna)
- Configured model reasoning effort: report only when explicitly exposed (eg. medium)
- Never guess unavailable values; say “not exposed” instead. (eg. the runtime may only provide `underlying_model_family` for the session model but have more detailed information for configured agent workers (eg. configured_model, configured_reasoning_effort))

Use structured data for the information for each plan slice and generate the corresponding text in the plan from that structured data:

Record planned and actual execution separately for **every** slice, including
parent-owned slices. Preserve historical planned workers even when the parent
implemented the work. Required attribution fields are: Planned worker, Actual
worker, Child thread, Actual model, Reasoning effort, Worker contribution,
Parent, Parent reasoning effort, Parent contribution, Validation, and any
delegation failure or reassignment. Include coding-agent identity, status,
planned configured model/effort and evidence references in the structured data.
An actual model field requires execution evidence; a configured worker model is
not proof of the model that executed a child thread.

For confirmed parent-only execution, use `none` for worker execution fields.
For historical facts without evidence, use `unknown — not recorded` for each
affected field. For unstarted work, use `pending` and fill actual fields before
completion. A partially implemented slice records known contributions and failed
or incomplete validation without being marked complete. Never reconstruct child
use from a plan assignment or a commit's author name. Record explicit user
reassignments and distinguish them from historical deviations with no recorded
approval. The structured ledger is authoritative; regenerate its plan text and
check for drift before committing attribution updates or completing a slice.

Example:
```json
  {
    "id": "example-slice",
    "coding_agent": "codex",
    "planned_worker": "terra_worker",
    "configured_model": "gpt-5.6-terra",
    "configured_reasoning_effort": "medium",
    "delegation_required": true,
    "status": "pending",
    "actual_worker": "pending",
    "child_thread": "pending",
    "actual_model": "pending",
    "reasoning_effort": "pending",
    "worker_contribution": "pending",
    "parent": "pending",
    "parent_reasoning_effort": "pending",
    "parent_contribution": "pending",
    "validation": "pending",
    "delegation_failure_or_reassignment": "none recorded"
  }
```

The properties in the structured data will vary (eg. planned slice versus a completed slice).

Messages that you send to other agents and your final answer may be read
by a human, so ensure they are legible. Always put proper spaces between
words and/or numbers.
