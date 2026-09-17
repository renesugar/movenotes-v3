# C7a compatibility decisions and evidence

C7a is a design/diagnosis slice, completed on 2026-09-17. Its implementation is
C7b; refined whole-corpus comparison is C7c. Existing runtime still refuses these
newly admitted cases. This report does not mark 7c complete or waive its gates.

Codex parent owns these decisions (runtime family GPT-6; exact model/effort not
exposed). User-authorized `luna_worker`, configured `gpt-5.6-luna` / fixed `max`,
executed the parent-written audit in `/root/notrios_c7a_monitor`. Actual child
model/effort are not exposed. After a usage limit removed the original workers,
`/root/c7a_evidence_resume` (same configured Luna role) completed missing evidence
housekeeping without rerunning scans. The worker waited for OS completion; parent used
25-minute notification waits rather than checking whether the audit had exited.

## Corpus evidence

Read-only sources and producer libraries are those recorded in
[the trial report](NOTRIOS_CORPUS_TRIALS.md). Producer code was inspected at
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
