# Notrios corpus trials — 7c (in progress)

The user authorized 7c in the unchanged Codex session. This is a parent-owned
slice. The user subsequently assigned harness completion and notification-based
monitoring to `luna_worker` (configured `gpt-5.6-luna`, fixed `max`), child
`/root/notrios_7c_monitor`. Actual child model/effort are not exposed. Codex
parent (runtime family GPT-6; exact alias/effort not exposed) owns investigation
and acceptance. Monitoring uses OS completion waits and parent 25-minute
notification waits, with occasional timeout fallback checks.

**Status: partial.** Both recipe imports finished successfully, but the real
conversion gates refused input. Full real-data pipelines were skipped; 7c is
not complete and 7d must not begin yet.

## Inputs and isolation

The three source paths and comparison contract remain those in
[NOTRIOS_IMPORT_PLAN.md](NOTRIOS_IMPORT_PLAN.md#corpus-and-measurement-procedure).
Initial allocated sizes: Joplin 1.5 GiB, recipe RAW 5.1 GiB, recipe vault 1.6 GiB.
The isolated, owner-only work directory is
`/media/$USER/HD2/movenotes-7c-20260916/`; HD2 initially had about 59 GiB free.
No remote localization, deployment or user-service configuration is used.

The current Notrios checkout advanced beyond the plan's producer pin. These
trials instead use `/tmp/movenotes-s28b-notriosctl`, whose Go build metadata
identifies clean revision `7662fdd5b55d6f34f14874f70ba6db9f9e7676ac`, Go 1.27.0,
Linux amd64, schema 28. Each route uses an explicit empty config, its own database,
asset store and publication profile. Publications and any note-bearing logs stay
on the private work volume. Only aggregate evidence will be committed.

## Measurement procedure

Each command has a durable `checkpoint.json`, `stdout.log`, `stderr.log` and
GNU time output `time.json`. Commands return before their checkpoint becomes
complete; failures stop the dependent workflow. A completed checkpoint is not
rerun automatically, and a running checkpoint requires inspection before restart.

Stages are producer ingestion, publication planning/review, publication, producer
verification, Python verification, conversion, vault export, site generation,
Hugo and Bluge indexing. Conversion additionally records callback timestamps,
current RSS and process peak RSS in `conversion-phases.jsonl`: payload construction
can be separated from the importer's verification pass. Phase-boundary RSS is
not claimed as a resettable phase-specific peak. GNU time measures each process
stage's peak. Publication planning retains default privacy exclusions and rejects
source-bundle inclusion; output is local only.

Synthetic controls contain 1,000 and 10,000 simple notes from one 10,000-note
isolated producer library. Their initial run overlaps the Joplin source-ingestion
stage; report wall times as contended observations, not isolated throughput.
Real routes run sequentially, bounded selection before full selection. Recipe
imports use batch size 500 (the pinned CLI maximum; failed 1,000 attempts are retained); Joplin uses the producer's default 100.

The completed recovery trial killed a synthetic conversion after payload creation,
required a rerun to refuse the stale lock, verified ownership tokens before
removing only the killed trial's directories, then checked fresh and unchanged
reruns and source/output hashes. It does not introduce an automatic repair path.

## Resume checkpoints

Inspect the private work tree and live processes before starting any command.
The current sequential orchestrator waits for Joplin ingestion, then gates each
route's full trial on its bounded trial. Independent routes continue after a
bounded failure; dependent stages are recorded as skipped.

- `/tmp/movenotes-7c-run.py`: measured producer ingestion.
- `/tmp/movenotes-7c-pipeline.py`: reviewed bounded/full publication through Bluge.
- `/tmp/movenotes-7c-convert.py`: conversion phase recorder.
- `/tmp/movenotes-7c-orchestrate.py`: sequential real-route driver.
- `/tmp/movenotes-7c-synthetic.py`: synthetic controls.
- `/tmp/movenotes-7c-recovery.py`: controlled abrupt-interruption recovery.
- `/tmp/movenotes-7c-compare-recipes.py`: disk-backed semantic comparison.
- `/tmp/movenotes-7c-monitor.py`: completion notification and aggregate evidence.
- `/tmp/movenotes-7c-resume.py`: corrected recipe attempts and downstream gates.

Copies of the workflow scripts are saved under the private work directory's
`scripts/` folder. Logs and per-stage checkpoints, not this status document, are
the authoritative execution state. Final aggregate notification is `notification.json`; detailed state is in
`terminal.json`, with corrected recipe rerun logs under `resume/`. Earlier
terminal snapshots and failed attempts are retained. The final regression rerun
is in `resume/final-regressions.log`; the older successful
`final-regressions/checkpoint.json` describes a different run.

## Observed results (2026-09-17)

Both recipe producer libraries contain 382,206 current documents. Producer
imports succeeded at the pinned schema. Stage measurements below use GNU time;
RSS is KiB and wall time is seconds.

| Producer ingestion | Wall seconds | Peak RSS KiB |
|---|---:|---:|
| Joplin | 1,567.83 | 534,216 |
| Recipe RAW | 7,245.65 | 2,959,800 |
| Recipe vault | 17,142.24 | 1,744,220 |
| Synthetic 10,000 | 371.15 | 37,660 |

All three bounded real publications passed producer and Python verification.
Joplin conversion refused unsupported/unaccounted active link syntax: a private
lexical diagnostic accepted 963 of 1,000 bodies and refused 37. Both recipe
conversions refused unsupported control characters. No source notes were
filtered to bypass these gates, and no importer policy was relaxed. Full real
pipelines, real attachment export checks, and downstream scale acceptance remain
unmeasured.

`recipe-comparison.json` records equal document counts but unequal semantic
multisets: 378,524 title matches, zero body matches, 25,330 tag matches, and zero
combined matches. Normalization uses NFC, LF line endings, title edge whitespace,
body trailing newlines, and sorted unique tags. These are independent multiset
counts, not paired-document agreement. Source/import differences require further
diagnosis before any equivalence claim or expanded normalization is justified.

Synthetic bounded 1,000 and full 10,000 document pipelines passed through Bluge.
The synthetic resource checks passed on a corpus with no resources, so they do
not establish real-corpus attachment fidelity. Recovery passed the controlled
kill, stale-lock refusal, ownership-checked cleanup, fresh rerun and unchanged
rerun checks.

| Synthetic 10,000 stage | Wall seconds | Peak RSS KiB |
|---|---:|---:|
| Plan | 1.68 | 22,940 |
| Publish | 48.33 | 55,684 |
| Producer verification | 6.66 | 30,088 |
| Python verification | 36.73 | 33,904 |
| Conversion, including internal verification | 128.32 | 50,060 |
| Vault export | 79.75 | 94,744 |
| Site generation | 81.33 | 51,476 |
| Hugo | 29.56 | 584,264 |
| Bluge indexing | 8.86 | 64,640 |

Private per-stage measurement files retain disk availability, output byte/file
counts and inventory hashes; conversion callback records separate phase timing.
These observations do not establish constant memory for the whole pipeline.

An earlier 262-test regression run passed. The final rerun executed 262 tests in
159.042 seconds with one receipt-propagation inventory comparison failure;
Luna proved both historical hashes are permutations of the same three JSONL
records. The test now compares complete search record multisets while preserving
exact checks on other files. All 262 tests passed after that correction
(139.150 seconds). Evidence: `resume/receipt-permutation-proof.json` and
`resume/final-regressions-corrected.log`. The original failure is retained.

A bounded producer-body diagnostic found U+0014 in both routes (five occurrences
in each first-100 revision sample). All sampled bodies began with YAML. Of 100
RAW sample titles, 98 matched vault titles; 73 paired bodies became equal after
removing the first YAML block and trimming edge whitespace. This exploratory
sample is not an equivalence result: matching by title is not necessarily unique,
and the whole-corpus comparison still includes embedded frontmatter. A revised
semantic audit must distinguish frontmatter/import metadata from recipe text
and reconcile tag representation, as the plan requires. No source data changed.

## Remaining acceptance work

Diagnose source/import semantic differences and refine the semantic audit; review
real-body control characters and bracket syntax against the frozen conversion
contract. Any contract expansion needs an explicit plan decision and targeted
regressions before retrying refused conversions. Reuse the completed producer
libraries; do not repeat the multi-hour imports. Only then run the outstanding
full real-data stages, attachment checks and final acceptance gate.

The revised plan inserts **C7a (Main) → C7b (Terra) → C7c (Luna)** before
resuming 7c. These pending prerequisites cover contract decisions, compatible
implementation, and a refined semantic/completion harness. Existing failed
attempts remain evidence; completed producer imports should be reused.

Performance prerequisites **P7a (Main) → P7b (Terra) → P7c (Luna)** now follow
C7a–C7c before resumed 7c. The multi-hour times above measure Go Notrios
producer ingestion; the supplied reviews examine movenotes Python importers.
The plan separates those tracks, profiles both, and adopts changes only after
controlled speedup and correctness evidence. Historical libraries remain intact;
new disposable imports are permitted for the planned paired experiments.

C7a is complete: [compatibility decisions](NOTRIOS_COMPATIBILITY_REVIEW.md).
It explains observed control provenance, a reliable recipe source join and
producer metadata/tag differences. C7b implementation and C7c full comparison
remain pending; original 7c refusals and skipped stages are not acceptance passes.
