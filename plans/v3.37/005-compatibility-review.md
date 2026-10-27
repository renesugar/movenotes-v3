# C7a compatibility decisions and evidence

C7a is a design/diagnosis slice, completed on 2026-09-17. Its implementation is
C7b; refined whole-corpus comparison is C7c. At C7a completion, runtime still
refused these newly admitted cases; C7b implementation evidence is recorded
below. This report does not mark 7c complete or waive its gates.

Codex parent owns these decisions (runtime family GPT-6; exact model/effort not
exposed). User-authorized `luna_worker`, configured `gpt-5.6-luna` / fixed `max`,
executed the parent-written audit in `/root/notrios_c7a_monitor`. Actual child
model/effort are not exposed. After a usage limit removed the original workers,
`/root/c7a_evidence_resume` (same configured Luna role) completed missing evidence
housekeeping without rerunning scans. The worker waited for OS completion; parent used
25-minute notification waits rather than checking whether the audit had exited.

## Corpus evidence

Read-only sources and producer libraries are those recorded in
[the trial report](010-corpus-trials.md). Producer code was inspected at
`7662fdd5b55d6f34f14874f70ba6db9f9e7676ac`, not inferred from the newer checkout.
Private aggregate evidence and scripts live at
`/media/$USER/HD2/movenotes-c7a-20260917/`.

| Route | Current producer documents | Bodies with non-whitespace C0 controls | Bounded publication bodies | Control-bearing bounded bodies | Existing lexical accept/refuse |
|---|---:|---:|---:|---:|---:|
| Joplin | 103,349 | 8 | 1,000 | 0 | 963 / 37 |
| Recipe RAW | 382,206 | 1,063 | 1,000 | 5 | 972 / 28 |
| Recipe vault | 382,206 | 1,063 | 1,000 | 27 | 989 / 11 |

Both recipe producer libraries have identical control occurrence totals;
U+0014 dominates (3,498 occurrences each). Other observed values include U+0001,
U+0002, U+0003, U+0004, U+0005, U+0006, U+0007, U+0008, U+000B, U+000E,
U+000F, U+0011, U+0012, U+0016, U+0017, U+001B, U+001C and U+001D. Joplin
also has U+001F. No leading BOM was found in any producer body; no NUL was found.

Twenty control-bearing source samples per recipe route had the same control
counts as their producer bodies. All eight Joplin source bodies match after
removing the RAW title according to the producer's `splitSourceTitle`; the
initial 7/8 result included that title in the comparison. All 3,000 bounded
publication documents matched their producer body's control counts. Controls
are present in source text, not an observed publication corruption. These
counts are not a claim of complete byte equality: producer metadata and link
rewrites intentionally change bodies.

First lexical failure shapes are: Joplin 34 bare-bracket candidates, one
reference definition, one reference use, one unsupported inline; recipe RAW 27
bare-bracket candidates and one unclosed bracket/internal-token category; recipe
vault 11 bare-bracket candidates. A first failure masks possible later failures.
These are lexical categories, not proof that all candidates are harmless prose.
The whole-note classification required below must still be implemented/tested.

The corrected audit took 138.46 seconds with peak RSS 35,864 KiB, reusing the
completed Joplin producer scan. Initial attempt failed because a verification
work directory had not been created; its evidence is retained under `attempt-1`.
`notification.json` and GNU-time output establish successful completion. These
are audit costs, not new importer performance measurements.

## Body control decision

Admit valid UTF-8 body text containing any non-NUL C0 character; retain the
leading-BOM and NUL refusals. Preserve those body bytes exactly. Keep all existing
control/whitespace restrictions on destinations, fragments, identity fields and
filenames; admitting body text does not admit a control-bearing URL. Do not
strip controls, normalize note bodies, or print raw bodies into progress logs.

A synthetic downstream probe inserted generated rows directly, deliberately
bypassing the current admission guard. SQLite, RAW serialization/parsing, vault
export and Hugo preserved all 28 non-NUL C0 values other than TAB/CR/LF (already
supported). Site generation produced valid JSONL. Existing search text processing
normalizes U+000B, U+000C and U+001C–U+001F as whitespace; all tested values remain
in HTML bytes. Search text is a projection, not the preservation store. This is
not a claim about visual rendering in every client or successful end-to-end
import under current code. C7b must add real importer fixtures and ensure no
accidental link or executable markup is introduced by control-bearing examples.

Private probe results: `control-probe-result.json` and the saved probe script.
Earlier temporary probes exposed a required output-directory setup, preservation
bundle files in a naive Markdown glob, and the existing bare-bracket refusal;
these were harness corrections, not runtime fixes.

## Literal brackets and unchanged link boundaries

Keep the current inline-token grammar and all link-record/target checks. Add only
flat literal bracket prose: `[sic]`, `[x]`, `[00:01-00:03]` and similar nonempty
single-line labels without nested brackets, backslashes or backticks. No image
prefix, adjoining second bracket group, or following parenthesized destination
may be accepted as literal prose. Treat intervening whitespace before such
suffixes conservatively. Unclosed/nested/ambiguous brackets still refuse.

Before admitting any literal pair, inspect the whole unprotected note for
possible reference definitions, including definitions after uses, case/spacing
variants and container-prefixed forms. For this revision, any possible active
reference definition or explicit reference use refuses the note, even if it
looks external; do not attempt partial reference resolution. It is acceptable
to conservatively refuse an ambiguous definition-like form. A classifier must
never accept a shortcut merely because its definition occurs later. Maintain
existing code/fence/escape protection; ambiguity containing internal targets
continues to refuse.

Every byte inside proposed literal prose must still be checked for unaccounted
internal schemes/IDs. Do not advance over a bracket pair and thereby hide
`document://`, `resource://`, `notrios://` or `:/<32 hex digits>`. Retained archive
link records must still match actual accepted inline tokens at exact UTF-8 byte
spans; an archived record pointing at supposed literal prose refuses. Literal
pairs are copied unchanged and produce no link record or title/path resolution.
Use bounded, linear scans rather than repeated suffix searches.

Actual reference links, unsupported inline syntax and unclosed/internal-token
cases observed in the corpus remain explicit refusals. C7b retests them and
reports remaining blockers. This decision alone cannot make all real bounded
or full trials pass; accepting more syntax requires a separate reviewed design,
not filtering notes or quietly narrowing 7c acceptance.

## Identity, receipt and completion decision

Retain `movenotes-notrios-v1`, `movenotes-publication-loose-v1`, the receipt field
set, schema 28 support and existing deterministic ID framing. This is an
admission-only extension: new bodies previously refused; all previously admitted
bodies, destination rewrites, generated properties and attachment suffixes retain
the same output. Changing `MAPPER_NAME` would currently also change every mapped
ID, so do not bump it merely to label a diagnostic revision.

C7b must prove identical old-admitted output inventories and receipts against
the baseline, plus unchanged-output no-op behavior. New syntax has no legitimate
old successful output to reuse. The existing strict receipt/inventory/source
checks remain mandatory; a new grammar acceptance does not validate a forged or
modified old marker. If implementation changes an old-admitted output or mapping
rule, stop and revise this version decision before keeping that change.
Performance/acceptance harness checkpoints additionally fingerprint consumer
source, so old test runs do not substitute for validation of changed code.

## Recipe comparison contract for C7c

The original whole-body/title/tag multiset result is not a semantic-equivalence
verdict. Pinned Joplin `buildDocumentBody` inserts source/Joplin metadata and a
final newline; pinned Obsidian `canonicalBody` normalizes line endings and
`augmentFrontmatter` adds source/path/folder metadata and strips leading LF from
the body after an existing frontmatter block. Both rewrite supported links.
These transformations must be checked separately from recipe semantics.

Use a disk-backed, duplicate-sensitive source identity join:

1. Decode the RAW note's namespaced `application_data` snapshot under explicit
   compressed/decompressed size limits. Validate its stored digest and path;
   never extract arbitrary compressed data without a bound. Reject absolute,
   traversal or ambiguous paths before resolving them. The RAW external ID must
   match the deterministic Obsidian note ID of the preserved path.
2. The recipe export script documents staging under `Recipes/<relative path>`.
   Remove exactly this declared prefix for this corpus only, retaining all
   remaining path components and case. Join to the vault producer's
   `document_sources.external_id`/`metadata_json.relative_path`, which must agree,
   and to the read-only vault file. Verify snapshot/file hashes. Record duplicate,
   missing, changed and unmappable identities; do not pair solely by title or
   guess arbitrary suffixes. Source paths stay private in diagnostics.
3. In a bounded 100-note check, all IDs matched the preserved paths; all 100
   snapshots matched current vault bytes after that declared prefix mapping.
   All 100 paired recipe bodies matched after accounting for the documented
   frontmatter and leading/final LF transformation. Producer titles agreed in
   98 cases. This proves a useful join and transformation sample, not full-corpus
   equivalence or an explanation for the two title differences.
4. Recognize only an exact, leading, line-delimited frontmatter block under the
   source's supported grammar. Parse proven recipe-generator scalar/list forms;
   reject duplicate keys and unsupported/ambiguous YAML for normalization rather
   than silently dropping fields. Retain unknown metadata and its exact bytes
   as separately compared evidence. Do not split at arbitrary `---` occurrences
   in recipe text. Independently validate producer-added metadata against its
   source before excluding those exact fields from recipe-text comparison.
5. Compare source semantic title, recipe body, tags and remaining recipe metadata
   separately, retaining duplicates of documents. Use NFC/LF only in the explicit
   semantic channel; exact source bytes/hashes remain a separate gate. Account
   for documented producer-added/final and leading LF changes without trimming
   arbitrary indentation/whitespace. Check decoded scalar meaning, not manually
   unescaped producer titles. Quantify and classify all title discrepancies;
   pinned Obsidian `frontmatterScalar` uses quote trimming rather than a complete
   YAML decoder, a candidate explanation to test rather than assume.
6. Record two tag channels: source recipe tags, and actual producer/publication
   tag associations. The RAW producer reads Joplin relations; the inspected
   pinned Obsidian importer has no corresponding tag-extraction call. Verify
   association counts and expected transformations instead of declaring these
   channels interchangeable. Measured counts: RAW 842,813 associations across
   356,876 documents; vault zero associations. The initial 25,330 tag-multiset
   matches are exactly the RAW documents without tags, not evidence of tag
   preservation between the routes. C7b must not synthesize tags from body YAML or
   private snapshots: that could bypass the reviewed publication's tag policy.
7. Check source → producer → publication independently using each route's own
   reviewed digest. Different bounded selections are not matching cohorts.
   Report common-source intersections and all selected/excluded/missing counts.
   Normalize internal-link identities only through verified records and the
   source join; never replace arbitrary ID-looking text to force equivalence.

C7c must distinguish source recipe equivalence from route output equivalence.
Explained importer metadata/tag/title differences still appear in the report;
zero unexplained differences are required for a positive semantic claim.
Known differences cannot silently waive tag, privacy or full 7c acceptance.

## Independent C7b acceptance cases

| Case | Required result |
|---|---|
| Each non-NUL C0 value in ordinary body, alongside UTF-8 and literal prose | Import succeeds; exact SQLite and preserved body bytes, RAW round trip and vault bytes; safe Hugo/JSONL generation with explicit search-whitespace expectations. |
| NUL, leading BOM, invalid UTF-8, body-size limits | Refuse with no successful receipt or completed output. |
| Controls in destinations/fragments; escaped/encoded internal targets outside the admitted grammar | Existing destination/fragment validation still refuses; body admission cannot bypass it. |
| Bare `[sic]`, `[x]`, timestamps, multiple literals adjacent to valid links | Copy literal bytes exactly; preserve valid link translations and UTF-8 offsets. |
| Definition before/after shortcut, case/space/container variants, explicit/collapsed references | Refuse; definitions inside protected code do not activate an outside shortcut. |
| Wiki/embed, nested/unclosed brackets, malformed inline suffix, internal URI inside apparent prose | Refuse; no hidden or unrecorded internal target is accepted. |
| Retained record over literal/protected bytes, stale/overlapping span, withheld target | Refuse using unchanged record/privacy checks. |
| Previously accepted immutable fixtures and completed reruns | Identical IDs, output inventories, receipts and no-op behavior; changed inventory/source still refuses. |

Expected data must be literal independent synthetic fixtures, not computed by the
new classifier. Leave immutable historical publications intact. C7c adds source
join/frontmatter tests for duplicate titles, duplicate identities, renamed/missing
paths, altered snapshots, unsupported YAML, quoted titles, mismatched tags and
unexplained body changes. Full runtime regression and live affected-path gates
belong to C7b/C7c; this documentation slice does not claim those future tests pass.

## C7b implementation and validation

Terra (`/root/notrios_c7b`, configured `gpt-5.6-terra` / fixed `medium`)
implemented the C7b body guard, conservative literal scanner and two new
regression methods; the slice completed on 2026-09-17. Parent reviewed the original-byte/protected-byte distinction and
requested escape/backtick and C0/Unicode-whitespace suffix regressions. Literal
spans must be identical in the original and protected projections; every C0
separator and Unicode whitespace is handled conservatively before a potential
reference/destination suffix. Previously valid active link checks are unchanged.
No mapper, receipt, source schema, tag projection or immutable fixture changed.

Luna (`/root/c7b_validation`, configured `gpt-5.6-luna` / fixed `max`) ran the
prepared scripts using blocking completion and terminal notifications. Actual
child models/efforts are not independently exposed. Private results are under
`/media/$USER/HD2/movenotes-c7b-20260917/`.

- Baseline is the frozen `d9fd94f` checkout. All three committed publication
  fixtures imported and reran unchanged. Candidate payload inventories match
  baseline exactly: 15 files / 376,112 bytes across schema-27/schema-28 resource
  publications and the schema-28 text publication. Candidate no-ops also retain
  exact payload inventories, IDs and receipts.
- Full five-module regression: **264 tests passed in 145.292 seconds**, with
  `PYTHONDONTWRITEBYTECODE=1` and `python3 -B`. Focused worker tests passed before
  final validation. Source fingerprints bind candidate checkpoints to tested code.
- Each original 1,000-document real publication was retried using its reviewed
  selection digest. All three still refuse unsupported/unaccounted active link
  syntax. No notes were filtered and no full corpus ingestion was repeated.
  These remain failures for 7c, not passing integrations.
- Independent live synthetic CLI/vault/Hugo/Bluge validation passed: three
  notes imported and reran unchanged, exact body bytes survived SQLite/RAW/vault,
  literal brackets remained prose, Hugo builds succeeded, and Bluge indexed all
  three notes. All 28 tested non-NUL C0 values survived unminified HTML; minified
  HTML normalized U+000C, and search normalized U+000B/U+000C/U+001C–U+001F as
  documented whitespace projections.
  The first site attempt exposed a harness log/output directory collision;
  fresh vault/site output paths now separate artifacts from checkpoint logs.
  A subsequent assertion identified form-feed normalization by Hugo minification;
  the harness now checks exact unminified HTML separately and records minified
  HTML whitespace normalization, without relaxing storage/vault preservation.
  Failed attempts are retained, with no force-overwrite or runtime workaround.

After the usage limit, the agent registry showed no surviving children. The
parent verified that no validation script was running and completed only the
remaining three-note unminified-Hugo/Bluge steps in one blocking invocation
(about 1.6 seconds), as final parent validation. Completed regressions, fixture
imports and corpus trials were reused; runtime source fingerprints still match
the passing 264-test checkpoint. No implementation ownership changed.

Canonical evidence: `baseline-notification.json`, `candidate-notification.json`,
`regressions/stderr.log`, per-fixture inventory files, per-route bounded refusal
logs, and `live/result.json` / `live-notification.json`. Final replay scripts
are `movenotes-c7b-validate-final-20260917.py` and
`movenotes-c7b-live-final-20260917.py` in that private work directory. The
existing reference/unclosed/unsupported syntax policy and source-to-route tag differences still block complete 7c
acceptance; C7c must quantify comparison differences without hiding those limits.

## C7d: the producer's link grammar, prose brackets and pass-through destinations

Resumed 7c's bounded conversions refused 7, 8 and 3 of 1,000 notes on C7a's
narrow literal-bracket boundary (see plans/v3.37/000-notrios-import-plan.md, "Resumed 7c
results so far"). A census of the three `v1.0.0` producer libraries put the
same boundary at 1,768 of 103,349 Joplin notes, an upper bound, and at 2,621
and 2,622 of 382,206 recipe notes. On 2026-10-24 the user decided the two open
questions: HTML images the producer rewrote are converted back, and every
non-internal destination is copied as found.

*Decision.* Inline links are recognised exactly as the producer's
`internal/markdownlinks` parser recognises them, and any other bracket is
prose. The importer only ever rewrites internal targets, and the producer only
records links its parser finds. So matching its parser is what makes every
recorded span a token, and no prose rule can hide an internal target: an
internal scheme or `:/` ID outside a token's destination, or outside a
recognised HTML image source, still refuses wherever it sits. An internal
destination must still use the strict C7a form, so its replacement stays a
byte-exact splice.

*Second decision (2026-10-24).* The user chose to admit two of the forms left
in Joplin: unrecorded wiki links are text, and a producer record inside
protected code (or at an escaped bracket) is accepted when it is one `external`
link with no internal target in its span, its bytes unchanged.

*Third decision (2026-10-25).* The full Joplin conversion refused 14 notes in
five forms, and the user chose to admit all of them:
- A record the producer resolved by name for a non-internal destination keeps
  that destination as written, and the match is not applied.
- An internal URI directly after `](` that has no record maps back to `:/id`.
  This is a label the producer's parser cannot read. The target must be in the
  publication.
- A recorded wiki link is text.
- A self-anchor record inside protected code is accepted unchanged.
- An ambiguous container fence refuses only when an internal target follows it.

*What stays refused.* Internal targets in any form other than a strict inline
destination, an unrecorded strict destination directly after `](`, or an
`<img>` `src` with an attachment relation. Also refused: encoded internal
targets; document or resource records inside protected code; records the
scanner cannot match; block or malformed fragments on internal targets; an
internal target after an ambiguous container fence; and an unrecorded internal
target missing from the publication.

*Mapper and receipt.* A body C7a accepted yields the same tokens and
replacements under C7d. Its strict links have the same spans in the producer's
grammar, a balanced title included. Its flat literals were never tokens, and
neither were the forms C7a refused. Accepted outputs therefore do not change,
and the mapper and receipt versions stay as they are; the immutable publication
fixtures and their reruns still pass byte for byte in the regression suite.

*Differential check against the producer.* Over all three libraries, every
Markdown link record the producer wrote outside protected code is a token here
with the same span, target and label: 75,776 of 75,776 in Joplin and every
record in both recipe libraries. Under C7d both recipe libraries scan with no
refusal at all. In Joplin, 82 notes still refuse on wiki links, 198 hold
producer records inside protected code (15 of them only `external` ones), about
5 hold an internal link the producer rewrote without recording it (its label
holds an escaped `\]`, or it starts at an escaped `\[`), and 1 meets the
ambiguous-container rule. These are library-body figures. A publication
plain-texts unresolved links and links to unselected documents, so the
published figures are at most these.

*Bounded acceptance.* With C7d all three bounded routes pass every stage:
conversion (15.15 s, 17.31 s and 11.90 s; peak RSS ≤ 55,992 KiB), vault export,
exact attachment bytes and reachable sets, site generation, Hugo, the
browser-runtime validation, Bluge indexing, the live-site tag check (29, 52
and 3 rows answered with the same totals), and the recovery trial.
