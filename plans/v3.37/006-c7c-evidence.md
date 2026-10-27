# C7c compatibility comparison evidence

This report records the C7c harness and validation state without copying note
IDs, titles, paths, source bytes, database locations, or private archive
contents into repository documentation.

## Harness and bounded validation

The comparator uses schema version 5 and rules version
`c7c-recipe-semantic-v6`. Identity sets, field groups, duplicate row
multisets, route-pair groups, route identity maps, and publication source
cohorts are materialized in private SQLite tables with explicit primary-key
indexes. Comparison SQL has no grouped CTE anti-joins or `SELECT DISTINCT`
joins that rely on SQLite automatic indexes. Every comparison substage runs
through a progress-handler deadline and records aggregate labels and
durations.

The final focused suite passed all 26 tests:

```text
Ran 26 tests in 19.851s
OK
```

The tests cover changed-input checkpoint rejection, checkpoint resume, stale
result rejection, PID reconnect, duplicate and NULL identity fail-closed
behavior, privacy span validation, publication readiness, parser grammar,
folder snapshots, pinned title handling, body status, separate tag channels,
and a 20,000-row end-to-end comparison. The scale case exercises every
comparison and publication query with a 30-second per-query deadline. `git
diff --check` passed.

An independent 100-record source-to-route smoke passed before the full run.
It selected tagged, untagged, numeric-metadata, leading-LF, and pinned-title
categories. Both RAW and vault had 100/100 documents, body hashes, and body
status results; vault metadata hashes matched 100/100. RAW titles were exact
100/100; vault titles were exact 98/100 and pinned-frontmatter matches 2/100.
The report contained no source content.

The corrected parser was also applied to all 401 records that had residual
status in the preceding attempt: all 400 numeric/boolean-tag records and the
single boolean-tag frontmatter record now return `ok`. The former vault outer
frontmatter status case also parses as `ok` under the reviewed producer scalar
rule. Unknown YAML remains refused.

## Fresh monitored corpus attempt

The fresh v6b attempt completed through the PIDFD monitor with one terminal
notification. Its private launch manifest, checkpoint, result, query trace,
child exit receipt, monitor state, and terminal notification are retained in
the private attempt directory. The child returned zero because the comparison
completed; `semantic_equal` is **false**, so no equivalence claim is made.

The monitor wall time was 5,174 seconds (about 86.2 minutes), and the
comparison checkpoint ran for about 4,161 seconds (about 69.4 minutes). The
private spool occupied 2,453,331,733 bytes at completion. All 46 recorded
comparison and publication queries completed under the 3,600-second
per-query deadline. The slowest recorded comparison substages were:

| Substage | Seconds |
|:--|--:|
| Route-pair row multiset | 71.76 |
| Route identity map | 44.08 |
| Vault row multiset | 27.33 |
| Vault recipe row multiset | 20.15 |
| RAW row multiset | 18.09 |

The durable child receipt measured 336,784 KiB peak RSS (about 329 MiB),
4,423.65 user CPU seconds, and 705.93 system CPU seconds. The terminal
notification records `returncode: 0`, `status: complete`,
`source_content_included: false`, and the changed checkpoint/result
generations.

## Aggregate corpus results

The source scan saw 1,237,553 files and 382,206 snapshots. It recorded
855,347 files without a snapshot, with all 382,206 source records status `ok`
and zero source parse failures or unsupported frontmatter/tag records.

Both producer routes contained 382,206 documents and joined the source cohort
with no missing or extra identities and no duplicate rows. RAW matched all
382,206 source titles, bodies, and recipe row multisets. Its metadata channel
is not projected by the RAW producer for all 382,206 rows. RAW carried
842,813 producer tag associations across 356,876 tagged rows.

The vault matched all 382,206 source bodies and metadata rows. It matched
378,524 titles exactly and 3,682 additional titles through the pinned
frontmatter scalar rule; zero title differences remain unexplained. Its
recipe row multiset matched 378,524 rows because the pinned title channel is
preserved separately. The vault route has no extracted tag associations; the
source recipe tag cohort contains 356,876 rows, so this remains a separate
producer channel and an expected omission rather than an equivalence claim.

The route comparison reports zero unexplained source-to-route body,
metadata, tag, or title differences after the documented route rules. The
overall result remains `semantic_equal: false` because route row multisets,
metadata projection, and tag channels are distinct producer contracts. The
source recipe semantic result is also false until those route contracts are
accepted or reconciled by the plan.

## Verified publication cohorts

All three bounded publication archives passed independent verification with
1,000 documents and 1,000 current-revision bodies each. RAW and vault matched
all 1,000 producer documents, titles, and bodies. The original Joplin
publication matched 987 producer bodies byte-for-byte. The remaining 13 were
independently verified as `privacy_plain_text_exact` using the reviewed
archive document/resource cohort, producer byte spans, and the pinned Notrios
publication link-rewrite rules. There were zero unexplained Joplin body
mismatches.

The publication comparison is ready with all three verified labels. Its RAW
and vault selected cohorts each contain 1,000 publication source keys, with
381,206 source keys outside the reviewed archive selection; their common
selected intersection has one matching title digest and zero matching body
digests. The original Joplin archive remains a separate source cohort.

Publication readiness does not override the recipe source/route result, so
C7c does not claim semantic equivalence.

## Checkpoint and notification contract

The final checkpoint fingerprint includes comparator code/profile, a conservative
inventory of top-level Python dependencies, producer database digests, source
inventories, complete publication file inventories, mapper/revision configuration,
and decoder limits. Stage preflight checks require configurable free disk space
(`--min-free-bytes`, default 1 GiB) and record the measurements. A changed input rejects reuse and
preserves the prior result; an incomplete run resumes from completed stages
and archives the previous attempt. Result, checkpoint, receipt, and terminal
notification files are written atomically. The terminal notification records
the command digest, checkpoint/result generations, return code, aggregate
semantic result, and measured child RSS. It explicitly marks that source
content was not included.

For a private reconnect, substitute the recorded PID and private paths in the
launch manifest; repository documentation contains no machine-specific input
locations:

```text
python3 -B scripts/notrios_c7c_monitor.py \
  --pid <pid> \
  --checkpoint <private-checkpoint> \
  --result <private-result> \
  --notification <private-notification>
```

The completed v6 comparison is accurate and reproducible, but C7c remains
blocked from claiming route semantic equivalence until the plan decides how
to handle the separate tag channel, RAW metadata omission, and pinned title
representation.

## Review, historical attempts and validation scope

C7c is complete as an explanatory comparison and resumable harness slice.
The measured route differences are retained as constraints for P7a–P7c and
resumed 7c; this does not accept tag equivalence or relax consumer link admission.
The existing five-module regression suite passed all 264 tests in 180.404s.
Together with the final 26 harness tests, 290 tests are accounted for. The full
suite preceded later harness-only corrections; the focused suite covers those
corrections, and importer/exporter implementation files were not changed.

Historical attempts remain private and separate: an interrupted initial run;
a four-hour stalled publication join stopped without success; a labelled
3,600-second identity-join timeout with a failure notification; and completed
comparisons whose parser/LF rules were subsequently corrected. Explicit indexed
aggregate tables and a 20,000-row full-query regression resolved the quadratic
joins. Folder/scalar/title/LF corrections were demonstrated on bounded source
cases before the final corpus comparison. Historical results are not substituted
for the final result.

The accepted full v6 corpus comparator SHA-256 is
`8304857a5e1fa79b3f8cbac61a323abb3e52498f1f56d45314e7db2f06ee3ea0`.
Subsequent changes strengthen dependency/publication fingerprint invalidation and
disk preflight only; semantic rules and corpus artifacts are unchanged. Those
operational changes passed targeted tests without repeating the corpus run.
An old checkpoint cannot be reused under the stronger fingerprint as if it were
produced by the final code.

Private run ID `652f8054ca8f2cef29879813` and monitor ID
`9560ea9c593e43309e14a700ae460a00` identify the accepted v6 attempt. Exact launch
arguments and reconnect paths are recorded in the private manifest referenced
by the execution ledger. The initial duration estimate proved too short; allow
about 90 minutes for this corpus, with a 3,600-second per-query failure limit.
The monitor blocks on process completion. Parent notification waits used the
25-minute fallback; where native waits returned prematurely, a long timed wait
avoided repeated worker/process polling. Worker progress messages were not
visible through its commentary, so final native handoffs carried parent updates.
