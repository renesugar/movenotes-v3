# P7c candidate validation

P7c validates the Python F02/F04 changes from `7aa9093` independently. C01/C02
collision fixes remain enabled in all four disposable variants: base, F02 only,
F04 only and both. The original `f0b218a` `_native_rows` function supplies the
F04 inverse; no production flags or importer edits are introduced by this slice.
The rejected Go G08 candidate is excluded. The original both-producer speed and
ratio goals remain unproven: Python results cannot satisfy Go producer goals.

## Completed isolated synthetic measurements

Three alternating unprofiled pairs per case, sequential HDD imports, batch 500.
Inputs are P7a's deterministic 2,000-note fixture, 10-note merge and separate
200-note/32-attachment fixture. Ratios below are medians of paired candidate/base
wall times (not ratios of independently selected medians). Per-process RSS comes
from the child measurement wrapper. All recorded paired output fingerprints match.

| Candidate / case | Base seconds | Candidate seconds | Median paired ratio |
|---|---|---|---:|
| F02 preserved fresh | 270.19, 270.61, 266.06 | 15.19, 15.43, 13.09 | 0.0562 |
| F04 native fresh | 14.97, 17.51, 15.26 | 12.10, 12.75, 12.73 | 0.8083 |
| F04 native unchanged | 15.27, 14.40, 13.88 | 10.49, 10.58, 10.23 | 0.7347 |
| F04 tiny merge | 0.49, 0.55, 0.51 | 0.70, 0.48, 0.46 | 0.9020 |
| F04 media fresh | 2.37, 2.06, 1.92 | 1.89, 1.66, 1.66 | 0.8058 |
| F04 media unchanged | 1.63, 1.71, 1.68 | 1.46, 1.56, 1.33 | 0.8957 |
| RAW fresh control | 7.10, 7.12, 7.32 | 7.98, 6.42, 7.74 | 1.0574 |
| RAW unchanged control | 4.69, 5.06, 4.38 | 4.86, 4.95, 4.95 | 1.0362 |

Tiny merges are subsecond and noisy;
the first candidate sample is slower. Controls and scale memory require review
before final adoption. Synthetic native fresh RSS spans 50,508–50,680 KiB base
and 50,636–50,760 KiB F04. This does not establish full-corpus memory behavior.

Private roots under `/media/$USER/HD2/`:

- `movenotes-p7c-20260918-f02-preserved`
- `movenotes-p7c-20260918-f04-native`
- `movenotes-p7c-20260918-f04-controls`

Each experiment retains results, individual stage logs and private databases.
Artifact manifests describe generated contents and sizes; no data was deleted.
The long batch uses blocking subprocess completion, durable records and long
notification waits. Original corpus inputs and prior acceptance libraries remain
read-only. Producer full-corpus trials are ineligible without a passing candidate.

A five-pair RAW control follow-up under
`movenotes-p7c-20260918-raw-control-5` gives median paired ratios 0.9772 fresh and
0.9678 unchanged, with all fingerprints matching. Only `obsidian2sql.py` differs
between the base/F04 source variants; RAW importer and shared runtime helpers
are byte-identical. The changing sign and spread of control timings supports
host/cache variability rather than an F04 RAW-path regression. No RAW speedup
is claimed.

Metric correction: the original time-wrapper field named `input_bytes` contains
GNU time `%I`, filesystem input operations, **not bytes**. New records use
`filesystem_input_operations`; source byte inventories are separate. No disk
throughput claim is derived from the old mislabeled field.

Harness review added refusal of missing/modified completed outputs, source/input
and harness fingerprint checks on resume, complete-matrix checks, atomic status
and root inventories. A changed harness starts a new matrix; completed historical
measurements retain their original harness provenance. Recovery validation must
not rewrite failed attempts or rerun successful import commands unnecessarily.

## Real recipe subset

The deterministic sorted selection contains 10,000 Markdown files / 15,846,157
bytes from 382,206 files / 602,218,600 bytes. File bytes and mtimes are copied and
inventoried. No configuration files were present. The manifest is outside the
input vault; preservation bundles are refused by the selection helper. Selection
is a bounded prefix, not a claim of statistically random sampling.

Private root: `movenotes-p7c-20260919-real-seed/f04-real-native`.

| F04 case | Base seconds | F04 seconds | Median paired ratio |
|---|---|---|---:|
| Fresh | 73.20, 73.89, 72.63 | 54.78, 54.51, 51.57 | 0.7377 |
| Unchanged | 52.14, 51.97, 49.20 | 33.53, 34.21, 31.51 | 0.6431 |

All six pairs match output fingerprints. Each database is 120,635,392 bytes.
Fresh peak RSS is 44,476–44,900 KiB base and 46,348–46,832 KiB F04. Unchanged
peak RSS is 44,288–44,924 KiB base and 45,000–45,024 KiB F04. The path-cache
memory cost is visible; full-scale acceptance must consider that cost.

The same batch's F02 prepared unchanged checks matched outputs but were noisy:
9.15→11.39, 10.71→10.06 and 9.54→10.60 seconds. Its small-merge case then failed
because the reused synthetic tiny vault shared identities with the preserved
seed. This was an unintended test-data collision, not a performance failure or
permission to weaken collision checks. The failed evidence remains intact. A
new disjoint, tag-free merge fixture and five-pair follow-up address this gap.

## Execution and recovery

Luna `/root/p7c_validation` authored the harness, variants and focused tests and
executed the initial synthetic matrices. Parent reviewed data selection, units,
output validation and resume behavior. Later worker external-tool calls stalled
before execution; the parent confirmed no active job, obtained required external
write approval and launched real-subset/final validation commands. Worker terminal
sessions cannot access parent session IDs, so parent tool-side long waits handled
those runs, without model-mediated short polling. Implementation stayed delegated;
this was parent final validation, not an implementation reassignment.

Configured worker: Codex `luna_worker`, `gpt-5.6-luna`, fixed `max`; actual child
model/effort not independently exposed. Parent runtime family GPT-6; exact parent
model/effort and billing route not exposed. Existing session suitability remains
confirmed. Structured provenance is in `NOTRIOS_IMPORT_EXECUTION.json`.

## Full-scale blocker — P7c remains incomplete

The controlled native-vault full trial was stopped during its **baseline** after
17,943.11 seconds (4h 59m 03s), with user CPU 13,879.65s, system CPU 3,960.92s and
peak RSS 576,096 KiB. The candidate was never started. These are interrupted-run
measurements, not a completed import time or speedup. The source vault remained
unchanged. The failed run is retained under
`movenotes-p7c-20260919-full-native`; its child exited from SIGINT (130).

The interruption traceback places the importer in `_existing_import_hashes`,
called by `_insert_rows` during a native batch flush. Fresh imports create the
database without indexes; P7b F02 creates `joplinididx` only **after** all rows
are imported, for folder repair. Thus F02 does not bound the preceding batch
collision lookups. This is the large-input case deferred under P7a F01, now
supported by real execution evidence. It is distinct from the review's incorrect
claim that previous batches' IDs are queried repeatedly: the growing table is
scanned even though each query asks only for the current batch's IDs.

A bounded synthetic check of the actual 500-ID query gives `SCAN notes` before
the index and `SEARCH notes USING INDEX joplinididx (joplin_id=?)` afterward.
For 2,000/4,000/8,000 existing rows, one unindexed lookup uses approximately
17,500/33,500/65,500 SQLite VM operations (rounded to 100). Per-batch work grows
with existing rows; repeating that across a fresh import produces quadratic
lookup work. This is structural evidence, not a claim that it accounts for every
second of the interrupted run. Private probe: `/tmp/movenotes-p7c-lookup-plan.json`.

The full trial was not left running through this known quadratic path merely to
obtain a baseline. No full-corpus benefit or memory acceptance is claimed for
F04, and no producer improvement is claimed for either Python candidate.

**Next prerequisite P7b2:** Codex `terra_worker` / `gpt-5.6-terra` / fixed `medium`
should implement an isolated bounded fresh-import ID lookup, considering the
existing index before insertion versus another bounded strategy. Keep C01/C02
and all ID/digest semantics constant, measure insertion/index-maintenance cost,
missing/duplicate IDs, fresh/unchanged/tiny merges, and interrupted rollback.
Own `obsidian2sql.py`, narrowly necessary `notesdb.py`, focused tests and candidate
harness updates; no Go/source-format changes. Parent reviews before Luna resumes
P7c. Do not simply move the index and assume it wins: measure the complete path.
Rerun the affected full comparison only after representative tests pass, holding
the new lookup treatment constant in F04 comparisons. Keep all old evidence.

P7c retains its incomplete status until this prerequisite and full-scale
acceptance are resolved. The original Go goals (both routes >=30% faster and
vault/RAW <=1.5) also remain unmet; this Python blocker does not explain or waive
those producer goals. Resumed 7c and 7d remain gated on parent/user review.

## Final prepared-library checks and checkpoint disposition

The corrected disjoint fixture completed five pairs per case under
`movenotes-p7c-20260919-f02-prepared-5`, with all fingerprints equal and cloned
seed hashes matching before each import.

| Case | Base seconds | F02 seconds | Median paired ratio |
|---|---|---|---:|
| Preserved unchanged | 9.68, 11.64, 9.73, 10.78, 11.08 | 9.35, 9.07, 9.36, 9.50, 10.45 | 0.9431 |
| Disjoint ten-note merge | 0.82, 0.81, 0.82, 0.87, 0.79 | 0.99, 0.93, 0.94, 0.79, 1.35 | 1.1481 |

The tiny-merge ratio is slower, despite small absolute times and substantial
spread; do not claim that every regression gate passed. The new lookup candidate
must recheck that case and total insertion cost. No additional repeats were used
to average away the unfavorable samples.

Ten focused harness tests pass, including variant isolation, metric/comparison
records, completion/resume handling and disjoint fixture preparation. Existing
299-test P7b results still cover unchanged production importer bytes; they are not
represented as newly rerun here. This slice introduces validation scripts only.

Final private inventory snapshots (logical bytes, not exclusive physical usage):

| Root suffix after `movenotes-p7c-20260919-` | Files | Logical bytes | Contents |
|---|---:|---:|---|
| `full-native` | 10 | 68,819 | Interrupted baseline status/log/time, rolled-back DB, exact frozen harness and lookup probe under `reproduction/` |
| `real-seed` | 76 | 2,025,958,813 | Completed real subset pairs, noisy unchanged pairs and failed original merge fixture |
| `f02-prepared-5` | 64 | 1,653,943,200 | Completed corrected prepared-library pairs and logs |
| `recipe-10000` | 10,001 | 21,084,523 | Read-only copied input under `vault/`, private selection manifest outside it |
| `merge-fixture` | 11 | 2,587 | Disjoint ten-note input and fixture manifest |

The interrupted importer closed its transaction and rolled back its uncommitted
rows; the large transient WAL did not survive as a completed database. No test
outputs were manually deleted. Each root has `ARTIFACT_MANIFEST.json`; the two
fixture roots use their own manifests rather than terminal notifications, so the
generic inventory labels their run status unknown. Prior synthetic roots retain
their separate manifests. Future cleanup must check dependencies first.

**Disposition:** F02/F04 have useful subset evidence; full adoption is pending.
P7c is a partial checkpoint, not complete acceptance. P7b2 is the next suggested
implementation slice. The full baseline need not be repeated unchanged through
its known quadratic lookup path; compare the bounded treatment under controlled
conditions after its correctness and subset gates pass.

Final harness review added unique attempt paths for replay logs and time files,
refusing orphan-file collisions instead of overwriting prior evidence. This did
not rerun or change any recorded benchmark.

## P7b2 resolution — bounded fresh-import ID lookups

P7b2 (Claude Code parent, 2026-10-22) creates the existing `joplinididx` when
`obsidian2sql.py` creates a new database, before the first batch. The batch
query, C01/C02 collision checks and all ID/digest semantics are unchanged;
existing databases already had the index from `open_database`, so merges and
reruns take the same path as before. The other indexes still wait for the final
pass. A regression test records every batch lookup's query plan during a fresh
import and requires `joplinididx` with no `SCAN`; it fails on the previous code.

Two treatments were measured against the previous code on deterministic recipe
subsets, with `--batch-size 500`. Outputs were fingerprint-identical across all
runs in each case.

| Case | Previous | Index at creation | In-memory run map |
|---|---:|---:|---:|
| 10,000 files fresh (2 runs) | 42.39, 37.87 s | 32.07, 29.95 s | 31.02, 33.01 s |
| 10,000 files unchanged (2 runs) | 25.65, 26.44 s | 25.72, 26.76 s | 26.38, 27.84 s |
| 40,000 files fresh | 330.45 s, 120,231 KiB | 130.08 s, 120,531 KiB | 136.81 s, 170,859 KiB |
| Ten-note merge into 10,000 (3 runs) | 0.50, 0.48, 0.53 s | 0.48, 0.53, 0.51 s | — |

The in-memory map was no faster and added memory proportional to the vault, so
the index treatment was adopted. From 10,000 to 40,000 files the previous fresh
import grew 8.3× and the adopted one 4.2×.

A single full-corpus scale check of the adopted code (not a paired benchmark)
imported all 382,206 files, 1,237,552 items, in **1,628.36 s** (user 1,397.00 s,
system 174.60 s, peak RSS 774,844 KiB). The interrupted P7c baseline had run
17,943.11 s without finishing. An identical rerun skipped all 1,237,552 items in
1,388.56 s (peak RSS 767,804 KiB). Private root:
`/run/media/$USER/HD2/movenotes-p7b2-20261022-full-native` (`P7B2_SCALE_CHECK.json`,
logs, times and the source tree used).

Consequences for resumed P7c:

- F02 is subsumed. The index now exists before any batch, so
  `notrios_p7c_prepare.py`'s F02 removal no longer changes behaviour, and every
  variant holds the P7b2 treatment constant, as this handoff required. Earlier
  F02 measurements stay historical evidence.
- The full corpus's peak RSS (about 757 MiB) and the unchanged rerun costing
  85% of a fresh import are new observations for P7c's memory and
  unchanged-path review; P7b2 does not address them.

## Resumed P7c — F04 with P7b2 constant (2026-10-22/23)

Claude Code Main ran the design frozen in the plan before any run. Variants
came from `scripts/notrios_p7c_prepare.py` at `HEAD` (`105027a`) with the
`f0b218a` reference; base and f04 differ only in F04's `_native_rows` change,
and both keep P7b2 and C01/C02. Runs were sequential, batch size 500, with
nothing else on the disk except one incremental `zg index` refresh at
2026-10-23T00:52:27Z, which ran on the home disk during R3 (recorded in
`HOST_EVENTS.txt`). Every comparison below had identical database fingerprints
and database sizes on both sides.

**R3, 10,000-file recipe subset, five alternating pairs** (ratio is f04 ÷ base):

| Case | Base (s) | F04 (s) | Pair ratios | Median |
|---|---|---|---|---:|
| Fresh | 43.36, 40.51, 35.22, 42.28, 41.06 | 35.19, 33.78, 32.94, 36.58, 32.80 | 0.812, 0.834, 0.935, 0.865, 0.799 | **0.834** |
| Unchanged rerun | 34.84, 32.66, 38.65, 29.94, 29.36 | 26.18, 28.17, 25.39, 24.64, 27.73 | 0.751, 0.863, 0.657, 0.823, 0.944 | **0.823** |
| Ten-note merge | 0.65, 0.53, 0.55, 0.50, 0.49 | 0.65, 0.52, 0.50, 0.52, 0.56 | 1.000, 0.981, 0.909, 1.040, 1.143 | 1.000 |

The `zg index` refresh overlapped only unchanged pairs 3 and 4 (pair 3's base
rerun and pair 4's f04 runs); excluding pair 3 the unchanged median is 0.843,
excluding both it is 0.863. The fresh case finished before it started. Median
peak RSS is 54,120 KiB base against 54,396 KiB f04 for fresh imports. The merge
is unchanged within 0.07 s, so the earlier small-merge noise does not recur with
P7b2 constant.

**R1, full native vault (382,206 files, 1,237,552 items), one pair:**

| Case | Base | F04 | Ratio |
|---|---|---|---:|
| Fresh | 1,911.79 s, 756,696 KiB | 1,853.15 s, 775,064 KiB | 0.969 |
| Unchanged rerun | 1,067.94 s, 742,328 KiB | 917.68 s, 767,324 KiB | 0.859 |
| Fresh setup for the unchanged case | 1,636.07 s, 750,692 KiB | 1,313.34 s, 776,308 KiB | 0.803 |

The third row is the fresh import the harness runs before each unchanged rerun;
it is not a gated measurement but is the same code on the same input. Both
databases are 4,968,349,696 bytes. F04's peak RSS is 2.4–3.4% higher, which is
the retained relative path per inventoried file (O(files), about 18–25 MiB here).

**R2, full RAW control (1,237,553 files), one pair:** `joplin2sql.py` is
byte-identical in both variants, so any difference is host noise.

| Case | Base | F04 | Ratio |
|---|---|---|---:|
| Fresh | 1,086.26 s, 1,845,848 KiB | 1,419.82 s, 1,847,524 KiB | 1.307 |
| Unchanged rerun | 993.95 s, 2,278,212 KiB | 750.47 s, 2,278,216 KiB | 0.755 |
| Fresh setup for the unchanged case | 1,482.25 s | 1,383.35 s | 0.933 |

The same code moved by −25% to +31% between single full-corpus runs, so one
full-corpus pair cannot resolve a 5% effect. Both RAW databases are
5,618,405,376 bytes. In both R1 and R2 the base side ran first in every
full-corpus pair; R2 shows no consistent first-run bias.

**R4, full preserved route.** `sql2obsidian.py` at `HEAD` exported R2's base
library (1,237,553 items) in 1,406.14 s at **3,668,096 KiB** peak RSS: 382,206
notes, 768 native directories and a 1,619,761-file, 2.56 GB vault whose
`.movenotes/manifest.json` is 530,428,800 bytes. `obsidian2sql.py` at `HEAD`
then imported the bundle in **2,255.54 s** at **1,936,788 KiB** peak RSS
(7,314,034,688-byte database); the round trip used 14.8 GB of disk. The first
attempt failed in under a second because `sql2obsidian.py` requires an existing
`--output` directory; it is kept as `attempt-1-missing-dir`. Against the RAW
library, every one of the 1,237,553 items is present and 69 of 75 compared
columns are identical on every row; the six `note_obsidian_*` snapshot columns
differ on exactly the 382,206 notes, because the reimport records the exported
vault's bytes. So the preserved route is lossless at full scale and no longer
quadratic. Both peaks hold the whole manifest: the exporter builds every item
dict and the complete `json.dumps` string, and the importer `json.loads` the
530 MB file. That is O(items) memory on a path the invariants require to be
bounded; it is planned as slice M1.

**R5, interrupted fresh import, 40,000 files.** Valid attempts used a Python
driver that restores default SIGINT handling in the child:

| Attempt | Interrupt landed in | Exit | Notes left | Rerun | Rerun fingerprint |
|---|---|---|---:|---|---|
| 3, SIGINT at 20 s | `_native_rows` inventory | `KeyboardInterrupt` | 0 | 181.07 s | `38edc15c…`, matches |
| 4, SIGINT at 60 s | batch insert (`notesdb` row tuple) | `KeyboardInterrupt` | 0 | 182.30 s | `38edc15c…`, matches |

`38edc15c96f2…` is the uninterrupted P7b2 40,000-file import. Two earlier
attempts were invalid and are kept: both started the import with a
non-interactive shell's `&`, whose child inherits SIGINT as ignored, so both ran
to completion. (Attempt 1 was first misread as finishing before its 60 s
signal; its timestamps show it ran about 3 minutes.) Recovery is correct, but
slow: the interrupted run leaves an empty library, and an import into an
existing library creates all eight indexes before its first insert, where a
new database defers all but `joplinididx`. Alternating runs into a new library
and into an empty existing one, all fingerprint-identical:

| Files | New library | Empty existing library | Slower by |
|---:|---|---|---:|
| 10,000 | 28.98, 28.96 s | 33.71, 33.90 s | 16.7% |
| 40,000 | 123.27, 121.47 s | 181.23, 180.50 s | 47.8% |

Peak RSS is the same on both sides. That is planned as slice I1.

**R6, attribution.** One cProfile run of an unchanged 10,000-file rerun (58.3 s
under the profiler) spent 24.8 s in the `_native_rows` inventory and 31.6 s
building rows that `_insert_rows` then skips: `parse_frontmatter` (20,000 calls)
13.1 s, `_frontmatter_summary` 11.5 s, link rewriting 3.2 s, compressed
application data 3.1 s. ID lookups and indexing were negligible. That is
planned as slice U1.

**F04 gates.** On the subset F04 meets the adoption gate in every pair: fresh
16.6% and unchanged 17.7% median improvement, merge unchanged, memory +0.5%,
outputs identical. At full scale the frozen gate asks R1 for at least a 5%
median improvement; its one gated fresh pair shows 3.1% and its unchanged pair
14.1%, and the ungated fresh setup pair 19.7%. All three full-scale F04 timings
are faster, but R2 shows single-pair noise of up to 31%, so R1 neither confirms
nor refutes 5%. Under the frozen gate F04's full-scale adoption was therefore
held as ambiguous and put to the user, who on 2026-10-23 **accepted F04 at full
scale** on this evidence. F04 stays in `HEAD`.

**Go producer targets — correction and removal.** An earlier draft of this
section called them "unmet". That was wrong: they were set against `notriosctl`
timings at Notrios `7662fdd` (7,245.65 s RAW, 17,142.24 s vault), 290 commits
before the `v1.0.0` pin and before Notrios's own J17/J32 import performance
work, and resumed P7c never ran Notrios. They were stale and unmeasured. On
2026-10-23 the user removed them from the plan. For this repository's own
importers, the full-corpus fresh vault/RAW ratio in this batch is about 1.27
base and 1.13 with F04 (1,774 and 1,583 s against 1,402 s, medians of all fresh
timings), with the RAW noise above; it is not comparable with the Go timings.

Private roots under `/run/media/$USER/HD2/`: `movenotes-p7c-20261022-sources`
(source trees, harness copies, run scripts, logs, `HOST_EVENTS.txt`),
`movenotes-p7c-20261022-variants`, `movenotes-p7c-20261022-r3-subset`,
`movenotes-p7c-20261022-r1r2-full`, `movenotes-p7c-20261022-r4-preserved` and
`movenotes-p7c-20261022-r5-recovery` (attempts, `empty-existing-check`).

## U1 — unchanged notes skipped before conversion (2026-10-23)

R6 showed an unchanged rerun spending most of its time converting notes that
`_insert_rows` then skips. U1 makes the same decision earlier. `_native_rows`
now reads note bytes one batch (`--batch-size`, 500 by default) ahead and looks
up that batch's `(ID, SHA-256 of the raw bytes)` pairs in the database with
`_existing_import_hashes`. A note already stored with the same bytes is passed
on as a skip marker without link rewriting, compressed application data or row
assembly. Everything else is converted as before. The database only gains rows
during an import, so a note found unchanged at read-ahead time would also have
been skipped at insert time. Tags are still read from every note, so missing
tag and note-tag rows are still recreated. Skipped notes still take a batch
slot, so batches close where they did and collision errors come in the same
order. A file that cannot be read or decoded is reported in file order.

Paired alternating runs of `scripts/notrios_p7c_benchmark.py`, `9c25e2a` (base)
against the U1 working tree (`obsidian2sql.py` SHA-256 `9b6eeb88…aa87`, the
committed file). Every output is fingerprint-identical to base.

| Case | Pairs | Base | U1 | Median U1/base | Peak RSS, U1 − base |
|---|---:|---:|---:|---:|---:|
| Unchanged rerun, 10,000 files | 5 | 25.81–40.52 s | 12.17–14.63 s | **0.472** | −2.1 MB |
| Unchanged rerun, full vault | 1 | 983.03 s | 515.14 s | **0.524** | −1.9 MB |
| Fresh import, 10,000 files | 5 | 29.93–47.92 s | 28.07–32.79 s | 0.938 | +2.1 MB (+4.0%) |
| Ten-note merge into 10,000 files | 5 | 0.53–0.60 s | 0.52–0.68 s | 1.038 | +0.5 MB (+1.8%) |

The ungated setup imports agree. The five 10,000-file fresh setups for the merge
case ran 0.86–0.98 of base. The full-vault fresh setup ran 1,537.89 s on base
and 1,601.87 s on U1 (1.042, one run, within the up to 31% single-run noise R2
showed), at 775,396 and 781,476 KiB peak RSS. The merge's median difference is
0.02 s, at the timer's 0.01 s resolution, with pairs from −0.04 to +0.08 s.

The fresh-import memory increase is one batch of notes held read ahead of the
batch waiting to be inserted. It is bounded by the batch size and does not grow
with the vault. U1's frozen acceptance asked for no memory regression, so the
increase was put to the user, who on 2026-10-23 **accepted U1 as measured**.

RAW imports (`joplin2sql.py`) and preserved-bundle items run unchanged code, so
R2's and R4's results stand for them. Only extra native files in a preserved
vault use U1's path.

Private roots under `/run/media/$USER/HD2/`: `movenotes-u1-20261023-sources`
(`SOURCES.txt` with hashes, harness copies, `run_u1.sh`, `run_u1.log`),
`movenotes-u1-20261023-variants` (`base`, `u1`), `movenotes-u1-20261023-subset`
and `movenotes-u1-20261023-full`.

## I1 — empty existing library imported like a new one (2026-10-23)

R5 showed that an import into an existing library with no rows, which is what
an interrupted fresh import leaves, kept all eight indexes and updated them row
by row, while a new database defers all but `joplinididx`. `obsidian2sql.py`
now checks the library it opens; when it holds no rows, it drops the other
indexes with `notesdb.drop_deferred_indexes`, and the final pass rebuilds them.
If that run stops too, the next open recreates them, which on an empty table is
immediate. A library holding any row takes the previous path, and
`joplin2sql.py` is unchanged.

Base is `902bad2`; I1 is that tree plus the working `obsidian2sql.py`
(`9aeb1f1f…5db`) and `notesdb.py` (`d7e857a0…94c`), the committed files.
Runs alternate, base first in pair 1.

| Case | Pairs | Base | I1 | Median I1/base | Pair range |
|---|---:|---:|---:|---:|---:|
| Empty existing library, 10,000 files | 5 | 38.25–41.18 s | 30.31–33.44 s | **0.799** | 0.761–0.874 |
| Empty existing library, 40,000 files | 3 | 194.62–258.40 s | 129.84–145.37 s | **0.667** | 0.533–0.670 |
| New database, 10,000 files | 5 | 30.66–36.07 s | 31.26–35.99 s | 1.020 | 0.966–1.041 |
| New database, 40,000 files | 3 | 125.80–134.11 s | 126.46–137.48 s | 1.025 | 0.991–1.029 |
| Unchanged rerun, 10,000 files | 5 | 11.80–13.24 s | 12.02–13.81 s | 1.041 | 0.908–1.101 |
| Ten-note merge into 10,000 files | 5 | 0.57–0.64 s | 0.53–0.63 s | 0.930 | 0.889–1.000 |

Every output in a case has one fingerprint, and the empty-library imports match
the new-database imports (`7945a871…` at 10,000 files, `38edc15c…` at 40,000).
All end with the same nine indexes. Peak RSS is unchanged in every case, within
0.6 MB.

For new databases, unchanged reruns and merges I1 runs the same statements as
base plus one `SELECT 1 FROM notes LIMIT 1`, so their medians (all inside the
pair spread) are measurement noise, not a regression.

**Recovery.** A real SIGINT 60 s into a 40,000-file I1 import (the
`r5_interrupt.py` driver) left 0 rows with only `joplinididx` and the settings
key. The rerun took 140.41 s at 126,140 KiB, against 181.23 and 180.50 s for
an empty-library import of the same files before I1 (R5's check), and matched the new-database fingerprint with
all nine indexes.

Private roots under `/run/media/$USER/HD2/`: `movenotes-i1-20261023-sources`
(`SOURCES.txt`, `i1_empty.py`, `run_i1.sh`, `run_i1.log`, harness copies),
`movenotes-i1-20261023-variants` (`base`, `i1`) and `movenotes-i1-20261023-runs`
(`empty-10k`, `empty-40k`, `harness-10k`, `harness-40k`, `interrupt-40k`).

## M1 — preservation manifest streamed both ways (2026-10-23)

R4 showed that the preserved round trip peaked at 3.5 GiB in `sql2obsidian.py`
and 1.8 GiB in `obsidian2sql.py`, from holding the whole 530 MB
`.movenotes/manifest.json`. The exporter kept every item dict and then the
complete `json.dumps` string; the importer `json.loads` the file.

`sql2obsidian.py` now writes the manifest as it produces items, through
`_ManifestWriter`, 1,024 items at a time. The file is byte-for-byte the
previous `json.dumps(manifest, ensure_ascii=False, indent=2)` output, and the
format is unchanged. Encoding one item per call rebuilt the indenting encoder
each time and was 8 s slower than `json.dumps` on R4's manifest; one call per
batch is not slower. `obsidian2sql.py` reads the manifest with `_JsonReader`,
which runs the standard decoder's `raw_decode` on one value at a time over 1 MiB
reads and walks only the enclosing object and item array. It keeps only what
the import uses: the item count, each RAW path in order, the resource IDs, and
each note's ID, vault path and digest. It reads the whole document before
deciding anything, so a malformed manifest still means a native import, as
before (V1 changes that). A number cut by the end of the buffer is retried
rather than decoded early.

Base is `4dec69b`. M1 is that tree with the working `sql2obsidian.py` and
`obsidian2sql.py`. The full-scale export and the first 40,000-file export
pairs ran the per-item writer (`5945c7d0…`). The final batched writer
(`974133db…`) was then paired again at 40,000 files; the committed file
(`f100e2d0…`) differs from it only in a docstring line. The reader
(`b323a2d1…`) did not change after the runs. Runs alternate, base first in
pair 1.

| Case | Pairs | Base | M1 | Median time M1/base | Peak RSS base → M1 |
|---|---:|---:|---:|---:|---:|
| Export, 40,000-file library (132,775 items), final writer | 3 | 165.37–214.30 s | 164.43–196.10 s | 0.986 (0.915–0.994) | 384,852 → 107,500 KiB (0.279) |
| Export, 40,000-file library, per-item writer | 3 | 192.46–204.46 s | 181.86–200.75 s | 0.957 (0.917–1.043) | 384,868 → 107,248 KiB (0.279) |
| Preserved import of that export | 3 | 160.33–182.20 s | 163.19–198.42 s | 1.063 (1.018–1.121) | 211,352 → 82,840 KiB (0.393) |
| Synthetic preserved bundle, fresh import | 5 | 9.51–10.25 s | 9.59–10.48 s | 1.038 (0.962–1.087) | 43,800 → 42,156 KiB |
| Synthetic preserved bundle, unchanged rerun | 5 | 6.81–6.93 s | 6.76–6.92 s | 0.999 (0.978–1.003) | 43,668 → 41,536 KiB |
| Export, full library (1,237,553 items), per-item writer | 1 | 1,463.81 s | 1,608.34 s | 1.099 | 3,637,316 → 816,632 KiB (0.225) |
| Preserved import of R4's vault (old-code manifest) | 1 | 2,755.18 s | 2,567.24 s | 0.932 | 1,936,876 → 515,968 KiB (0.266) |

**Identity.**
- Every export in a case has one manifest digest and one whole-vault digest:
  - at 40,000 files, `5a315af0…` and `30f45283…` (172,777 files);
  - at full scale, `61daef6c…` and `b7770fad…` (1,619,761 files).
- The full-scale manifests from both base and M1 are byte-identical to R4's own (`61daef6c…`).
- Every preserved import in a case has one fingerprint, with the same summary line:
  - 40,000 files: `a6f1f307…`, "imported 132,775 item(s) from Joplin preservation bundle; 0 unchanged item(s) skipped";
  - R4's vault: `8c0991bf…`, which is R4's import fingerprint, with 1,237,553 items.
- Every exit status is zero.

**Time, isolated.** The paired totals move either way, by up to 12% across 3 pairs and 10% on the single full-scale pair. R2's RAW control showed up to 31% for identical code. To measure M1's own cost, `micro.py` timed only the manifest read and write on R4's manifest, alternating three times each.
- **Read:** median 25.4 s against `json.loads` plus the old derivation at 21.7 s. That is about 4 s, or 3 µs per item, in Python around `raw_decode`, 0.2% of the full preserved import. A regex fast path for the separators measured no better and was reverted.
- **Write:** the final batched writer took 24.9 s (23.26–26.25 s) against `json.dumps` at 26.2 s (24.93–28.76 s). The per-item writer took 36.1 s.

All outputs were byte-identical. The full-scale export's 1.099 includes the per-item writer's roughly 8 s; the remainder is within the single-pair noise.

**Memory.** The importer now keeps O(items) only for the compact state above: 302,700 KiB for R4's 1,237,553 items, against 1,933,600 KiB for `json.loads`. The exporter holds at most 1,024 item dicts. The remaining 816,632 KiB full-scale export peak was not attributed further, but the manifest now contributes at most one batch to it.

**Equivalence.**
- `test_streamed_manifest_matches_one_json_dump` checks the writer's bytes against `json.dumps` for zero, one and three items at batch sizes 1, 2 and 1,024.
- `test_manifest_reader_matches_json_loads` checks the reader against a `json.loads` reference over 13 documents (malformed, duplicate keys, odd whitespace, a missing separator, numbers cut by the buffer) at read sizes from 1 character to 1 MiB.
- `fuzz.py` made 140,000 random comparisons with that reference, including damaged documents, at seven read sizes. There were no mismatches.

Private roots under `/run/media/$USER/HD2/`:
- `movenotes-m1-20261023-sources`: `SOURCES.txt`, `SOURCES-m1b.txt`, `m1_pairs.py`, `m1b_pairs.py`, `run_m1.sh`, `run_m1.log`, `micro.py`, `micro-results.txt`, `fuzz.py`, harness copies;
- `movenotes-m1-20261023-variants`: `base`, `m1`, `m1b`;
- `movenotes-m1-20261023-runs`: `export-40k`, `export-40k-m1b`, `import-40k`, `harness-preserved`, `export-full`, `import-full`, `full-manifests.txt`.
