# P7a performance investigation — 2026-09-18

P7a is complete as an investigation. No production optimization has been adopted.
The original 382,206-document Go timing gap remains quantitatively unresolved:
new synthetic profiles identify candidates, not a controlled explanation of the
old runs. Python preserved-vault import has a separately reproduced, severe
folder-parent lookup bottleneck. These are different executables.

## Inputs, versions and measurement limits

Reviewed Union Alpha and Grok 4.6 under `~/prompts/` and
`~/projects/notrios/performance-code-review.md`. The latter's heading
mentions movenotes, but its findings concern Notrios Go. F01–F15 below correspond
to the plan; G01–G10 distinguish the additional Go review.

Python baseline is movenotes commit `b60470a`; the run manifest records source
hashes. Go acceptance pin is `7662fdd5b55d6f34f14874f70ba6db9f9e7676ac`.
Read-only current Notrios inspection used `f478da7f1065d95d47cf21612833cef991bb8255`,
schema 28. Current code is not a replacement acceptance pin. Profiling exported
pinned source into a disposable directory and added an opt-in CLI pprof wrapper;
the original Notrios checkout and acceptance libraries were not modified.

The sequential HDD run used Python 3.12.3, SQLite 3.45.1, Go 1.27.0 and batch 500.
It generated 2,000 deterministic notes, mixed short/long bodies, metadata, Unicode,
tags and links, plus a separate 200-note/32-resource fixture. Fresh, unchanged,
small-merge and preserved-source paths ran in distinct stages. Total profiled
batch wall time was 807.386 seconds. Synthetic fixtures are not recipe samples.
SQL trace and cProfile add substantial overhead; SQL counters describe traced
statements and direct UPDATE row counts, not all underlying database operations.
Cumulative profile times overlap and must not be summed. The Go command wrapper's
child RSS high-water mark is cumulative, so it is not a per-command memory result.

| Python fresh route | Profiled import wall seconds | Separate unprofiled CLI wall seconds |
|---|---:|---:|
| Native vault | 31.731 | 15.117 |
| RAW | 14.435 | 6.485 |
| Preserved vault | 269.952 | 249.098 |

The columns have slightly different boundaries (import body versus whole CLI).
These single unprofiled runs establish instrumentation sensitivity, not noise
bounds or a candidate speedup. Preserved import remains slow without profiling.

## Python review dispositions

Evidence anchors are `obsidian2sql.py` (`_native_rows`, `_existing_import_hashes`,
`_insert_rows`, preservation overlay and finalization), `notesdb.py`
(`populate_missing_note_folders`, `_INSERT_COLUMNS`, index setup), `joplin2sql.py`
(RAW parsing/resources), `common.py` (resource copy), and the private profiles.

| Finding | Disposition and evidence | Candidate or limit |
|---|---|---|
| F01 fingerprints | Confirmed-not-hot in this subset; existing-hash queries total 0.16–0.54s. Alpha's repeated queries for prior batches are incorrect: queries are scoped to current input IDs. | Defer adaptive preload until large unchanged/merge evidence; same-batch collision is separate C01 below. |
| F02 folder fallback | Confirmed-hot: one `populate_missing_note_folders` call consumes 242.197s of 269.952s preserved fresh. It runs before lookup indexes; EXPLAIN shows parent lookup `SCAN notes`, becoming indexed SEARCH after index creation. Native fresh fallback is 0.484s. | Bound parent lookup before fallback; merely narrowing updated rows does not fix fresh correlated scans. Preserve missing-parent/cycle behavior and existing folder values. |
| F03 frontmatter | Confirmed-hot: native fresh 4,000 parses / 3.407s cumulative; scalar conversion 2.073s. Head and full parsing repeat. | Avoid redundant parsing and ordinary-scalar JSON exceptions with equivalent grammar. All string encodes total only 0.200s; regex cache dispatch 0.231s, not repeated full compilation. Character counts cannot replace byte limits. |
| F04 paths/stat | Confirmed-hot for paths: 12,021 `relative_to` calls / 8.355s cumulative in native fresh. 2,026 stat calls cost 0.085s. | Carry relative paths once; preserve path semantics/order. Blanket two-stats-per-note claim incorrect; os.walk does not expose cached DirEntry metadata. |
| F05 resource set/link guards | Deferred: rewrite costs 3.721s, but this does not isolate rebuilding resource sets from parsing. Attachment fixture has only 32 resources. | Measure components first; syntax guards must cover whitespace/escape forms actually accepted by regexes. |
| F06 row tuples | Confirmed-not-hot enough to prioritize: generator about 0.7–0.8s. Schema has 75 insert columns, not 87. | Naive itemgetter loses absent-key-to-NULL behavior. No demonstrated whole-import win. |
| F07 RAW tail parsing | Confirmed-hot: splitting/parsing totals 3.155s fresh and 3.334s unchanged; physical splitting about 1.1s. | Differential-test tail parser against exact bytes, CR/LF/CRLF, OCR controls, ordered unknown properties and body boundaries. |
| F08 preserved overlay | Confirmed-hot write amplification: unchanged run executes 2,001 UPDATE statements, directly touches 2,000 rows, total wall 20.287s; preservation path 18.099s cumulative. | Compare all overlay fields before skipping. Digest alone cannot detect path/metadata changes. Benefit of skipping writes still requires an experiment. |
| F09 resources | Alpha's unchanged Joplin double-comparison claim incorrect: probe counts one comparison and skipped copy. Validation and copying are separate passes intentionally. | Do not remove validation-before-copy barrier. Attachment work cannot explain resource-free recipe gap. C02 below is separate. |
| F10 compression | Confirmed-not-hot here: zlib about 0.5s native. | Defer; lower compression changes envelope bytes/storage and fingerprints, despite lossless decompression. |
| F11 concurrency | Deferred; no evidence yet that process/IO overlap beats serial after simpler fixes. | Single writer, bounded queues, deterministic ordering and total child memory remain required. |
| F12 index deferral | Already addressed for fresh imports; incremental index removal deferred. | Keep required lookup indexes; F02 actually needs a lookup index or equivalent bounded algorithm earlier. |
| F13 progress/regressions | Progress options already exist on both Python importers; claimed asymmetry overstated. | Add structural regressions for adopted changes; do not use fragile fixed wall-time tests. |
| F14 image_resources | Out-of-path for both measured importers. | No proposed recipe-import benefit. |
| F15 transaction/settings | Already addressed: batches, executemany, WAL/NORMAL and an import transaction. Fresh runs have two BEGIN/COMMIT pairs including initialization, not per-batch commits. | No unsafe durability changes or speculative global caches. |

Correctness findings are independent of performance adoption:

- **C01:** two same-batch rows with one item ID and different digests are both
  inserted (probe: inserted 2, database rows 2). Pending batch IDs are not added
  to the existing-ID map. Fix collision handling with within/across-batch cases.
- **C02:** the resource helper used by preservation overwrites an existing
  destination with different bytes. The helper reproducer confirms this behavior;
  add end-to-end preserved-import collision/rollback coverage before changing it.

The baseline probes deliberately assert observed behavior, including defects.
They are evidence tools, not declarations that those defects are correct; revise
or retire their expectations when the associated fix is tested.

## Notrios review and shared techniques

Pinned synthetic Go fresh RAW took 47.812s; vault 75.849s. Unchanged took 19.604s
and 40.560s. CPU profiling was enabled, so these are not adoption benchmarks.
RAW has 45.75 CPU sample seconds, vault 60.56. Vault `markdownlinks.Extract`
accounts for 29.78 cumulative CPU seconds (49.17%); `canonicalBody` 10.33s and
block extraction 8.75s. RAW regex find contributes 24.67s (53.92%). SQLite prepare
contributes 10.29s RAW (22.49%) and 9.75s vault (16.10%). Regex, caller, block and
SQLite shares overlap. They identify work to isolate, not additive gap estimates.

| Go finding | Audit/profile disposition and transfer |
|---|---|
| G01 prepared statements | Confirmed-hot preparation; current `execPreparedLocked` prepares/finalizes per call. Batch-scoped reset/rebind, as existing manifest code uses, is a strong isolated candidate. Preserve locking, error cleanup and transaction lifetime. |
| G02 duplicate block/link rebuild | Confirmed relevant in profiles and source. Investigate revision-checked block reuse; retain first-write visibility and final forward-link/namespace refresh. Removing the second pass wholesale is unsafe. |
| G03 existence queries load bodies | Confirmed source behavior, cost not isolated. Candidate typed bounded existence API preserving deleted-item semantics; defer until query counts/allocations justify it. |
| G04 resource/source metadata writes | Source-supported, deferred for attachment-specific profiles. Stage bytes and batch metadata without changing failure/visibility guarantees. |
| G05 byte bounds | Count-only batches can retain very large total bodies (500 × 64MiB is about 31GiB). Robustness candidate, not demonstrated speedup. Bound re-reads before mutation/hash checks. |
| G06 repeated resource reads | Source-supported, deferred: recipes have no resources. Validate bytes actually stored, not a stale inventory digest. |
| G07 duplicate RAW maps | Source-supported, allocation benefit unmeasured here. Transfer ownership only after proving no readers; distinguish preservation modes. |
| G08 link line/column scans | Source-confirmed repeated prefix scanning; link extraction is hot. Test sorted offsets/one scan with Unicode rune columns and exact output equivalence. |
| G09 alias dedup | Linear appendUnique buckets can become quadratic on collisions; adversarial benchmark needed. Use sets selectively rather than penalizing unique inputs. |
| G10 parser allocations | Source-supported split/join/title/list-prefix costs; individual gains unmeasured. RAW body reconstruction is only 0.33 CPU seconds here. Do not repeat rejected comparison-only byte-to-string allocation claims. |

Additional transferable candidates: use Joplin's linear builder technique for
Obsidian reverse replacement splices, with overlap policy and byte ranges proved;
omit retained property order only when preservation does not need it; hash already
read Markdown while retaining subsequent source revalidation; reuse checkpoint
skip/counter discipline across importers only with metadata repair and crash tests.
Compact digests/derived paths and cached ancestry can reduce retained memory;
Python path reuse is independently hot. Disk-backed inventories/keyset iteration
and bounded ReadDir require stable ordering/digests and should follow smaller
fixes. Python regex substitution already assembles output linearly: Go splice
advice is not automatically applicable there.

Existing Notrios evidence prevents rediscovering completed or rejected work:

- `performance/v1.0-j17/README.md`: current Obsidian batching already replaced
  per-note commits. Corrected HDD 10k observations were 27.1/31.1ms per note before
  and 13.2/13.1/13.3ms after. Earlier measurements were contaminated, including an
  update-path FTS scan and concurrent work. Do not reuse the earlier attribution.
- `performance/v1.0-j19/README.md`: preparation/block work was substantial;
  buffer pooling, streamed fingerprinting and comparison conversion proposals
  failed their tests. Retained full-file cloning fixes cut memory, not necessarily
  wall time. Deferring FTS visibility was rejected; retain inline visibility.
- `performance/v1.0-j20/README.md`: separate clean warm full 382,206-note runs
  report vault 5,245.5s and RAW 5,907.9s (ratio 0.888), reversing the old gap.
  These use different revisions/conditions and are inherited evidence, not our
  controlled speedup result. Later vault 5,278.2s reduced memory without a proven
  time win. Current batching/memory changes must not be proposed as new fixes.

Thus newer Notrios techniques are relevant, but explaining the historical
9,896.59-second gap requires controlled producer comparisons. No percentage of
that gap is assigned to Python findings or to these independent historical runs.

## Frozen candidate handoff and adoption protocol

P7b belongs to **Codex terra_worker, configured gpt-5.6-terra / fixed medium**.
Parent owns review/adoption. Billing route is not exposed; existing session
suitability confirmation remains in force. Actual execution metadata must be
recorded from evidence, not copied from configured values.

1. Start with isolated Python F02 bounded parent lookup, then F04 relative-path
   reuse, F03 parsing, F07 RAW parsing and F08 overlay as evidence warrants.
   Owned files: `obsidian2sql.py`, `notesdb.py`, `joplin2sql.py`, narrowly necessary
   `common.py`, focused importer tests and performance harnesses. Separate C01/C02
   correctness changes from speed claims. Preserve exact-source/resource barriers.
2. Producer track: first freeze old-pin/current-baseline applicability, then test
   G01 and G08 separately before broader G02 work. Any Go edit requires an explicit
   disposable checkout/file handoff and external-write approval where applicable;
   no original Notrios checkout mutation or acceptance-pin promotion is implied.
   A current baseline's already-implemented batching must not be bundled as a new
   candidate win. Keep producer and Python result/adoption tables separate.
3. P7c runs at least three alternating baseline/candidate unprofiled pairs per
   representative subset (five preferred), serially with equal input manifests,
   source/binary hashes, flags, batch size, disk, cache policy and no competing
   imports. Include fresh, unchanged, tiny merge, preserved-source, attachment,
   long-body/link-dense and collision-heavy cases appropriate to the candidate.
   Record wall/user/system, actual per-process peak RSS, disk/WAL, counts and
   correctness. Profile separately; never compare instrumented with uninstrumented.
4. Adopt only a repeatable gain above measured variability (target >=5% median),
   with no material regression or invariant failure. Run all required regressions,
   exact restoration/hash/metadata checks, collision and recovery tests. Query,
   read and update counts can be stable structural tests; timing thresholds are
   benchmark criteria, not brittle CI tests.
5. Run controlled full baseline/candidate imports per affected producer route,
   reporting RAW and vault separately, absolute gap and ratio. Goals remain >=30%
   faster for both and vault/RAW <=1.5; never slow RAW to close the gap. Unmet goals
   are reported, not hidden by subset wins. P7c acceptance does not waive 7c's
   compatibility/equivalence gates.

## Reproduction, monitoring and cleanup inventory

Use new output directories; scripts refuse existing profile/timing roots:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/notrios_p7a_profile.py run --output NEW_PROFILE_ROOT --notes 2000 --notrios-source ~/projects/notrios --pin 7662fdd5b55d6f34f14874f70ba6db9f9e7676ac
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/notrios_p7a_profile.py timing --inputs NEW_PROFILE_ROOT --output NEW_TIMING_ROOT
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/notrios_p7a_probes.py
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/notrios_p7a_artifacts.py --root NEW_PROFILE_ROOT --root NEW_TIMING_ROOT
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests/test_notrios_p7a.py
```

Completed private roots (not repository artifacts):

| Root under `/media/$USER/HD2/` | Contents | Files / logical bytes excluding inventory itself |
|---|---|---:|
| `movenotes-p7a-20260918-monitor` | Generated inputs, fresh/unchanged libraries, Python/Go profiles, disposable pinned build, stage logs, probes and run manifests | 14,338 / 449,758,090 |
| `movenotes-p7a-20260918-unprofiled` | Separate fresh timing databases, logs, results and terminal notification | 8 / 186,873,196 |

Each has `ARTIFACT_MANIFEST.json` listing every subdirectory's purpose and recursive
logical size, plus top-level files. Logical sizes are not exclusive physical disk
allocation. Rebuildable tools/libraries are identifiable for later cleanup; preserve
summaries, input/source hashes and downstream dependencies. No evidence was deleted.

Parent wrote instrumentation, probes, inventories and this analysis. Auxiliary
`/root/p7a_monitor` (configured Luna/max, actual model/effort not exposed) executed
the sequential batches, then probes/inventories. Registry checks preceded waits
after interruption. Long completion waits and terminal handoffs replaced minute
polling; future data-heavy slices use the same arrangement. With two slots,
Terra implementation and Luna execution must be staged, not spawned concurrently.
A batch should contain multiple cases with separate stage outputs and durable
terminal status. On interruption inspect process/agent survival before resuming.

Validation: 30-note harness smoke, completed 2,000-note multi-route profile batch,
three unprofiled fresh imports, five baseline probes, and two artifact-inventory
unit tests passed. No production importer changes were made; prior C7c regression
results remain historical rather than being represented as newly rerun here.
