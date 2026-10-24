# Plan: Import a Notrios publication handoff

Status: slices **1a–1d, 2a–2e, 3a–3d and 4a–4c complete**. The subsequent
collection-capabilities compatibility fix is committed as `cc4ec25`. Notes,
links, tags and resources are implemented, and the public import CLI is available.
Plan revised on **2026-09-13** for Notrios database schema **28**.
Schema-28 prerequisites **S28a and S28b are complete**. The importer declares
schema support **28**, with separately pinned producer fixtures and differential
evidence. The [vault/site tag review](NOTRIOS_TAG_REVIEW.md) is complete.
Resource slices **5a–5d are complete**. The
[resource safety review](NOTRIOS_RESOURCE_REVIEW.md) found no required runtime
change and adds full-import interruption and mutation evidence. All **246 tests**
passed at that milestone. Slice **6a is complete**: the staged receipt is
validated and the internal API exposes an allowlisted content-free summary.
Slice **6b is complete**: `notrios2sql.py --input SOURCE --output DESTINATION`
exposes verified publication and safe reruns. Slice **6c is complete**: explicit,
validated receipt sidecars preserve both digests outside notes and search inputs.
Slice **6d is complete**: CLI help explains output and exit codes, bounded phase
progress reports aggregate counts, and failure tests prevent premature success.
Slice **7a is complete**: current schema-28 and historical schema-27 publications
pass the offline importer CLI → SQLite → vault acceptance tests. All **262 tests**
passed at that milestone. Slice **7b is complete**: real Hugo/Ledger, Bluge and Pagefind
acceptance passed after a Ledger subpath fix (`85ac1b0`). See the
[live acceptance report](NOTRIOS_SITE_ACCEPTANCE.md). C7a and C7b are complete:
the frozen body/literal admission extension is implemented, all 264 regressions pass, old accepted outputs are byte-identical,
and the new three-note Hugo/Bluge flow passes. **C7c is complete**: the
[comparison and resume harness](NOTRIOS_C7C_EVIDENCE.md) accounts for all
382,206 source identities per recipe route, with zero unexplained source-to-route
body/metadata/title differences. Tag channels remain separate; route equivalence
and full 7c acceptance are not claimed. **P7a is complete**; see [performance evidence](NOTRIOS_PERFORMANCE_EVIDENCE.md).
**P7b is complete**; see [candidate evidence](NOTRIOS_P7B_EVIDENCE.md).
**P7c is complete**; its full-scale blocker, fresh-import ID lookups
that scanned the growing table, was fixed by **P7b2 (complete)**: the full
382,206-file recipe vault now imports in 1,628 s, where the interrupted baseline
ran 17,943 s without finishing. See [P7c evidence](NOTRIOS_P7C_EVIDENCE.md). The producer link-syntax
prerequisites came first: **S43a, S43b, S43c and E1 are complete**. S43a found two
downstream fixes, now planned as **S43c** and **E1**. **Resumed P7c ran its
whole frozen matrix** (R1–R6, all outputs identical). On 2026-10-23 the user
accepted F04 at full scale and removed the Go producer targets from the plan.
P7c found three fixes, planned as **U1**, **I1** and **M1**. **U1 is complete**:
an unchanged rerun now takes 0.47 (subset) and 0.52 (full vault) of the time it
did before. The user then added **V1** after M1: a damaged preservation bundle
becomes an error that prints the commands to run next. **I1 is complete**: an
import into an empty existing library takes 0.80 (10,000 files) and 0.67
(40,000 files) of the time it did. **M1 is complete**: the preservation
manifest is streamed both ways, so the full library's export peaks at 0.8 GiB
instead of 3.5 GiB and its preserved import at 0.5 GiB instead of 1.8 GiB,
with identical output. **V1 is complete**: a damaged preservation bundle is
refused before the output is touched, with the next steps printed as complete
commands, and exports record their source library in `.movenotes/export.json`.
Next is **resumed 7c**.
Plan revised on **2026-10-22**: all remaining work is assigned to the Claude Code
main model (**Main**), and the user confirmed this for the session. No Codex
worker or monitor remains in the plan. See
[Coding-agent assignments](#coding-agent-assignments-and-session-confirmation).
S43b and resumed 7c pin the released Notrios **`v1.0.0`** (`2aab9a8`). The
remaining order is resumed 7c → 7d → 7e.
Slice **7c remains incomplete**; isolated work
and checkpoints are under `/media/$USER/HD2/movenotes-7c-20260916/`.
Both recipe imports succeeded (382,206 documents each), but bounded real
conversions refused input and semantic comparison differed. Full real trials
remain skipped; see [partial trial evidence](NOTRIOS_CORPUS_TRIALS.md).
Compatibility prerequisites C7a–C7c and measured performance prerequisites
P7a–P7c precede resumed 7c. The performance investigation distinguishes Go
producer timings from Python importer review claims and adopts only measured
winners. Do not proceed to 7d until the outstanding acceptance gates are resolved.

The frozen admission checklist is
[NOTRIOS_IMPORT_CONTRACT.md](NOTRIOS_IMPORT_CONTRACT.md). It distinguishes
producer defaults from enforced consumer restrictions and records the pinned
producer's metadata, link-rewrite and CLI limitations.

The frozen implementation interfaces, projection rules and lifecycle are in
[NOTRIOS_IMPORT_DESIGN.md](NOTRIOS_IMPORT_DESIGN.md), with
[identity and projection vectors](testdata/notrios/design-v1.json). They specify
the initial Linux no-replace publication primitive, Markdown conversion limits,
token-aware final-path export and generated RAW title handling.

## Goal and scope

Implement a standard-library-only Python importer:

```text
Notrios publication_handoff → notrios2sql.py → notesdb.sqlite + resources/
                                            → sql2obsidian.py → obsidian2site.py
```

Notrios owns selection, privacy decisions, withheld-link rewriting and reviewed
publication. movenotes owns vault and site projections. This is not a restore,
backup or sync tool. Consumption must not require access to the source library,
fetch remote media, deploy a site, or execute note content.

Prefer the existing downstream pipeline, but do not promise that it needs no
changes: retained Notrios document links need an exporter mapping. Any required
exporter change must be narrow and covered by existing-format regressions.
Do not change canonical site path rules or theme layouts for this adapter.

## Reviewed sources and corrections

Original Notrios reference checkout: `~/projects/notrios`, commit
`bdecfeda00e582d5aa6170d15b37ba27c9656f1d`. This remains the provenance pin for
completed slices and existing fixtures. The schema-28 prerequisite work targets
`7662fdd5b55d6f34f14874f70ba6db9f9e7676ac` (clean local checkout inspected
2026-09-13); do not relabel historical evidence as generated by this newer pin.

- [Native format](../notrios/NATIVE_ARCHIVE_V2.md),
  [consumer contract](../notrios/contracts/archive-v2/README.md),
  [registry](../notrios/contracts/archive-v2/contract.json), schemas and fixtures.
  The external contract exists now; the deferred-contract paragraph in
  [publishing policy](../notrios/PUBLISHING_POLICY.md) is stale on that point.
- `internal/archivev2/format.go`, `records.go`, verifier/exporter and tests are
  the executable reference. `cmd/notriosctl/publish.go` and its tests define
  the reviewed-plan command sequence.
- [notesdb.py](notesdb.py), [joplin2sql.py](joplin2sql.py),
  [sql2joplin.py](sql2joplin.py), [obsidian2sql.py](obsidian2sql.py),
  [obsidianmeta.py](obsidianmeta.py), [sql2obsidian.py](sql2obsidian.py),
  and [cleanres.py](cleanres.py) define the destination contract. Read the
  repository orientation in [AGENTS.md](AGENTS.md) before implementation.
  [LEDGER_MIGRATION_PLAN.md](LEDGER_MIGRATION_PLAN.md) holds current site decisions.

Corrections to the original plan:

1. `commit_sha256` binds the semantic archive manifest. The reviewed planner
   digest is `snapshot.selection_manifest_sha256`; the planner calls its output
   `manifest_sha256`. Store both, with distinct meanings. Checksums are not
   signatures and do not independently prove a person approved publication.
2. Manifest index descriptors bind index chunks, which list records, blobs and
   optional pack containers. Index chunks do not list themselves. Fanout and
   pack layouts both exist.
3. The vault exporter selects by `joplin_type_`, requires `joplin_id`, and uses
   `joplin_parent_id`. Tags join through `joplin_note_id` and `joplin_tag_id`.
   Generic `note_*` columns alone are insufficient.
4. Resources are metadata rows plus exact files under `<output>/resources/`,
   not attachment bytes stored in `note_data`.
5. Publication tests preserve included document/resource URIs. Ignoring every
   `link` record would leave broken links. Translate included targets without
   reconsidering Notrios' privacy decisions or resurrecting withheld links.
   Slice 1a also found that stale rewrites may be skipped while their records
   are dropped; archive integrity cannot prove that all withheld links vanished.
6. Existing independent archive goldens include non-publication state. They
   are verifier positives but importer refusal cases. Generate a separate real
   publication fixture; changing a full archive's target is not equivalent.

## Admission and verification decisions

Initial release supports **loose archive-v2 publication handoffs only**. Refuse
full archives, subset transfers, archive-v1, physical SQLite snapshots and
unknown formats before accessing objects. No unsafe override is planned.
Reject required `objects.pack.v1` until a separate pack implementation is
verified; report that the caller must produce a loose publication. Do not claim
support for the entire Notrios `current-v2` reader profile while packs refuse.

Unknown required capabilities refuse; bounded unknown optional capabilities may
be ignored. Profile `movenotes-publication-loose-v1` now has schema support level 28:
require `12 <= minimum_schema_version <= 28` and
`minimum_schema_version <= source_schema_version <= maximum_schema_version`.
Do not treat `maximum_schema_version` as a future-reader ceiling. The contract
freezes exact field, capability and semantic admission rules.

Implement complete Python verification. The Notrios CLI is an independent test
oracle, not a required installed runtime dependency. JSON Schema alone is not
verification. Enforce strict JSON types, duplicate/unknown-field refusal,
finite numeric values, byte/depth limits while reading, final LF, ordered unique
index entries, exact fanout paths, regular files, no symlinks, no extra files or
unexpected directory shapes, all hashes, totals and typed counts. Empty valid
fanout directories are allowed, matching the pinned verifier. Registry limits
are ceilings, not allocation instructions. Refuse oversized input before materializing it.

Match Go's `ComputeCommitSHA256` semantic encoding, including field order,
defaults, omitted fields and escaping. Hashing original JSON bytes or using
Python `sort_keys=True` is not equivalent. Independent vectors must cover
Unicode, HTML-sensitive characters, optional fields and alternate input
whitespace/key ordering. Match legacy explicitly zero blob `record_counts`.

Use temporary indexed SQLite spools for objects, records, references and ID
maps. Stream hashing/copies and batch inserts by both row count and byte budget.
Avoid archive-wide body dictionaries, `fetchall()` and repeated index scans.
Verify revision ownership, references, collection membership, notebook cycles
and depth, semantic MIME/size consistency and unused blob descriptors. Shared
bytes may have different semantic MIME uses; descriptor MIME is a storage hint.

Also enforce the consumer publication projection: no deleted documents, extra
historical revisions, provenance, source bundles or saved searches, and empty
revision metadata/collection settings/link context. Producer opt-ins can include
provenance or source bundles; these still refuse. Resource metadata, revision
messages and relation anchor JSON are not automatically stripped by Notrios;
validate them but do not blindly project them into public outputs. The contract
defines the remaining field and retained-link restrictions. The target label
alone is not evidence of sanitization. Do not invent a private-tag filter that
changes the reviewed set.

## Output, identity and mapping decisions

Build the complete SQLite database and resources in a sibling staging directory.
Only publish the directory after full verification and conversion. Rehash bytes
at use, or consume immutable verified staged copies, to close the verification/
use gap. Rollback of SQLite alone does not undo copied resource files.

Initially require an absent destination, or recognize a complete identical
import as a no-op. Reject changed or unrelated existing destinations. Do not
replace them. Define destination reservation/recheck, stale-stage ownership and
interruption recovery in 1c; concurrent writers must not replace each other.
Cross-handoff merging and changed-note updates are deferred.

Generate deterministic 32-character lowercase hexadecimal Joplin-compatible IDs
from a versioned, unambiguous namespace containing Notrios `database_id`, record
kind and source identity. Relations use composite identity. Snapshot/replica IDs
and filenames must not affect identity. Freeze algorithm and vectors in 1c.
Retain the full source key to detect truncated-hash collisions. Same mapped ID
with different bytes/meaning is an error, not input to `removedups.py`.

| Source | Destination behavior |
|---|---|
| `collection` | Validate membership; keep minimal import bookkeeping. Do not copy arbitrary settings to frontmatter or invent collection folders. |
| `notebook` | FOLDER row, mapped `joplin_id`/parent, title and timestamps; matching generic aliases; actual hierarchy preserved. |
| `document` + current `revision` + body | NOTE row with complete Joplin fields, mapped notebook, revision title, document timestamps and `note_original_format='notrios'`. Validate decoding/MIME; explicitly refuse unsupported representations. |
| `tag` | TAG row with mapped ID and original name. |
| `document_tag` | NOTE_TAG row with its own deterministic ID, mapped `joplin_note_id`/`joplin_tag_id` and generic relation aliases. |
| `resource` + blob | RESOURCE metadata row and exact streamed file at `resources/<mapped-id>[.<extension>]`; canonical semantic MIME, size and safe extension. Source filenames never determine paths. |
| `document_resource` | Validate relation/reachability; preserve association and explicitly handle attachments with no inline body link. |
| retained `link` | Validate endpoints and UTF-8 byte offsets; translate included targets. Do not leak raw context/targets into frontmatter. |
| forbidden publication records | Refuse even when checksums are valid. |

Reuse generated ordered Joplin property conventions. Notrios JSON/body bytes
must not masquerade as original Joplin RAW or native Obsidian snapshots:
`note_source_raw` and `note_obsidian_*` stay empty for this source.

Link translation is a Main design gate. Resource targets become the
`:/<mapped-id>` form the existing resource rewriter recognizes. For note links,
choose a minimal exporter extension using its final deduplicated path mapping;
do not guess paths from titles in the importer. Freeze fragment, Unicode
byte-offset, overlap, code-span and unsupported-syntax behavior before assigning
implementation. Preserve external URLs and withheld plain text/redaction during
translation; never consult the source library to resolve a withheld target.
Normal vault export can remove leading titles and add trailing newlines; document
that behavior and use `--no-simplify-urls` for fidelity checks. This projection
is not a lossless Notrios backup round trip.

Store a versioned import receipt in namespaced `settings` entries: both digests,
snapshot/database IDs, target, supported contract/profile and mapper version.
Settings do not automatically reach a vault/site: 6c implements explicit
`--include-notrios-receipt` propagation to `.movenotes/notrios-receipt.json` in
the vault and `static/movenotes/notrios-receipt.json` in the site, excluded from
rendered notes and search. See the frozen propagation contract in the design. Do not propagate
source filesystem paths or arbitrary private metadata. An optional expected
reviewed digest compares against the selection digest, independently of archive
integrity verification.

## Coding-agent assignments and session confirmation

**Remaining work is scoped to `claude` (Claude Code, terminal CLI).** On
2026-10-22 the user reassigned every remaining slice to the main model:
"Rewrite the plan to use the main model for all work. The work-arounds used for
codex are not necessary for this terminal CLI." `Main` now means the Claude Code
parent for every slice that is not complete: S43a, S43b, P7b2, resumed P7c,
resumed 7c, 7d and 7e, and the later S43c and E1. No worker, subagent or auxiliary monitor is planned. A
Claude subagent is not a substitute for `luna_worker` or `terra_worker`. Use
one only if the user explicitly asks for it, and record a plan amendment first.

Completed slices keep their Codex history unchanged. In their rows, `Main` is the
Codex parent, `Luna` is `codex:luna_worker` and `Terra` is `codex:terra_worker`.
The slice tables name **planned** owners; the execution ledger below records who
actually did the work. The earlier Codex session, its confirmation evidence and
the superseded assignments stay in the ledger under `previous_sessions`,
`assignment_history` and each reassigned slice's own `assignment_history`. Scope,
dependencies and acceptance criteria are unchanged by this reassignment.

At the beginning of each implementation session, follow
[Mandatory planned delegation](AGENTS.md#mandatory-planned-delegation). Show the
user the active coding agent and this plan's parent model and effort, mark which
values are runtime-reported and which are configured, and state the billing route
or `not exposed`. Then ask whether these assignments are current for the session.
Wait for an explicit answer before implementation. Requested plan or provenance
edits and read-only inspection can proceed while confirmation is pending.

Confirmation applies only to the stated session, coding agent, model
configuration and billing route. Reconfirm when any of those changes;
compaction alone does not require repeating it. Never silently switch provider,
model or effort, or start delegating.

The following table is generated from
[NOTRIOS_IMPORT_EXECUTION.json](NOTRIOS_IMPORT_EXECUTION.json). The Claude Code
row is the current assignment. The Codex rows are history for completed slices.

<!-- NOTRIOS-ASSIGNMENTS:START -->
Session confirmation: **confirmed**.

2026-10-22 user, in the restarted Claude Code session: Yes, these assignments are current for this session. Answered after being shown the Claude Code parent as the only owner of remaining work, runtime-reported model claude-opus-5-5 from Anthropic, and configured alias, reasoning effort and billing route not exposed. Applies to this unchanged session; each slice still needs its own authorization. Earlier the same day the user directed the reassignment: Rewrite the plan to use the main model for all work. The work-arounds used for codex are not necessary for this terminal CLI.

| Coding agent | Execution owner | Configured model | Reasoning effort | Availability | Billing route |
|---|---|---|---|---|---|
| claude | parent | not exposed; runtime reports claude-opus-5-5 | not exposed | Main for all remaining slices; no workers planned | not exposed; assignments confirmed by user for this session |
| codex | parent | not exposed | not exposed | Historical: completed slices only; runtime reported GPT-6 family | not exposed; suitability was confirmed for the earlier Codex session |
| codex | luna_worker | gpt-5.6-luna | max | Historical: completed slices only; not assigned to remaining work | not exposed; suitability was confirmed for the earlier Codex session |
| codex | terra_worker | gpt-5.6-terra | medium | Historical: completed slices only; not assigned to remaining work | not exposed; suitability was confirmed for the earlier Codex session |

Runtime-reported parent family: **Claude Opus 5.5 (runtime-reported model ID claude-opus-5-5)**. Product/client version: not exposed; model provider: Anthropic (runtime-reported).

- All remaining work (resumed 7c, 7d and 7e) is planned for the Claude Code parent, called Main in the slice tables. No worker or subagent is planned.
- Codex luna_worker and terra_worker do not exist in Claude Code and are not replaced by Claude subagents. Spawning one requires an explicit user request and a recorded plan amendment first.
- The Codex auxiliary Luna monitor is retired for remaining work. Main runs long data-heavy commands as harness-tracked background commands, is re-invoked once when they exit, and does not poll.
- The runtime-reported model ID is not a configured alias. Reasoning effort, client version and billing route are not exposed.
- Completed slices keep their recorded Codex attribution. The earlier Codex session is under previous_sessions and its assignments under assignment_history.
<!-- NOTRIOS-ASSIGNMENTS:END -->

Next slice: **resumed 7c — large-corpus trials**, assigned to the Claude Code
parent (**Main**). Session assignments are confirmed. Slice authorization is
pending.

**Resumed P7c, complete (2026-10-23).** R1–R6 ran as frozen below; every
comparison is fingerprint-identical, and the five required modules and the
harness tests pass. See [the resumed results](NOTRIOS_P7C_EVIDENCE.md#resumed-p7c--f04-with-p7b2-constant-2026-102223).
The user decided the two open questions on 2026-10-23: "Remove the Go targets
from the plan ; Accept F04 at full scale." What they were decided on:

- *F04 at full scale.* F04 meets the adoption gate on the 10,000-file subset in
  all five alternating pairs (median fresh 0.834, unchanged 0.823, merge 1.000,
  memory +0.5%). R1's single gated fresh pair shows only 3.1%, against the
  frozen 5% gate; its unchanged pair shows 14.1% and its ungated fresh setup
  pair 19.7%. R2's RAW control, with identical code, moved −25% to +31%
  between single runs, so R1 cannot resolve 5%. Under the frozen gate the
  result is held as ambiguous. Options: accept F04 on the subset evidence plus
  three consistently faster full-scale timings; run more alternating
  full-corpus pairs (about an hour per pair per case); or remove F04 from
  `HEAD`. **Decided: accepted at full scale**, on the subset evidence and the
  three faster full-scale timings, so F04 stays in `HEAD`.
- *Go producer targets.* They were set against `notriosctl` timings at Notrios
  `7662fdd`, which is 290 commits before the `v1.0.0` pin and predates Notrios's
  own J17/J32 performance work. Resumed P7c ran only this repository's Python
  importers, so the targets were stale and unmeasured, not met or unmet.
  **Decided: removed from the plan**; see the adoption gates below.

The runs also found three fixes, planned below as U1, I1 and M1. U1's design
and acceptance are frozen in its row under
[the performance prerequisites](#performance-investigation-and-measured-adoption-before-resuming-7c).
The user confirmed the order U1 → I1 → M1 → resumed 7c on 2026-10-23.

*Before the resume (2026-10-22, kept as the frozen record):* P7c was
incomplete: its full Python native baseline was interrupted at
17,943.11s while executing unindexed batch-ID lookups. See
[P7c evidence and bounded handoff](NOTRIOS_P7C_EVIDENCE.md). **P7b2 / Main is
complete**: a new database gets `joplinididx` before the first batch, so every
lookup is indexed; C01/C02 and merge/rerun paths are unchanged. Resumed
**P7c / Main** must account for three P7b2 findings before running its matrix:
- F02 is subsumed: the index exists before any batch, so
  `notrios_p7c_prepare.py`'s F02 removal no longer changes behaviour. Every
  variant now holds the P7b2 treatment constant, and the F02 comparisons are
  historical. Re-scope the matrix to F04 with P7b2 constant before running it.
- The full-corpus fresh import peaks at about 757 MiB RSS, and an identical
  rerun costs 85% of a fresh import (1,388.56 s). Review both against the
  memory and unchanged-path targets.
- The private evidence volume now mounts at `/run/media/$USER/HD2`, not
  `/media/$USER/HD2`. Check recorded absolute paths before any `--resume`.

**Resumed P7c design (frozen 2026-10-22, before any run).** Earlier P7c
matrices are complete and are not rerun; this finishes the slice with the
P7b2 treatment held constant.

- *Variants:* `scripts/notrios_p7c_prepare.py` from `HEAD` with the `f0b218a`
  reference, as before. `_native_rows` is unchanged since `7aa9093`, so its F04
  inverse is exactly `HEAD` minus F04. Every variant keeps P7b2 and C01/C02;
  base and f02 now behave identically, as do f04 and both. The script records
  the P7b2 constant in `SOURCE_VARIANTS.json`. Comparisons are base versus f04.
- *R1, full native vault:* one alternating base/f04 pair, fresh and unchanged,
  over all 382,206 files (`f04-real-native`). This is F04's full-corpus
  confirmation and its full-scale memory check.
- *R2, full RAW control:* one alternating pair, fresh and unchanged, over the
  1,237,553-file recipe RAW (`raw-control-f04`). `joplin2sql.py` is identical
  in both variants, so this is the matched-condition RAW timing, a noise
  control and the Python vault/RAW ratio.
- *R3, real-subset small merge:* five alternating pairs over the 10,000-file
  recipe subset with the disjoint ten-note merge fixture (`f04-native`: fresh,
  unchanged, small merge). This rechecks the small-merge noise with P7b2 constant.
- *R4, full preserved route:* export R2's base fresh library with
  `sql2obsidian.py`, then import that bundle once with `HEAD`. This is a scale
  confirmation of P7b2 on the route F02 targeted, not a pair; the pre-P7b2
  baseline is the known quadratic path, and the handoff says not to repeat it.
- *R5, recovery:* interrupt a 40,000-file fresh import with SIGINT, check it
  leaves no rows, then rerun it and compare its fingerprint with an
  uninterrupted import.
- *R6, attribution:* one cProfile run of an unchanged 10,000-file rerun, kept
  separate from the timing runs, to explain why an unchanged rerun costs 85%
  of a fresh import.
- *Inputs:* synthetic RAW/preserved/media inputs from
  `movenotes-p7a-20260918-monitor` satisfy the harness's required arguments;
  the cases above read only the named corpora. Outputs go to new
  `/run/media/$USER/HD2/movenotes-p7c-20261022-*` roots, run sequentially with
  nothing else on the disk, batch size 500.
- *Gates:* the adoption gates below are unchanged. F04 is adopted at full scale
  only if R1 shows at least a 5% median improvement with no unexplained memory,
  disk, small-merge or RAW regression. *(Frozen text. R1 could not resolve 5%;
  the user accepted F04 at full scale on 2026-10-23. The Go producer targets
  this bullet also named were removed from the plan the same day.)*

F02/F04 subset gains and exact output comparisons are retained. F04 is adopted
at full scale by the user's decision; F02 is subsumed by P7b2. Rejected Go G08
stays out of full trials; no Go candidate is approved. Any producer implementation needs an explicit handoff naming its
files and checkout, plus the user's approval to write to the Notrios checkout.

Remaining sequence (U1, I1, M1 and V1 complete): resumed 7c → 7d → 7e, subject to the
unresolved compatibility gates. Every data-heavy
run follows the background-run rule under
[Execution and handoff rules](#execution-and-handoff-rules). Preserve C7c's documented differences: RAW's 842,813 tag
associations versus vault zero, RAW metadata projection omission, and 3,682
pinned title representations. The original bounded publications still encounter
unsupported link syntax in consumer conversion; verification/comparison does not
waive those refusals. Existing 7c ownership/history and Ledger `85ac1b0` remain
unchanged. See [C7c evidence](NOTRIOS_C7C_EVIDENCE.md).

## Execution and handoff rules

Every remaining slice is Main-owned, so no slice needs delegation. Main does the
design, implementation, review, validation and plan update itself. If the user
asks for a subagent, first amend this plan and the ledger with that slice's
planned worker, model and effort, and get the session confirmation again.
AGENTS.md's mandatory-delegation rules then apply to that slice. Do not spawn a
subagent only to find material in the workspace or to watch a run. Historical
worker assignments and their recorded deviations stay as they are. A historical
session restriction explains a deviation only where evidence records it. It is
not retroactive approval of a reassignment.

Freeze a slice's design decisions before implementing it, and record any newly
discovered design decision in the plan before acting on it. S43a follows the
link grammar frozen in 1c and amended by C7a; P7b2 follows the P7a/P7c handoff.

Work on **one slice at a time**. Before starting, write down the slice's inputs,
owned files, dependencies, excluded files and acceptance commands. Preserve
other people's edits in the working tree. Do not run overlapping writers against
shared data.

**Data-heavy runs.** This replaces the Codex Luna monitor, PIDFD notifier and
25-minute notification-wait workarounds for all remaining work. Prepare the full
sequential script, durable checkpoints, expected duration, stall threshold and
safe resume commands before a large run. Main launches the run as a
harness-tracked background command and is re-invoked once when it exits. Main
does not poll the process, re-read logs or start a status check while it runs. A
single diagnostic is allowed only after the recorded stall threshold has passed.
Each run still records its run ID, exit status, time, peak RSS, disk use, output
counts and hashes in its result directory. If the session ends or a usage limit
interrupts it, the durable result and checkpoints remain the source of truth.
Resume from them without repeating completed stages. Command output goes to log
files, so tool output is not needed as evidence.

Each slice ends with focused passing checks, a progress-log update identifying
the next item, and a coherent Git commit. Record unfinished work and exact
resume commands on interruption. Do not expose incomplete features through the
supported CLI or mark code complete before its acceptance checks pass. Keep
private data, generated libraries, SQLite databases and bulky evidence out of
Git. Use sanitized fixtures and aggregate measurements in committed evidence.

After completing and committing an item, ask the user whether to proceed to the
next item and stop until they answer. The user explicitly asked for this
per-item pause on 2026-09-05. It is unchanged by the 2026-10-22 reassignment.

Proposed files: `notrios_archive.py` for verification, `notrios2sql.py` for
mapping/CLI, `test_notrios2sql.py`, and `testdata/notrios/`. Module boundaries
and helper APIs were frozen in 1c.

## Structured execution provenance

[NOTRIOS_IMPORT_EXECUTION.json](NOTRIOS_IMPORT_EXECUTION.json) is authoritative
for planned assignments, session confirmation and actual execution records.
[render_notrios_execution.py](render_notrios_execution.py) renders the assignment
table and per-slice execution appendix, and checks coverage and planned-owner
agreement with the task tables:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B render_notrios_execution.py
PYTHONDONTWRITEBYTECODE=1 python3 -B render_notrios_execution.py --check
```

Update the structured data first, then regenerate the plan. Actual worker/model
and effort require execution evidence; role configuration alone does not prove
which model ran. Record child thread IDs from spawn results. Completed
parent-only work uses `none` for worker fields. Missing historical parent model
or effort is `unknown — not recorded`; unstarted actual fields are `pending`.
The historical parent-only attribution is supported by the conversation's
explicit no-worker report and available progress entries, not inferred from
worker labels or Git authors. No child use or precise historical backend model
is invented. Per-slice commit references and original progress reports retain
the detailed implementation and validation evidence.

Before completing a delegated slice, record planned worker, actual worker,
child thread, actual worker model/effort, worker contribution, parent identity
and effort, parent contribution, validation owner/results, and any delegation
failure or reassignment. For unavailable runtime metadata, record `not exposed`
and ask the user for client status/configuration or billing confirmation if
needed; user-supplied configuration remains labeled as such. The historical Codex
runtime exposed exact configured Luna/Terra role models and efforts, but only a
GPT-6 family label for the parent. The current Claude Code runtime reports the
parent model as Opus 5.5 (`claude-opus-5-5`) from Anthropic. It exposes no
configured alias, reasoning effort, client version or billing route. For a
Main-only slice, record worker fields as `none`. Record the parent as
`Claude Code`, with the runtime-reported model and family. Record the parent
reasoning effort as `not exposed` unless the runtime or the user states it.

## Step 1 — Freeze contract and fixtures

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 1a / Main — complete | Reviewed pinned schemas, verifier, producer and CLI; froze [consumer contract](NOTRIOS_IMPORT_CONTRACT.md). | None | All twelve payload field sets and twenty hard limits cross-checked; every refusal sourced or identified as consumer policy; loose-only admission and both digests confirmed. |
| 1b / Main — complete | Generated [synthetic publication fixture and reproduction evidence](testdata/notrios/README.md) using the clean pinned CLI's real import/plan/publish commands. | 1a | Production compatibility and verification passed; 3 notes, 3 resources, nested notebooks, duplicate titles, Unicode tags, 8 retained links, 3 rewritten links and zero skipped rewrites. Exact digests/bytes and excluded sentinels checked. |
| 1c / Main — complete | Froze [APIs, row/property mapping, conversion limits, identity, staging and link/attachment design](NOTRIOS_IMPORT_DESIGN.md), with [machine-readable vectors](testdata/notrios/design-v1.json). | 1b | 13 identity vectors checked with independent framing and system SHA-256; all 8 real-fixture link spans and 3 complete projected bodies checked; concrete later acceptance cases assigned. |
| 1d / Luna — complete | Added [offline fixture-copy/inventory/record helpers and baseline assertions](test_notrios2sql.py), plus [baseline and regeneration instructions](testdata/notrios/README.md). | 1c | Nine standard-library-only baseline tests pass using committed synthetic data; no producer invocation or runtime importer dependency. |

Use independently generated contract goldens as well as producer publications;
neither alone protects against the producer and consumer sharing a bug.

## Step 2 — Verify before conversion

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 2a / Main — complete | Added strict bounded JSON, immutable manifest model, Go-compatible canonicalization and declaration/target gates in [notrios_archive.py](notrios_archive.py). | 1d | Six independently generated Go serialization vectors; strict JSON/limit/type/schema/capability/target tests; manifest-only admission and refusals without object access. Full archive verification is not implied. |
| 2b / Main — complete | Added no-follow fanout reads, streamed checked copies, strict index/envelope checks and a temporary indexed SQLite spool behind `_stage_archive_objects`. | 2a | Missing/corrupt/truncated objects, invalid ordering/counts/paths, symlinks/special files and extras refuse with owned-state cleanup. Legacy zero blob counts/valid empty fanout directories pass; byte/row batch and copy limits tested. Record semantics remain for 2d. |
| 2c / Terra — complete | Added table-driven rehashed hostile inputs and exact byte-limit boundaries against the frozen APIs. Executed locally under the session delegation constraint. | 2b | Exact LF/CRLF index and record limits, UTF-8 MIME limits, capability bounds, integer/count shapes, malformed record JSON and index-chunk shadowing checked with specific refusals. Legacy zero blob counts remain accepted. |
| 2d / Main — complete | Added typed immutable records, indexed reference/blob joins, bounded notebook walks, publication gates, Go-compatible MIME normalization and the context-owned verifier API. | 2c | The real publication passes. Rehashed schema/identity/reference/tree/history/reachability/MIME failures assert specific refusals; 56 Go MIME vectors are frozen. Blob reads require authenticated EOF. |
| 2e / Main — complete | Completed the [pinned-verifier audit](NOTRIOS_VERIFIER_AUDIT.md), froze 47 differential cases and measured streaming behavior. Fixed failed-read state and file/directory handle lifetime. | 2d | Shared rules and deliberate consumer refusals agree with expectations. Source/private-copy mutations, authenticated EOF and OS descriptor cleanup tested; 8,004 tags and a 32 MiB blob verified with under 3 MiB of measured Python peak allocation. |

No import path becomes available before 2e. A packed archive must keep refusing
even if some files resemble loose objects.

## Step 3 — Notebooks and current notes

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 3a / Luna — complete | Implemented pure deterministic keys/IDs, all five complete row builders, ordered generated properties and the frozen resource suffix map in `notrios_mapping.py`. Executed locally under the session delegation constraint. | 2e | Frozen key/ID vectors, aliases/NULL defaults, numeric property types, empty/Unicode titles, timestamp flooring and notesdb round trips pass. Equal injected IDs retain distinct full keys for 3b collision refusal. |
| 3b / Main — complete | Added the internal staged importer, frozen conversion bounds, SQLite identity registry and byte-bounded row batches, completion inventory/receipt, verified reruns and Linux no-replace publication. Executed locally under the session delegation constraint. | 3a | Verification/insertion/copy/inventory/rename/fsync faults, competing writers, stale locks, ownership changes and altered completed outputs refuse without overwriting the destination. |
| 3c / Terra — complete | Validated the existing staged notebook/current-note writer with nine integration tests and real text-only vault export subprocesses. Executed locally under the session delegation constraint. | 3b | Exact counts, hierarchy, aliases, title/body/date projection, duplicate/empty titles, selected notebooks, empty bodies, notebook-only publications and bundle hashes pass; invalid parent/revision/body refuses before insertion. |
| 3d / Terra — complete | Implemented the bounded protected-token scanner, exact retained-link reconciliation, note/self/external projection and final-path exporter pass, plus generated RAW title handling. Executed locally under the session delegation constraint. | 3c | Duplicate titles, filtered links, fragments, injected first-write length fallback, finalized bundle hashes and generated RAW reimport pass; stale/missing/protected links and unsupported syntax refuse. |

This is a development milestone. Until Steps 4–6 complete, reject inputs needing
unfinished features rather than silently omitting data.

The internal library entry point now accepts resource-free archives with notes,
tags, note-tag memberships and validated note, self-anchor and HTTP(S) links. Its narrow Markdown grammar
protects code, requires retained records for active internal links, and refuses
ambiguous or unsupported active syntax. Resources and their association records
still refuse until their conversion slices are complete.
It checks every body/link before considering an existing-output no-op. Step 3c
verifies notebook/current-note integration and text-only vault export; 3d adds
matching-title heading retention, generated RAW title preludes, note-link
translation and round trips. Reimport can change duplicate-title suffix ordering;
each export resolves links against its own actual paths. Internal receipt/completion and
expected-selection checks implement the frozen 3b failure/no-op protocol; 6a/6b
still own the final summary and public CLI. Resource-write fault tests use a
synthetic staged file, not enabled archive-resource conversion. No CLI is exposed.

## Schema-28 prerequisites — before continuing Step 4

**State: S28a and S28b complete.** The consumer's supported database schema
level is 28; [current-producer evidence](testdata/notrios/schema28/README.md)
passes. No Notrios database migration or notesdb schema change was needed.

Evidence from the local producer comparison, original pin through the new pin:

- Commit `01367b5deb708e9bb0e798fd911893bc8dcb340f` introduces
  [0028_fts_rowid_map.sql](../notrios/internal/store/migrations/0028_fts_rowid_map.sql).
  It creates and backfills `documents_fts_rowid(document_id, fts_rowid)`, indexes
  `fts_rowid`, and sets SQLite `user_version=28`. This is a rebuildable private
  FTS lookup, not document, revision, resource, tag or sync payload state.
- The [registry](../notrios/contracts/archive-v2/contract.json) changes only
  `current_schema_version` from 27 to 28. Archive format remains
  `notrios-archive` version 2, contract schema version remains 1, and the minimum
  database schema remains 12. The record schemas, capabilities, hard limits,
  manifest encoding and compatibility evaluator are unchanged in this range.
  The physical-refusal fixture also changes; physical snapshots still refuse.
- [export.go](../notrios/internal/archivev2/export.go) declares source/maximum
  schema from the source database and minimum schema 12. Thus a normal new
  `source=28, minimum=12, maximum=28` handoff already passes the existing schema
  bounds gate. The required change is the declared reader support level and its
  boundary tests, not a new source-version ceiling or a relaxed verifier.
- The other portable-record change is omission of collection `capabilities`.
  [records.go](../notrios/internal/archivev2/records.go) still accepts legacy
  arrays; the exporter no longer writes them. Movenotes commit `cc4ec25` already
  accepts absence and validates present arrays. Keep that work and its tests.
  Correct stale prose claiming that the producer always retains this array.

Decisions for these slices: retain reader profile `movenotes-publication-loose-v1`,
mapper `movenotes-notrios-v1`, receipt version and contract schema version 1.
The schema-28 private index changes no mapped identity or projection rule, so
no output migration or receipt invalidation is planned. Preserve the original
schema-27 publication fixture, digest/MIME vectors and audit evidence verbatim;
add separately named schema-28 evidence with its own producer pin and digests.
Do not copy FTS tables or open/migrate a user's source database. Use sanitized,
isolated test data only. New producer fixtures must use real publication
commands, not a manifest-only version edit.

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| S28a / Main — complete | Update the schema support bound in `notrios_archive.py` to 28, the contract/design's current support declarations and relevant tests. Reconcile collection-field prose and record the new reference pin without rewriting historical provenance. | 4b and `cc4ec25` | Accept minimum 28 with valid source/maximum bounds; reject minimum 29, minimum below 12 and inverted bounds. Accept normal schema-28/minimum-12 manifests and future source/maximum values when their minimum is supported and all other gates pass. Keep unknown capability/field, pack and physical refusals, and optional/legacy collection-array validation. Original fixtures and identity vectors pass unchanged. |
| S28b / Main — complete | Add a separately pinned synthetic schema-28 publication fixture and reproducible compatibility/verifier evidence using the updated producer. Extend the differential audit and converter/no-op regression evidence as needed; update fixture documentation and this plan. | S28a | Current producer compatibility and full verification pass; Python fully verifies the new archive with omitted collection capabilities and still verifies the original schema-27 archive. A resource-free real publication converts through notes/tags/links and the vault pipeline; identical reruns remain no-ops. Resource-bearing fixtures verify but conversion continues to refuse until Step 5. Run focused boundary/collection tests, the differential audit against the new pin, and all five Python regression modules with both bytecode-suppression flags. Record exact commands, producer hash, digests and results. |

Each prerequisite is a separate reviewable commit under the existing per-slice
workflow. If fixture generation or the updated oracle reveals a semantic change
beyond this comparison, record the discrepancy and revise the affected contract
before admitting it. Resume 4c only after both prerequisites pass.

## Producer link-syntax prerequisites — titles in projected bodies

**State: not started.** Found 2026-09-26 while reviewing what in Notrios beyond
the schema-28 change affects this importer. Slices are named for the producer
item that caused them, `S43`, not for a schema level.

**What changed in the producer.** Notrios v1.0 J43 makes a rewrite carry a
link's title. Until it, the Obsidian importer built each rewritten link from the
display text and the resolved URI alone, so `[a](Target.md "A title")` was stored
as `[a](document://default/documents/doc_x)` and the title was gone from the
note. It is now stored as `[a](document://default/documents/doc_x "A title")`,
with the author's own delimiter — `"…"`, `'…'` or `(…)` — copied byte for byte.
`notriosctl fix` keeps titles for the same reason. The producer change is on
Notrios `develop` at `f4de470`; at the time of writing it is not yet pushed,
archived or released, so no pin is recorded here yet.

*Update 2026-10-22, verified against Git and GitHub.* Notrios is released.
The annotated tag `v1.0.0` points to
`2aab9a8fe7c1ba8e411cd6003a6115b09abd6b9a`. The GitHub release `v1.0.0` was
published, not as a draft, on 2026-10-22T16:47:30Z. J43's `f4de470` is an
ancestor of the tag. The clean local checkout's `main` is `5b91019`, the same as
`origin/main`. Its only commits after the tag are J10 release records and
performance/release scripts, with no producer source change. At the tag, the
registry declares `current_schema_version` 28 and the migrations end at
`0028_fts_rowid_map.sql`. Between the S28 pin `7662fdd` and the tag,
`contracts/` is unchanged. `internal/archivev2` changes only where the verifier,
export and restore spools are placed (J22's per-instance temp space); the
archive format is unchanged. **S43b pins Notrios `v1.0.0` /
`2aab9a8fe7c1ba8e411cd6003a6115b09abd6b9a`,** and resumed 7c uses the same pin.

**Why it blocks consumption.** `_INLINE` in `notrios_links.py` admits no
whitespace, parentheses, backslash or angle brackets in a destination and
requires the closing parenthesis immediately after it. A titled link therefore
does not tokenise; `scan_markdown` then finds an internal URI inside the literal
span and refuses. Verified against the current module:

| body | result |
|---|---|
| `[link](document://default/documents/doc_x "A title")` | **REFUSED** — unsupported or unaccounted active link syntax |
| `[link](document://default/documents/doc_x 'A title')` | **REFUSED** |
| `[link](document://default/documents/doc_x (A title))` | **REFUSED** |
| `![shot](resource://default/resources/res_y "Photo")` | **REFUSED** |
| `[link](document://default/documents/doc_x)` | 1 token, unchanged |

The refusal is fail-closed, so nothing is mis-projected and no wrong link is
published — but a handoff containing any titled link cannot be consumed at all.
`scan_markdown` is the shared chokepoint for conversion-time link accounting
(`notrios_links.py`), projection (`notrios_links.py`) and the vault projection in
`sql2obsidian.py`, so the refusal lands at the earliest gate rather than late.

**What needs no change, recorded so it is not re-investigated.** Three other
producer changes in the same range are neutral or favourable here:

- **J37** stopped the producer emitting `[[document://…]]` inside a Markdown
  target. That shape tokenised but could not validate, so it reached
  `unmapped internal link in projected note`. One fewer refusal, and no new
  syntax to admit.
- **J41** and **J42** made the producer resolve targets carrying balanced
  parentheses and angle-bracketed targets containing spaces. Those links now
  become canonical `document://` or `resource://` URIs, which are free of
  spaces, parentheses and brackets and tokenise today; before, they stayed as
  author text and refused. Fewer refusals, again with nothing to admit.
- **Unresolved** links still keep the author's bytes exactly as before, so a
  destination holding a space, parenthesis or angle bracket that the producer
  cannot resolve refuses exactly as it does now. That is pre-existing behaviour
  of this importer's narrow grammar, is not caused by any producer change, and is
  **not** admitted by this prerequisite.

**Link rows are unaffected.** The producer records a link's destination alone in
its stored rows, with a title never reaching the target — asserted in the
producer's own tests. Mapped identity, projection rules and receipts therefore do
not move, and no output migration or receipt invalidation is planned.

**Decisions for these slices.** Retain reader profile
`movenotes-publication-loose-v1`, mapper `movenotes-notrios-v1`, receipt version
and contract schema version 1. Admit exactly one new thing: an optional title
after an otherwise validated destination, preserved byte for byte in projected
output. Keep refusing every other destination character, keep the protected-code
and reference-ambiguity refusals, and do not change canonical site path rules or
theme layouts. Preserve the schema-27 and schema-28 fixtures, digest/MIME vectors
and audit evidence verbatim; add separately named evidence with its own producer
pin and digests. New producer fixtures must use real publication commands, not a
hand-edited body.

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| S43a / Main — complete | Admit an optional title in the link grammar and carry it through projection unchanged. The destination itself keeps today's character set; the title is copied, never parsed or normalised, because the producer copies it and three delimiters are legal. Update the contract/design declarations and the link-grammar tests. | S28b | All four titled forms above tokenise, with the destination and fragment identical to the untitled case and the title preserved byte for byte in projected bodies. A link with no title projects byte for byte as it does today. Destinations containing a space, parenthesis, backslash or angle bracket still refuse when there is no title to explain them. Protected code, reference-ambiguity and unmapped-internal refusals are unchanged. Existing fixtures and identity vectors pass unchanged. |
| S43b / Main — complete | Add a separately pinned publication fixture whose notes carry titled internal links, produced by a real publication command from the released producer, Notrios `v1.0.0` (`2aab9a8fe7c1ba8e411cd6003a6115b09abd6b9a`, contains J43), and record its pin and digests. Extend the differential audit and the converter/no-op regression evidence. | S43a | The new archive verifies and converts through notes/tags/links and the vault pipeline; identical reruns remain no-ops. Titles survive into the vault projection. The schema-27 and schema-28 archives still verify and convert unchanged. Run the focused grammar/boundary tests, the differential audit against the new pin, and all Python regression modules with both bytecode-suppression flags. Record exact commands, producer hash, digests and results. |

**Ordering.** This is a consumption blocker for any handoff produced after J43,
so it comes before further Step 4 work on a post-J43 producer. A handoff produced
before J43 is unaffected and needs no change, which is why the existing fixtures
stay valid and stay pinned.

*Decided 2026-10-22:* the remaining order is S43a → S43b → P7b2 → resumed P7c →
resumed 7c → 7d → 7e. *Amended the same day, after S43a:* S43c and E1 come
after S43b and before P7b2. S43c changes `obsidian2sql.py`, which P7b2 also
changes, so P7b2's benchmarks then measure final code. E1 must land before any
7c rerun or 7d recipe repeats an import after an export. S43 and P7b2 share no code or data. P7b2 changes the
movenotes Python importers' ID lookups; S43 changes the Notrios link grammar and
adds a fixture. S43 goes first because it is small and fixes the producer pin
that resumed 7c needs. It also lets the bounded real publications be
regenerated from the release before the multi-hour P7c and 7c runs. Resumed 7c
and 7d now depend on S43b. A v1.0.0 handoff can carry titled links, which
refuse without S43a. 7c's trials use that release, as decided below. 7d's
documented publication → import → vault → site recipe must work with the
released producer.

**Fixes found during S43a (2026-10-22).** Both are planned work, not just
recorded findings. Each needs its design frozen here before implementation.

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| S43c / Main — complete | Carry link titles through the downstream tools that S43a does not own (scope extended by the frozen design below to `common.py`, `cleanres.py` and `sql2obsidian.py`). `obsidian2sql._normalise_target` splits a title only when the target does not start with `./` or `../`. The vault exporter writes `../` for notes in other folders, so a titled cross-folder link from a Notrios export stays unresolved on native reimport, where the untitled link resolves. When it does resolve a link, it writes `[display](:/id)` and drops the title. `obsidian2site` keeps titles on external links but drops them on resolved note and asset links. Fix both to split exactly one delimited title the way S43a's grammar does, and write it back after the rewritten destination. Owns `obsidian2sql.py`, `obsidian2site.py` and their tests. | S43b | Titled `./`, `../` and bare relative note and attachment links resolve on native reimport exactly as their untitled forms do, with the title bytes kept after the `:/id` destination. Site output keeps titles on resolved note and asset links. Untitled links and all canonical URLs, path maps and theme layouts are byte-identical; prove the URL maps unchanged over a real vault, as AGENTS.md requires. Undelimited suffixes are left as they are today. Focused tests plus all five regression modules. |
| E1 / Main — complete | Stop exporters modifying the database they read. `notesdb.connect()` runs `PRAGMA journal_mode=WAL`, so `sql2obsidian.py` or `sql2joplin.py` run on a completed Notrios import rewrites `notesdb.sqlite`: header bytes 18–19 change from `01 01` to `02 02` and the change counter advances. A later identical `notrios2sql.py` rerun then refuses with `completed payload inventory differs`, and the documented import → vault recipe cannot be repeated. Before implementation, decide between opening read-only when no migration is needed and an explicit read-only flag; migrating an older database in place must stay as it is for other workflows. Owns `notesdb.py` (a narrow read-only open path), the two exporters' open calls and tests. | S43a finding | After a vault export and a Joplin export of a completed import, the import directory is byte-identical, an identical rerun reports `unchanged`, and no `-wal` or `-shm` file is left behind. Older databases that need migration still migrate, with that existing behaviour covered by a regression test. Exporter output is unchanged. Focused tests plus all five regression modules. |

**S43c design, frozen 2026-10-22 before implementation.** Reading the code
found a third consumer that the original S43c row did not name.
`common.RESOURCE_LINK_RE` admits no title, and `cleanres.py` builds its set of
referenced resources from it. So `cleanres.py` deletes a resource file whose only
references are titled, such as `![x](:/id "Photo")`. That is data loss. S43a made
it reachable for Notrios imports, which now keep titled image embeds, and it was
already possible for Joplin notes. The same regex is why `sql2obsidian.py`
leaves a titled resource link in an ordinary note unconverted. S43c therefore
owns `common.py`, `cleanres.py` and `sql2obsidian.py` as well. Decisions:

1. **One title grammar.** Use the grammar S43a froze for `notrios_links.py`, as a
   `str` pattern in `common.py`: spaces or tabs, then one `"…"`, `'…'` or
   `(…)` on one line with no backslash, backtick or closing delimiter inside,
   then optional spaces or tabs. Anything else is not a title.
2. **`common.RESOURCE_LINK_RE`** accepts that optional title after `:/<id>`, and
   `get_resource_links` keeps its return shape. `cleanres.py` then counts
   titled references. `sql2obsidian.rewrite_resource_links` writes the title
   back after the rebuilt path. Following S43a's exporter rule, a titled image
   becomes a Markdown image rather than an `![[name]]` wiki embed; untitled
   output is unchanged.
3. **`obsidian2sql` native reimport.** The Markdown link pattern tries a titled
   form first: a destination without spaces or parentheses, or an `<…>`
   destination, followed by a title. It falls back to today's pattern
   unchanged. A resolved titled link becomes `[display](:/id<title>)`; an
   unresolved one keeps its bytes. Untitled links take today's path, so their
   output cannot change, and that includes the existing quoted-title stripping
   in `_normalise_target`.
4. **`obsidian2site`.** For a resolved note or asset link, append the existing
   `_split_markdown_destination` suffix only when it is exactly one title under
   decision 1. Otherwise keep today's output, which drops the suffix. External
   links already keep theirs. No path map, canonical URL, template or theme
   change is involved.
5. **Proof that nothing else moves.** Generate the site from a deterministic,
   bounded subset of the real recipe vault before and after the change; the
   whole vault has no titled links, so the outputs must be byte-identical. Also
   compare `sql2obsidian` and `obsidian2site` output for the S43b vault, where
   only titled links may differ.

**E1 design, frozen 2026-10-22 before implementation.** The user chose
automatic read-only opening when no migration is needed. A probe of SQLite
3.46.1 refined how. A `mode=ro` connection to a rollback-journal database
(which a completed Notrios import is) reads, refuses writes and leaves nothing
behind. To a WAL-mode database, the kind `joplin2sql.py` and `obsidian2sql.py`
write, it leaves `-wal` and `-shm` files it cannot remove. A read-write
connection with `PRAGMA query_only=ON` on a WAL database also refuses writes,
leaves the bytes unchanged and removes both files on close. Decisions:

1. Add `notesdb.open_database_for_reading(path, prog)`. It reads the SQLite
   header's write-version byte, then opens a rollback-journal database with
   `mode=ro`, or a WAL database read-write with `query_only=ON`. Neither changes
   the journal mode.
2. It checks, without writing, whether `migrate_database` would change
   anything: an older `db_version`, a missing column or a missing shared index.
   If so, or if the read-only open fails (for example on a hot journal), it
   closes that connection and returns `open_database` instead, so migration and
   recovery behave exactly as they do today.
3. `sql2obsidian.py` and `sql2joplin.py` call it; they only read. Other tools,
   which write, keep `open_database`.

**No other remaining producer work affects this importer.** The producer's open
items at the time of writing are a reimport skip (J39), a reader affordance for
ambiguous links (J40) and release documentation and the release itself (J9, J10).
The first two change producer-internal behaviour and a reader UI, not the handoff
format; the last two move the producer pin without changing it. If J39 ships a
rule version that invalidates stored import state, that is internal to the
producer's own reimport path and does not reach a publication handoff.

*Update 2026-10-22 — no producer schema change.* J39 is complete. On
2026-10-20, before any code was written, its owner decided against the planned
schema addition. The skip redefines the Obsidian note fingerprint in
`import_item_states` and adds no column. A schema-29 column would also have broken
sync with schema-28 builds. So the registry stays at `current_schema_version` 28,
and the support level, admission bounds, receipts and identity vectors in S28a
need no change. Even a future source/maximum schema 29 with minimum 12 would
pass the existing gate, as S28a's acceptance already tests. Items J44–J50
landed after this review: search sidecar indexers, web dependency advisories,
preview wiki embeds and attachments, and release-set contents. Their titles
point to producer-internal, UI or release work. The archive contract and format
are verified unchanged through `v1.0.0` (see the update above). S43b's
differential audit and fixture comparison against the release confirm
handoff-level behaviour, including any body changes from importer work.

## Step 4 — Tags

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 4a / Luna — complete | Added streamed TAG/NOTE_TAG insertion using the frozen builders and indexed ID lookups, with type-count, alias and membership-target checks before publication. Executed locally under the session delegation constraint. | 3d | `load_note_tags` returns the fixture's four sorted tag titles across the correct six memberships; bounded batches, unattached tags, unchanged reruns and injected finalization failures pass. |
| 4b / Luna — complete | Added Unicode, whitespace, quoting, duplicate-name and multiple-membership round trips through the actual vault importer/exporter, plus eleven rehashed invalid-relation cases. Executed locally under the session delegation constraint. | 4a | YAML tag text survives reimport; the default bundle preserves distinct source tag IDs and duplicate-name memberships; malformed/duplicate identities refuse during verification. |
| 4c / Main — complete | Reviewed [vault/site tag semantics](NOTRIOS_TAG_REVIEW.md), added real-publication integration coverage and corrected the superseded M2 search description. | 4b, S28b | Written tags survive vault export; default and capped site generation keep generated words out of taxonomy/search-source tags while retaining their postings. The explicit-tag cap exception is documented. No runtime changes needed. |

## Step 5 — Resources and attachments

Slice 5a implements storage inside `_build_payload`: verified resource records
become RESOURCE rows after note-tag memberships, and `_copy_resource` writes
opaque bytes via `VerifiedArchive.open_blob` with bounded reads, explicit
size/SHA-256 checks, exclusive creation and file fsync. Storage paths use mapped
IDs and frozen MIME extensions, never source filenames. A repeated source
resource is copied once; different IDs sharing bytes remain separate resources.
The owned stage and completion inventory retain the existing cleanup/publication
contract. `notrios_document_resources` uses the frozen `relation_id` spelling.
Slice 5b populates every mapped association, validates inline resource targets
against the owning note's relations, and appends the frozen deterministic list
for relation-only resources. Existing completed outputs are not migrated.

The 5b implementation removes the temporary resource admission gate. Vault
export uses protected active tokens, actual note paths and required resource
copies. Preservation-bundle reimport retains attachment presentation paths in
the dedicated Obsidian column; exact snapshots retain their bytes while their
active mapped resources are copied. Storage tests still isolate low-level copy
failures; projection tests exercise full publication and vault round trips.
The public importer CLI is available as of slice 6b.

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 5a / Terra — complete | Connected the frozen resource row builder to bounded authenticated copies, exclusive mapped-ID filenames and staged item counts. Corrected the reserved relation table column to `relation_id`. Executed locally under the session delegation constraint. | 4c | Exact hashes/sizes and metadata, tiny read/batch bounds, safe display names, extensionless names, empty bytes, distinct IDs sharing bytes, collisions and read/write/fsync cleanup pass. Resource admission remains gated until 5b projects links/attachments. |
| 5b / Terra — complete | Translated retained resource links and implemented relation-only attachment behavior frozen by Main in 1c. Assigned worker completed inherited parent work, including exact snapshot attachment restoration. | 5a | Images/files resolve from nested notes; shared bytes with differing semantic MIME work; withheld resources absent; Main reviews the mapping. |
| 5c / Terra — complete | Added attachment regressions with independent byte comparisons and bounded fixture generation; no runtime change needed. | 5b | Duplicate filenames, Unicode/escaping, zero-byte and large streamed files; exact attachment bytes. |
| 5d / Main — complete | Reviewed reachability, rehash-at-use and interrupted-copy recovery in [the resource review](NOTRIOS_RESOURCE_REVIEW.md), with three additional full-import regressions. No runtime change required. | 5c | No writes outside staging or overwrites; failure cannot expose partial completed output. |

Do not run `cleanres.py` during import. Its Markdown-reference rule could remove
a relation-only attachment; the adapter must resolve that representation.

## Step 6 — Receipt and public CLI

Target refusal is mandatory in 2a, not deferred to this step.

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 6a / Luna — complete | Validated the existing versioned settings receipt in staging and added the allowlisted `ImportResult.summary()` API after successful publication. | 5d | Both digests correct; failed imports have no success receipt. |
| 6b / Main — complete | Finalized `--input`/`--output` CLI, reviewed-selection digest checking, JSON success stdout, stderr diagnostics, identical completed reruns and conflicting-output refusal. | 6a | Digest mismatch/changed source refuse; same import is safe; no unsafe override. |
| 6c / Main — complete | Specify and implement explicit receipt propagation to vault/site outside notes/indexes. | 6b | Both digests traceable; no claim that settings propagate automatically; no source-path leakage. |
| 6d / Terra — complete | Help/errors/progress and CLI subprocess tests against Main's finalized CLI contract. | 6c | Consistent `--input`/`--output`, phase/count progress, nonzero errors and no success on partial output. |

## Step 7 — End-to-end acceptance and documentation

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 7a / Terra — complete | Small offline publication-fixture → SQLite → vault regression with independent expectations. | 6d | Notes/tags/links, exact attachments, absence of excluded sentinels and receipt assertions pass. |
| 7b / Main — complete | Actual local Hugo/Ledger + Bluge build and bounded Pagefind fixture; test search/subpath URLs. | 7a | Canonical URLs, links, attachments, explicit tag counts and backend isolation correct; excluded sentinel absent from publishable files/index sources. |
| 7c / Main | Resume after C7a–C7c and P7a–P7c; large-corpus trials below; record time/RSS/disk/counts/hashes and failure recovery. Partial Codex execution is retained; remaining work is Claude Code Main. Resumed trials use the Notrios `v1.0.0` pin. | P7c, S43b, E1, U1, I1, M1, V1 | Importer bounds demonstrated; stage bottlenecks separated; no unmeasured whole-pipeline memory claim. |
| 7d / Main | README script list/usage and CHANGELOG from measured accepted commands. The CHANGELOG also records S43c's generic fixes: `cleanres.py` no longer deletes resources referenced only by titled links, and native vault reimport no longer leaves a stray `)` or an unresolved titled link. It also records E1: `sql2obsidian.py` and `sql2joplin.py` no longer rewrite the database they read, P7b2's bounded fresh-import lookups, F04's faster native inventory and, if adopted, U1's faster unchanged reruns, I1's faster recovery after an interrupted fresh import, M1's bounded preservation-manifest memory and V1's refusal of a damaged preservation bundle, with its recovery commands and `--ignore-preservation`. Reassigned from Codex Luna on 2026-10-22. | 7c, S43b, S43c, E1, U1, I1, M1, V1 | Reproducible publication → import → vault → site recipe; loose/fresh-output limitations; no private content in public examples. |
| 7e / Main | Full regression gate, evidence/diff review, final status and commit. | 7d | Every required method passes; skipped integrations not counted as acceptance. |

### Compatibility prerequisites added after partial 7c trials

Revision authorized by the user on 2026-09-17. The successful producer imports
are reusable evidence: each recipe library has 382,206 documents. Preserve the
original 7c results and failed attempts; new slices do not retroactively change
its planned owner or turn refusals/skips into passes. The current design remains
binding until C7a explicitly revises it. No new producer/schema pin is implied.

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| C7a / Main — complete | Diagnose real-body refusals and source/import differences; amend NOTRIOS_IMPORT_DESIGN.md and specify independent sanitized fixtures, comparison rules and mapper/version consequences. | Partial 7c evidence | Completed in NOTRIOS_COMPATIBILITY_REVIEW.md and the amended design: non-NUL body controls, narrow literal brackets, unchanged mapper/receipts conditional on identical old outputs, source-path comparison and explicit retained refusals. |
| C7b / Terra — complete | Implemented only the C7a-approved body/link compatibility changes in notrios2sql.py, notrios_links.py and focused test_notrios2sql.py fixtures/tests; dependent serializer/exporter changes require Main's explicit scoped handoff. | C7a | 264 regressions pass; immutable fixture payloads and reruns are byte-identical to baseline; independent three-note CLI/vault/Hugo/Bluge validation passes. Original bounded conversions still refuse unsupported link syntax; no notes filtered. Main reviewed. |
| C7c / Luna — complete | Implemented disk-backed semantic comparisons, verified publication cohorts, indexed duplicate-sensitive joins, checkpoint/resume and PIDFD notification scripts with bounded query deadlines. | C7b | All 382,206 source identities per route accounted for; zero unexplained source-to-route differences under documented rules; tags remain explicitly separate, route equivalence false. Full corpus terminal notification, measured RSS, focused/scale/recovery checks and Main review recorded in NOTRIOS_C7C_EVIDENCE.md. |

**Monitoring for data-heavy slices.** *Historical, C7a–P7c under Codex:* the
user required a low-usage method for that work. A Codex `luna_worker`
(configured `gpt-5.6-luna`, fixed `max`) ran each harness and blocked on OS
completion or a PIDFD. It notified the parent once, and the parent waited on
native notifications with a 25-minute timeout. Those runs, and their recorded
auxiliary assignments, stay in the ledger as they are.

*From 2026-10-22, all remaining work:* that workaround is retired, as the user
directed, because Claude Code's own background commands supply the completion
notification. Resumed P7c, resumed 7c and any later data-heavy slice follow the
background-run rule under [Execution and handoff rules](#execution-and-handoff-rules).
The low-usage goal still holds: no frequent process polling and no repeated log
reads. Durable checkpoints, the recorded run ID, the expected duration, the stall
threshold and safe resume commands are prepared before every large run. They
survive usage-limit interruptions. Do not run overlapping writers against shared
data.

**C7a decisions to make before implementation:**

- Audit bounded examples plus streaming aggregate counts of refused body forms.
  Both recipe samples contain U+0014; distinguish actual C0 characters, a leading
  BOM, and controls in link destinations. Establish which stage introduced each
  form using source → producer → publication evidence. Check exact preservation
  through Python/SQLite/Joplin RAW/Obsidian and safe renderer/search behavior.
  Prefer preserving admitted body bytes; do not remove controls globally or
  weaken URL/target validation. If a form cannot be represented faithfully,
  document its explicit refusal and the remaining acceptance limitation.
- Distinguish literal bracketed prose (including observed annotations) from
  inline links, reference definitions/uses, shortcut references, wiki syntax and
  malformed/ambiguous constructs. Account for reference definitions across the
  whole note before treating a bracket pair as prose. Retain protected-code
  rules, complete internal-link accounting, withheld-target constraints, exact
  UTF-8 byte spans, overlap checks and fail-closed ambiguous internal targets.
  Specify the supported subset; do not promise a complete Markdown parser.
- Use sanitized independently expected fixtures for accepted prose and controls,
  with negative cases for hidden/unrecorded internal targets, reference syntax,
  malformed destinations, control-bearing URLs and changed/stale link spans.
  Preserve original bytes outside approved destination replacements and the
  established relation-only suffix. Do not edit immutable historical fixtures.
- Decide whether admitted syntax/output changes require a mapper/receipt version
  update. Check old completed outputs, no-op detection, source digests and output
  inventories; do not reuse an old completion marker as evidence for new code.
- Define recipe semantics from actual source/import metadata. Both sampled
  producer bodies retain YAML; initial whole-body hash differences therefore
  are not a completed semantic comparison. Identify only proven frontmatter
  envelopes and their fields using existing supported parsing rules; preserve
  unknown or ambiguous blocks and do not split at arbitrary `---` separators.
  Separate recipe text, title, tags and provenance metadata. Reconcile RAW tag
  relations, YAML tags and vault tags explicitly; retain the existing NFC/LF
  normalization only where justified. Compare duplicate-sensitive multisets or
  groups keyed by independently validated source identity; titles alone are not
  unique keys. Report missing/extra/ambiguous groups and field-level mismatches,
  including explained source/import/privacy differences, without excluding rows
  merely because they differ. Require zero unexplained differences before
  declaring equivalence; known differences require quantified acceptance limits.

**Resume and measurement contract (C7c → 7c):**

- Reuse the completed pinned producer libraries and read-only sources for
  compatibility work. P7a–P7c authorize separate disposable baseline/candidate
  imports when required for controlled performance experiments; those must not
  overwrite existing acceptance libraries. Recipe
  imports use the pinned CLI maximum batch size 500. Outside those recorded experiments, reingestion is justified only by a
  demonstrated producer/import defect and a recorded pin/input change.
  *Decided 2026-10-22:* resumed 7c moves to the released Notrios `v1.0.0`
  (`2aab9a8fe7c1ba8e411cd6003a6115b09abd6b9a`). Both conditions hold. The pin
  change is recorded in the S43 section. The producer defects fixed since
  `7662fdd` are demonstrated in the producer's own plan: J37, J41 and J42 link
  resolution, and J43 dropped titles. They change the bodies a handoff carries.
  So resumed 7c re-imports the three corpora into fresh libraries with the release
  and regenerates the bounded publications. It then reruns the C7c comparison
  harness on the new libraries. The `7662fdd` libraries, C7c's accepted v6
  results and the partial 7c evidence are kept, not overwritten. C7c's
  documented differences must be re-established, not assumed. Check the release
  CLI's import flags and batch limit from its own help before reusing 500.
- Bind each new checkpoint to input inventories/digests, producer and consumer
  revisions (or working-tree hashes), mapper version, arguments and profile
  digest. Reuse only matching successful upstream stages. Preserve old attempts;
  changed conversion code invalidates conversion and dependent exports/builds,
  while comparison-rule changes invalidate comparison results. Use fresh output
  paths for corrected attempts. An aggregate must distinguish historical runs
  from the current attempt and never report an older passing regression as the
  result of a newer failing run.
- Keep a sequential executable harness with bounded disk checks, stage exit
  codes, time/RSS, output counts/hashes and conversion phase callbacks. Main
  launches it as a harness-tracked background command and is re-invoked once
  when it exits. Use the estimated run duration as the stall threshold for a single
  diagnostic, and avoid repeated process polling. After a reconnect, resume from
  the durable checkpoints rather than re-attaching to the old process.
- Rerun all three bounded conversions and downstream gates first, then full real
  trials. Measure producer/Python verification, conversion, vault export, site
  generation, Hugo and Bluge separately. Compare real attachment bytes and exact
  reachable sets; resource-free synthetic checks cannot satisfy this gate.
  Refused notes cannot be filtered out to manufacture an acceptance pass.
- Preserve the corrected receipt-test invariant: complete search-source record
  multisets match despite parallel completion order, duplicates included; other
  deterministic artifacts remain exact. Run the full five-module regression
  gate with both bytecode controls after final changes, plus recovery and small
  live-site checks affected by compatibility changes. Retain old failures.
- Main records actual execution evidence (Main-only for remaining work) in the structured ledger,
  reviews comparisons and stage evidence, and marks 7c complete only when its
  outstanding gates pass. If a refusal remains intentional, explicitly revise
  the acceptance scope with the user; do not count skipped full integrations as
  passed. 7d and 7e remain downstream of completed 7c.

**Resumed 7c design (frozen 2026-10-23, before any run).** The user
authorized resumed 7c ("Start it") and chose its work volume the same day:
"Internal disk". HD2 had 52 GB free, against an estimated 70–90 GB, and the
internal disk 538 GB.

- **Inputs.**
  - Producer: Notrios `v1.0.0` (`2aab9a8`). The binary is S43b's build, SHA-256
    `b4f368a9…e55c` and Go build `vcs.revision=2aab9a8`, copied into the work
    root and checked before every stage.
  - Consumer: this repository at the commit that adds the harness. Every stage
    records the hashes of the Python files it runs.
  - The three corpora under
    [Corpus and measurement procedure](#corpus-and-measurement-procedure),
    read-only.
  - Release help and source were checked before reuse. Import batches are
    still 1–500 (`cmd/notriosctl/main.go`). The publish commands accept the
    `--profiles` and `--target publication_handoff` forms S43b ran. Recipe
    imports use `--batch-size 500`; Joplin uses the default of 100, as before.
- **Work root.** `~/movenotes-work/7c-20261023`, mode 700, outside every
  source tree and this repository. It is not indexed and never committed.
  - The `7662fdd` libraries on HD2 and C7c's results are kept and not read for
    acceptance. C7c's accepted v6 run lived under `/tmp` and no longer exists,
    so the comparison is rerun, as the contract requires.
- **Harness.** `scripts/notrios_7c_trials.py`, sequential, with no private
  path in its code; every path is an argument. It carries the earlier private
  harness forward:
  - per-stage `checkpoint.json`, GNU time, logs, disk before and after, and
    aggregate output counts, bytes and digests;
  - the conversion phase log;
  - archived failed attempts.

  Each checkpoint is bound to a fingerprint: argv, producer binary hash,
  consumer file hashes, and input digests (the source inventory or the
  upstream stage's output digest). A completed stage is reused only when its
  fingerprint matches. Otherwise it runs into a fresh path, and the old
  attempt is kept.
- **Phases.** Each runs as one harness-tracked background command.
  1. *Producer:* source inventories, then fresh imports of the Joplin, recipe
     RAW and recipe vault libraries.
  2. *Bounded:* for each route, the first 1,000 documents by ID, with link
     action `plain_text`. The stages are profile, plan (asserting no source
     bundles), publish, producer verify, Python verify, conversion, vault
     export (`--include-notrios-receipt --no-simplify-urls`), the attachment
     check (exact bytes and reachable sets, archive → database → vault), site
     generation (Ledger, Bluge), Hugo and the Bluge index. Then a live-site
     check and the recovery trial.
     - *Live-site check:* serve each bounded site with the generated server on
       loopback. `/api/health` and `/` answer 200. A `tag:` query returns
       exactly the number of `search-source.jsonl` rows carrying that tag. A
       returned URL answers 200.
     - *Recovery trial:* on the bounded Joplin archive, which has real
       attachments, kill the conversion after its payload is built. A rerun
       must refuse the stale lock. Clean up only after checking ownership.
       A fresh rerun must match the bounded conversion's output digest, and
       an unchanged rerun must leave it unchanged.
  3. *Full:* the same stages over every document, all notebooks plus unfiled
     documents. Each route's full tier is gated on its bounded tier.
  4. *Comparison:* `notrios_c7c.py` on the new recipe libraries and the three
     bounded publications, with C7c's v6 rules.
  5. *Regression:* the five-module gate with both bytecode controls, plus the
     harness tests.
- **Durations and stall thresholds.**
  - The `7662fdd` producer imports took 1,568 s, 7,246 s and 17,142 s on HD2.
    Phase 1's stall threshold is their sum doubled, 52,000 s.
  - Phase 2 is expected to take minutes; its threshold is 3,600 s.
  - Phase 3's threshold is set from phase 2's per-1,000-document stage times,
    scaled to the full counts and doubled, and recorded before launch.
  - Phase 4 is expected to take about 90 minutes, with a 3,600 s per-query
    limit; its threshold is 4 h.
  - Under the background-run rule, a single diagnostic is allowed only after a
    threshold passes.
- **Acceptance.**
  - Every stage exits 0, or a refusal is recorded with its aggregate
    diagnostic and the route's dependent stages are recorded as skipped.
    Refused notes are never filtered out. A refusal that remains blocks 7c
    until the user revises its scope.
  - Each full plan selects every document.
  - Attachment bytes and reachable sets are exact on every route that has
    resources.
  - Conversion RSS and phase times at bounded and full scale are recorded
    side by side. Only measured bounds are claimed, per stage, with no
    whole-pipeline memory claim.
  - The comparison accounts for all 382,206 identities per route, with zero
    unexplained source-to-route differences. C7c's documented differences are
    re-established and quantified against its accepted figures: the separate
    tag channel, the RAW metadata projection and the 3,682 pinned titles. Any
    change from those figures is explained by a producer change between
    `7662fdd` and `v1.0.0`.
  - The live-site and recovery checks pass.
  - The regression gate passes after the final change.
- **Owned files.** `scripts/notrios_7c_trials.py`, `test_notrios_7c.py`, the
  resumed section of `NOTRIOS_CORPUS_TRIALS.md`, this plan and its ledger.
  Importer, exporter and site code is excluded. A defect found there is
  recorded here as a fix before any change, as before.

### Performance investigation and measured adoption before resuming 7c

Added at the user's request on 2026-09-17. Read both supplied reviews:

- [Union Alpha review](~/prompts/movenotes-v3-performance-review-union-alpha.md),
  sections 1–6, including its proposed code, estimates and correctness gates.
- [Grok 4.6 review](~/prompts/movenotes-v3-performance-review-grok4.6.md),
  both overlapping finding lists; deduplicate repeated claims without losing
  findings unique to either review.
- [Existing measured performance review](PERFORMANCE_REVIEW.md) provides prior
  Python baselines and rejected settings, not a baseline for the Notrios producer.

**Identify the measured executable first.** The 382,206-document timings were
`/tmp/movenotes-s28b-notriosctl import joplin-raw` (7,245.65 s) and
`... import obsidian` (17,142.24 s), both recipe batch size 500 and pinned producer
revision `7662fdd5b55d6f34f14874f70ba6db9f9e7676ac`. The observed vault/RAW ratio is
about 2.37, with a 9,896.59 s wall-time gap. These are Go Notrios ingestion
measurements, not runs of `joplin2sql.py` or `obsidian2sql.py`. The supplied reviews
primarily concern the latter Python paths. Investigate both tracks, but attribute
improvements to the executable/stage actually tested. Equal document counts do
not imply equal source bytes, metadata, links, SQL work or filesystem operations.
Historical runs are observations, not controlled speedup baselines.
*These timings no longer set any target: the user removed the Go producer
targets on 2026-10-23 (see the adoption gates below).*

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| P7a / Main | Audit every review claim against pinned/current code; trace the actual producer and Python paths, profile representative imports, freeze benchmark protocol and candidate handoffs in a sanitized performance evidence document. | C7c | Each finding classified with source and measurement evidence; dominant contributors to the observed gap identified or explicitly unresolved; baseline and candidate scope separated by executable. |
| P7b / Terra | Implement isolated, profile-supported candidates approved by P7a, with focused correctness/performance regressions. Own only explicitly handed-off importer/helpers/tests; use a separate bounded candidate per experiment. | P7a | Each candidate preserves invariants and has a reproducible baseline comparison; ineffective/regressing candidates are rejected, not bundled into production. Main reviews before promotion. |
| P7b2 / Main — complete | Bound fresh-import ID lookups before each batch; preserve collision/rollback semantics and compare complete import cost. Own Python importer, narrowly needed database helper, tests and candidate harness only. Reassigned from Codex Terra on 2026-10-22. | P7c scale finding | Representative fresh/unchanged/merge checks pass; no growing-table scan per batch; measured candidate ready for resumed P7c. |
| P7c / Main — complete | Execute the frozen sequential benchmark matrix, full-corpus confirmation and final regression/recovery commands; prepare aggregate findings dispositions and reproducible scripts. Partial Codex Luna execution is retained; remaining work reassigned to Main on 2026-10-22. | P7b; P7b2 for scale-blocker resume | Repeatable performance improvement demonstrated for each adopted change; paired route times, resources and correctness evidence reported. Main proposes adoption; the user decided F04 and removed the Go targets on 2026-10-23. |

P7a and P7b are complete under their recorded Codex assignments. P7b2 is
complete under Claude Code Main, and so is the remaining P7c work. Their data-heavy runs follow the
background-run rule in [Execution and handoff rules](#execution-and-handoff-rules).
They need no auxiliary monitor, and Main does not poll for progress.

**Fix found during resumed P7c (2026-10-22).** Planned work, not just a
recorded finding, at the user's direction. Its design is frozen here before
implementation.

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| U1 / Main — complete | Skip unchanged native vault files before converting them. R6's profile of an unchanged 10,000-file rerun (58.3 s under cProfile) spends 31.6 s building rows that are then skipped: two frontmatter parses per file (13.1 s), link rewriting (3.2 s), compressed application data (3.1 s) and JSON encoding. That is why an unchanged full-corpus rerun costs 85% of a fresh import. `_insert_rows` decides "unchanged" from the item ID and the SHA-256 of the file's raw bytes alone. The ID is already known after the inventory pass (the frontmatter `joplin-properties` id, or the path-derived ID), so the same decision can be made from a batched lookup of `(ID, raw digest)` before conversion. Owns `obsidian2sql.py`, tests and a candidate harness. | P7c | An identical rerun and a merge into an existing library produce databases fingerprint-identical to the current code, with the same inserted/skipped counts and the same collision errors (changed bytes under an existing ID still refuse). Tag and note-tag rows of skipped notes stay exactly as they are; the design must show they need no regeneration, or regenerate them cheaply. Fresh imports are unaffected. Measured with paired alternating runs: the unchanged rerun improves by at least the 5% adoption gate on the 10,000-file subset and in one full-corpus pair, with no fresh, small-merge or memory regression. The preserved-bundle and RAW unchanged paths are checked against R2 and R4; extending U1 to them needs its own measured evidence. Focused tests plus all five regression modules. |

*Order (decided 2026-10-22, when U1 was added):* U1 comes after resumed P7c
and before resumed 7c. It changes `obsidian2sql.py`, so landing it during
P7c's frozen matrix would invalidate that matrix's comparisons. Landing it
before 7c means 7c's full-corpus trials, which include unchanged reruns,
measure the final code. 7c and 7d now also depend on U1, and 7d's CHANGELOG
records it if it is adopted.

*U1 result (2026-10-23).* Adopted. Paired alternating runs against `9c25e2a`
are fingerprint-identical throughout. The unchanged rerun's median time is 0.472
of the previous code's on five 10,000-file pairs and 0.524 in the full-vault
pair (983.03 s to 515.14 s). Fresh imports are not slower (subset median 0.938;
one ungated full-vault run 1.042, within the single-run noise R2 showed), and
the ten-note merge differs by 0.02 s on 0.55 s. Fresh imports peak about 2 MB
(subset, +4.0%) to 6 MB (full vault, +0.8%) higher, because one batch of notes
is read ahead of the batch being inserted; that bound does not grow with the
vault. U1's acceptance said "no memory regression", so the increase was put to
the user, who accepted U1 as measured. RAW imports and preserved-bundle items
run unchanged code, so R2 and R4 stand for them. Details in the
[P7c evidence](NOTRIOS_P7C_EVIDENCE.md#u1--unchanged-notes-skipped-before-conversion-2026-10-23).

**Fixes found by resumed P7c's R4 and R5 (2026-10-23).** Planned work at the
user's standing direction, with designs frozen here before implementation.

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| I1 / Main — complete | Defer secondary indexes when importing into an existing library that holds no notes. R5 showed the cost: an interrupted fresh import correctly leaves an empty library, but `open_database` → `migrate_database` → `ensure_indexes` then creates all eight indexes before the rerun's first insert, while a new database defers all but `joplinididx` to the final pass. Fresh imports into an empty existing library took 33.71 and 33.90 s against 28.98 and 28.96 s into a new one at 10,000 files, and 181.23 and 180.50 s against 123.27 and 121.47 s (48% slower) at 40,000 files, with identical fingerprints. When `obsidian2sql.py` finds the notes table empty, it drops the secondary indexes other than `joplinididx` before inserting and rebuilds them in the final pass. An interruption then leaves an index-free empty library, whose next open recreates the indexes as now. Owns `obsidian2sql.py`, at most a narrowly needed `notesdb.py` helper, and tests. `joplin2sql.py`'s same path is measured and extended only with its own evidence. | P7c | A fresh import into an empty existing library, and the rerun after an interrupted fresh import, are fingerprint-identical to a fresh import into a new database and end with the same index set. Non-empty libraries keep today's path unchanged. Measured with alternating pairs at 10,000 and 40,000 files: the empty-library import improves by at least the 5% gate, with no regression for new databases, unchanged reruns or merges. A test checks the index set after an interrupted and recovered import. Focused tests plus all five regression modules. |
| M1 / Main — complete | Bound the preservation manifest's memory. R4's full-scale round trip peaked at 3,668,096 KiB in `sql2obsidian.py` and 1,936,788 KiB in `obsidian2sql.py`'s preserved import, both from holding the whole `.movenotes/manifest.json` (530 MB, 1,237,553 items): the exporter keeps every item dict and then the complete `json.dumps` string, and the importer `json.loads` the file. The exporter will stream the manifest, writing each item as it is produced, byte-identical to today's output, with no format change. The importer will read version-1 manifests with a stdlib-only incremental decoder (`json.JSONDecoder.raw_decode` over buffered reads), keeping only the compact per-item fields it uses. A malformed or unrecognised manifest keeps today's behaviour: `_load_manifest` ignores it and the vault imports as native. Whether that silent fallback should become an error is a separate question for the user, not part of M1. Owns `sql2obsidian.py`, `obsidian2sql.py`'s manifest reader and tests. | P7c | Exported manifests are byte-identical to the current code's on the existing fixtures and on R4's library. Preserved imports are fingerprint-identical, with the same counts and errors, including for existing manifests. Peak RSS of the full-scale export and preserved import falls measurably, with time not worse beyond the gate's noise. Memory stays O(items) only for compact per-item state the importer needs, which the design documents. Measured on R4's full library plus a paired subset. Focused tests plus all five regression modules. |

*I1 result (2026-10-23).* Adopted. `obsidian2sql.py` drops every index but
`joplinididx` when the library it opens holds no rows (new helper
`notesdb.drop_deferred_indexes`); the final pass rebuilds them. Alternating
base/I1 pairs against `902bad2`: the empty-library import's median time is
0.799 of base at 10,000 files (five pairs, 0.761–0.874) and 0.667 at 40,000
(three pairs, 0.533–0.670), fingerprint-identical to a fresh import into a new
database and ending with the same nine indexes. A real SIGINT 60 s into a
40,000-file import left no rows and only `joplinididx`; the rerun took 140.41 s
and matched the new-database fingerprint and index set. For new databases,
unchanged reruns and merges the medians were 1.020 and 1.025 (fresh, 10,000 and
40,000 files), 1.041 (unchanged) and 0.930 (merge), inside each case's pair
spread (0.966–1.041, 0.991–1.029, 0.908–1.101, 0.889–1.000). I1 runs the same
statements there plus one `SELECT 1 FROM notes LIMIT 1`, so these are noise,
not a regression. Peak RSS is unchanged. `joplin2sql.py` is not changed. Details
in the [P7c evidence](NOTRIOS_P7C_EVIDENCE.md#i1--empty-existing-library-imported-like-a-new-one-2026-10-23).

*M1 result (2026-10-23).* Adopted. `sql2obsidian.py` writes the manifest
through `_ManifestWriter`, 1,024 items per encode, byte-identical to the
previous `json.dumps`. An encode per item rebuilt the indenting encoder each
time and cost 8 s on R4's manifest, so batches replaced it. `obsidian2sql.py`
reads it with `_JsonReader` (`raw_decode` per value over 1 MiB reads) into a
compact `_Manifest`: item count, RAW paths, resource IDs, and each note's ID,
vault path and digest. A malformed manifest still means a native import until
V1. Against `4dec69b`, every output is identical: manifests, whole vaults,
import fingerprints and summary lines, and R4's old-code manifest imports to
R4's fingerprint. Peak RSS falls to 0.279 (40,000-file export), 0.393 (its
preserved import), 0.225 (full export, 3,637,316 → 816,632 KiB) and 0.266
(full preserved import, 1,936,876 → 515,968 KiB). Paired times move both ways
(0.932–1.099), inside the gate's noise. Timed alone on R4's manifest, the final
writer is not slower than `json.dumps` (24.9 against 26.2 s), and the reader
costs about 4 s more than `json.loads` (25.4 against 21.7 s), 0.2% of the
import. The reader matched a `json.loads` reference in 140,000 fuzzed
comparisons. Details in the [P7c evidence](NOTRIOS_P7C_EVIDENCE.md#m1--preservation-manifest-streamed-both-ways-2026-10-23).

*Order (proposed 2026-10-23; the user answered "Yes to the I1 and M1 order"
the same day):* resumed P7c → U1 → I1 → M1 → resumed 7c → 7d → 7e. U1 and I1 both change `obsidian2sql.py`'s
native path, so they land one at a time, each with its own measurement.
M1 changes the preserved route, which resumed 7c measures at full scale. All
three precede 7c so that 7c measures the final code.

**Damaged preservation bundles (added 2026-10-23).** The user decided that a
malformed manifest becomes an error, that the slice follows M1, and that the
error's next steps use actual paths wherever they are known, with a labelled
suggestion where a path depends on how the user's files are organised and a
placeholder only where nothing better is possible. The same day the user added
that the exporter records the source database's path in the bundle, so the
re-export step needs no placeholder, with a path under the user's home
directory written as `~/…` so that no user name is recorded. They then
extended this to other paths: a path segment equal to the user name (`$USER`)
is recorded as `$USER`, as in `/run/media/$USER/HD2/…`.

| Slice / planned owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| V1 / Main — complete | Refuse a damaged preservation bundle instead of importing the vault as native, and print the commands to run next. Today `_load_manifest` returns `None` for invalid JSON, a non-object or a wrong `format`, never checks `version`, and `obsidian2sql.py` then imports the vault as plain Obsidian and reports success, dropping the non-note items, unknown properties and RAW bytes the bundle exists to keep. `sql2obsidian.py` writes the manifest last and not atomically, so an interrupted export leaves a vault that looks complete. **Design.** (1) A bundle is present when `.movenotes/manifest.json` or `.movenotes/joplin-raw/` exists. `obsidian2sql.py` checks it before creating or migrating the output database, so a refusal writes nothing. It refuses: invalid JSON, giving line, column, byte offset and file size, and saying that a file ending mid-document is what an interrupted export leaves; a non-object or another `format`; a `version` other than 1, naming it and saying this release reads version 1 and movenotes needs updating; `items` that is not a list (already an error, now with next steps); and `joplin-raw/` with no manifest. (2) Each refusal exits nonzero, says nothing was imported, and lists the applicable next steps as complete commands: restore `manifest.json` from a backup and rerun the original command; import the RAW copy with `joplin2sql.py --input <vault>/.movenotes/joplin-raw --output <same output>`, lossless for the export but without Obsidian edits made since (offered only when `joplin-raw/` exists); import as a plain vault with the original command plus `--ignore-preservation`, keeping edits but dropping Joplin-only items and properties; or re-export from the source database (`mkdir`, `sql2obsidian.py`, then `obsidian2sql.py` on the new vault with the same output), without edits made since the export. (3) Commands use actual paths and options. The original command is `sys.orig_argv`: interpreter, its flags, the script path as invoked and every option. The other scripts run with the same interpreter and flags, from the running script's directory. Every argument is quoted with `shlex`. A path that depends on how the user's files are organised gets a concrete suggestion labelled as one: the re-export directory is a new sibling `<vault name>-reexport`, with a numeric suffix if that exists, marked "suggested; any new empty directory works". The re-export uses the bundle's export record (see 5): its recorded source database and its original `sql2obsidian.py` options (`--notebooks`, `--no-frontmatter`, `--no-simplify-urls`, `--include-notrios-receipt`), so the new export matches the old one. A recorded `~/…` path is expanded with the importer's own home directory, and a recorded `$USER` segment with the importer's own user name, so the printed command holds a concrete path. If that directory does not exist or holds no `notesdb.sqlite`, the path is still printed, labelled "recorded when the vault was exported; not found here". A placeholder remains only for vaults exported before V1, which have no export record, or whose record is unreadable: a named placeholder with a line saying what it is (the directory given to `sql2obsidian.py --input`, which holds `notesdb.sqlite`). Values from the record are only printed, shell-quoted, and never run, since a vault can come from someone else. (4) New `obsidian2sql.py --ignore-preservation` imports as a native vault even when a bundle is present, valid or not; `.movenotes/` stays excluded from the native walk, as now. (5) `sql2obsidian.py` writes a small export record, `.movenotes/export.json` (its own `format` and `version` 1), before anything else in the bundle, so even an interrupted export has one. It holds the source database directory and the export options. No user name is recorded. A path under the exporter's home directory (`Path.home()`, from `$HOME`) is written as `~/` plus the relative part. In any other path, each whole segment equal to the user name (`$USER`, falling back to `getpass.getuser()`) is written as `$USER`, as in `/run/media/$USER/HD2/library`; a segment that only contains the name, such as `<name>-backup`, is kept. The record lists which substitutions it applied, so a real path that happens to start with `~` or contain a `$USER` segment is not expanded by mistake. Paths in the recorded export options get the same treatment. The record is a new file: the manifest's bytes and format are unchanged. `sql2obsidian.py` then writes the manifest to a temporary file in `.movenotes/`, fsyncs it and renames it into place, so an interrupted export leaves no manifest (refused as a bundle without one) instead of a truncated file. It lands on M1's streamed writer. (6) README documents the refusal, the recovery commands and `--ignore-preservation`. Not in V1: moving a re-exported bundle into an edited vault, which would need proof that it reproduces the original bundle. Owns `obsidian2sql.py`'s bundle check and messages, `sql2obsidian.py`'s export record and manifest write, the README section and tests. | M1 | Every refusal case has a test checking the nonzero exit, that nothing is written to a new or an existing library, and the exact message. The printed commands are run as printed, from a fixture whose paths contain spaces: the RAW-copy and `--ignore-preservation` commands succeed, the original command succeeds after the manifest is restored, and the re-export commands succeed as printed, with the recorded source database and options. The export record's tests check that a source under `$HOME` is recorded as `~/…` and that neither the home path nor the user name appears in the record; that a source outside the home directory is recorded with each segment equal to the user name as `$USER`, a segment merely containing it kept, and no other change; that the record holds the user name nowhere; that `~/…` and `$USER` records printed under a different `$HOME` and `$USER` expand to that home and user; that a path really starting with `~` or holding a literal `$USER` segment round-trips unchanged; and that a vault with no export record, or an unreadable one, gets the labelled placeholder. Valid version-1 bundles import fingerprint-identically to today, with the same counts and errors; native vaults are unchanged. An export interrupted before the rename leaves no `manifest.json`, and completed manifests are byte-identical to M1's. Focused tests plus all five regression modules. No timing change is expected; the check runs once per import. |

*Order (decided 2026-10-23):* M1 → V1 → resumed 7c. V1 changes the same
manifest writer and reader as M1, so it builds on M1's streamed versions instead
of the code M1 replaces. It precedes 7c, which runs the preserved route, and 7d
records it in the CHANGELOG.

*V1 result (2026-10-23).* Adopted, with the amendment below.

- **Refusal.** `obsidian2sql.py` checks the bundle before it touches the
  output and refuses all eleven damaged forms tested, against a new and an
  existing library alike, writing nothing to either. The error states the
  reason, that nothing was imported, and the applicable next steps as
  complete, shell-quoted commands built from the failing command line. Every
  printed command was run as printed and succeeded, from a fixture whose paths
  contain spaces. The re-export reproduced the original vault byte for byte,
  with its recorded `--notebooks` and `--no-frontmatter`.
- **Export record.** `.movenotes/export.json` keeps the user name out (`~/…`
  and `$USER` segments) and expands for another `$HOME` and `$USER`. A
  missing, unreadable or unsafe record gets the labelled placeholder.
- **Identity.** On the 40,000-file library, V1's export differs from
  `7d9a879`'s only in `export.json` and the bundle README. The manifest is
  byte-identical, the imports fingerprint-identical with the same summary,
  and the harness's preserved and native cases fingerprint-identical.
- **Tests.** All 304 tests in the five required modules pass.

Details in the [P7c evidence](NOTRIOS_P7C_EVIDENCE.md#v1--damaged-preservation-bundles-refused-2026-10-23).

*V1 amendment (2026-10-23, found while implementing V1).* `sql2obsidian.py`
removed a previous bundle only when it began writing the new one, after every
note. So a re-export into an existing vault that stopped among the notes left
the old export's bundle in place: complete and valid, but beside notes it no
longer described. The importer would take the pair for a finished export
whose notes had been edited since. A `--no-preserve-joplin` re-export never
removed an old bundle at all.

V1 therefore moves the removal, and the export record's write, to before the
first note (`start_preservation_bundle`). This holds with or without
preservation. A bundle is now present when `.movenotes` holds a manifest, a
`joplin-raw/` copy or an export record. A record alone is refused as an
export that did not finish, with only the plain-import and re-export steps
offered.

Two more safeguards, because a vault can come from someone else. A record
value holding control characters, which could rewrite the terminal, makes the
record count as unreadable. A recorded notebook name that starts with `-` is
printed as `--notebooks=-x`, so that argparse does not take it for an option.
The acceptance gains tests for each of these.

**P7a completed audit:** [performance evidence](NOTRIOS_PERFORMANCE_EVIDENCE.md)
classifies F01–F15 and the additional Notrios review G01–G10, records separate
correctness defects C01/C02, and freezes the P7b handoff. The Notrios review at
`~/projects/notrios/performance-code-review.md` is a required third
input. Current Notrios batching is already implemented; its independent newer
full-corpus timings cannot substitute for controlled acceptance-pin comparisons.
The historical Go gap remains quantitatively unresolved. Python preserved import
has a reproduced unindexed folder-parent lookup bottleneck. Candidate gains remain
unproven until P7c. Every long batch must retain per-case outputs, terminal status
and an artifact manifest with directory purposes/sizes for future cleanup decisions;
use `scripts/notrios_p7a_artifacts.py` or the equivalent for that harness.

**Original review findings register (dispositions now in the evidence report):**

| ID / source | Finding to investigate | Required applicability and correctness checks |
|---|---|---|
| F01 / both | Obsidian adaptive fingerprint preload versus input-scoped queries; in-run duplicate/digest tracking | Measure fresh, unchanged full reimport and tiny merges separately; preserve fallback hashes and identical/different-ID collision semantics within/across batches and preserved/native routes. A whole-input map is O(N), not constant memory. Verify Alpha's claimed redundant re-query actually occurs. |
| F02 / Grok | Scope folder fallback UPDATE to newly inserted rows; avoid unnecessary native-folder fallback | Count touched rows/queries, inspect query plans and validate missing parents/folders and existing-row preservation. |
| F03 / both | Frontmatter byte accounting, duplicate head/full parsing, regex dispatch; Grok's JSON-exception scalar parsing | Preserve exact byte cap, UTF-8/BOM/CRLF behavior, complete delimiter recognition and supported YAML semantics. Character counts cannot replace UTF-8 byte limits; a prefix search for `---` is not a complete fence parser. Measure parsing/open counts before caching; no whole-vault body/frontmatter retention disguised as bounded streaming. Python re caching means repeated calls are not necessarily repeated compilation. |
| F04 / both | Cache relative paths/stat metadata and reduce inventory work | Measure syscall/path work; validate symlinks, normalized IDs, ordering and source mutation handling. Do not assume os.walk supplies reusable stat results. Prior site-generator speedups do not predict import speedups. |
| F05 / Grok | Reuse resource-ID set; skip link regexes when no relevant syntax | Prove actual hot path, preserve every supported Markdown/wiki/escape case and internal-link accounting; measure link-dense and link-free workloads. |
| F06 / Alpha | Faster shared row-tuple construction with itemgetter | Preserve absent-key → NULL semantics; audit all callers including Twitter and Notrios. Compare row values and SQL statement counts, not just tuple microbenchmarks. |
| F07 / both | Joplin tail-only property parsing instead of whole-body splitting/joining | Differential-check exact raw/body/properties/hash/title over synthetic edge cases and the real RAW corpus. Preserve CR, LF, CRLF, unknown ordered properties, OCR controls, bodyless items and trailing boundaries; never use str.splitlines(). Do not adopt the review's sample regex without proving equivalent semantics and bounded worst-case work. |
| F08 / both | Preserved Obsidian overlay: avoid unchanged BLOB writes, batch updates | Measure native versus preserved paths separately; compare raw snapshot bytes, digests, metadata envelopes, rename mappings and all needed column updates. Preserve changed-content detection. |
| F09 / both, conflicting claims | Resource double reads, digest reuse/hash-while-copy, validation-before-copy and collision handling | Reconcile Alpha's double-comparison claim with Grok's denial against the exact revision. Preserve all-resources validation/rollback guarantees and exact bytes; the proposed one-pass copy changes that barrier. Validate copied bytes and source mutation handling; a faster digest shortcut must not silently replace required byte comparison. Check alleged preservation overwrite behavior with a reproducer. Recipe corpora have no resources, so attachment wins cannot explain their timing gap. |
| F10 / Grok | Optional lower zlib compression level | Retain complete namespaced application_data and exact restoration; measure CPU versus database/disk growth and output compatibility. Never remove duplication required for lossless round trips. |
| F11 / Alpha; Grok conditional | Opt-in process parsing or bounded thread I/O overlap | Only after profiles justify it: measure startup, pickling/IPC, HDD contention and total child RSS; bound queued work and retain deterministic ordering, a single SQLite writer, cancellation and rollback. Default serial behavior must remain correct. No assumed 2–4× speedup. |
| F12 / Alpha | Optional non-lookup index drop/rebuild for large incremental imports | Low priority; first verify actual lookup needs and DDL/transaction recovery. Keep collision indexes and required schema state. Do not confuse existing fresh-import index deferral with missing optimization. |
| F13 / both | Progress symmetry and missing Obsidian structural performance regressions | Profile progress overhead before optimizing it; add meaningful query/row/read-count or bounded-allocation regressions for adopted changes, not fragile fixed-time CI assertions. Preserve monotonic phase reporting. |
| F14 / Grok | image_resources._existing_content_matches whole-file read | Check whether this is invoked by either measured route; classify out-of-path if not. Address only with a scoped, measured workload and unchanged byte/collision semantics. |
| F15 / both | Shared transaction/batching, WAL settings, hashes and existing index optimizations | Verify they already exist rather than reimplement them. Reject synchronous=OFF, globally forced huge caches/temp_store=MEMORY and speculative mmap. Preserve transaction/rollback and durability guarantees. |

P7a must mark each F01–F15 as confirmed-hot, confirmed-not-hot, already addressed,
incorrect, out-of-path or deferred with evidence and reason. Record disagreements
explicitly. Review percentages are hypotheses, not accepted performance claims.
A confirmed correctness defect must be recorded separately; fixing it is not
justified or rejected solely by its speed, and it cannot be advertised as a
performance win without measurements.

**Two-track profiling and experiment protocol:**

1. For Notrios producer ingestion, inspect the pinned code through the local
   `~/projects/notrios` checkout/history. Record the current checkout
   separately; do not silently substitute it for the pinned binary. Profile the
   actual Go importers using supported CPU/allocation/trace facilities or a
   narrowly instrumented disposable build. Attribute directory discovery,
   source read/decode/frontmatter/links, hashing, SQL queries/writes/indexes,
   batch commits/fsync/WAL/checkpoints and finalization; include CPU versus wait
   time and host I/O contention. Do not assume Python transaction rules describe
   the Go producer. Use read-only inspection first; any Notrios source change
   needs an explicit file/checkout handoff and required external-write approval.
   Keep schema compatibility and producer pin changes explicit in the plan.
2. For movenotes Python ingestion, independently benchmark the reviewed
   `joplin2sql.py`/`obsidian2sql.py` paths, using cProfile/allocation or operation
   counters where useful. Check the reviews' claimed revision/line references
   against the actual tree. Never attribute Python-only savings to the measured
   Go ingestion gap. Test potentially transferable ideas in Go only after a
   measured corresponding bottleneck is demonstrated there.
3. Freeze baseline and candidate source hashes, tools, flags, batch sizes,
   storage location, free space, input inventories and machine/load conditions.
   Correctness/compatibility changes from C7a–C7c are held constant during each
   performance A/B pair. Use separate fresh outputs for every fresh import;
   unchanged and incremental runs use identically prepared copies of the same
   initial database/assets. Do not reuse a completed output as a fresh baseline.
4. Use deterministic representative subsets before costly full runs: multiple
   note sizes, frontmatter/link densities, deep paths, native/preserved vaults,
   fresh/unchanged/full and small-merge scenarios, and a separate attachment
   corpus. Count bytes/files/notes/tags/relations as well as documents. Capture
   wall/user/system time, docs/s, bytes/s, per-stage time, peak process-tree RSS,
   I/O bytes/syscalls, SQL counts/plans where available, and disk/WAL growth.
   Keep instrumentation runs separate from uninstrumented timing trials.
5. Run at least three paired unprofiled baseline/candidate subset trials,
   alternating order; report individual results, median and variability. Record
   warm/cold-cache conditions without silently flushing shared host caches.
   No simultaneous imports or synthetic jobs on the benchmark disk. Use stdlib
   harnesses and existing tools; optional hyperfine/strace are not prerequisites.
6. Promote only credible subset winners to full 382,206-document confirmation
   for the affected route(s). Budget and checkpoint these multi-hour runs; one
   controlled full baseline/candidate pair per affected route is the initial
   minimum, with repeat trials only when variability or near-threshold results
   require them. Measure RAW and vault under matched conditions, even when a
   change targets just one. Historical 7c times alone cannot establish a speedup.
   Reuse a matching controlled full result for later acceptance where all input,
   implementation and gate fingerprints agree; do not repeat it needlessly.

**Adoption gates:** The objective is to substantially reduce this
repository's import times without cutting content. Report absolute seconds
saved and per-route speedups, and measure RAW and vault under matched
conditions so a change to one route cannot hide a regression on the other.

*Removed 2026-10-23, at the user's direction:* the Go producer targets (at least
30% lower wall time for each `notriosctl` route and vault/RAW ≤1.5, against the
observed ~2.37). They were measured on Notrios `7662fdd`, not the `v1.0.0` pin;
Notrios has since done its own import performance work, and nothing in this
repository can change them. Notrios's import performance is that project's to
track. The Go profiling track above remains as the record of how P7a and P7b
were run.

Adopt a candidate only when representative end-to-end improvement exceeds
observed measurement noise (target ≥5% median for a meaningful candidate), with
no unexplained material regression on the other route, small merges, memory,
disk usage or recovery. Phase/microbenchmark wins alone do not qualify. Record
individual and combined effects; a combined result cannot hide a harmful member.
Hold ambiguous results for more evidence and reject candidates with no measured
benefit. Preserve before/after patches, logs and adopted/rejected/deferred status
in the findings register; retain only demonstrated winners in the final change.

All adopted changes must preserve exact source/snapshot bytes and unknown
properties, collision errors, tag/link/attachment semantics, exclusion/receipt
rules and interrupted-import recovery. Require independent corpus inventories,
normalized semantic checks frozen by C7a, RAW differential parsing where relevant,
small end-to-end fixtures and the five-module regression suite; include producer
tests for changed Go code. Performance success never waives compatibility gates.
P7c reports partial results honestly if the objective is unmet. Main reviews the
full evidence before resuming 7c and keeps 7d blocked until 7c acceptance completes.

### Corpus and measurement procedure

These are inputs for creating isolated Notrios libraries, **not** archive-v2
inputs for `notrios2sql.py`:

| Local source | Use |
|---|---|
| `~/Documents/Joplin Archive/JoplinExport_2026_07_18/` | Large Joplin RAW corpus with attachments; import into a disposable Notrios library. |
| `~/projects/recipedb/recipe_joplin` | Large recipe RAW corpus, no resources. |
| `~/projects/recipedb/recipe_vault` | Same recipe data as Obsidian; compare semantic output against the RAW route. |

Start with synthetic fixtures, then bounded selections, then full local trials.
Inspect pinned CLI help and record actual Notrios import commands; do not invent
flags. Use separate disposable libraries for the recipe routes and each route's
own reviewed publication digest. Compare normalized titles/bodies/tags/counts,
not independent Notrios IDs or byte-identical frontmatter. Explain source-import
or privacy-selection differences before declaring equivalence. For attachments,
compare exact bytes and reachable sets.

Keep source directories read-only. Put work/evidence on a writable volume with
measured free space, for example under `/media/$USER/HD2`; never in source trees.
Real-data output stays local. Commit only sanitized reproduction instructions
and aggregate evidence. Checkpoint every expensive stage with digests, tool
versions and output paths so usage limits do not force repeating completed work.

Measure verification, SQL conversion, vault export, Hugo and search separately.
The existing exporter retains whole-vault metadata maps; bounded importer design
does not prove constant-memory behavior downstream. Follow
[PERFORMANCE_REVIEW.md](PERFORMANCE_REVIEW.md) for complexity decisions, and the
deployment documents for measured platform limits; do not restate those numbers
here from memory.

### Required regression gate

Run focused `test_notrios2sql.py` cases per implementation slice. At release,
run the repository-required suite plus the new module:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_movenotes.py test_image_resources.py test_obsidian2sql.py test_obsidian2site.py test_notrios2sql.py
```

Both the environment variable and `-B` are required because tests spawn Python.
If subprocess-heavy classes stall together, run every class separately and
record all results. Hugo/Go/Pagefind acceptance requires actual executions;
missing tools leave gates outstanding. Documentation-only plan review needs
diff/link checks, not a claim that the future importer or runtime gates passed.

## Deferred work

- Packed publications: Main designs pack/trailer/range verification, adds
  frozen-vector tests and performs differential acceptance before admission.
  Originally Luna was to add the tests; reassigned to Main with the rest of the
  remaining work on 2026-10-22.
- Multiple handoffs, changed-note updates and transactional merge recovery.
  Namespace isolation alone does not implement merging.
- Full/subset archives, lossless Notrios round trips, physical snapshots and sync.

## Progress log

| Date | Item | Result / next action |
|---|---|---|
| 2026-09-05 | Plan review | Corrected format/mapping decisions; seven steps split into owned slices with dependencies and acceptance gates. No importer implemented or corpus/site tests run. Next: 1a. |
| 2026-09-05 | 1a complete | Added the pinned field/limit/publication checklist and `movenotes-publication-loose-v1` declaration. Recorded producer metadata retention, policy overrides, skipped-rewrite limitations and CLI/report requirements for 1b. Documentation/schema/limit/order checks only; no fixture generated. Next: ask to proceed to 1b. |
| 2026-09-05 | Worker assignment review | Assigned 2c, 3c, 3d, 5a, 5b, 5c, 6d and 7a to Terra for bounded implementation/regression work. Luna retains mechanical slices; Main retains design, safety and acceptance decisions and reviews both worker roles. Slice order and per-item user confirmation remain unchanged. Next: ask to proceed to 1b. |
| 2026-09-05 | 1b complete | Committed producer-generated loose publication, synthetic v1 inputs, generator and reports/expectations under `testdata/notrios/`. Verified exact selected content/resources, withheld/history sentinel absence and matching reviewed/commit digests. Recorded actual anchor representation, planner resource-link classification and timestamp normalization for 1c. No importer, mapping APIs or 1d test module implemented. Next: ask to proceed to 1c. |
| 2026-09-06 | 1c complete | Froze module interfaces, length-framed IDs, complete row/property defaults, MIME/body limits, Linux no-replace staging/recovery/no-op, token-aware note/resource links and relation-only attachment suffix. Specified actual-path second-pass export and generated RAW title serialization after reviewing exporter behavior. Checked 13 ID vectors with independent framing/system SHA-256, 8 fixture spans, 3 full body projections, 3 explicit path examples, fixture inventory and documentation links/diff. No runtime importer/exporter changes or runtime suite executed. Next: ask to proceed to 1d. |
| 2026-09-06 | 1d complete | Main implemented the bounded fixture-test slice locally: isolated archive-copy/inventory/record helpers, nine offline baseline tests and regeneration guidance. Focused tests passed; the repository-required four modules plus `test_notrios2sql.py` passed all 112 tests in 56.142s after permitting the existing tests' local HTTP sockets outside the sandbox. Documentation links/diff checked. Fixture bytes and runtime scripts unchanged; no Notrios invocation or importer implementation. Existing `.gitignore` edit excluded from the slice. Next: ask to proceed to 2a. |
| 2026-09-07 | 2a complete | Implemented bounded strict JSON, all twenty frozen limits, immutable manifest shape, Go semantic serialization/checksum and publication/reader/schema/capability/loose-location gates. `read_manifest` opens only the manifest through no-follow directory handles; no index/record/blob verification or importer CLI is claimed. Six digest vectors generated independently with Go 1.27.0 from seven verbatim pinned structs; regeneration matches byte-for-byte and all limits match the registry. All 22 focused tests and 125 full regression tests passed (52.843s, with local HTTP sockets permitted). Documentation links/diff checked; original publication fixture unchanged. Next: ask to proceed to 2b. |
| 2026-09-07 | 2b complete | Added held-directory/no-follow object reads, 1 MiB streamed checked copies, strict index and record-envelope/count checks, disk-backed exact inventory joins and an owned temporary SQLite spool. Batch row/byte limits, cleanup/lifetime, valid empty fanout directories, legacy zero blob counts, damaged/missing objects, cross-chunk order, malformed JSONL, bad paths, symlinks/FIFOs and extra files tested. All 34 focused tests and 137 full regression tests passed (55.635s, with existing local HTTP sockets permitted). Twenty-two independent Go storage-MIME syntax vectors reproduce exactly; clarified equal duplicate parameter acceptance. Documentation links/diff checked; original fixture unchanged. Payload semantics/reference checks and complete `VerifiedArchive` remain pending. Next: ask to proceed to 2c. |
| 2026-09-07 | 2c complete | Added six test methods covering exact 4096-byte index and 1048576-byte record lines with LF/CRLF, UTF-8 MIME byte limits, optional capability bounds, hostile integer/count shapes, rehashed malformed record JSON and cross-chunk index shadowing. Each refusal asserts its code and reason; existing legacy zero blob count coverage passes. Corrected test expectations for name grammar and nesting errors, and balanced shadow-fixture totals so it reaches the intended gate. No implementation changes needed. All 40 focused tests passed within the full 143-test regression run (57.046s, existing local HTTP sockets permitted). Diff checked; original fixture unchanged. Next: ask to proceed to 2d. |
| 2026-09-07 | 2d complete | Implemented immutable typed payloads and keys, indexed SQLite identity/reference/blob joins, bounded notebook parent walks, current-revision ownership/history checks, resource reachability and publication metadata/link gates. Added `verify_archive`, ordered record/relation lookups and private-copy blob reads with size/hash checks at authenticated EOF; partial consumption refuses. All 56 focused tests passed within the 159-test full regression run (69.902s, existing local HTTP sockets permitted). Added 56 independent Go 1.27.0 semantic MIME vectors and their reproducer; relevant producer verifier/format sources still match the pinned commit. Rehashed scalar/schema/graph/publication/MIME mutations, immutable API lifetime, empty blobs and exact text limits pass. Original fixture unchanged; no converter or CLI exposed. Diff/documentation checked. Next: ask to proceed to 2e, the differential and point-of-use safety audit. |
| 2026-09-07 | 2e complete | Audited the exact pinned fixture CLI against 47 rehashed cases: six shared acceptances, 24 shared refusals and 17 specified consumer refusals all matched. Fixed two reproduced blob-lifetime defects: caught read failures could reuse verified EOF, and outstanding contexts retained file/directory descriptors after archive exit. Added source-relocation/private-copy corruption, repeated-read, injected I/O, OS-handle and 17 MiB streaming-body regressions. Final full suite: 166 tests passed (63 focused, 76.097s; existing local HTTP sockets permitted). Separate 504-tag/1 MiB and 8,004-tag/32 MiB memory samples peaked at 1,455,654 and 2,136,831 traced Python bytes; report distinguishes native/process RSS. Evidence source hashes, documentation links and diff checked; original fixture unchanged. The pinned archive-v2 source package remains unchanged in the neighboring checkout. No conversion/CLI exposed. Next: ask to proceed to 3a. |
| 2026-09-07 | 3a complete | Added pure framed source keys and SHA-256-derived IDs, millisecond UTC formatting, all five complete row builders, exact ordered generated properties and the fixed resource extension/display-name mapping. Nine mapping tests cover frozen vectors, key rejection before hashing, injected equal IDs with distinct full keys, all columns/aliases/numeric types, privacy omissions, empty/Unicode titles, document-owned timestamps, year 0000 and SQLite/property round trips. Corrected two test assumptions: extension vectors use resource IDs, and the current DATETIME column is returned as text rather than a Python datetime object. All 175 regression tests passed (72 focused, 76.209s; existing local HTTP sockets permitted). No archive/fixture changes, database lifecycle or CLI added. Main executed locally under the session delegation constraint. Next: ask to proceed to 3b. |
| 2026-09-07 | 3b complete | Added the internal staged importer and frozen conversion limits, full-key collision registry, indexed identity lookups, byte/row-bounded insertion, final SQLite integrity/reference checks, strict disk-backed completion inventory, receipt and verified unchanged reruns. Publication uses an owned sibling lock/stage/work lifecycle and Linux renameat2(RENAME_NOREPLACE), with file/directory fsync and ownership-checked cleanup. Fourteen lifecycle tests cover failed verification/insertion/finalization, interrupted synthetic resource writes, inventory/marker fsync, pre/post-publication failures, empty-directory races, a competing writer, stale locks, unsupported publication, changed ownership, bounded hashes/batches, selection checks and edited outputs. Fixed conversion I/O diagnostics being replaced during verifier-context unwinding. All 189 tests passed (86.318s, existing local HTTP sockets permitted); the sandbox-only attempt failed solely on those socket permissions. Main executed locally under the session delegation constraint. The original fixture and existing import/export code remain unchanged. No CLI exposed; conservative text-only development gate and remaining 3c/3d/6 scope documented above. Next: ask to proceed to 3c. |
| 2026-09-07 | 3c complete | Validated the existing staged notebook/current-note writer with nine integration tests, including real sql2obsidian subprocesses. Checks cover frozen document IDs, notebook hierarchy and aliases, source-key insertion order, revision titles, document-owned millisecond dates, exact Unicode/CRLF/trailing-whitespace database bodies, duplicate/empty-title vault filenames, selected notebooks, empty bodies, notebook-only publications and final bundle hashes. Rehashed missing/cyclic parents, missing/wrong-owner revisions, unsupported MIME and malformed/control-bearing bodies refuse before insertion, including an invalid last note; body/projected-byte limits refuse before body-stream opening. Factored an owned text-publication fixture helper shared with 3b tests. Corrected test assumptions about the fixture ID-map key and canonical blob-reference MIME; no runtime changes were needed. All 198 tests passed (100.849s, existing local HTTP sockets permitted); nine focused cases passed in 3.480s. Main executed locally under the session delegation constraint. Original fixture unchanged; the documented matching-title/generated-RAW/link adaptation remains in 3d, and no CLI is exposed. Next: ask to proceed to 3d. |
| 2026-09-07 | 3d complete | Added bounded lexical code/escape protection, exact UTF-8 token/span and retained-record reconciliation, URI/fragment agreement and count/byte limits, with single-pass destination replacement for note links and unchanged external/self tokens. The importer now admits this note-link subset while continuing to refuse tags/resources. Added the marked-note exporter finalization pass using actual returned paths, escaped filtered labels with numeric omissions, missing-target refusal and finalized bundle hashes; generated RAW gets exactly one title prelude, with matching body headings preserved on export/reimport. Sixteen focused tests passed (5.607s), covering malformed/stale/overlapping/missing/protected records, Unicode, code, bounds, duplicate titles, selection, injected ENAMETOOLONG/final-write failure, direct Joplin export, empty/multiline titles and RAW reimport. Reimport can exchange duplicate-title suffixes because its insertion order differs; tests correctly validate each export against its own paths. All 214 regression tests passed (93.100s, existing local HTTP sockets permitted). Main executed and reviewed locally under the session delegation constraint. Original fixture and site path maps unchanged; resource/attachment projection and the public CLI remain deferred. Next: ask to proceed to 4a. |
| 2026-09-08 | 4a complete | Added TAG and NOTE_TAG insertion after notes in binary source-key order, using frozen row builders, indexed full-key ID lookups and document-created membership timestamps. Removed the tag admission gate while preserving resource refusal. Finalization now checks per-type counts, note/tag aliases, membership target types and uniqueness before publication. Four integration tests pass (1.022s): the original four tags and six memberships load as explicit sorted per-note title lists; mapped IDs, aliases, dates, order, tiny batches, unattached tags and identical reruns are checked; injected wrong targets, aliases and counts leave no published output. All 218 regression tests passed (91.317s, existing local HTTP sockets permitted). Main executed locally under the session delegation constraint. Original fixture and existing exporters unchanged; broader tag-name/YAML/reimport cases remain in 4b, and resources/public CLI remain deferred. Next: ask to proceed to 4b. |
| 2026-09-08 | 4b complete | Added four round-trip/mutation tests over an owned ten-tag/fourteen-membership archive, including distinct IDs with the same name on one note. Independent YAML scalar checks and real vault import/export subprocesses cover composed/decomposed Unicode, Japanese, spaces, tabs, quotes, backslashes, punctuation and literal true. The default bundle preserves identities and membership multiplicity; native name-based import preserves tag text and exact vault bytes; selected-notebook bundles retain only their memberships. Eleven rehashed duplicate/shape/type/ID/reference mutations refuse during verification before conversion. Corrected test expectations to the verifier’s existing JSON-shape error family; no runtime changes were needed. Four focused tests passed (5.255s), and all 222 regression tests passed (96.398s, existing local HTTP sockets permitted). Main executed locally under the session delegation constraint. Original fixture unchanged. Next: ask to proceed to 4c. |
| 2026-09-13 | Schema-28 plan amendment | Compared original producer pin with clean `7662fdd5b55d6f34f14874f70ba6db9f9e7676ac`; identified the private FTS rowid migration, registry support-level bump and already-integrated optional collection capabilities change (`cc4ec25`). Added S28a/S28b before 4c, preserving historical fixtures and receipt/identity semantics. Documentation-only change; implementation and producer execution remain pending. Next: ask to proceed to S28a. |
| 2026-09-13 | S28a complete | Raised the reader minimum-schema support bound to 28 and updated contract/design declarations against producer pin `7662fdd5b55d6f34f14874f70ba6db9f9e7676ac`. Added valid schema-28 and future-source admission cases, plus independent minimum-29 and inverted-bound refusals. Reconciled collection-capabilities prose while retaining the existing optional/legacy validation. All 13 focused tests passed (0.407s). Ran all five regression modules with `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v`; the sandbox run completed 218 methods in 102.750s with only localhost socket-denial errors, then both affected HTTP classes passed all 12 methods in 6.073s with sockets permitted. Across the two runs, all 226 distinct methods passed (suite enumeration confirmed). Logs: `/tmp/movenotes-s28a-focused.log`, `/tmp/movenotes-s28a-tests.log`, `/tmp/movenotes-s28a-http-tests.log`. Existing fixture/vector/audit files unchanged; no receipt, mapper or notesdb schema change. Diff and changed-document links checked. New-producer fixture generation and differential execution remain S28b. Next: ask to proceed to S28b. |
| 2026-09-13 | S28b complete | Built the clean pinned producer with Go 1.27.0 and generated two real schema-28 publications via `generate_schema28.py`: the existing resource seed/update and a separate resource-free seed. Saved unchanged archives, exact inventories/digests, sanitized command/report metadata and read-only schema evidence under `testdata/notrios/schema28/`. The current producer and Python verify both new handoffs and the original schema-27 archive. Extended the development audit runner with explicit fixture/case selection and retained binary-hash checks; 56 cases matched (9 shared acceptances, 30 shared refusals, 17 specified consumer-only refusals). Four new offline tests cover immutable fixtures, current audit replay, 15-row conversion/no-op and actual vault tags/links/bundle hashes, plus continued resource conversion refusal. All 17 focused tests passed (6.644s), and all 230 regression tests passed (101.920s, localhost sockets permitted; both bytecode-suppression flags). Commands, pins, digests and limits are in the schema-28 README; logs are `/tmp/movenotes-s28b-audit.log`, `/tmp/movenotes-s28b-focused.log` and `/tmp/movenotes-s28b-tests.log`. Original fixtures/vectors/audit results unchanged; no importer runtime or producer edits. Next: ask to proceed to 4c. |
| 2026-09-14 | 4c complete | Reviewed TAG/NOTE_TAG to YAML-list to site explicit/generated-tag flow; documented site casefold/deduplication and the taxonomy-cap exception in `NOTRIOS_TAG_REVIEW.md`. Added a real schema-28 publication → vault → site test for default and cap-one settings: written tags match search-source tags, only published survives the cap, and generated préface stays out of taxonomy/search-source tags while its posting identifies the correct document. Corrected the early Ledger M2 table to reflect completed Step 46. Initial focused attempt mistakenly included section index files in note assertions; narrowing to note pages fixed the test without runtime changes. Four focused tests passed (3.991s); all 231 tests across the five regression modules passed (104.534s, localhost sockets permitted), with `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v`. Logs: `/tmp/movenotes-4c-focused.log`, `/tmp/movenotes-4c-tests.log`. Documentation links and diff checked; fixtures and runtime files unchanged. Generated-input review only; no new Hugo/Pagefind/browser/live-Bluge validation claimed. Next: ask to proceed to 5a. |
| 2026-09-14 | 5a complete | Connected frozen RESOURCE row mapping to staged authenticated blob copies with bounded reads, exclusive mapped-ID/MIME-suffix files, explicit size/SHA-256 checks and file fsync. Resource rows join existing bounded batches and per-type finalization counts; corrected the reserved association column to `relation_id`. Four storage tests pass (0.714s): exact three-resource files/metadata and seven-byte reads, tiny batches, safe/extensionless names, distinct IDs sharing bytes, empty blobs, existing-file and bad hash/size refusal, plus real stage cleanup after second-resource read/short-write/fsync faults. Tests bypass unfinished note projection only to isolate storage; production preflight still refuses resources until 5b handles associations and link projection. All 235 five-module regression tests passed (103.850s, localhost sockets permitted), using both bytecode-suppression flags. Logs: `/tmp/movenotes-5a-focused.log`, `/tmp/movenotes-5a-tests.log`. Diff/documentation links checked; source fixtures unchanged. Main executed locally under the session delegation constraint. Next: ask to proceed to 5b. |
| 2026-09-14 | 5b complete | Following explicit session confirmation, delegated takeover to `codex:terra_worker` (configured `gpt-5.6-terra`, `medium`; native identifier `/root/notrios_5b`). Worker completed earlier parent work, preserved exact snapshot bytes and attachment paths through bundle reimport, and added indexed resource-identity provenance to distinguish missing resources from omitted notes. Parent reviewed mapping, bounds and snapshot behavior, integrated documentation and ran final validation. All 241 tests across the five required modules passed (117.237s), with both bytecode-suppression flags and localhost sockets permitted; log `/tmp/movenotes-5b-tests.log`. Focused resource, MIME, filtered-bundle, missing-row/file and protected-code checks pass; frozen fixture bodies and source hashes match. Original fixtures unchanged. Usage-limit interruption resumed on the same worker; actual backend model/effort not independently exposed. Full attribution is in the generated ledger. Public CLI remains Step 6. Next: ask to proceed to 5c. |
| 2026-09-14 | 5c complete | Assigned `codex:terra_worker` (`gpt-5.6-terra`, fixed `medium`; native identifier `/root/notrios_5c`) added duplicate Unicode/punctuation filename, escaped-label and resolved-link checks through vault/bundle/filtered round trips, plus zero-byte and 9,252,864-byte opaque resources. The larger fixture is generated in blocks; resource reads are tracked by blob hash, and independent streaming hashes verify published, vault, preservation and re-exported bytes. Existing sanitization handles wiki delimiters; runtime code and immutable fixtures are unchanged. Parent reviewed coverage and final assertions, updated documentation/provenance and ran validation after the usage-limit interruption. All 8 final focused tests passed (14.839s); all 243 tests across the five regression modules passed (121.125s), with both bytecode-suppression flags and localhost sockets permitted. Logs: `/tmp/movenotes-5c-final-focused.log`, `/tmp/movenotes-5c-tests.log`. Next: ask to proceed to 5d. |
| 2026-09-14 | 5d complete | Codex parent reviewed the full resource path at baseline `22929c8`: indexed reachability, authenticated consumption, exclusive mapped-ID writes, owned staging, no-replace publication and recovery. Added three full-import regressions for orphan refusal before payload creation, same-size corruption/symlink at second-resource consumption, and abrupt child exit during a real write followed by stale-lock refusal and inspected manual recovery. No runtime defect found within the frozen boundary; process-exit evidence does not claim physical power-loss testing or adversarial same-user path protection. Review: `NOTRIOS_RESOURCE_REVIEW.md`. All 21 focused tests passed (5.912s); all 246 five-module regression tests passed (124.044s), with both bytecode-suppression flags and localhost sockets permitted. Logs: `/tmp/movenotes-5d-focused.log`, `/tmp/movenotes-5d-tests.log`. Runtime code and immutable fixtures unchanged; documentation links, diff and attribution checked. No worker used: this slice is parent-owned. Next: ask to proceed to 6a (`codex:luna_worker`, `gpt-5.6-luna`, fixed `max`). |
| 2026-09-15 | 6a complete | Assigned `codex:luna_worker` (`gpt-5.6-luna`, fixed `max`; native identifier `/root/notrios_6a`) added `ImportResult.summary()` with only status, both digests and row/resource counts, returning a fresh JSON-compatible dictionary without destination/content. Tests compare the staged SQLite receipt and completion marker against independent pinned fixture values and the exact versioned allowlist, check created/unchanged summaries and mutation isolation, and cover pre-rename receipt cleanup and the existing post-rename durability-error exception (complete receipt retained, no success result). No new persisted summary payload or CLI is exposed. Parent specified the summary interface, reviewed the patch, updated documentation/provenance and ran all five regression modules. All 25 focused tests passed (19.302s); all 249 regression tests passed (128.500s), with both bytecode-suppression flags and localhost sockets permitted. Logs: `/tmp/movenotes-6a-focused.log`, `/tmp/movenotes-6a-tests.log`. User resumed after a usage-limit interruption; no reassignment. Immutable fixtures unchanged. Next: ask to proceed to 6b. |
| 2026-09-15 | 6b complete | Codex parent finalized the public CLI using `--input`/`--output` (replacing provisional positional syntax), optional strict reviewed-selection digest, non-abbreviated arguments and no unsafe override flags. Successful stdout is one content-free JSON summary; existing helper progress and errors go to stderr, with cleanup notes retained. Import and rerun safety use the existing verified lifecycle. Four subprocess tests cover creation, unchanged source/output inventories, mismatch on new/existing output, valid rehashed source changes, unrelated/edited destinations, malformed/unsafe usage and injected sealing failure without success stdout. Corrected an initial invalid notebook field in the test fixture; no importer rule change was needed. All 4 focused tests passed (10.784s); all 253 five-module regression tests passed (132.355s), with both bytecode-suppression flags and localhost sockets permitted. Logs: `/tmp/movenotes-6b-focused.log`, `/tmp/movenotes-6b-tests.log`. Help and finalized contract reviewed; fixture instructions, links, diff and attribution checked. No worker used: parent-owned slice. Next: ask to proceed to 6c. |
| 2026-09-15 | 6c complete | Codex parent specified and implemented opt-in validated receipt sidecars for vault and site exports. Both source digests survive outside notes, preservation payloads and generated search inputs; strict allowlists, bounded JSON, no-follow reads, atomic replacement and stale-sidecar removal are covered. Filtered exports retain upstream lineage; reimport does not restore settings automatically. Five focused tests passed (14.751s); all 258 five-module regression tests passed (160.004s) with both bytecode-suppression flags and localhost sockets permitted. Initial focused assertions were corrected for timestamped landing pages and normalized write errors. Logs: `/tmp/movenotes-6c-focused.log`, `/tmp/movenotes-6c-tests.log`. Help, diff and documentation reviewed; fixtures unchanged. Live Hugo/search builds remain 7b. No worker used: parent-owned slice. Next: ask to proceed to 6d (Terra, medium). |
| 2026-09-15 | 6d complete | Assigned `terra_worker` (`/root/notrios_6d`; configured `gpt-5.6-terra` / `medium`) implemented optional library phase callbacks, CLI stderr phase/count reporting and explicit help output/exit-code documentation. Completion is emitted only after importer return, including cleanup and durability checks. Parent reviewed and requested exact ordered phase assertions and a post-publication cleanup failure case; worker completed both. Six focused CLI tests passed (13.098s); parent ran all 260 five-module regression tests successfully (149.849s), with both bytecode-suppression flags and localhost sockets permitted. Logs: `/tmp/movenotes-6d-focused.log`, `/tmp/movenotes-6d-tests.log`. Source/destination inventories, receipt/summary shape and safety logic remain unchanged. Design, fixture instructions, links, diff and attribution checked. User resumed final validation after a usage limit; no reassignment. Next: ask to proceed to 7a (Terra, medium). |
| 2026-09-15 | 7a complete | Assigned `terra_worker` (`/root/notrios_7a`; configured `gpt-5.6-terra` / `medium`) implemented real importer CLI → SQLite → vault regressions for the current schema-28 resource publication and historical schema-27 publication. Frozen expectations independently check summary/digests, source inventory, receipt agreement across SQLite/marker/vault, complete schema-28 bodies, paths/titles/tags/links, exact attachment hashes and excluded sentinels throughout publication and vault. Parent requested stronger full-body and cross-stage receipt assertions, reviewed worker follow-up and validated the result. Both focused tests passed (2.697s); all 262 five-module regression tests passed (138.773s), with both bytecode-suppression flags and localhost sockets permitted. Logs: `/tmp/movenotes-7a-focused.log`, `/tmp/movenotes-7a-tests.log`. Documentation distinguishes historical S28b limitations from current support; links, diff and attribution checked. No runtime or immutable fixture data edits. Live Hugo/search and performance work remain 7b/7c. Next: ask to proceed to 7b (Main). |
| 2026-09-16 | 7b complete | Codex parent ran the real current-schema fixture through the CLI/vault and Hugo/Ledger with separate Bluge and Pagefind builds, then Chromium at /archive/ on desktop/mobile. Found Bluge result URLs missing the prefix; fixed the theme adapter with a regression in Ledger `85ac1b0` (approved external-checkout write), rebuilt both sites and reran checks. Both builds have 24 HTML pages; Pagefind indexed 3 notes/74 words. Tag/taxonomy counts agree (3/1/1/1), links/attachments/receipts and backend isolation pass, all ten excluded sentinels and two receipt digests return no search results, and browser console/HTTP checks are clean. Sixteen theme JS tests and all 262 Python regressions passed (150.295s). Initial Hugo sandbox cache failure resolved with approved cache access. Reusable fixture-only harnesses and NOTRIOS_SITE_ACCEPTANCE.md capture tools, pins, commands, limits and evidence. User resumed after usage limit; no worker/reassignment. No scale claims. Next: ask to proceed to 7c (Main). |
| 2026-09-18 | C7c complete | Delegated to Codex luna_worker /root/c7c_harness (configured gpt-5.6-luna / fixed max; actual model/effort not independently exposed). Added semantic comparator, paired smoke, durable child receipts and PIDFD monitor. Parent review found stale-result, duplicate, publication, parser and quadratic-query issues; worker corrected them with targeted and 20k scale tests, preserving failed attempts. Final v6 comparison covered 382,206 source records per route: all identities/bodies match, vault metadata matches, 3,682 title representations explained, zero unexplained source-to-route differences. RAW 842,813 / vault 0 tag associations remain separate; semantic_equal remains false. All three bounded publications verify (Joplin 987 exact + 13 privacy projections). Runtime 5,174s, peak RSS 336,784 KiB; no full 7c acceptance. Existing 264 tests passed; final focused validation and reproduction details in NOTRIOS_C7C_EVIDENCE.md. Next: ask to proceed to P7a (Main; Luna/max monitoring). |
| 2026-09-18 | P7a complete | Parent audited all three reviews and wrote profiling/probe/inventory scripts; Luna /root/p7a_monitor executed sequential batches with long completion waits. Synthetic 2,000-note Python/Go profiling and unprofiled sanity runs complete; Python preserved fresh 249.098s unprofiled, with unindexed folder lookup dominating its profile. Current Notrios already batches imports; old Go gap remains quantitatively unresolved. Two inventory tests and baseline probes passed. See NOTRIOS_PERFORMANCE_EVIDENCE.md for dispositions, manifests and frozen candidate handoff. No production optimization adopted. Next: ask to proceed P7b, Terra/fixed medium; Luna/fixed max for staged large-run monitoring. |
| 2026-09-18 | P7b complete | Terra /root/p7b_candidates implemented F02/F04 Python candidates, C01/C02 collision fixes, comparison/long-batch scripts and disposable Go G08 experiment. Luna monitored sequential validation; 299 Python tests passed, all 18 completed imports match after narrowly correcting generated timestamp comparison. Native/preserved median subset times fall 15.1%/94.6%; RAW control median is 2.9% higher within observed variability. Both Go suites pass, but G08 regresses no-link/long-line benchmarks and is rejected. Usage interruption was recovered after registry checks; /root/p7b_monitor_resume ran only remaining stages. See NOTRIOS_P7B_EVIDENCE.md; full-corpus adoption remains P7c, Luna/fixed max. |
| 2026-09-19 | P7c partial — blocked | Luna authored isolated variants/harness and ran synthetic matrices; parent reviewed and ran final real-data validation after worker tool approval stalls. Isolated F02 preserved subset improves94.4%; F04 real10k fresh/unchanged improves26.3%/35.7%, all outputs match. Full native baseline interrupted at17,943.11s in unindexed batch-ID lookup; candidate not run. No full acceptance or Go goal claim. P7b2 Terra/medium is the next prerequisite; retain failed/complete evidence and long notification monitoring. |
| 2026-09-26 | Producer review | Reviewed Notrios changes beyond schema 28 for effect on this importer. Found one consumption blocker: producer item J43 now carries a link's title through its rewrite, and the link grammar here admits no whitespace in a destination, so every titled internal link refuses with `unsupported or unaccounted active link syntax` at the shared scanner — verified against the current module for double-quoted, single-quoted, parenthesised and embed forms. Fail-closed, so nothing is mis-projected, but a post-J43 handoff cannot be consumed. Recorded as the S43 prerequisites. Producer items J37, J41 and J42 need no change and remove or reduce existing refusals; unresolved links with spaces, parentheses or angle brackets refuse as they already did and are not admitted. Link rows and mapped identity are unaffected. No other open producer item affects the handoff format. No code, fixture or test changed. Next: ask to proceed to S43a. |
| 2026-10-22 | Assignment amendment | At the user's request, reassigned all remaining work (S43a, S43b, P7b2, resumed P7c, resumed 7c, 7d, 7e) to the Claude Code main model and retired the Codex worker and monitor workarounds. Superseded assignments are kept in the ledger's `assignment_history`. The S43 ledger records were missing and are now added. Completed 6c, 6d, 7a and 7b table rows were marked complete to match the ledger. Added dated notes from the Notrios plan: J39 shipped without a schema change, and J43 and J10 are complete, with the pin to be verified in S43b. Documentation and provenance only, with no code, fixture or test changed. The renderer `--check` was not run, because the session's shell sandbox failed to start. Claude Code session confirmation is pending. Next: confirm assignments, then ask to proceed to S43a. |
| 2026-10-22 | Decisions recorded | In the restarted session the shell works and the renderer `--check` passes. The user confirmed the Claude Code assignments for this session. Verified the Notrios release against the local checkout and GitHub: `v1.0.0` is at `2aab9a8`, is published, and contains J43. The schema is still 28, and the archive contract and format are unchanged since `7662fdd`. Decided the order S43a → S43b → P7b2 → resumed P7c → resumed 7c → 7d → 7e. Added S43b as a dependency of 7c and 7d. Resumed 7c re-imports with the release into fresh libraries and keeps the old evidence. Re-evaluation of the P7 targets, the small-merge noise and 7c's acceptance scope is deferred until those slices need it, as the user directed. Documentation and provenance only. Next: ask to proceed to S43a. |
| 2026-10-22 | S43a complete | The Claude Code parent read the producer's J43 `TitleSuffix` code at `v1.0.0`. It then added one optional delimited title to the protected link grammar (`Token.title_suffix`), copied byte for byte. Titles that hold controls or internal targets refuse. Vault note and attachment links keep titles; a titled image becomes a Markdown image, and untitled output is byte-identical. Undelimited suffixes, escaped or multi-line titles and spaces, parentheses or angle brackets in destinations still refuse. The design and contract declarations are updated; mapper, receipt, reader profile, fixtures and identity vectors are unchanged. The link projection and integration classes pass all 21 tests. All 273 tests in the five required modules pass (168.108s) with both bytecode-suppression controls. Two pre-existing downstream defects were found and added as fix slices rather than only logged, at the user's direction: S43c (titled `./`/`../` links stay unresolved on native reimport, and titles are dropped there and on site note/asset links) and E1 (`notesdb.connect()` switches the input to WAL, so exporting a completed import changes `notesdb.sqlite` and a later identical rerun refuses). No worker was used. Next: ask to proceed to S43b. |
| 2026-10-22 | S43b complete | The Claude Code parent built a clean Notrios `v1.0.0` binary (`b4f368a9…`) from a temporary clone; the default module mode is required, because `-mod=mod` rewrites the release's `go.mod`. It added a synthetic titled-link Obsidian vault and `generate_v1_titled.py`, which drives real `import obsidian`, `tags add` and publish commands. The resulting publication has commit `7f093e27…` and selection `a8537bb0…`: 3 notes, 3 tags, 1 resource and 11 links. It covers every title form, a titled embed, an angle-bracket destination the producer resolved, and a withheld titled link rewritten to its label. The generator checks titled tokens and absent sentinels against raw archive bytes. The differential audit's injected references are now declared per fixture (older fixtures keep `doc_public`/`res_image`), and all 56 cases matched against the release binary: 9 shared acceptances, 30 shared refusals and 17 consumer-only refusals. `NotriosV1TitledTest` passes 3 tests covering conversion, unchanged reruns, byte-for-byte titles in the database and vault, tags, attachment bytes and bundle hashes. All 276 tests in the five required modules pass (193.270s) with both bytecode-suppression controls; the schema-27 and schema-28 fixtures still verify and convert unchanged. No new movenotes defect was found. No worker was used. Next: ask to proceed to S43c. |
| 2026-10-22 | S43c complete | The Claude Code parent froze the design first, because reading the code found a third consumer: `cleanres.py` built its referenced set from a title-blind regex, so it deleted resources referenced only by titled links. That is data loss, made reachable for Notrios imports by S43a's titled embeds. `common.LINK_TITLE` now carries S43a's grammar. `RESOURCE_LINK_RE` accepts it, so `cleanres.py` counts titled references and `sql2obsidian.py` keeps resource titles (a titled image becomes a Markdown image). `obsidian2sql.py` tries a titled form first and keeps the title after `:/id`; everything else takes the unchanged untitled pattern. `obsidian2site.py` keeps exactly one delimited title on resolved note and asset links. A baseline-versus-new harness shows a 3,000-note subset of the real recipe vault unchanged: 7,426 site files are identical after normalising generation-time values, and 7,736 reimported items are identical. For the S43b titled vault only the titled notes change, with site URLs unchanged; reimport previously left a stray `)` and an unresolved titled image. The new regression tests fail on the baseline and pass now. All 282 tests in the five required modules pass (194.732s) with both bytecode-suppression controls. 7d's CHANGELOG entry now must record these generic fixes. No worker was used. Next: ask to proceed to E1. |
| 2026-10-22 | E1 complete | The Claude Code parent probed SQLite 3.46.1 and refined the user's decision: a `mode=ro` connection to a WAL database leaves `-wal`/`-shm` behind, so `notesdb.open_database_for_reading` uses `mode=ro` for rollback-journal databases and `query_only` for WAL ones. Neither changes the journal mode. A read-only check falls back to `open_database` when migration or recovery is needed. `sql2obsidian.py` and `sql2joplin.py` use it. A completed Notrios import is now byte-identical after both exports, leaves no sidecar files, and reruns as `unchanged`; it previously refused with `completed payload inventory differs`. Exporter output is identical to `HEAD` for the 3,000-note real recipe subset (10,738 vault and 7,736 Joplin files) and for the titled import. New tests cover both journal modes and migration of a database missing an index or at an older version. `PERFORMANCE_REVIEW.md` is updated. All 285 tests in the five required modules pass (197.130s) with both bytecode-suppression controls. No worker was used. Next: ask to proceed to P7b2. |
| 2026-10-22 | P7b2 complete | The Claude Code parent measured two bounded treatments against the previous code on deterministic recipe subsets: creating `joplinididx` when `obsidian2sql.py` creates a new database, and an in-memory map of this run's IDs. All outputs were fingerprint-identical. At 40,000 files the fresh import took 330.45 s before, 130.08 s with the index and 136.81 s with the map, which also added about 50 MiB of memory. The index treatment was adopted, so the batch query and C01/C02 checks are unchanged and merges and reruns take the same path as before; 10,000-file unchanged reruns and ten-note merges are unchanged in output and time. A full-corpus scale check imported all 382,206 files (1,237,552 items) in 1,628.36 s, where the interrupted P7c baseline ran 17,943.11 s without finishing; an identical rerun skipped every item in 1,388.56 s. A new regression test records each batch lookup's query plan during a fresh import and fails on the previous code. All 286 tests in the five required modules pass, and the P7c harness tests pass. F02 is now subsumed, and the full-corpus memory, unchanged-rerun cost and changed evidence mount path were added to resumed P7c's plan. `PERFORMANCE_REVIEW.md` and the P7c evidence are updated. No worker was used. Next: ask to proceed to resumed P7c. |
| 2026-10-22 | U1 added | At the user's request, R6's finding became plan slice U1 instead of a note for later: an unchanged native rerun converts every file (frontmatter, links, compressed application data) before `_insert_rows` finds it unchanged, which is why it costs 85% of a fresh import. U1 makes the same `(ID, raw digest)` decision before conversion; its acceptance requires fingerprint-identical results, unchanged collision errors and a measured paired improvement. Ordered after resumed P7c and before resumed 7c; 7c and 7d now depend on U1. Documentation and provenance only, while the R3/R1/R2 batch runs. No worker was used. |
| 2026-10-23 | Resumed P7c results | The Claude Code parent ran the frozen R1–R6 matrix with P7b2 constant; every comparison is fingerprint-identical. On five alternating 10,000-file pairs F04 is faster in every pair (median fresh 0.834, unchanged 0.823, merge 1.000, memory +0.5%). At full scale R1's single gated fresh pair is 0.969, below the frozen 5% gate, with unchanged 0.859 and the ungated fresh setup 0.803; R2's RAW control, with identical code, moved −25% to +31%, so F04's full-scale adoption is held as ambiguous for the user. R4 exported the full RAW library in 1,406 s and reimported the bundle in 2,256 s, losslessly (only the `note_obsidian_*` snapshot columns differ, on the 382,206 notes), but at 3.5 GiB and 1.8 GiB peak RSS from holding the 530 MB manifest. R5's SIGINT, in the inventory and in a batch insert, left no notes, and both reruns matched the uninterrupted fingerprint; two earlier attempts were invalid because a non-interactive shell's `&` made the child ignore SIGINT. The reruns were slow because an empty existing library builds all eight indexes before inserting. The Go producer targets remain unmet. 286 tests in the five required modules pass (149.366 s) and the 11 harness tests pass. I1 and M1 are added from R5 and R4, with the order I1 → M1 after U1 proposed. P7c stays open. No worker was used. Next: the user's F04 and Go-target decisions and the I1/M1 order, then ask to proceed to U1. |
| 2026-10-23 | P7c complete | The user decided: "Remove the Go targets from the plan ; Accept F04 at full scale." F04 is adopted at full scale and stays in `HEAD`; `PERFORMANCE_REVIEW.md` records it. The Go producer targets are removed from the adoption gates and the frozen design, with a dated note. Correction to the row above: they were not "unmet". They were set on `notriosctl` timings at Notrios `7662fdd`, 290 commits before the `v1.0.0` pin and Notrios's own J17/J32 performance work, and P7c never ran Notrios. The P7c evidence and ledger record are corrected to match. Documentation and provenance only. No worker was used. Next: the user's answer on the proposed I1/M1 order, then ask to proceed to U1. |
| 2026-10-23 | Order confirmed | The user answered "Yes to the I1 and M1 order; proceed with U1." The order is U1 → I1 → M1 → resumed 7c → 7d → 7e; 7c and 7d now also depend on I1 and M1, and 7d's CHANGELOG text adds F04, I1 and M1. Documentation only. Next: U1, authorized. |
| 2026-10-23 | U1 complete | The Claude Code parent made `obsidian2sql.py` read note bytes one batch ahead and look up each batch's `(ID, raw digest)` pairs before conversion; a note stored with the same bytes is counted as skipped without being converted, while its tags are still collected and batch boundaries, collision checks and read-error order stay as before. Three tests added; the unchanged-rerun test fails on the previous code. All 289 tests in the five required modules pass (172.590 s). Paired against `9c25e2a`, all outputs fingerprint-identical: unchanged rerun 0.472 (subset, five pairs) and 0.524 (full vault, 983.03 s to 515.14 s); fresh 0.938; merge 1.038, 0.02 s. Fresh-import peak memory rises by one read-ahead batch, +2.1 MB (+4.0%) on the subset and +5.9 MB (+0.8%) on the full vault; the user accepted U1 as measured. No worker was used. Next: ask to proceed to I1. |
| 2026-10-23 | V1 added | The user decided: "Yes, make it an error; add the slice after M1". A damaged preservation bundle (invalid manifest JSON, another format, an unknown version, or `joplin-raw/` without a manifest) will be refused before the output database is touched, instead of the vault being silently imported as native. The error prints the next steps as complete commands built from the failing command line; at the user's direction, a path that depends on how the user's files are organised is a labelled suggestion, and a placeholder is used only for the source database, which nothing records. V1 also adds `--ignore-preservation` and writes the manifest atomically. Ordered after M1 and before resumed 7c; 7c and 7d now depend on V1. Documentation and provenance only. No worker was used. Next: ask to proceed to I1. |
| 2026-10-23 | V1 revised | The user decided: "the absolute path recorded in the exporter should use the `$HOME` environment variable or `~` instead of writing user names in absolute paths ; update plan to record the source database's path in the bundle so step 4 needs no placeholder." V1's exporter now writes `.movenotes/export.json` first, recording the source database (as `~/…` when it is under the home directory) and the export options; the re-export step prints them as an exact command. A placeholder remains only for vaults exported before V1, or with an unreadable record. The manifest's format is unchanged. Documentation and provenance only. No worker was used. Next: I1, authorized ("Then, start I1"). |
| 2026-10-23 | V1 revised again | The user decided: "The `$USER` environment variable is available for other paths containing a user name. Update the plan to replace other instances of paths containing user names." Outside the home directory, V1's export record writes each path segment equal to the user name as `$USER` (as in `/run/media/$USER/HD2/…`), and the importer expands it with its own user name. The record lists the substitutions it applied, so literal `~` or `$USER` in a real path is kept. Documentation and provenance only, while I1's measurements run. No worker was used. |
| 2026-10-23 | I1 complete | The Claude Code parent made `obsidian2sql.py` drop every index but `joplinididx` when it opens a library with no rows, through a new `notesdb.drop_deferred_indexes`; the final pass, or the next open after an interruption, rebuilds them. Three tests added; two fail on the previous code. All 292 tests in the five required modules pass (181.434 s). Alternating pairs against `902bad2`, all outputs fingerprint-identical: empty-library import 0.799 (10,000 files, five pairs) and 0.667 (40,000 files, three pairs); a real SIGINT at 40,000 files left no rows and the rerun matched a new-database import, indexes included. New-database, unchanged and merge medians (1.020, 1.025, 1.041, 0.930) fall inside their pair spreads, on code I1 does not change. No worker was used. Next: ask to proceed to M1. |
| 2026-10-23 | M1 complete | The Claude Code parent made `sql2obsidian.py` stream the preservation manifest in batches of 1,024 items, byte-identical to the previous output, and `obsidian2sql.py` read it one value at a time into compact per-item state. Two tests were added, and all 294 tests in the five required modules pass (138.691 s). A fuzz of 140,000 comparisons against `json.loads` found no mismatch. Alternating pairs against `4dec69b`, all outputs identical, including R4's existing manifest and import fingerprint: peak RSS 0.28 (40,000-file export), 0.39 (its import), 0.22 (full export) and 0.27 (full preserved import); times within noise, and isolated read and write costs measured on R4's manifest. A per-item encoder was 8 s slower and was replaced by batches; a regex reader fast path measured no better and was reverted. No worker was used. Next: ask to proceed to V1. |
| 2026-10-23 | V1 complete | The user authorized V1 ("Start V1"). The Claude Code parent made `obsidian2sql.py` refuse a damaged preservation bundle before touching the output: invalid, empty or non-UTF-8 JSON, another format or version, non-list items, an unreadable manifest, and a `joplin-raw/` copy or export record without a manifest. The error prints the next steps as commands built from the failing command line. Added `--ignore-preservation` and `.movenotes/export.json` (source library as `~/…` or with `$USER` segments, plus options), and made the manifest write atomic. Found while implementing and fixed, recorded as a plan amendment: a stopped re-export, or any `--no-preserve-joplin` one, left the previous bundle beside notes it no longer described. Record values are printed only after a control-character check. 10 tests were added and the reader test rewritten; all 304 tests in the five required modules pass (184.010 s). Every printed command succeeds as printed. Against `7d9a879` the manifests and import fingerprints are identical, and only the record and the bundle README differ. The assignments note no longer lists M1 and V1 as remaining; the M1 commit had changed it only in rendered text. No worker was used. Next: ask to proceed to resumed 7c. |

## Assignment amendment — 2026-10-22

At the user's request, the remaining slices moved from Codex to Claude Code. The
user wrote: "Rewrite the plan to use the main model for all work. The
work-arounds used for codex are not necessary for this terminal CLI." The
parent made this documentation and provenance update, and no worker was spawned.
Product role: Claude Code (terminal CLI). Runtime-reported model: Opus 5.5,
`claude-opus-5-5`, provider Anthropic. Configured alias, reasoning effort, client
version and billing route: not exposed.

| Slice | Previous planned owner | New planned owner |
|---|---|---|
| S43a, S43b | Codex parent (Main) | Claude Code parent (Main) |
| P7b2 | `codex:terra_worker`, `gpt-5.6-terra`, fixed `medium` | Claude Code parent (Main) |
| P7c (remaining) | `codex:luna_worker`, `gpt-5.6-luna`, fixed `max` | Claude Code parent (Main) |
| 7c (remaining) | Codex parent, plus auxiliary Luna monitor | Claude Code parent (Main), no monitor |
| 7d | `codex:luna_worker`, `gpt-5.6-luna`, fixed `max` | Claude Code parent (Main) |
| 7e | Codex parent (Main) | Claude Code parent (Main) |
| Deferred pack tests | Luna | Main |

Retired workarounds for remaining work: the auxiliary Luna monitor, PIDFD
completion notifiers, 25-minute parent notification waits, and the fallback
rules for worker approval stalls. The recorded partial P7c and 7c executions,
including their Luna threads, are unchanged. Scope, acceptance criteria and
slice dependencies are unchanged. The per-item pause and the commit rules still
apply.

Later the same day, in the restarted session, the user confirmed the
assignments: "Yes, these assignments are current for this session." Decisions
recorded with that confirmation:
- The order is S43a → S43b → P7b2 → resumed P7c → resumed 7c → 7d → 7e.
- S43b and resumed 7c pin Notrios `v1.0.0`.
- 7c and 7d now also depend on S43b. This is the one dependency change, made at
  the user's direction because it makes sense.
- Open items about the P7 targets, small-merge noise and 7c's acceptance scope
  are re-evaluated when those slices need them.

## Attribution amendment — 2026-09-14

At the user's request, added coding-agent-specific session confirmation and
mandatory delegation rules, restored historical planned owners, and recorded
planned versus actual execution for all 31 slices. The parent performed this
documentation/provenance update; no worker was spawned. Product role: Codex;
runtime-reported family: GPT-6; exact parent alias/effort, client version,
provider field and billing route: not exposed. The implementation scopes,
dependencies, acceptance criteria and ordering were compared with the prior
plan and are unchanged. Generated attribution/coverage checks and diff checks
pass. No implementation tests were rerun for this documentation update.
At that review, the four uncommitted 5b implementation files were paused for
assigned-worker takeover after confirmation; the focused failures were unresolved.

## Per-slice execution provenance

Generated from the structured ledger; expand a slice to inspect its attribution.

C7a completed on 2026-09-17: parent froze compatibility decisions; Luna executed
the streaming audit (138.46 s corrected run, 35,864 KiB peak RSS) with OS completion
notification. Three producer libraries and 3,000 bounded publication bodies were
audited; 100 snapshot/path pairs matched source bytes and documented recipe-body
transformations. Downstream synthetic probes preserved non-NUL C0 through vault
and Hugo; search whitespace normalization is documented. No new runtime changes
in C7a. Existing reference/unsupported syntax and tag differences remain 7c gates.
See NOTRIOS_COMPATIBILITY_REVIEW.md for limits, independent C7b cases and evidence.

C7b completed on 2026-09-17: assigned Terra implemented non-NUL C0 body
preservation and narrow literal brackets, including parent-requested original-byte
and conservative whitespace suffix checks. Luna ran baseline/candidate fixtures,
264 regressions (145.292 s), bounded corpus retries and live checks with completion
notifications. After the usage limit removed children, parent finished the small
unminified-Hugo/Bluge follow-up without repeating completed runs. Three old fixture
payloads match baseline exactly; the new three-note flow passes. Three real
bounded conversions still refuse unsupported link syntax, so 7c remains incomplete.
Next: C7c (Luna / max), pending restored worker capacity and slice authorization.

<!-- NOTRIOS-EXECUTION:START -->
<details><summary>1a — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Reviewed pinned schemas, verifier, producer and CLI; froze [consumer contract](NOTRIOS_IMPORT_CONTRACT.md). |
| Validation | Parent checked contract fields, limits, links and reference pin; documentation only. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | 9e936b7:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | 9e936b7 |

</details>

<details><summary>1b — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Generated [synthetic publication fixture and reproduction evidence](testdata/notrios/README.md) using the clean pinned CLI's real import/plan/publish commands. |
| Validation | Parent generated the real fixture and checked producer compatibility, full verification and independent byte/selection expectations. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | b0e9ac9:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | b0e9ac9 |

</details>

<details><summary>1c — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Froze [APIs, row/property mapping, conversion limits, identity, staging and link/attachment design](NOTRIOS_IMPORT_DESIGN.md), with [machine-readable vectors](testdata/notrios/design-v1.json). |
| Validation | Parent checked 13 identity vectors, eight link spans and three projected bodies; no runtime suite. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | 9110d74:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | 9110d74 |

</details>

<details><summary>1d — complete; planned luna_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | luna_worker |
| Planned configured model | gpt-5.6-luna |
| Planned reasoning effort | medium |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Implemented directly despite planned worker assignment. Added [offline fixture-copy/inventory/record helpers and baseline assertions](test_notrios2sql.py), plus [baseline and regeneration instructions](testdata/notrios/README.md). |
| Validation | Parent ran nine focused tests and all 112 regressions (56.142s). |
| Delegation failure or reassignment | Historical deviation: parent implemented assigned worker work; no child execution. Progress mentions a session delegation constraint where present; explicit reassignment approval unknown — not recorded. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | b22d2e6:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | b22d2e6 |

</details>

<details><summary>2a — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Added strict bounded JSON, immutable manifest model, Go-compatible canonicalization and declaration/target gates in [notrios_archive.py](notrios_archive.py). |
| Validation | Parent ran 22 focused tests and all 125 regressions (52.843s). |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | 62fc682:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | 62fc682 |

</details>

<details><summary>2b — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Added no-follow fanout reads, streamed checked copies, strict index/envelope checks and a temporary indexed SQLite spool behind `_stage_archive_objects`. |
| Validation | Parent ran 34 focused tests and all 137 regressions (55.635s). |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | 7c965f9:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | 7c965f9 |

</details>

<details><summary>2c — complete; planned terra_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | terra_worker |
| Planned configured model | gpt-5.6-terra |
| Planned reasoning effort | medium |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Implemented directly despite planned worker assignment. Added table-driven rehashed hostile inputs and exact byte-limit boundaries against the frozen APIs. Executed locally under the session delegation constraint. |
| Validation | Parent ran 40 focused tests within all 143 regressions (57.046s). |
| Delegation failure or reassignment | Historical deviation: parent implemented assigned worker work; no child execution. Progress mentions a session delegation constraint where present; explicit reassignment approval unknown — not recorded. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | 6f4b026:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | 6f4b026 |

</details>

<details><summary>2d — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Added typed immutable records, indexed reference/blob joins, bounded notebook walks, publication gates, Go-compatible MIME normalization and the context-owned verifier API. |
| Validation | Parent ran 56 focused tests within all 159 regressions (69.902s). |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | 7cd6c2a:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | 7cd6c2a |

</details>

<details><summary>2e — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Completed the [pinned-verifier audit](NOTRIOS_VERIFIER_AUDIT.md), froze 47 differential cases and measured streaming behavior. Fixed failed-read state and file/directory handle lifetime. |
| Validation | Parent ran 47 differential cases, memory/lifetime checks and all 166 regressions (76.097s). |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | 9fb8e99:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | 9fb8e99 |

</details>

<details><summary>3a — complete; planned luna_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | luna_worker |
| Planned configured model | gpt-5.6-luna |
| Planned reasoning effort | medium |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Implemented directly despite planned worker assignment. Implemented pure deterministic keys/IDs, all five complete row builders, ordered generated properties and the frozen resource suffix map in `notrios_mapping.py`. Executed locally under the session delegation constraint. |
| Validation | Parent ran nine mapping tests within all 175 regressions (76.209s). |
| Delegation failure or reassignment | Historical deviation: parent implemented assigned worker work; no child execution. Progress mentions a session delegation constraint where present; explicit reassignment approval unknown — not recorded. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | 86e3a1e:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | 86e3a1e |

</details>

<details><summary>3b — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Added the internal staged importer, frozen conversion bounds, SQLite identity registry and byte-bounded row batches, completion inventory/receipt, verified reruns and Linux no-replace publication. Executed locally under the session delegation constraint. |
| Validation | Parent ran lifecycle tests within all 189 regressions (86.318s). |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | e331238:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | e331238 |

</details>

<details><summary>3c — complete; planned terra_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | terra_worker |
| Planned configured model | gpt-5.6-terra |
| Planned reasoning effort | medium |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Implemented directly despite planned worker assignment. Validated the existing staged notebook/current-note writer with nine integration tests and real text-only vault export subprocesses. Executed locally under the session delegation constraint. |
| Validation | Parent ran nine focused tests and all 198 regressions (100.849s). |
| Delegation failure or reassignment | Historical deviation: parent implemented assigned worker work; no child execution. Progress mentions a session delegation constraint where present; explicit reassignment approval unknown — not recorded. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | 5c84068:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | 5c84068 |

</details>

<details><summary>3d — complete; planned terra_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | terra_worker |
| Planned configured model | gpt-5.6-terra |
| Planned reasoning effort | medium |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Implemented directly despite planned worker assignment. Implemented the bounded protected-token scanner, exact retained-link reconciliation, note/self/external projection and final-path exporter pass, plus generated RAW title handling. Executed locally under the session delegation constraint. |
| Validation | Parent ran 16 focused tests and all 214 regressions (93.100s). |
| Delegation failure or reassignment | Historical deviation: parent implemented assigned worker work; no child execution. Progress mentions a session delegation constraint where present; explicit reassignment approval unknown — not recorded. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | 5acbf58:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | 5acbf58 |

</details>

<details><summary>S28a — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Update the schema support bound in `notrios_archive.py` to 28, the contract/design's current support declarations and relevant tests. Reconcile collection-field prose and record the new reference pin without rewriting historical provenance. |
| Validation | Parent ran 13 focused tests; all 226 distinct regressions passed across sandbox and HTTP reruns. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | 93755ac:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | f07192c:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | f07192c |

</details>

<details><summary>S28b — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Add a separately pinned synthetic schema-28 publication fixture and reproducible compatibility/verifier evidence using the updated producer. Extend the differential audit and converter/no-op regression evidence as needed; update fixture documentation and this plan. |
| Validation | Parent ran 56 differential cases, 17 focused tests and all 230 regressions (101.920s). |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | 93755ac:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | 10024cc:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | 10024cc |

</details>

<details><summary>4a — complete; planned luna_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | luna_worker |
| Planned configured model | gpt-5.6-luna |
| Planned reasoning effort | medium |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Implemented directly despite planned worker assignment. Added streamed TAG/NOTE_TAG insertion using the frozen builders and indexed ID lookups, with type-count, alias and membership-target checks before publication. Executed locally under the session delegation constraint. |
| Validation | Parent ran four focused tests and all 218 regressions (91.317s). |
| Delegation failure or reassignment | Historical deviation: parent implemented assigned worker work; no child execution. Progress mentions a session delegation constraint where present; explicit reassignment approval unknown — not recorded. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | b987ed5:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | b987ed5 |

</details>

<details><summary>4b — complete; planned luna_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | luna_worker |
| Planned configured model | gpt-5.6-luna |
| Planned reasoning effort | medium |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Implemented directly despite planned worker assignment. Added Unicode, whitespace, quoting, duplicate-name and multiple-membership round trips through the actual vault importer/exporter, plus eleven rehashed invalid-relation cases. Executed locally under the session delegation constraint. |
| Validation | Parent ran four focused tests and all 222 regressions (96.398s). |
| Delegation failure or reassignment | Historical deviation: parent implemented assigned worker work; no child execution. Progress mentions a session delegation constraint where present; explicit reassignment approval unknown — not recorded. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | 6dc7ba2:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | 6dc7ba2 |

</details>

<details><summary>4c — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Reviewed [vault/site tag semantics](NOTRIOS_TAG_REVIEW.md), added real-publication integration coverage and corrected the superseded M2 search description. |
| Validation | Parent ran four focused tests and all 231 regressions (104.534s). |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | 280a6f8:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | 280a6f8 |

</details>

<details><summary>5a — complete; planned terra_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | terra_worker |
| Planned configured model | gpt-5.6-terra |
| Planned reasoning effort | medium |
| Assignment confirmation | historical assignment; not retroactive approval |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | unknown — not recorded |
| Parent underlying model family | unknown — not recorded |
| Parent reasoning effort | unknown — not recorded |
| Parent contribution | Implemented directly despite planned worker assignment. Connected the frozen resource row builder to bounded authenticated copies, exclusive mapped-ID filenames and staged item counts. Corrected the reserved relation table column to `relation_id`. Executed locally under the session delegation constraint. |
| Validation | Parent ran four storage tests and all 235 regressions (103.850s). |
| Delegation failure or reassignment | Historical deviation: parent implemented assigned worker work; no child execution. Progress mentions a session delegation constraint where present; explicit reassignment approval unknown — not recorded. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | cef03a7:NOTRIOS_IMPORT_PLAN.md progress log; Conversation execution record: parent-only implementation; no worker threads recorded. |
| Commit | cef03a7 |

</details>

<details><summary>5b — complete; planned terra_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | terra_worker |
| Planned configured model | gpt-5.6-terra |
| Planned reasoning effort | medium |
| Assignment confirmation | confirmed for current Codex session on 2026-09-14; implementation still requires slice authorization |
| Actual worker | terra_worker |
| Child thread | /root/notrios_5b (native canonical task identifier; separate thread UUID not exposed) |
| Actual model | not exposed — configured worker model gpt-5.6-terra |
| Reasoning effort | not exposed independently — configured fixed medium |
| Worker contribution | Reviewed inherited parent projection/association implementation; completed exact-snapshot attachment materialization, bundle attachment-path retention, and indexed preserved-resource identity checks in obsidian2sql.py/sql2obsidian.py; corrected test setup and finalizer coupling; added semantic-MIME, protected-token, exact/edited snapshot, selected-bundle and missing-resource regressions. |
| Parent | Codex; exact model not exposed |
| Parent underlying model family | GPT-6 (runtime-reported during implementation) |
| Parent reasoning effort | not exposed |
| Parent contribution | Before delegation: initial uncommitted projection, association, exporter and test implementation in four files. After confirmation: spawned and resumed assigned worker, reviewed frozen mapping and snapshot/filtering/bounded-memory invariants, authorized necessary obsidian2sql.py dependency and minimal resource-identity table, requested corrections, integrated a comment correction, updated plan/design/provenance and ran final regression gate. |
| Validation | Worker: 20 focused tests passed (13.642s); after final missing-row fix, ResourceProjection 6/6 (8.861s), plus Obsidian importer 8/8 (11.517s) during review. Parent final five-module suite: all 241 tests passed (117.237s), PYTHONDONTWRITEBYTECODE=1 and python3 -B, local HTTP sockets permitted. Earlier full run also passed 241 (116.538s) before final review completion. Diff and documentation links checked; immutable fixtures unchanged. |
| Delegation failure or reassignment | Earlier parent implementation bypassed planned delegation; no retroactive worker attribution. After explicit confirmation, terra_worker took over. Worker interrupted by usage limit; same worker resumed using followup_task after user requested continuation. No reassignment. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | Uncommitted working tree at attribution review; /tmp/movenotes-5b-resources.log; Native spawn/followup and worker messages for /root/notrios_5b; User explicitly resumed 5b after usage-limit interruption; /tmp/movenotes-5b-tests.log; /tmp/movenotes-5b-tests-before-final-review.log |
| Commit | Git commit containing this completion record: feat: project Notrios resource links and vault attachments |

</details>

<details><summary>5c — complete; planned terra_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | terra_worker |
| Planned configured model | gpt-5.6-terra |
| Planned reasoning effort | medium |
| Assignment confirmation | Confirmed unchanged Codex session; user explicitly authorized 5c. |
| Actual worker | terra_worker |
| Child thread | /root/notrios_5c (native canonical task identifier; separate thread UUID not exposed) |
| Actual model | not exposed — configured worker model gpt-5.6-terra |
| Reasoning effort | not exposed independently — configured fixed medium |
| Worker contribution | Added two attachment regressions and disposable fixture/hash helpers in test_notrios2sql.py: duplicate Unicode/punctuation names, resolved links and escaped labels, bundle and filtered round trips, zero-byte and 9252864-byte opaque resources, bounded tracked reads and independent streamed hashes. No runtime changes. |
| Parent | Codex; exact model not exposed |
| Parent underlying model family | GPT-6 (runtime-reported) |
| Parent reasoning effort | not exposed |
| Parent contribution | Delegated to assigned worker, reviewed consumer filename rules and independent byte/streaming evidence, requested final assertions, updated plan/provenance/fixture documentation and performed final validation. |
| Validation | Worker focused class: 8 tests passed (14.274s), before final assertions. Parent final focused class: 8 tests passed (14.839s). Parent full five-module regression suite: all 243 tests passed (121.125s), with PYTHONDONTWRITEBYTECODE=1 and python3 -B; localhost sockets permitted. Diff and generated attribution checks pass; runtime code and immutable fixtures unchanged. |
| Delegation failure or reassignment | No reassignment. Usage-limit interruption after worker edits; user requested continuation. Worker no longer listed on resume; parent reviewed and validated its completed edits without taking over implementation. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | User: Proceed with 5c; Native spawn of /root/notrios_5c; /tmp/movenotes-5c-focused.log; /tmp/movenotes-5c-final-focused.log; Worker handoff and native followup messages for /root/notrios_5c; User: Continue with 5c after usage limit; /tmp/movenotes-5c-tests.log |
| Commit | Git commit containing this completion record: test: cover Notrios attachment names and streamed bytes |

</details>

<details><summary>5d — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Confirmed unchanged Codex session; user explicitly authorized 5d. |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Codex; exact model not exposed |
| Parent underlying model family | GPT-6 (runtime-reported) |
| Parent reasoning effort | not exposed |
| Parent contribution | Reviewed indexed resource reachability, authenticated private-copy consumption, exclusive descriptor-relative resource writes, completion/no-replace publication, ownership cleanup and immutable reruns. Added three full-import safety regressions and NOTRIOS_RESOURCE_REVIEW.md; updated plan/provenance/fixture documentation. No runtime changes. |
| Validation | 21 focused safety/storage/lifecycle tests passed (5.912s). All 246 tests across the five regression modules passed (124.044s), with PYTHONDONTWRITEBYTECODE=1 and python3 -B; localhost sockets permitted. New tests cover orphan refusal, same-size corruption and symlink at second-resource use, abrupt resource-write process exit, stale-state refusal and inspected manual recovery. Diff, generated attribution and document links checked; runtime code and immutable fixtures unchanged. |
| Delegation failure or reassignment | none — parent-owned slice |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | User: Proceed with 5d; NOTRIOS_RESOURCE_REVIEW.md; /tmp/movenotes-5d-focused.log; /tmp/movenotes-5d-tests.log |
| Commit | Git commit containing this completion record: test: audit Notrios resource publication safety |

</details>

<details><summary>6a — complete; planned luna_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | luna_worker |
| Planned configured model | gpt-5.6-luna |
| Planned reasoning effort | max |
| Assignment confirmation | Confirmed unchanged Codex session; user explicitly authorized 6a. |
| Actual worker | luna_worker |
| Child thread | /root/notrios_6a (native canonical task identifier; separate thread UUID not exposed) |
| Actual model | not exposed — configured worker model gpt-5.6-luna |
| Reasoning effort | not exposed independently — configured fixed max |
| Worker contribution | Added ImportResult.summary() with the explicit status/digests/counts allowlist and fresh dictionary semantics; added independent pinned receipt/summary tests plus pre-rename and post-rename durability failure checks. |
| Parent | Codex; exact model not exposed |
| Parent underlying model family | GPT-6 (runtime-reported) |
| Parent reasoning effort | not exposed |
| Parent contribution | Delegated assigned slice, specified the summary API without changing persisted payload, reviewed receipt allowlist and failure semantics, reconciled design ownership, updated documentation/provenance and ran the final regression gate. |
| Validation | Worker: all 25 focused tests passed (19.302s). Parent: all 249 tests across the five regression modules passed (128.500s), with PYTHONDONTWRITEBYTECODE=1 and python3 -B; localhost sockets permitted. Exact pinned digests, receipt allowlist/serialization, completion equality, fresh path-free summaries, unchanged results and pre/post-rename failures checked. Diff and generated attribution checked; immutable fixtures unchanged. |
| Delegation failure or reassignment | No reassignment. Usage-limit interruption after worker handoff; user requested continuation and parent resumed final validation/documentation. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | User: Proceed with 6a; Native spawn of /root/notrios_6a; /tmp/movenotes-6a-focused.log; Worker handoff for /root/notrios_6a; /tmp/movenotes-6a-tests.log; User resumed 6a after usage limit on 2026-09-15 |
| Commit | Git commit containing this completion record: feat: expose content-free Notrios import summaries |

</details>

<details><summary>6b — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Confirmed unchanged Codex session; user explicitly authorized 6b. |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Codex; exact model not exposed |
| Parent underlying model family | GPT-6 (runtime-reported) |
| Parent reasoning effort | not exposed |
| Parent contribution | Implemented --input/--output and optional reviewed-selection digest CLI with strict non-abbreviated options, single allowlisted JSON stdout result and stderr progress/errors; reused existing importer publication/refusal logic. Added subprocess creation, rerun, mismatch, changed-source, conflict, malformed-usage and sealing-failure checks. Updated finalized CLI design and fixture instructions. |
| Validation | All 4 focused CLI tests passed (10.784s); manual --help inspected. All 253 tests across the five regression modules passed (132.355s), with PYTHONDONTWRITEBYTECODE=1 and python3 -B; localhost sockets permitted. Initial changed-source test used a nonexistent title field; corrected to valid notebook name so it exercises receipt mismatch. Diff, document links and generated attribution checked; immutable fixtures unchanged. |
| Delegation failure or reassignment | none — parent-owned slice |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | User: Proceed with 6b; /tmp/movenotes-6b-focused.log; /tmp/movenotes-6b-tests.log |
| Commit | Git commit containing this completion record: feat: expose safe Notrios publication CLI |

</details>

<details><summary>6c — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Confirmed unchanged Codex session; user explicitly authorized 6c. |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Codex; exact model not exposed |
| Parent underlying model family | GPT-6 (runtime-reported) |
| Parent reasoning effort | not exposed |
| Parent contribution | Specified and implemented strict opt-in receipt propagation from settings to vault and site sidecars; added subprocess, exclusion, validation, rerun and atomic-write regressions; updated design, fixture instructions, plan and provenance. |
| Validation | All 5 focused tests passed (14.751s); all 258 tests across five regression modules passed (160.004s), with PYTHONDONTWRITEBYTECODE=1 and python3 -B and localhost sockets permitted. Help text and diff checked. Initial focused assertions were corrected to exclude timestamped landing pages and expect the normalized receipt write error. Live Hugo/search build acceptance remains 7b. |
| Delegation failure or reassignment | none — parent-owned slice |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | User: Proceed with 6c; continue with 6c after usage limit; notrios_receipt.py; test_notrios2sql.py:NotriosReceiptPropagationTest; /tmp/movenotes-6c-focused.log; /tmp/movenotes-6c-tests.log |
| Commit | Git commit containing this completion record: feat: propagate validated Notrios receipt sidecars |

</details>

<details><summary>6d — complete; planned terra_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | terra_worker |
| Planned configured model | gpt-5.6-terra |
| Planned reasoning effort | medium |
| Assignment confirmation | Confirmed unchanged Codex session; user explicitly authorized 6d. |
| Actual worker | terra_worker |
| Child thread | /root/notrios_6d |
| Actual model | GPT-5 family (worker runtime report); exact execution model alias not exposed |
| Reasoning effort | not exposed — configured medium is not execution evidence |
| Worker contribution | Implemented optional fixed-phase library progress callback and bounded CLI stderr phase/count reporting, completion only after importer return, and help output/exit-code documentation. Extended subprocess tests for exact create/rerun phase ordering, safe help, preflight/sealing/durability/cleanup failures, empty failure stdout and no premature completion. |
| Parent | Codex; exact model not exposed |
| Parent underlying model family | GPT-6 (runtime-reported) |
| Parent reasoning effort | not exposed |
| Parent contribution | Scoped delegation and froze callback semantics; reviewed code and requested exact phase-order and post-publication cleanup-failure coverage; reviewed final worker changes, ran full regression, updated design, fixture instructions, plan and structured provenance, checked document links and diff. |
| Validation | Worker focused CLI suite: all 6 tests passed (13.098s), /tmp/movenotes-6d-focused.log. Parent full five-module regression: all 260 tests passed (149.849s), /tmp/movenotes-6d-tests.log, with PYTHONDONTWRITEBYTECODE=1 and python3 -B and localhost sockets permitted. Diff, local document links and generated attribution checked; immutable fixtures unchanged. |
| Delegation failure or reassignment | No reassignment. User resumed after usage-limit interruption during parent final validation; assigned worker completed implementation and review follow-up. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | User: Proceed with 6d; Native spawn of /root/notrios_6d; Worker handoff for /root/notrios_6d with runtime metadata; /tmp/movenotes-6d-focused.log; Parent review follow-up to /root/notrios_6d; Worker follow-up handoff for /root/notrios_6d; /tmp/movenotes-6d-tests.log; User: Continue with 6d after usage limit |
| Commit | Git commit containing this completion record: feat: report Notrios CLI phases and completion safely |

</details>

<details><summary>7a — complete; planned terra_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | terra_worker |
| Planned configured model | gpt-5.6-terra |
| Planned reasoning effort | medium |
| Assignment confirmation | Confirmed unchanged Codex session; user explicitly authorized 7a. |
| Actual worker | terra_worker |
| Child thread | /root/notrios_7a |
| Actual model | GPT-5 family (worker runtime report); exact execution model alias not exposed |
| Reasoning effort | not exposed — configured medium is not execution evidence |
| Worker contribution | Added NotriosPublicationToVaultAcceptanceTest using actual importer and vault exporter subprocesses on current schema-28 and historical schema-27 frozen resource publications. Checks independent summary/receipt expectations, unchanged source inventory, exact note paths/titles/tags, complete transformed bodies, attachment hashes and excluded sentinels throughout publication and vault. Addressed parent review with full body comparisons and SQLite/marker/vault receipt agreement. |
| Parent | Codex; exact model not exposed |
| Parent underlying model family | GPT-6 (runtime-reported) |
| Parent reasoning effort | not exposed |
| Parent contribution | Scoped delegation and current-schema coverage; reviewed implementation and requested full body and cross-stage receipt assertions; reviewed final worker changes, ran full regression, updated fixture instructions and historical schema-28 scope, plan and provenance, and checked document links/diff. |
| Validation | Worker focused acceptance suite: all 2 tests passed (2.697s), /tmp/movenotes-7a-focused.log. Parent full five-module regression: all 262 tests passed (138.773s), /tmp/movenotes-7a-tests.log, with PYTHONDONTWRITEBYTECODE=1 and python3 -B and localhost sockets permitted. Diff, local document links and generated attribution checked. Runtime code and immutable fixture data unchanged; live Hugo/search and performance acceptance remain 7b/7c. |
| Delegation failure or reassignment | none |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | User: Proceed with 7a; Native spawn of /root/notrios_7a; Worker handoff for /root/notrios_7a with runtime metadata; /tmp/movenotes-7a-focused.log; Parent review follow-up to /root/notrios_7a; Worker follow-up handoff for /root/notrios_7a; /tmp/movenotes-7a-tests.log |
| Commit | Git commit containing this completion record: test: cover Notrios publication to vault acceptance |

</details>

<details><summary>7b — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Confirmed unchanged Codex session; user explicitly authorized 7b. |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Codex; exact model not exposed |
| Parent underlying model family | GPT-6 (runtime-reported) |
| Parent reasoning effort | not exposed |
| Parent contribution | Ran actual schema-28 fixture import/vault/Hugo builds, compiled and queried Bluge, indexed Pagefind and drove desktop/mobile Chromium under /archive/. Found Bluge result URLs losing the prefix; fixed and tested the Ledger adapter in theme commit 85ac1b0, then rebuilt both sites and reran browser acceptance. Added reproducible fixture-only acceptance helpers and report; reviewed screenshots, inventories, tag counts, attachment hashes, receipt exclusion and backend isolation; updated plan/provenance. |
| Validation | Both real builds passed (24 HTML pages each); Pagefind indexed 3 pages/74 words. Four explicit tag counts matched taxonomy and both live backends (3/1/1/1); 12 excluded-sentinel/digest searches per backend returned no results. No browser console errors, HTTP failures or horizontal overflow at 1365x900 and 390x844. Artifact scans passed (103 Bluge, 122 Pagefind files). All 16 theme JS tests passed with --test-isolation=none. All 262 Python regressions passed in 150.295s with both bytecode flags and localhost sockets permitted. Saved browser/artifact helpers rerun successfully. See NOTRIOS_SITE_ACCEPTANCE.md. |
| Delegation failure or reassignment | none — parent-owned slice; user resumed after usage limit. Theme write outside workspace explicitly approved through filesystem escalation. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | User: Proceed with 7b; continue with 7b after usage limit; NOTRIOS_SITE_ACCEPTANCE.md; Ledger theme commit 85ac1b070c657b975629ed728c700694811d6e80; /tmp/movenotes-7b/browser-results.json; /tmp/movenotes-7b/artifact-results.json; /tmp/movenotes-7b/theme-tests.log; /tmp/movenotes-7b-tests.log |
| Commit | Git commit containing this completion record: test: record live Notrios site acceptance |

</details>

<details><summary>C7a — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | User authorized C7a on 2026-09-17; unchanged Codex assignments and long notification monitoring confirmed. |
| Actual worker | luna_worker (audit execution/monitoring and evidence housekeeping) |
| Child thread | /root/notrios_c7a_monitor; /root/c7a_evidence_resume |
| Actual model | not exposed — configured gpt-5.6-luna is not execution evidence |
| Reasoning effort | not exposed independently — configured fixed max |
| Worker contribution | Executed parent-written streaming diagnostic with blocking completion; retained failed setup attempt and reused completed producer scan. Corrected audit completed in 138.46s with 35864 KiB peak RSS. Resumed child verified terminal metadata and owner-only script/result copies without rerunning scans. |
| Parent | Codex; exact model not exposed |
| Parent underlying model family | GPT-6 (runtime-reported) |
| Parent reasoning effort | not exposed |
| Parent contribution | Authored audit/probes, fixed verification work-directory setup, inspected pinned producer frontmatter/identity behavior, traced source controls and 100 preserved snapshot/path pairs, measured tag associations, exercised synthetic downstream control preservation, froze contract/comparison/fixture/version decisions, updated design/plan/provenance, validated docs and committed prior receipt-test correction separately. |
| Validation | Three producer libraries audited (103349/382206/382206 documents) and three bounded publications (1000 each). Source-control trace: all eight Joplin after RAW-title removal, 20 samples per recipe route; bounded publication control counts agree with producers. 100 source snapshots and recipe bodies match after documented prefix/frontmatter/LF transformations; producer titles match 98/100, remaining comparison C7c. Synthetic non-NUL C0 storage/RAW/vault/site/Hugo probe passed; search whitespace projection documented. Focused receipt test passed in 2.403s; prior corrected full 262 suite passed in 139.150s. Document links, diff and generated attribution checks pass. No C7a runtime implementation or claim of full 7c acceptance. |
| Delegation failure or reassignment | Audit attempt1 failed due missing verifier work directory; parent fixed harness and worker resumed without repeating completed scan. Usage limit removed worker threads before final housekeeping; user requested liveness check, then parent spawned same Luna role /root/c7a_evidence_resume. No silent model/owner substitution. |
| Planned assignment evidence | NOTRIOS_IMPORT_PLAN.md compatibility prerequisites added 2026-09-17 |
| Execution evidence | User: revise the plan to address these compatibility gaps before resuming 7c; User explicitly required the same long-notification monitoring for data-heavy updated slices.; Native spawn /root/notrios_c7a_monitor; /tmp/movenotes-c7a-audit.py; NOTRIOS_COMPATIBILITY_REVIEW.md; Private /media/$USER/HD2/movenotes-c7a-20260917/notification.json and execution-time.log; User resumed C7a after usage limit and requested checking agent liveness before waits; Native spawn /root/c7a_evidence_resume; final evidence housekeeping handoff |
| Commit | Git commit containing this completion record: docs: freeze Notrios corpus compatibility decisions |

</details>

<details><summary>C7b — complete; planned terra_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | terra_worker |
| Planned configured model | gpt-5.6-terra |
| Planned reasoning effort | medium |
| Assignment confirmation | User: Proceed with C7b; unchanged confirmed Codex assignments and long notification monitoring. |
| Actual worker | terra_worker (implementation); luna_worker (validation) |
| Child thread | /root/notrios_c7b; /root/c7b_validation |
| Actual model | not exposed — configured worker models are not execution evidence |
| Reasoning effort | not exposed independently — configured Terra medium and Luna max |
| Worker contribution | Terra implemented non-NUL C0 body admission, conservative flat literal brackets and independent positive/adversarial regressions; corrected masked-escape/backtick acceptance and C0/Unicode suffix handling after parent review. Luna ran baseline/candidate fixtures, the full five-module suite, original bounded corpus conversions and initial live builds using blocking completion notifications. |
| Parent | Codex; exact model not exposed |
| Parent underlying model family | GPT-6 (runtime-reported) |
| Parent reasoning effort | not exposed |
| Parent contribution | Scoped Terra delegation and reviewed the implementation; requested original-byte and suffix-validation corrections. Prepared frozen baseline and independent validation harnesses, repaired checkpoint/output path collision and distinguished minified HTML whitespace from exact preserved bytes. After usage-limit registry confirmed no children and a one-time process check found no active validation, finished only the remaining three-note unminified-Hugo/Bluge check in one blocking invocation. Reviewed evidence/source fingerprints, updated design/plan/provenance and committed C7b. |
| Validation | Worker focused tests passed. All 264 five-module regressions passed in 145.292s with both bytecode controls. Three immutable fixture payloads match baseline 5b2a7e2 exactly (15 files / 376112 bytes); imports and unchanged reruns pass. Independent three-note CLI/vault/Hugo/Bluge passes, including exact non-NUL C0 preservation in SQLite/RAW/vault/unminified HTML and documented HTML/search whitespace projections. All three original 1000-document conversions still refuse unsupported link syntax: retained 7c blockers, not acceptance passes. Final runtime source fingerprints match the passing suite. Diff, document links and generated attribution checked. |
| Delegation failure or reassignment | No implementation reassignment. Initial live harness output/checkpoint collision and overstrict minified-HTML assertion were corrected with historical failures retained. Usage limit removed completed worker threads; no agents survived on registry check. Parent performed remaining small final validation within its existing review/validation scope, without repeating data-heavy runs. Resumed runtime now has one active-agent slot; future delegation requires restored capacity or approved reassignment. |
| Planned assignment evidence | NOTRIOS_IMPORT_PLAN.md compatibility prerequisites added 2026-09-17 |
| Execution evidence | User: revise the plan to address these compatibility gaps before resuming 7c; User explicitly required the same long-notification monitoring for data-heavy updated slices.; User: Proceed with C7b; Native spawn /root/notrios_c7b and /root/c7b_validation; Baseline 5b2a7e2; /tmp/movenotes-c7b-validate.py and /tmp/movenotes-c7b-live.py; NOTRIOS_COMPATIBILITY_REVIEW.md C7b implementation and validation; Private /media/$USER/HD2/movenotes-c7b-20260917 baseline/candidate/live notifications and regression log; Worker final handoff /root/notrios_c7b; monitor handoffs /root/c7b_validation; User resumed C7b after usage limit and required liveness check; registry returned only parent; Parent final live script exit 0; runtime hashes match passing regression checkpoint |
| Commit | Git commit containing this completion record: feat: admit preserved Notrios controls and literal brackets |

</details>

<details><summary>C7c — complete; planned luna_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | luna_worker |
| Planned configured model | gpt-5.6-luna |
| Planned reasoning effort | max |
| Assignment confirmation | User authorized C7c conditional on sufficient capacity; runtime reports two total slots and Luna spawn succeeded on 2026-09-17. Existing Codex model/effort and billing suitability confirmation retained. |
| Actual worker | luna_worker |
| Child thread | /root/c7c_harness |
| Actual model | not exposed |
| Reasoning effort | not exposed |
| Worker contribution | Implemented notrios_c7c.py, paired source smoke, PIDFD monitor/durable child receipts and 26 focused tests. Corrected source grammar, route rules, privacy projections, duplicate joins, full-input/dependency fingerprinting and disk/query bounds after parent review. Executed existing regression suite, scaled tests, bounded probes and final monitored corpus comparison; retained failed attempts and sanitized evidence. |
| Parent | Codex |
| Parent underlying model family | GPT-6 |
| Parent reasoning effort | not exposed |
| Parent contribution | Verified restored capacity, delegated assigned Luna, reviewed implementation and requested concrete corrections for stale results, duplicate accounting, source integrity, publication cohorts/privacy transforms, parser rules, quadratic joins and checkpoint dependencies. Reviewed final aggregate results and source fingerprint, updated plan/provenance/evidence and performed final checks/commit. No worker-owned implementation substituted. |
| Validation | 264 existing tests passed (180.404s); final 26 focused tests passed (19.851s), including 20k scaled query execution, checkpoint/resume/reconnect, dependency/blob mutation and disk/query bounds. Accepted v6 corpus: 382,206 source records per route, all identities/bodies match, vault metadata matches, 3,682 titles explained, zero unexplained source-to-route differences with explicitly separate tag channels. Three 1,000-document publications verified; Joplin 987 exact + 13 privacy projections. Runtime 5,174s, RSS 336,784 KiB; semantic_equal false, full 7c not accepted. Final checkpoint-only changes tested without repeating unchanged semantic corpus rules. |
| Delegation failure or reassignment | No reassignment. Previous one-slot capacity limitation resolved; native Luna spawn succeeded. |
| Planned assignment evidence | NOTRIOS_IMPORT_PLAN.md compatibility prerequisites added 2026-09-17 |
| Execution evidence | Native worker /root/c7c_harness; configured Luna/max; execution backend model/effort not independently exposed.; NOTRIOS_C7C_EVIDENCE.md; Historical completed run /tmp/movenotes-c7c-20260918-final; failed attempts /tmp/movenotes-c7c-20260917-corrected and /tmp/movenotes-c7c-20260918-indexed.; Accepted v6 attempt /tmp/movenotes-c7c-20260918-rules-v6b-final: launch.json, comparison/result.json, checkpoint.json, comparison-progress.json, monitor receipt and terminal-notification.json. Run 652f8054ca8f2cef29879813; monitor 9560ea9c593e43309e14a700ae460a00.; Final comparator semantic corpus fingerprint 8304857a5e1fa79b3f8cbac61a323abb3e52498f1f56d45314e7db2f06ee3ea0; later fingerprint/disk-only hardening has 26 passing focused tests. |
| Commit | this commit |

</details>

<details><summary>P7a — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | parent |
| Planned configured model | not exposed |
| Planned reasoning effort | not exposed |
| Assignment confirmation | User: Proceed with P7a. Existing confirmed Codex roles/efforts/billing suitability retained; two slots permit parent and auxiliary Luna monitor. |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Codex |
| Parent underlying model family | GPT-6 |
| Parent reasoning effort | not exposed |
| Parent contribution | Audited three reviews, pinned/current sources and profiles; authored sequential profile/timing harness, probes, artifact inventories, tests and evidence report; froze candidate ownership and benchmark protocol. No production importer edits. |
| Validation | 30-note smoke; completed 2000-note Python/pinned-Go multi-route profiling; three unprofiled fresh imports; five baseline probes; two artifact-inventory tests. See NOTRIOS_PERFORMANCE_EVIDENCE.md. |
| Delegation failure or reassignment | No reassignment. Parent owns P7a investigation; auxiliary Luna owns data-heavy execution and monitoring. |
| Planned assignment evidence | NOTRIOS_IMPORT_PLAN.md performance prerequisites added 2026-09-17 |
| Execution evidence | User authorization: Proceed with P7a; additional requested Notrios review ~/projects/notrios/performance-code-review.md.; Native monitor /root/p7a_monitor; scripts/notrios_p7a_profile.py and scripts/notrios_p7a_probes.py.; NOTRIOS_PERFORMANCE_EVIDENCE.md; Private completed monitor and unprofiled roots under /media/$USER/HD2/movenotes-p7a-20260918-*: manifests, notification.json, profiles/results and ARTIFACT_MANIFEST.json. |
| Commit | P7a completion commit (contains this ledger) |

</details>

<details><summary>P7b — complete; planned terra_worker</summary>

| Property | Value |
|---|---|
| Coding agent | codex |
| Planned worker | terra_worker |
| Planned configured model | gpt-5.6-terra |
| Planned reasoning effort | medium |
| Assignment confirmation | User: Proceed with P7b. Unchanged confirmed Codex roles/efforts/billing suitability; two total slots allow staged Terra implementation and Luna monitoring. |
| Actual worker | terra_worker |
| Child thread | /root/p7b_candidates |
| Actual model | not exposed |
| Reasoning effort | not exposed |
| Worker contribution | Terra implemented F02 early existing-index creation, F04 path reuse, C01/C02 collision fixes, focused tests, durable comparison and long-batch scripts, and disposable current-Notrios G08 patch/benchmarks. G01 and F03/F07/F08 deferred with rationale. |
| Parent | Codex |
| Parent underlying model family | GPT-6 |
| Parent reasoning effort | not exposed |
| Parent contribution | Reviewed resource validation barrier, index lifecycle and merge cost, output comparator completeness, durable status, source pin isolation; prepared frozen baseline/candidate source copies and staged Luna execution. |
| Validation | 299 Python tests passed; all18 imports completed, corrected comparison matches all pairs with unchanged source/input hashes; both disposable Go full suites passed; G08 microbench regressions reject current candidate. Four final comparator tests pass. NOTRIOS_P7B_EVIDENCE.md. |
| Delegation failure or reassignment | Usage limit stopped Terra; registry confirmed error then same assigned worker resumed. Original Luna monitor unavailable after interruption; same configured role resumed as /root/p7b_monitor_resume. No implementation reassignment. |
| Planned assignment evidence | NOTRIOS_IMPORT_PLAN.md performance prerequisites added 2026-09-17 |
| Execution evidence | User requested investigation of Union Alpha and Grok 4.6 performance reviews and adoption only after demonstrated improvement.; Native spawn /root/p7b_candidates following user authorization: Proceed with P7b.; NOTRIOS_P7B_EVIDENCE.md; Private /media/$USER/HD2/movenotes-p7b-20260918 and -go notifications/logs/manifests; python-comparison/RECOMPARE_REPORT.json preserves original failed comparison.; User continued P7b after usage limit; registry checked before worker recovery. |
| Commit | P7b completion commit (contains this ledger) |

</details>

<details><summary>P7b2 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-22; user authorized: Proceed (after the E1 report asking whether to proceed to P7b2). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code |
| Parent underlying model family | Claude Opus 5.5 (runtime-reported model ID claude-opus-5-5) |
| Parent reasoning effort | not exposed |
| Parent contribution | Measured two bounded treatments against the previous code (joplinididx created with a new database; an in-memory map of this run's IDs) on 10,000- and 40,000-file recipe subsets and a ten-note merge, adopted the index treatment in obsidian2sql.py, updated the notesdb.ensure_joplin_id_index docstring, added a query-plan regression test, ran a full-corpus scale check, and updated PERFORMANCE_REVIEW.md, NOTRIOS_P7C_EVIDENCE.md and the resumed P7c plan (F02 subsumed; full-corpus memory and unchanged-rerun cost; evidence mount path). |
| Validation | All outputs fingerprint-identical across treatments: 10,000-file fresh/unchanged (2 runs each), 40,000-file fresh, ten-note merge into a 10,000-file library (3 runs per side). 40,000-file fresh import: 330.45 s previous, 130.08 s adopted, 136.81 s in-memory map (+~50 MiB). Full corpus 382,206 files / 1,237,552 items: fresh 1,628.36 s (peak RSS 774,844 KiB), identical rerun skipped all items in 1,388.56 s; interrupted P7c baseline ran 17,943.11 s without finishing. New query-plan regression test fails on the previous code. All 286 tests in the five required modules passed (180.679s) with PYTHONDONTWRITEBYTECODE=1 and -B; test_notrios_p7c.py 10 tests pass. |
| Delegation failure or reassignment | 2026-10-22 user reassignment from codex terra_worker (gpt-5.6-terra, fixed medium) to the Claude Code parent before any work started; previous assignment kept in assignment_history. Not a delegation failure. |
| Planned assignment evidence | P7c full-scale finding; NOTRIOS_P7C_EVIDENCE.md; 2026-10-22 user reassignment to the Claude Code parent |
| Execution evidence | P7c stopped full baseline in _existing_import_hashes; EXPLAIN SCAN notes before index.; User: Proceed; Private /run/media/$USER/HD2/movenotes-p7b2-20261022-full-native (P7B2_SCALE_CHECK.json, logs, times, source tree); NOTRIOS_P7C_EVIDENCE.md P7b2 resolution |
| Commit | Git commit containing this completion record: perf: index item IDs before a fresh Obsidian import (P7b2) |

</details>

<details><summary>P7c — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex (partial execution to 2026-09-19); claude (remaining work) |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Codex partial run: User: Proceed with P7c. Existing Codex roles, efforts and billing suitability confirmed for unchanged session. Remaining work: Claude Code session assignments confirmed by user on 2026-10-22; resume authorized by the user on 2026-10-22 (Proceed). |
| Actual worker | luna_worker |
| Child thread | /root/p7c_validation |
| Actual model | not exposed |
| Reasoning effort | not exposed |
| Worker contribution | Authored variants, matrix/long-batch/subset/merge harnesses and tests; executed synthetic isolated F02/F04 and RAW control matrices. Prepared remaining final-validation commands. |
| Parent | Codex (partial run to 2026-09-19); Claude Code parent (remaining work) |
| Parent underlying model family | GPT-6 (Codex partial run); Claude Opus 5.5, runtime-reported claude-opus-5-5 (remaining work) |
| Parent reasoning effort | not exposed |
| Parent contribution | Reviewed resume/input/metric correctness; launched real10k and fullnative/final prepared tests after worker external-tool approval stalls; long tool-side waits. Interrupted full baseline at17,943.11s, traced unindexed batch lookup and confirmed EXPLAIN/VM scaling. Added P7b2 prerequisite; no production edits. 2026-10-22/23, Claude Code parent: froze the resumed design (R1-R6) before running; fixed notrios_p7c_prepare.py's F02 marker for P7b2 and recorded the P7b2 constant; ran R3 (five alternating 10,000-file pairs), R1 (full native pair), R2 (full RAW control pair), R4 (full sql2obsidian export and preserved import, plus a column comparison with the RAW library), R5 (SIGINT recovery at 40,000 files, plus new-versus-empty-library checks) and R6 (cProfile of an unchanged rerun); recorded the results in NOTRIOS_P7C_EVIDENCE.md; planned U1, I1 and M1 from R6, R5 and R4. Corrected the Go-target report (stale, not unmet) and recorded the user's decisions in the plan and evidence. |
| Validation | Isolated synthetic and real10k comparisons match. Corrected prepared-seed5pairs match; smallmerge slower/noisy remains unresolved. Fullbaseline interrupted17943.11s in unindexed lookup, candidate not run. Ten focused harness tests pass. Full acceptance blocked; NOTRIOS_P7C_EVIDENCE.md. 2026-10-23 resumed P7c: every comparison fingerprint-identical. R3 10,000 files, five alternating pairs, f04/base medians fresh 0.834, unchanged 0.823, merge 1.000; RSS +0.5%. R1 full native single pair: fresh 0.969, unchanged 0.859, ungated fresh setup 0.803; RSS +2.4-3.4%. R2 RAW control (identical joplin2sql.py): 1.307, 0.755, 0.933, so single-pair noise reaches 31%. F04 meets the subset gate; its full-scale gate (R1 >=5%) could not be resolved by one pair, and the user accepted F04 at full scale on 2026-10-23. R4: export 1,406 s at 3,668,096 KiB, preserved import 2,256 s at 1,936,788 KiB; all 1,237,553 items present and 69 of 75 columns identical, only the note_obsidian_* snapshot columns differ on the 382,206 notes. R5: SIGINT in inventory and in batch insert both leave 0 notes, and both reruns match the uninterrupted fingerprint. Go producer targets were stale (set on Notrios 7662fdd, not v1.0.0) and never measured here; the user removed them from the plan on 2026-10-23. 286 tests in the five required modules pass (149.366 s) with PYTHONDONTWRITEBYTECODE=1 and -B; test_notrios_p7c.py 11 tests pass. |
| Delegation failure or reassignment | Worker external ps/approval calls stalled; parent final-validation launches and long tool waits used after confirming no active process. Worker could not access parent terminal session. No implementation reassignment. 2026-10-22: user reassigned the remaining P7c work from codex luna_worker (gpt-5.6-luna, fixed max) to the Claude Code parent and retired the Luna monitor; the partial Luna record above is unchanged. No worker was used for the remaining work. |
| Planned assignment evidence | NOTRIOS_IMPORT_PLAN.md performance prerequisites added 2026-09-17; 2026-10-22 user reassignment to the Claude Code parent |
| Execution evidence | User requested investigation of Union Alpha and Grok 4.6 performance reviews and adoption only after demonstrated improvement.; User: Proceed with P7c; native spawn /root/p7c_validation; NOTRIOS_P7C_EVIDENCE.md; Private movenotes-p7c-* HD2 manifests, source hashes, results, failed full trial and child traceback.; User: Proceed (resumed P7c, 2026-10-22); Private /run/media/$USER/HD2/movenotes-p7c-20261022-{sources,variants,r3-subset,r1r2-full,r4-preserved,r5-recovery}; NOTRIOS_P7C_EVIDENCE.md, Resumed P7c — F04 with P7b2 constant; User, 2026-10-23: Remove the Go targets from the plan ; Accept F04 at full scale. |
| Commit | P7c partial-evidence checkpoint; 6f010c6 resumed-P7c results; P7c completion commit (contains this ledger) |

</details>

<details><summary>U1 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-22; U1 authorized by the user on 2026-10-23 (Yes to the I1 and M1 order; proceed with U1). On 2026-10-23 the user accepted U1 as measured, including the bounded fresh-import memory increase. |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | Implemented the batched read-ahead in obsidian2sql.py: _native_rows reads note bytes one batch ahead, looks up the batch's (ID, raw digest) pairs with _existing_import_hashes, and yields _UnchangedNote markers for notes stored with the same bytes instead of converting them; tags are still collected for every note; import_native_rows counts markers as skipped and keeps batch boundaries with batch_slots; read errors are re-raised in file order. Added three tests to test_obsidian2sql.py. Ran the paired alternating base-versus-U1 benchmark with scripts/notrios_p7c_benchmark.py on the 10,000-file subset and the full vault, recorded the results and put the fresh-import memory increase to the user. |
| Validation | All 289 tests in the five required modules pass (172.590 s) with PYTHONDONTWRITEBYTECODE=1 and -B, including test_unchanged_rerun_converts_no_note (fails on the previous code), test_skipped_notes_still_restore_missing_tags and test_unreadable_note_after_unchanged_notes_reports_utf8_error. Paired alternating runs, base 9c25e2a against U1, every output fingerprint-identical: 10,000-file subset, five pairs each, median U1/base unchanged rerun 0.472, fresh import 0.938, ten-note merge 1.038 (0.02 s on 0.55 s, pairs -0.04 to +0.08 s); full vault, one pair, unchanged rerun 0.524 (983.03 s to 515.14 s). Ungated setup imports: subset fresh 0.86-0.98 in all five, full-vault fresh 1.042 (1,537.89 s to 1,601.87 s, one run). Peak RSS: unchanged -2.1 MB subset and -1.9 MB full; fresh +2.1 MB (+4.0%) subset and +5.9 MB (+0.8%) full, from one batch of read-ahead notes; merge +0.5 MB. The user accepted U1 as measured on 2026-10-23. RAW (joplin2sql.py) and preserved-bundle items are unchanged code; R2 and R4 stand for them. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | Resumed P7c R6 profile, 2026-10-22; user: Add a plan item to fix this. |
| Execution evidence | NOTRIOS_P7C_EVIDENCE.md, section U1 — unchanged notes skipped before conversion; /run/media/$USER/HD2/movenotes-u1-20261023-sources (SOURCES.txt, harness copies, run_u1.sh, run_u1.log); /run/media/$USER/HD2/movenotes-u1-20261023-subset/results.json; /run/media/$USER/HD2/movenotes-u1-20261023-full/results.json; Scratch profile /tmp/claude-$UID/-home-$USER-projects-movenotes-v3/<session>/scratchpad/p7c-r6/unchanged.prof |
| Commit | Git commit containing this completion record: perf: skip unchanged vault notes before converting them (U1) |

</details>

<details><summary>I1 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-22; I1 authorized by the user on 2026-10-23 (Then, start I1). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | Added notesdb.drop_deferred_indexes and made obsidian2sql.py call it when the library it opens holds no rows, so the import inserts with only joplinididx and the final pass rebuilds the rest. Added three tests to test_obsidian2sql.py. Wrote an alternating empty-library driver (i1_empty.py) and ran it with scripts/notrios_p7c_benchmark.py and a real SIGINT recovery at 10,000 and 40,000 files; recorded the results. |
| Validation | All 292 tests in the five required modules pass (181.434 s) with PYTHONDONTWRITEBYTECODE=1 and -B, including test_import_into_empty_library_defers_indexes and test_interrupted_imports_recover_with_the_same_indexes (both fail on the previous code) and test_import_into_non_empty_library_keeps_its_indexes. Alternating pairs, base 902bad2 against I1, every output fingerprint-identical: empty-library import median I1/base 0.799 at 10,000 files (five pairs, 0.761-0.874) and 0.667 at 40,000 files (three pairs, 0.533-0.670), same fingerprint and index set as a new-database import. SIGINT 60 s into a 40,000-file I1 import left 0 rows and only joplinididx; the rerun took 140.41 s at 126,140 KiB and matched the new-database fingerprint, ending with all nine indexes. Regression cases on code I1 does not change (one added SELECT): fresh 1.020 (10,000, 0.966-1.041) and 1.025 (40,000, 0.991-1.029), unchanged 1.041 (0.908-1.101), merge 0.930 (0.889-1.000); peak RSS unchanged. joplin2sql.py not changed. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | Resumed P7c R5 recovery check, 2026-10-23; user directive: Update the plan if you find items that need to be fixed instead of just logging their existence. |
| Execution evidence | NOTRIOS_P7C_EVIDENCE.md, section I1 — empty existing library imported like a new one; /run/media/$USER/HD2/movenotes-i1-20261023-sources (SOURCES.txt, i1_empty.py, run_i1.sh, run_i1.log, harness copies); /run/media/$USER/HD2/movenotes-i1-20261023-runs (empty-10k, empty-40k, harness-10k, harness-40k, interrupt-40k) |
| Commit | Git commit containing this completion record: perf: import into an empty library like a new one (I1) |

</details>

<details><summary>M1 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-22; M1 authorized by the user on 2026-10-23 (Proceed with M1.). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | Added sql2obsidian._ManifestWriter, which writes the preservation manifest as items are produced, 1,024 items per encode, byte-identical to the previous json.dumps; the first per-item version was 8 s slower on R4's manifest and was replaced by batches. Replaced obsidian2sql._load_manifest with an incremental _JsonReader over json.JSONDecoder.raw_decode and 1 MiB reads, keeping a compact _Manifest (item count, RAW paths, resource IDs, note ID/path/digest), with a number cut by the buffer end retried; _import_preserved_joplin uses it. A regex separator fast path measured no better and was reverted. Added test_streamed_manifest_matches_one_json_dump and test_manifest_reader_matches_json_loads. Wrote m1_pairs.py, run_m1.sh, micro.py and fuzz.py; ran the paired, isolated and fuzz measurements and recorded them. |
| Validation | All 294 tests in the five required modules pass (138.691 s) with PYTHONDONTWRITEBYTECODE=1 and -B. fuzz.py: 140,000 comparisons of the reader with a json.loads reference, read sizes 1 character to 1 MiB, damaged documents included, 0 mismatches. Alternating pairs against 4dec69b, every exit zero and every output identical: 40,000-file export (132,775 items) manifest 5a315af0... and vault 30f45283..., final writer median time 0.986 and peak RSS 0.279 (384,852 -> 107,500 KiB); its preserved import fingerprint a6f1f307... with the same summary, time 1.063 (1.018-1.121) and RSS 0.393; synthetic bundle fresh 1.038 (0.962-1.087), unchanged 0.999. Full library (1,237,553 items), one pair: export manifest 61daef6c..., byte-identical to R4's, vault b7770fad..., RSS 3,637,316 -> 816,632 KiB, time 1.099 with the per-item writer; preserved import of R4's old-code vault fingerprint 8c0991bf... (R4's) with the same summary, RSS 1,936,876 -> 515,968 KiB, time 0.932. Isolated on R4's manifest: read 25.4 s against json.loads 21.7 s (302,700 against 1,933,600 KiB); final write 24.9 s against json.dumps 26.2 s, same bytes. Paired time changes are within the gate's noise (R2 control up to 31%). |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | Resumed P7c R4 full preserved route, 2026-10-23; user directive: Update the plan if you find items that need to be fixed instead of just logging their existence. |
| Execution evidence | NOTRIOS_P7C_EVIDENCE.md, section M1 — preservation manifest streamed both ways; /run/media/$USER/HD2/movenotes-m1-20261023-sources (SOURCES.txt, SOURCES-m1b.txt, m1_pairs.py, m1b_pairs.py, run_m1.sh, run_m1.log, micro.py, micro-results.txt, fuzz.py, harness copies); /run/media/$USER/HD2/movenotes-m1-20261023-runs (export-40k, export-40k-m1b, import-40k, harness-preserved, export-full, import-full, full-manifests.txt) |
| Commit | Git commit containing this completion record: perf: stream the preservation manifest both ways (M1) |

</details>

<details><summary>V1 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-22; V1 authorized by the user on 2026-10-23 (Start V1). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code parent |
| Parent underlying model family | Claude Opus 5.5, runtime-reported claude-opus-5-5 |
| Parent reasoning effort | not exposed |
| Parent contribution | obsidian2sql.py: _check_bundle runs before the output is touched and raises _BundleProblem (unreadable, syntax, format, version, items, no-manifest, unfinished); _JsonReader reports absolute offsets and whether the file was cut, described with line, column, byte and size; _refusal prints the applicable next steps as shlex-quoted commands from sys.orig_argv, with a labelled suggested re-export directory and the recorded source and options or a labelled SOURCE_LIBRARY placeholder; added --ignore-preservation; record values with control characters are refused and dash-led notebook names printed as --notebooks=VALUE. obsidianmeta.py: portable_path and expand_portable_path (~/ under home, $USER segments, substitutions listed). sql2obsidian.py: start_preservation_bundle removes any previous bundle and writes .movenotes/export.json before the first note; _ManifestWriter writes manifest.json.partial, fsyncs and renames. Found and fixed during V1 (plan amendment): a re-export stopped among the notes, or any --no-preserve-joplin re-export, left the previous bundle beside notes it no longer described. README section and bundle README line. Added DamagedBundleTest (10 tests) and rewrote the reader test for refusal kinds; wrote v1_roundtrip.py, run_v1.sh and fuzz-v1.py and recorded the results. |
| Validation | All 304 tests in the five required modules pass (184.010 s) with PYTHONDONTWRITEBYTECODE=1 and -B; the 15 harness tests pass. Every new DamagedBundleTest test except the valid-bundle one fails on 7d9a879. Eleven refusal cases refuse against a new and an existing library and write nothing to either; the full message is checked exactly; every printed command runs as printed from a fixture with spaces in its paths and succeeds (restore, RAW copy, --ignore-preservation, and a re-export that reproduces the original vault byte for byte with its recorded --notebooks and --no-frontmatter). Export-record tests cover ~/, $USER segments, a segment merely containing the name, expansion under another HOME and USER with the not-found label, literal ~ and $USER directories, missing, unreadable, foreign and control-character records. fuzz-v1.py: 140,000 comparisons with a json.loads reference, 0 mismatches; truncating two real manifests at every offset is always refused as cut short. Against 7d9a879 on the 40,000-file library: exports differ only in .movenotes/export.json and README.md, manifests byte-identical (5a315af0...), import fingerprints identical (a6f1f307...) with the same summary; harness preserved, preserved-unchanged, native, native-unchanged and native-small-merge fingerprint-identical over three alternating pairs. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | 2026-10-23 user: Yes, make it an error; add the slice after M1 ; Option 4 should use actual paths if available (eg. command line that caused the error has paths to input files) ; only use placeholders if necessary ; paths that require knowledge of how files are organized aren't readily apparent to user so a suggestion instead of a placeholder would be useful (as long as it is identified as such). Revised the same day, user: If the absolute path is under the user's /home directory, the absolute path recorded in the exporter should use the $HOME environment variable or ~ instead of writing user names in absolute paths ; update plan to record the source database's path in the bundle so step 4 needs no placeholder. Revised again the same day, user: The $USER environment variable is available for other paths containing a user name. Update the plan to replace other instances of paths containing user names. |
| Execution evidence | NOTRIOS_P7C_EVIDENCE.md, section V1 — damaged preservation bundles refused; /run/media/$USER/HD2/movenotes-v1-20261023-sources (SOURCES.txt, v1_roundtrip.py, run_v1.sh, run_v1.log, fuzz-v1.py, harness copies); /run/media/$USER/HD2/movenotes-v1-20261023-runs (roundtrip-40k, harness) |
| Commit | Git commit containing this completion record: feat: refuse a damaged preservation bundle with recovery commands (V1) |

</details>

<details><summary>7c — in progress; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | codex (partial execution to 2026-09-16); claude (remaining work) |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Codex partial run: Confirmed unchanged Codex session; user explicitly authorized 7c. Remaining work: Claude Code session assignments confirmed by user on 2026-10-22; resumed 7c authorized by the user on 2026-10-23 (Start it.), with the work on the internal disk (user answer: Internal disk). |
| Actual worker | luna_worker (harness/monitoring only) |
| Child thread | /root/notrios_7c_monitor |
| Actual model | not exposed — configured worker model is not execution evidence |
| Reasoning effort | not exposed — configured max is not execution evidence |
| Worker contribution | Completed durable checkpointed harness, corrected pinned-CLI batch limit to 500, monitored imports with OS completion notifications, ran bounded routes, synthetic full pipeline, recovery, semantic comparison and regressions; retained failures and skipped dependent full trials. Proved historical test hashes are row permutations and ran corrected 262-test regression gate successfully. |
| Parent | Codex; exact model not exposed |
| Parent underlying model family | GPT-6 (runtime-reported) |
| Parent reasoning effort | not exposed |
| Parent contribution | Inspected producer pin and source sizes, prepared initial harness and isolated measurements, investigated Joplin lexical refusal, reviewed terminal evidence and recorded partial acceptance; used 25-minute native notification waits with occasional fallback checks. Corrected nondeterministic receipt-test search row comparison; sampled control characters and embedded frontmatter differences; retained 7c as incomplete. |
| Validation | Partial corpus acceptance: both 382,206-document recipe imports succeeded; three bounded real publications passed both verifiers but conversion refused. Full real tiers skipped. Synthetic 10,000 pipeline and recovery passed. Initial semantic multisets differ and include embedded frontmatter; refined semantic audit pending. Corrected full regression passed all 262 tests in 139.150s. Historical failure proven to be JSONL row permutation. See NOTRIOS_CORPUS_TRIALS.md. |
| Delegation failure or reassignment | User explicitly added Luna harness/monitoring delegation to parent-owned 7c to reduce model usage; no silent substitution. 2026-10-22: user moved the remaining 7c work to the Claude Code parent and retired the Luna harness/monitoring delegation. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md |
| Execution evidence | User: Proceed with 7c; User request for Luna monitoring with long notification waits; native spawn /root/notrios_7c_monitor; NOTRIOS_CORPUS_TRIALS.md; Private /media/$USER/HD2/movenotes-7c-20260916/notification.json and resume/final-regressions.log; 2ea17ca: committed receipt-test ordering correction; 7c remains incomplete; 2026-10-23: resumed 7c design frozen in NOTRIOS_IMPORT_PLAN.md before any run |
| Commit | none — uncommitted |

</details>

<details><summary>7d — pending; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-22; slice implementation still requires authorization. |
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
| Delegation failure or reassignment | 2026-10-22 user reassignment from codex luna_worker (gpt-5.6-luna, fixed max) to the Claude Code parent before any work started; previous assignment kept in assignment_history. Not a delegation failure. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md; 2026-10-22 user reassignment to the Claude Code parent |
| Execution evidence | none |
| Commit | pending |

</details>

<details><summary>7e — pending; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-22; slice implementation still requires authorization. |
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
| Delegation failure or reassignment | 2026-10-22: coding agent changed from the Codex parent to the Claude Code parent by user; planned owner unchanged. |
| Planned assignment evidence | e3af032:NOTRIOS_IMPORT_PLAN.md; 2026-10-22 coding-agent change to Claude Code |
| Execution evidence | none |
| Commit | pending |

</details>

<details><summary>S43a — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-22; user authorized: Commit the plan amendment, then proceed with S43a. |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code |
| Parent underlying model family | Claude Opus 5.5 (runtime-reported model ID claude-opus-5-5) |
| Parent reasoning effort | not exposed |
| Parent contribution | Read the producer's J43 TitleSuffix implementation at v1.0.0, added one optional delimited title to the protected link grammar (Token.title_suffix), refused titles holding controls or internal targets, carried titles into vault note and attachment links (titled images become Markdown images; untitled output unchanged), updated design/contract declarations and added link-grammar, vault-rewrite and real import/export tests. |
| Validation | Link projection and integration classes: 21 tests passed. All 273 tests in the five required modules passed (168.108s) with PYTHONDONTWRITEBYTECODE=1 and -B. Immutable fixtures and identity vectors unchanged. Found two pre-existing downstream defects, planned as S43c (titled links through native reimport and site) and E1 (exporters rewrite their input database). |
| Delegation failure or reassignment | 2026-10-22: planned as a Codex parent slice; coding agent changed to the Claude Code parent by user before any work started. Planned owner unchanged. |
| Planned assignment evidence | NOTRIOS_IMPORT_PLAN.md producer link-syntax prerequisites added 2026-09-26; 2026-10-22 coding-agent change to Claude Code |
| Execution evidence | User: Commit the plan amendment, then proceed with S43a.; Notrios v1.0.0 internal/markdownlinks/parser.go markdownDestination/TitleSuffix and internal/importers/obsidian/obsidian.go rewrite; Local log /tmp/claude-$UID/-home-$USER-projects-movenotes-v3/<session>/scratchpad/s43a-tests.log |
| Commit | Git commit containing this completion record: feat: admit titled links in Notrios bodies (S43a) |

</details>

<details><summary>S43b — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-22; user authorized: proceed to S43b. |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code |
| Parent underlying model family | Claude Opus 5.5 (runtime-reported model ID claude-opus-5-5) |
| Parent reasoning effort | not exposed |
| Parent contribution | Built a clean Notrios v1.0.0 binary from a temporary clone; added a synthetic titled-link Obsidian vault and generate_v1_titled.py, which drives real import obsidian, tags add and publish commands and checks raw archive bytes; installed the fixture under testdata/notrios/v1.0.0; made the differential audit's injected references fixture-declared (old fixtures keep doc_public/res_image) and ran all 56 cases against the release binary; added NotriosV1TitledTest and fixture documentation. |
| Validation | Producer compatibility and verification accept; Python fully verifies. 56 differential cases matched (9 shared acceptances, 30 shared refusals, 17 consumer-only refusals). NotriosV1TitledTest: 3 tests passed (5.333s), covering immutable fixture, conversion, unchanged rerun, byte-for-byte titles in database and vault, tags, attachment bytes and bundle hashes. All 276 tests in the five required modules passed (193.270s) with PYTHONDONTWRITEBYTECODE=1 and -B; schema-27 and schema-28 fixtures still verify and convert unchanged. |
| Delegation failure or reassignment | 2026-10-22: planned as a Codex parent slice; coding agent changed to the Claude Code parent by user before any work started. Planned owner unchanged. |
| Planned assignment evidence | NOTRIOS_IMPORT_PLAN.md producer link-syntax prerequisites added 2026-09-26; 2026-10-22 coding-agent change to Claude Code |
| Execution evidence | User: proceed to S43b; testdata/notrios/v1.0.0/README.md; publication-titled/generation.json (cli_sha256 b4f368a9879ce16b544c0d7bd175f95ad4647b43b71f0172bf0344dda048e55c); testdata/notrios/v1.0.0/verifier-audit.json; Local logs /tmp/movenotes-s43b/generate.log and /tmp/movenotes-s43b/s43b-tests.log |
| Commit | Git commit containing this completion record: test: pin a Notrios v1.0.0 titled-link publication (S43b) |

</details>

<details><summary>S43c — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-22; user authorized: Proceed (S43c). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code |
| Parent underlying model family | Claude Opus 5.5 (runtime-reported model ID claude-opus-5-5) |
| Parent reasoning effort | not exposed |
| Parent contribution | Froze the S43c design in the plan after finding that cleanres deletes resources referenced only by titled links. Added common.LINK_TITLE (the S43a grammar) and let RESOURCE_LINK_RE accept it; sql2obsidian keeps resource titles (titled images become Markdown images); obsidian2sql tries a titled link form first and keeps the title after :/id, falling back to the unchanged untitled pattern; obsidian2site keeps exactly one delimited title on resolved note and asset links. Added regression tests and a baseline-versus-new comparison harness. |
| Validation | Baseline (a82487c export) versus new: a deterministic 3,000-note subset of the real recipe vault gives a site whose 7,426 files are identical after normalising generation-time values, and a native reimport whose 7,736 items are identical. For the S43b titled vault, only the two titled notes change: site URLs are unchanged with titles added, and reimport now resolves every titled link (fixing a stray parenthesis and an unresolved titled image). The new tests fail on the baseline (cleanres there deleted the titled-referenced file) and pass now. All 282 tests in the five required modules passed (194.732s) with PYTHONDONTWRITEBYTECODE=1 and -B. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | S43a finding, 2026-10-22; user: Update the plan if you find items that need to be fixed instead of just logging their existence. |
| Execution evidence | User: Proceed; Local harness /tmp/movenotes-s43c/pipeline.sh, compare_site.py, compare_db.py; outputs /tmp/movenotes-s43c/out-base and out-new; Local log /tmp/movenotes-s43c/s43c-tests.log |
| Commit | Git commit containing this completion record: fix: keep Markdown link titles in reimport, site and cleanres (S43c) |

</details>

<details><summary>E1 — complete; planned parent</summary>

| Property | Value |
|---|---|
| Coding agent | claude |
| Planned worker | parent |
| Planned configured model | not exposed; runtime reports claude-opus-5-5 |
| Planned reasoning effort | not exposed |
| Assignment confirmation | Claude Code session assignments confirmed by user on 2026-10-22; user authorized: proceed with E1 on that basis (automatic read-only opening when no migration is needed). |
| Actual worker | none |
| Child thread | none |
| Actual model | none |
| Reasoning effort | none |
| Worker contribution | none |
| Parent | Claude Code |
| Parent underlying model family | Claude Opus 5.5 (runtime-reported model ID claude-opus-5-5) |
| Parent reasoning effort | not exposed |
| Parent contribution | Probed SQLite 3.46.1 read-only behaviour (a mode=ro connection to a WAL database leaves -wal/-shm behind) and froze the refined design in the plan. Added notesdb.open_database_for_reading: mode=ro for rollback-journal databases, query_only for WAL ones, and a read-only migration check that falls back to open_database for migration or recovery. Switched sql2obsidian and sql2joplin to it, added tests and updated PERFORMANCE_REVIEW.md. |
| Validation | A completed Notrios import is byte-identical after a vault export and a Joplin export, leaves no -wal/-shm, and reruns as unchanged (it previously refused). HEAD versus new exporter output is identical for the 3,000-note real recipe subset (10,738 vault and 7,736 Joplin files) and for the titled import. New tests cover both journal modes, refused writes, no leftover files, and migration of a database with a missing index or an older db_version. All 285 tests in the five required modules passed (197.130s) with PYTHONDONTWRITEBYTECODE=1 and -B. |
| Delegation failure or reassignment | none recorded |
| Planned assignment evidence | S43a finding, 2026-10-22; user: Update the plan if you find items that need to be fixed instead of just logging their existence. |
| Execution evidence | User: proceed with E1 on that basis; Local logs /tmp/movenotes-e1/e1-tests.log; comparison outputs under /tmp/movenotes-e1/cmp |
| Commit | Git commit containing this completion record: fix: stop exporters rewriting the database they read (E1) |

</details>
<!-- NOTRIOS-EXECUTION:END -->
