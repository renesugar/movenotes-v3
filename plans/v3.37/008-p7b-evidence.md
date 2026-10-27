# P7b isolated import candidates

P7b implements candidates selected by [P7a](007-performance-evidence.md).
Full-corpus performance adoption remains P7c; no acceptance producer pin changes.
Python baseline is `f0b218a`. The Go experiment uses current Notrios
`f478da7f1065d95d47cf21612833cef991bb8255`, not historical acceptance pin
`7662fdd5b55d6f34f14874f70ba6db9f9e7676ac`.

## Changes and limits

- **F02:** create the existing `joplinididx` before Obsidian's folder repair.
  Fresh imports previously deferred it until after the correlated parent lookup.
  General index creation remains deferred. Existing imports reuse the same index;
  there is no extra composite index to rebuild/drop for each small merge.
  The repair SQL and parent ordering remain unchanged.
- **F04:** retain the relative path computed during inventory and reuse it for
  identity, resource and note processing. Path normalization and traversal order
  remain unchanged; the inventory holds a tuple/string per source entry.
- **C01 correctness:** track identities pending in each insert batch. Identical
  duplicates skip; different digests fail before that batch inserts. Existing
  transaction rollback remains responsible for earlier batches.
- **C02 correctness:** preserved resources validate all existing destinations
  before copying any resource. Differing bytes and non-file/symlink destinations
  fail. Default helper callers retain streaming behavior. This prevents a late
  collision from leaving earlier copies; it is not a new atomic-filesystem
  guarantee for arbitrary I/O failures or concurrently mutated sources.
- **G08 experiment:** packaged current-Notrios parser patch precomputes newline
  offsets, binary-searches the line and counts runes within that line. Existing
  Markdown-before-wikilink result order and context extraction remain unchanged.
  This avoids rescanning preceding lines, but does not remove repeated column
  scans for many links on one long line. See `experiments/notrios-p7b/README.md`.
  The original Notrios checkout is unchanged.

**Deferred:** F03 frontmatter, F07 RAW parsing and F08 overlay need independent
experiments and broader exact-byte tests; they are not silently bundled into
these candidates. G01 preparation reuse requires a reviewed statement-lifetime
owner across ordinary saves and importer transactions; no global statement cache
was introduced. Other P7a dispositions remain in force. C01/C02 are correctness
fixes, not claimed performance gains.

## Validation protocol and artifacts

Terra authored `scripts/notrios_p7b_benchmark.py` and
`scripts/notrios_p7b_long_batch.py`. The driver runs all eight Python test modules,
three alternating unprofiled pairs for each Python fresh route, baseline/candidate
Go suites and four Go parser microbenchmarks sequentially. Per-stage logs,
atomic terminal status, source/input fingerprints and artifact inventories avoid
short polling and retain failures. Output roots must be new; no evidence is deleted.

Python comparisons fingerprint note bodies, source envelopes/properties, metadata,
source timestamps, auxiliary tables/settings and resource trees. They exclude
local `note_id`/`note_internal_date` and normalize import-generated native tag and
relation timestamps only. This comparison is broader than an ID/count check,
but does not replace exact export roundtrips, recovery tests or the full P7c matrix.
The focused comparator test detects body, envelope, timestamp, auxiliary-table and
resource divergence. The baseline probe now has `--expect-fixed` for C01/C02.

Frozen Python source copies are `/tmp/movenotes-p7b-python-baseline` and
`/tmp/movenotes-p7b-python-candidate`. Disposable Go copies are under
`/tmp/movenotes-p7b-go/{baseline,candidate}`. The P7a generated 2,000-note inputs
are read-only inputs to this batch, not recipe-corpus samples. Exact launch
arguments and stage statuses are in the private run's `notification.json`.

The subset comparison tests the combined Python candidate. Before attributing a
speedup to F04 alone, P7c must compare F02-only/F04-only variants, plus unchanged,
small merge, attachments and memory effects. G08 needs old/new full-Candidate
parity on broader context/overlap fixtures and representative end-to-end imports;
microbenchmark gains alone cannot justify adoption. No full 382,206-note runs
are launched by P7b. Existing 7c compatibility gates remain unchanged.

## Execution attribution

Codex parent (runtime family GPT-6; exact model/effort not exposed) scoped and
reviewed the work, prepared isolated source copies and owns final acceptance.
`/root/p7b_candidates` used the configured Terra worker (gpt-5.6-terra, fixed medium)
for implementation; `/root/p7a_monitor` used configured Luna (gpt-5.6-luna, fixed
max) for the long sequential validation batch. Actual child model/effort were not
independently exposed. Existing session billing suitability confirmation applies;
billing route is not exposed. The authoritative ledger is
`plans/v3.37/notrios-import-ledger.json`. Two-slot capacity required staged workers.

## First completed batch (retained, initially failed comparison)

Private root: `/media/$USER/HD2/movenotes-p7b-20260918`.
All **299 Python tests passed** in 176.102s. All 18 fresh import commands succeeded.
The comparator correctly withheld success because native tag/relation property
JSON contained generated timestamps not normalized by its first version. The
original failed result remains intact; corrected comparison must explicitly
account for that difference without rerunning completed imports. Go stages were
not reached in that batch.

| Route | Baseline seconds, three pairs | Candidate seconds, three pairs | Median change |
|---|---|---|---|
| Native vault | 15.029, 15.498, 16.044 | 13.155, 14.728, 12.149 | 15.1% lower |
| Preserved vault | 253.118, 255.654, 262.870 | 13.448, 13.779, 14.344 | 94.6% lower |
| RAW control | 6.542, 6.379, 7.566 | 6.996, 6.733, 6.631 | 2.9% higher |

RAW has no targeted performance change and these small differences overlap its
observed variability; no RAW speedup is claimed. Preserved fingerprints matched
in every pair. Native correctness requires the corrected comparison described
above. These are synthetic fresh subsets, not producer timings or full-corpus
adoption evidence. The first inventory recorded 42 files / 1,121,364,956 logical
bytes before later small evidence files; regenerate it for current cleanup sizes.

## Corrected comparison and Go disposition

The new `python-comparison/RECOMPARE_REPORT.json` compares all 18 completed outputs:
record set complete, source hashes unchanged, input hashes unchanged, every paired
fingerprint equal. It records the exact comparator SHA-256. Normalization now
also covers only the four generated timestamp keys in ordered property records
for type-5 `.movenotes/tags/` and type-6 `.movenotes/note-tags/` rows. Unknown
properties, their order, bodies and genuine source timestamps remain compared.
The first failed comparison is retained. No importer timing was rerun to repair
the comparator. Focused comparator tests passed after this change; the prior
299-test production regression run used the same production importer bytes.

The resumed Luna worker `/root/p7b_monitor_resume` verified process liveness and
ran only the remaining Go stages under
`/media/$USER/HD2/movenotes-p7b-20260918-go`. Baseline and candidate `go test ./...`
both passed. Identical benchmark source was installed in both trees.

| Go parser microbenchmark | Baseline ns/op | Candidate ns/op | Candidate change | Allocations baseline → candidate |
|---|---:|---:|---:|---:|
| Many links, one line | 18,910,073 | 13,088,193 | 30.8% lower | 1,021 → 1,022 |
| Many lines with links | 22,981,481 | 7,477,073 | 67.5% lower | 1,022 → 1,028 |
| No links | 5,890,782 | 7,745,784 | 31.5% higher | 0 → 7 |
| One link after a long line | 10,667,375 | 15,567,442 | 45.9% higher | 5 → 6 |

**G08 is rejected in its current form.** These are single benchmark invocations,
not an end-to-end speedup proof; the substantial regressions are sufficient to
withhold it. The patch is retained as a reproducible rejected experiment. Do not
promote it or spend full-corpus validation on it. A revised approach would need
new bounded measurements and differential tests before entering the P7c producer
matrix. No Go production performance change is adopted by P7b.

P7c's next actionable work is isolated F02/F04 validation, unchanged/small-merge
and attachment cases, memory effects, and broader correctness/recovery checks
under Luna/max monitoring. Reuse completed matching measurements where relevant.
Only credible route-specific winners proceed to full confirmation. The >=30%
both-producer and <=1.5 ratio goals remain unproven; Python subset results do not
satisfy them. G01 and other deferred producer candidates require a reviewed
implementation handoff before testing, not an unrecorded Luna implementation.
