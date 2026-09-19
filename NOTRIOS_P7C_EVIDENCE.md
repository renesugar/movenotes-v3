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
