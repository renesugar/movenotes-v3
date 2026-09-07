# Plan: Import a Notrios publication handoff

Status: slices **1a–1d and 2a complete** on 2026-09-07. Manifest admission is
implemented; full archive verification and conversion remain pending.
Next item: **2b**, pending the user's instruction to proceed.

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

Notrios reference checkout: `~/projects/notrios`, commit
`bdecfeda00e582d5aa6170d15b37ba27c9656f1d`. Confirmed unchanged in 1a.

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
be ignored. Profile `movenotes-publication-loose-v1` has schema support level 27:
require `12 <= minimum_schema_version <= 27` and
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
Settings do not automatically reach a vault/site: 6c must define content-free
traceability sidecars excluded from rendered notes and search. Do not propagate
source filesystem paths or arbitrary private metadata. An optional expected
reviewed digest compares against the selection digest, independently of archive
integrity verification.

## Execution and agent handoff rules

Slices 1a–1d and 2a are complete; all other slices below are pending. Worker names refer to
the roles available in this session:

| Owner | Agent configuration | Assignment rule |
|---|---|---|
| Luna | `agent_type="luna_worker"`; fixed `gpt-5.6-luna`, reasoning `medium` | Mechanical helpers, pure builders, straightforward table-driven tests and documentation against frozen inputs. |
| Terra | `agent_type="terra_worker"`; fixed `gpt-5.6-terra`, reasoning `medium` | Bounded implementation and regression work needing cross-file reasoning, filesystem/subprocess handling or debugging against Main's approved contract. |
| Main | Main model | Contract/privacy decisions, verifier semantics, transactional safety, cross-format design, integration acceptance and final review. |

The Terra assignments use the available role's stated purpose, not measured
performance on this repository. They do not change scope or acceptance gates.
Main must freeze the relevant design before either worker starts; especially,
Terra implements 3d and 5b only after the link/attachment decisions in 1c are
concrete. Escalate newly discovered design decisions to Main rather than guessing.
Implementation may delegate these slices; this plan review does not require
parallel agents.

Work on **one slice at a time**. Assign inputs, owned files, dependencies,
excluded files and acceptance commands explicitly. Tell workers they are not
alone in the codebase and must preserve others' edits. Main reviews every Luna
or Terra result before the next dependent slice. Do not edit shared helpers/tests from
multiple simultaneous tasks.

Each slice ends with focused passing checks, a progress-log update identifying
the next item, and a coherent Git commit. Record unfinished work and exact
resume commands on interruption. Do not expose incomplete features through the
supported CLI or mark code complete before its acceptance checks pass. Keep
private data, generated libraries, SQLite databases and bulky evidence out of
Git. Use sanitized fixtures and aggregate measurements in committed evidence.

After completing and committing an item, ask the user whether to proceed to the
next item and stop until they answer. This per-item pause was explicitly requested
by the user on 2026-09-05 and also applies to delegated slices.

Proposed files: `notrios_archive.py` for verification, `notrios2sql.py` for
mapping/CLI, `test_notrios2sql.py`, and `testdata/notrios/`. Main freezes module
boundaries and helper APIs in 1c before delegating implementation.

## Step 1 — Freeze contract and fixtures

| Slice / owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 1a / Main — complete | Reviewed pinned schemas, verifier, producer and CLI; froze [consumer contract](NOTRIOS_IMPORT_CONTRACT.md). | None | All twelve payload field sets and twenty hard limits cross-checked; every refusal sourced or identified as consumer policy; loose-only admission and both digests confirmed. |
| 1b / Main — complete | Generated [synthetic publication fixture and reproduction evidence](testdata/notrios/README.md) using the clean pinned CLI's real import/plan/publish commands. | 1a | Production compatibility and verification passed; 3 notes, 3 resources, nested notebooks, duplicate titles, Unicode tags, 8 retained links, 3 rewritten links and zero skipped rewrites. Exact digests/bytes and excluded sentinels checked. |
| 1c / Main — complete | Froze [APIs, row/property mapping, conversion limits, identity, staging and link/attachment design](NOTRIOS_IMPORT_DESIGN.md), with [machine-readable vectors](testdata/notrios/design-v1.json). | 1b | 13 identity vectors checked with independent framing and system SHA-256; all 8 real-fixture link spans and 3 complete projected bodies checked; concrete later acceptance cases assigned. |
| 1d / Luna — complete | Added [offline fixture-copy/inventory/record helpers and baseline assertions](test_notrios2sql.py), plus [baseline and regeneration instructions](testdata/notrios/README.md). | 1c | Nine standard-library-only baseline tests pass using committed synthetic data; no producer invocation or runtime importer dependency. |

Use independently generated contract goldens as well as producer publications;
neither alone protects against the producer and consumer sharing a bug.

## Step 2 — Verify before conversion

| Slice / owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 2a / Main — complete | Added strict bounded JSON, immutable manifest model, Go-compatible canonicalization and declaration/target gates in [notrios_archive.py](notrios_archive.py). | 1d | Six independently generated Go serialization vectors; strict JSON/limit/type/schema/capability/target tests; manifest-only admission and refusals without object access. Full archive verification is not implied. |
| 2b / Main | Safe fanout reader, streamed hashes, index validation and temporary indexed spool. | 2a | Missing/corrupt/truncated chunks/objects, ordering/totals, traversal, symlinks and extras refuse without output mutation. |
| 2c / Terra | Table-driven hostile mutations and byte-limit boundary tests using frozen APIs; diagnose failures against the frozen contract. | 2b | Each failure has a specific assertion; legacy zero blob counts and bounded optional capabilities accepted. |
| 2d / Main | Typed records, reference joins, tree checks, MIME and publication invariants. | 2c | Correctly rehashed but semantically invalid archives refuse for the intended reason; real publication passes. |
| 2e / Main | Differential audit against Notrios for shared format rules, plus consumer-specific refusals and point-of-use safety. | 2d | Duplicate identities, missing references, wrong revision owners, unused blobs and source mutation covered; memory bounded. |

No import path becomes available before 2e. A packed archive must keep refusing
even if some files resemble loose objects.

## Step 3 — Notebooks and current notes

| Slice / owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 3a / Luna | Pure deterministic ID and complete row/property builders in the module assigned by 1c. | 2e | Frozen vectors, generic/Joplin aliases, timestamps, Unicode/empty titles; IDs stable across snapshots. |
| 3b / Main | Staged database lifecycle, byte-bounded batches, collision checks and atomic destination publication. | 3a | Injected verification/insertion/finalization faults leave no completed partial output or overwritten destination. |
| 3c / Terra | Notebook/note integration and text-only vault subprocess tests. | 3b | Counts/hierarchy/title/body/date assertions; invalid parent/revision/body refuses. |
| 3d / Terra | Implement included-note link translation and minimal exporter adaptation using final paths, following Main's frozen 1c design. | 3c | Links resolve with duplicate titles/renaming/fragments; withheld/external text correct; existing exporter tests pass; Main reviews cross-format behavior. |

This is a development milestone. Until Steps 4–6 complete, reject inputs needing
unfinished features rather than silently omitting data.

## Step 4 — Tags

| Slice / owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 4a / Luna | TAG/NOTE_TAG mapping using frozen ID and row helpers. | 3d | `load_note_tags` returns expected sorted titles on the correct notes. |
| 4b / Luna | Unicode, spaces/quoting, duplicate names and multiple-membership tests. | 4a | Vault YAML tags survive re-import; malformed/duplicate relation identities rejected by verification. |
| 4c / Main | Review vault/site tag semantics. | 4b | Written tags remain written tags; generated word tags never enter taxonomy or search-source tags. |

## Step 5 — Resources and attachments

| Slice / owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 5a / Terra | Resource metadata builder and streamed staged copy using approved APIs and Main's staged-output design. | 4c | Exact hashes/sizes; safe names and extensionless resources; conflicting bytes refuse. |
| 5b / Terra | Translate retained resource links and implement relation-only attachment behavior frozen by Main in 1c. | 5a | Images/files resolve from nested notes; shared bytes with differing semantic MIME work; withheld resources absent; Main reviews the mapping. |
| 5c / Terra | Attachment regressions with independent byte comparisons. | 5b | Duplicate filenames, Unicode/escaping, zero-byte and large streamed files; exact attachment bytes. |
| 5d / Main | Review reachability, rehash-at-use and interrupted-copy recovery. | 5c | No writes outside staging or overwrites; failure cannot expose partial completed output. |

Do not run `cleanres.py` during import. Its Markdown-reference rule could remove
a relation-only attachment; the adapter must resolve that representation.

## Step 6 — Receipt and public CLI

Target refusal is mandatory in 2a, not deferred to this step.

| Slice / owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 6a / Luna | Versioned settings receipt and content-free import summary in staging. | 5d | Both digests correct; failed imports have no success receipt. |
| 6b / Main | Finalize CLI, expected reviewed-digest comparison, identical completed rerun and conflicting-output refusal. | 6a | Digest mismatch/changed source refuse; same import is safe; no unsafe override. |
| 6c / Main | Specify and implement explicit receipt propagation to vault/site outside notes/indexes. | 6b | Both digests traceable; no claim that settings propagate automatically; no source-path leakage. |
| 6d / Terra | Help/errors/progress and CLI subprocess tests against Main's finalized CLI contract. | 6c | Consistent `--input`/`--output`, phase/count progress, nonzero errors and no success on partial output. |

## Step 7 — End-to-end acceptance and documentation

| Slice / owner | Work and owned output | Depends on | Acceptance |
|---|---|---|---|
| 7a / Terra | Small offline publication-fixture → SQLite → vault regression with independent expectations. | 6d | Notes/tags/links, exact attachments, absence of excluded sentinels and receipt assertions pass. |
| 7b / Main | Actual local Hugo/Ledger + Bluge build and bounded Pagefind fixture; test search/subpath URLs. | 7a | Canonical URLs, links, attachments, explicit tag counts and backend isolation correct; excluded sentinel absent from publishable files/index sources. |
| 7c / Main | Large-corpus trials below; record time/RSS/disk/counts/hashes and failure recovery. | 7b | Importer bounds demonstrated; stage bottlenecks separated; no unmeasured whole-pipeline memory claim. |
| 7d / Luna | README script list/usage and CHANGELOG from measured accepted commands. | 7c | Reproducible publication → import → vault → site recipe; loose/fresh-output limitations; no private content in public examples. |
| 7e / Main | Full regression gate, evidence/diff review, final status and commit. | 7d | Every required method passes; skipped integrations not counted as acceptance. |

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

- Packed publications: Main designs pack/trailer/range verification; Luna adds
  frozen-vector tests; Main performs differential acceptance before admission.
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
