# Notrios publication consumer contract — slice 1a

Status: design frozen on 2026-09-05 for the first importer implementation.
No importer or verifier is implemented by this document. This is the admission
checklist for [NOTRIOS_IMPORT_PLAN.md](NOTRIOS_IMPORT_PLAN.md), not a claim that
movenotes already supports archive-v2.

## Reference pin and authority

Reviewed Notrios commit: `bdecfeda00e582d5aa6170d15b37ba27c9656f1d`.
The local checkout at `~/projects/notrios` matched this commit and had
no working-tree changes at review. Its registry and store both report schema 27.
The links below refer to that adjacent checkout; inspect the pinned revision if
it later advances. No changes to Notrios are part of this slice.

| Reference | Rules used here |
|---|---|
| [Registry](../notrios/contracts/archive-v2/contract.json) | Contract version, capabilities, hard limits and separate formats. |
| [Manifest schema](../notrios/contracts/archive-v2/schemas/manifest.schema.json) | Exact manifest/nested fields and required members. |
| [Index schema](../notrios/contracts/archive-v2/schemas/index-entry.schema.json) | Exact index-entry fields. |
| [Record schema](../notrios/contracts/archive-v2/schemas/record-envelope.schema.json) | Envelope and all twelve payload field sets. |
| [format.go](../notrios/internal/archivev2/format.go) | `Manifest`, nested structs, `ComputeCommitSHA256`, `validateManifest`, `DefaultLimits`. |
| [index.go](../notrios/internal/archivev2/index.go) | `ObjectLocation`, `IndexObject`, `IndexEntry.validate`, `ObjectTotals`. |
| [records.go](../notrios/internal/archivev2/records.go) | Payload types and `countForRecordType`. |
| [verify.go](../notrios/internal/archivev2/verify.go) | `VerifyDirectory`, `addRecord`, `validateContainers`, `reconcile`, JSON/MIME/path helpers. |
| [compatibility.go](../notrios/internal/archivev2/compatibility.go) | `EvaluateCompatibility`, schema inequalities and capability-name grammar. |
| [export.go](../notrios/internal/archivev2/export.go) | `writeDocuments`, `writeRevision`, `writeLink`, `writeResources`, `writeHeaderRecords`, `buildManifest`. |
| [publish.go](../notrios/internal/archivev2/publish.go) | Rewrite decisions, stale spans and byte-offset adjustments. |
| [Publication tests](../notrios/internal/archivev2/publish_test.go) | Default projection, retained links, metadata stripping, stale rewrites, unevaluated query blocks. |
| [Selection implementation](../notrios/internal/store/sqlite_selection.go) | Policy defaults/overrides, reachable resources and `selectionManifestDigest`. |
| [Store export](../notrios/internal/store/sqlite_export.go) | Current revision selection and resource/tag relation reads. |
| [Profiles](../notrios/internal/publish/profiles.go) | `Validate` and `RequireReviewedPlan`. |
| [Publication CLI](../notrios/cmd/notriosctl/publish.go) / [CLI tests](../notrios/cmd/notriosctl/publish_test.go) | Profile/plan/run flags, JSON nesting and digest comparisons. |

Use the published schemas for field presence/types and the executable verifier
for semantic checks. Deliberate stricter consumer rules are labeled below;
do not weaken them merely because the generic Go verifier accepts a value.
The native-format prose and publishing policy summarize defaults, but do not
fully describe all producer options or fields retained in a publication.

## Reader declaration

Frozen consumer profile name: `movenotes-publication-loose-v1`.

| Declaration | Supported value / admission rule |
|---|---|
| External contract | `notrios-archive-v2`, contract schema version 1. |
| Container | Directory with `manifest.json`; `format="notrios-archive"`, integer `version=2`. |
| Target | Exactly `snapshot.target="publication_handoff"`. No override. |
| Reader | `minimum_reader_version=2`; consumer schema support level **27**. |
| Schema bounds | `12 <= minimum_schema_version <= 27` and `minimum_schema_version <= source_schema_version <= maximum_schema_version`. Do not require source or maximum to be at most 27; new fields/capabilities must still pass all other gates. |
| Layout | `fanout` only for every index descriptor and indexed object; kinds `records` and `blob` only. `totals.packs` must be absent or zero. |
| Required capabilities | Exactly the five base capabilities listed below, sorted, unique and all present. Any additional required capability refuses. |
| Optional capabilities | Sorted unique list, disjoint from required; unknown names may be ignored within the declared limits and grammar. Optional declarations cannot enable packed objects or unknown record fields/types. |

The five base names, in order, are:

```text
identity.database-replica.v1
objects.index.v1
objects.sha256.v1
records.jsonl.v1
revisions.complete.v1
```

Capability names use `^[a-z0-9][a-z0-9_.:-]{1,127}$`; required plus optional
have at most 64 entries, each at most 128 bytes. These are archive capabilities;
collection capabilities are a separate string array, not this reader whitelist.
Sources: registry, `format.go`, `compatibility.go`.

Refuse before object access: absent/incomplete or malformed manifest; wrong
format/version/target; invalid schema bounds; reader too old; missing or unknown
required capability, including `objects.pack.v1`; invalid capability lists;
packed manifest locations or nonzero pack totals. For `notrios-sqlite-image`,
report that a loose archive-v2 publication is required, never open SQLite image
bytes. Sync NCB1/NEV1/NAR1 and archive-v1 are not alternate supported containers.
Refuse undeclared pack entries/locations discovered later in the index too.
Sources: compatibility/format/index code; target and loose-only restrictions are
consumer scope decisions. This is neither Notrios' complete `current-v2` profile
nor its historical executable `previous-loose-v2` implementation.

## Manifest fields and digest checklist

All fields in these rows are required unless marked `?`. Order is the Go struct
serialization order, which matters for the semantic commit digest.

| Object | Ordered fields |
|---|---|
| Manifest | `format`, `version`, `commit_sha256`, `snapshot`, `compatibility`, `index`, `totals`, `counts` |
| Snapshot | `id`, `created_at`, `target`, `database_id`, `source_replica_id`, `consistency`, `collection_ids`, `selection_manifest_sha256` |
| Compatibility | `minimum_reader_version`, `source_schema_version`, `minimum_schema_version`, `maximum_schema_version`, `required_capabilities`, `optional_capabilities` |
| Index descriptor | `sha256`, `size_bytes`, `entries`, `media_type`, `location` |
| Location | `layout`, `path?`, `pack_sha256?`, `offset?`, `length?` |
| Totals | `objects`, `bytes`, `record_chunks`, `blobs`, `packs?` |
| Counts | `collections`, `notebooks`, `search_notebooks`, `tags`, `documents`, `revisions`, `document_tags`, `resources`, `document_resources`, `links`, `provenance`, `source_bundles` |

- IDs match `^[a-z0-9][a-z0-9_.:-]{1,127}$`; SHA-256 strings match
  `^[0-9a-f]{64}$`. Snapshot creation time is RFC3339 UTC with up to nanosecond
  precision. `consistency` is exactly `sqlite_read_transaction`.
- `collection_ids` is nonempty, sorted, unique and equals the set of collection
  records. It may include an otherwise unused default collection: the producer
  includes it when no explicit collection selector is supplied.
- `commit_sha256` is SHA-256 of Go `json.Marshal` of the typed semantic manifest
  with the commit field omitted, not set to null or an empty encoded string.
  Reconstruct structs in the order above; compact separators, no final newline,
  Go string escaping (including `<`, `>`, `&`, U+2028/U+2029). Omit zero-valued
  optional location fields and `totals.packs`; do not sort object keys or arrays.
  Required arrays remain arrays, including empty optional-capability lists.
- The original manifest's whitespace/key order do not change this digest.
  Index and records chunks, by contrast, hash their exact bytes including LF.
  The chain is commit → index descriptor hash → object descriptor hash → bytes.
- `snapshot.selection_manifest_sha256` is an opaque planner digest, equal to
  CLI `plan.manifest_sha256` and run `report.selection_manifest_sha256` for a
  successful reviewed run. It is not the archive commit digest or a hash of the
  printed/truncated plan JSON. The consumer cannot recompute it from the archive
  because withheld decisions and the source selection are not present.
- An expected reviewed digest compares to the selection digest. Both digests
  belong in the receipt with distinct names. Neither authenticates a sender.

Sources: manifest schema; `format.go:ComputeCommitSHA256`; `index.go` structs;
`export.go:buildManifest`; `sqlite_selection.go:selectionManifestDigest`;
publication CLI `runPublishPlan`/`runPublishRun`.

## Index, byte and filesystem checklist

Index entries have required `sha256`, `kind`, `media_type`, `size_bytes`,
`location`, and optional `records`, `record_counts`. A records entry requires
both optional fields semantically, with positive `records` equal to the sum
of its complete twelve-field `record_counts`. Blob entries have absent/zero
`records` and absent or explicitly all-zero `record_counts`. Do not refuse the
legacy all-zero representation. `null` is not an admitted substitute for absence.

For loose locations require `path=objects/sha256/<hash[0:2]>/<hash[2:4]>/<hash>`.
Reject pack fields even if zero/empty: this is a stricter consumer shape rule
than Go's zero-value check. Index descriptors use
`application/vnd.notrios.archive-v2-index+jsonl`; records use
`application/vnd.notrios.archive-v2-records+jsonl`. Blob descriptor MIME must
parse, but need not be textually canonical (matching `IndexEntry.validate`).

Verify every descriptor size and hash, index descriptor uniqueness, strictly
increasing object hashes across chunks in manifest order, entry count per
chunk, decoded counts per records chunk, and aggregate counts/totals. Index
descriptors are in entry order, not necessarily hash order. Records have no
required dependency order: documents may precede notebooks/collections.

For this loose profile, `totals.objects=sum(index.entries)=record_chunks+blobs`,
`record_chunks>0`, and `totals.bytes` is the sum of indexed records/blob sizes.
Index chunk bytes and manifest bytes are **not** included in those totals;
they have their own limits. No indexed descriptor may point to an index chunk.
Every blob must be referenced by a record with its exact hash and size.

Root and objects must be real directories/regular files, with no symlinks or
special files. Refuse traversal, backslashes, wrong fanout, extra files and
unexpected directory shapes. Allowed directory shapes are `objects`,
`objects/sha256`, and one/two levels of two-character lowercase hex fanout;
empty directories of these shapes are allowed by the pinned verifier. Do not
misinterpret “no extra directories” as refusing those. Verify exact inventory
with a disk-backed join/count; avoid an archive-sized path set. Keep stable file
handles or immutable verified copies and rehash at consumption where required.

Sources: `index.go:IndexEntry.validate`; `verify.go:scanIndex`,
`verifyRecordObject`, `validateArchiveTree`, `openRegular`, `reconcile`;
`restore.go` for rehash-at-use precedent. No output may appear complete before
these and the record/publication gates pass.

## Hard limits and strict decoding

These are the pinned registry ceilings in exact bytes/counts. They are not
promises that the eventual Markdown converter can hold a 16 GiB body in memory;
slice 1c must set any smaller conversion limit explicitly.

| Registry key | Ceiling |
|---|---:|
| `max_manifest_bytes` | 4194304 |
| `max_objects` | 8000000 |
| `max_index_objects` | 1000 |
| `max_index_entries_per_object` | 10000 |
| `max_index_entry_bytes` | 4096 |
| `max_index_object_bytes` | 67108864 |
| `max_records` | 64000000 |
| `max_records_per_object` | 10000 |
| `max_record_bytes` | 1048576 |
| `max_record_object_bytes` | 16777216 |
| `max_blob_bytes` | 17179869184 |
| `max_total_bytes` | 4398046511104 |
| `max_path_bytes` | 255 |
| `max_path_depth` | 8 |
| `max_json_depth` | 32 |
| `max_collections` | 1000 |
| `max_notebooks` | 1000000 |
| `max_notebook_depth` | 32 |
| `max_capabilities` | 64 |
| `max_capability_name_bytes` | 128 |

Refuse wider caller limits. Check aggregate and per-object limits before reads,
and actual bytes/counters during reads. Use bounded LF-delimited binary reads,
not `str.splitlines()`. Require final LF, disallow blank JSONL records and trailing
JSON values. CRLF remains admissible JSON whitespace with LF termination; hash
it unchanged. The consumer line-byte ceiling includes the terminating LF;
boundary tests must distinguish this conservative rule from Go Scanner buffer
behavior. JSON nesting counts `{` and `[` outside strings, with root depth one.

Use the schemas' exact case-sensitive fields and required members; reject
duplicate keys at every depth, unknown structured fields, null where a typed
value is required, booleans as integers, fractional/exponent spellings for
integer fields, nonfinite numbers, invalid UTF-8 and unpaired surrogate escapes.
Use signed 64-bit range for integer fields, further narrowed by their limits.
Some Go decoding accepts missing zero-valued fields or repairs invalid text;
matching those accidents is not part of this profile. Arbitrary keys *inside*
admitted `settings_json`, `metadata_json` and `anchor_json` objects are allowed
subject to depth/size/duplicate-key rules; they are not unknown record fields.

Common semantic limits from `verify.go:addRecord`: nonblank collection/notebook/
tag names at most 4096 UTF-8 bytes; revision title at most 1048576 bytes; resource
filename at most 4096 bytes; MIME input at most 255 bytes. The whole record-line
limit still applies. Required and nonempty optional record timestamps must be RFC3339 UTC
(accept `Z` or zero offset, not nonzero offsets); integer coordinate/ordinal
constraints are below. Notebook root counts as depth one, maximum 32.

## Payload field checklist

Exact required/optional fields come from the record schema; the following table
is the complete field inventory. No payload type is silently ignored.

| Type | Required fields | Optional fields |
|---|---|---|
| `collection` | `id`, `name`, `capabilities`, `settings_json`, `created_at` | `description` |
| `notebook` | `id`, `name`, `builtin`, `position`, `created_at`, `updated_at` | `parent_id`, `icon_emoji` |
| `search_notebook` | `id`, `name`, `query`, `builtin`, `sort_anchor`, `created_at` | `icon_emoji` |
| `tag` | `id`, `name`, `created_at` | None |
| `document` | `id`, `collection_id`, `notebook_id`, `current_revision_id`, `created_at`, `updated_at` | `deleted_at` |
| `revision` | `id`, `document_id`, `title`, `body`, `body_mime_type`, `metadata_json`, `created_at` | `message` |
| `document_tag` | `document_id`, `tag_id` | None |
| `resource` | `id`, `collection_id`, `blob`, `mime_type`, `metadata_json`, `created_at` | `filename`, `unreferenced_at`, `unreferenced_reason` |
| `document_resource` | `document_id`, `resource_id`, `relation_type`, `ordinal`, `anchor_json` | None |
| `link` | `id`, `source_document_id`, `relation_type`, `source_format`, `raw_target`, `source_start_byte`, `source_end_byte`, `source_line`, `source_column`, `resolution_status` | `target_document_id`, `target_resource_id`, `target_uri`, `display_text`, `anchor_type`, `anchor_value`, `context` |
| `provenance` | `document_id`, `source_system`, `metadata_json`, `created_at`, `updated_at` | `external_id`, `author`, `author_id`, `thread_id`, `reply_to`, `source_url`, `published_at`, `published_ts` |
| `source_bundle` | `source_system`, `source_key_sha256`, `collection_id`, `item_key_sha256`, `item_type`, `relative_path`, `content`, `property_order_json`, `updated_at` | `external_id` |

Every envelope is exactly `{type, payload}` with an object payload. `body`,
`blob` and `content` references are exactly `{sha256, size_bytes, media_type}`.
Optional ID fields, when present, must match the ID grammar; omit a missing
parent/target rather than accepting an empty ID. JSON-object fields contain
objects, not JSON encoded as a string. `builtin` is boolean; `position`, ordinal
and link coordinates are integers. Other scalar payload fields are strings,
except provenance `published_ts` (integer) in that forbidden payload type.

## Record and publication admission checklist

The base graph checks below derive from `verify.go:addRecord`,
`validateContainers` and `reconcile`; publication behavior derives from the
named producer functions. Consumer additions make the projection narrower than
generic archive-v2, and must be tested with otherwise correctly rehashed input.

| Type | Base integrity checks and consumer publication decision | Producer evidence |
|---|---|---|
| `collection` | Unique ID; valid name/time, sorted unique string capabilities; declared set equals snapshot scope. **Require `settings_json={}`**; admit description/capabilities for validation but do not project them to public metadata. | `writeHeaderRecords` always emits empty settings and retains description/capabilities. |
| `notebook` | Unique ID, existing parent if present, no cycle/depth overflow, name/times valid. Preserve tree; no invented per-collection parent relationship. | `writeHeaderRecords` includes used notebooks and ancestors. |
| `search_notebook` | **Refuse every record** and nonzero manifest count. Recognize its schema; do not silently drop it. | `writeHeaderRecords` emits these only for full archives. |
| `tag` | Unique ID, nonblank name/time valid. Do not silently drop or rename memberships based on a private-tag word list. | `writeHeaderRecords`, `writeDocuments`. |
| `document` | Unique ID; collection/notebook/current revision exist; revision belongs to this document. **Require `deleted_at` absent/empty and exactly its one current revision.** | `writeDocuments` uses current-only revisions; normal publish profiles disallow Trash. |
| `revision` | ID/document ownership and body hash/size exist; JSON metadata object and time/title valid. Semantic MIME must match canonical `body.media_type`. **Require `metadata_json={}`**, no extra history, and unique revision IDs as well as owner pairs. Admit optional message but do not project it. | `writeRevision` strips revision metadata but copies `Message`. |
| `document_tag` | Unique `(document_id, tag_id)` relation; both endpoints exist. | `writeDocuments`. |
| `resource` | Unique ID and existing collection; exact referenced blob size/hash, semantic MIME matches canonical `blob.media_type`; filename/time/metadata object valid. Require reachability from an included document-resource relation. Metadata and unreferenced-state fields need not be empty; validate then omit them from the public projection. | `writeResources` copies these fields; `loadSelectionResourcesLocked` selects via document-resource references. |
| `document_resource` | Unique `(document_id, resource_id, relation_type, ordinal)`; endpoints exist, nonblank relation type, nonnegative ordinal and object anchor JSON. Validate anchor metadata; only reviewed link/attachment mapping may consume it, never blindly serialize it publicly. | `writeDocuments` copies relation/ordinal/anchor JSON. |
| `link` | Unique ID and existing source/target IDs; nonblank relation/format/status; `0 <= start <= end`, nonnegative line/column. **Require context absent/empty and status exactly `resolved` or `external`**; reject withheld/unresolved/ambiguous/invalid/deleted/excluded statuses. At most one target ID; resolved ID-less links must be self-anchors; external links must be HTTP(S) with no internal target ID. Validate actual UTF-8 spans/target agreement before translating in 1c/3d. | `writeLink`, `publicationLinkNeedsRewrite`, `rewriteBodyLinks`. Base verifier does not check status enums, target URI agreement or spans against body bytes. |
| `provenance` | **Refuse every record** and nonzero manifest count, even if a producer opt-in permitted it. | `writeDocuments` follows effective `IncludeProvenance`; default is false. |
| `source_bundle` | **Refuse every record** and nonzero manifest count, even if a producer opt-in permitted it. | `writeSourceBundles` follows selection keys; default `IncludeSourceBundles` is false. |

Semantic MIME equality means normalize the revision/resource MIME with the
reference Go MIME rules and compare to the already canonical blob-reference
MIME. Do not require storage descriptor MIME equality: the same exact bytes can
serve multiple semantic types. Generic verification can accept non-Markdown
bodies; conversion MIME/decoding support is a separate 1c gate.

The strict revision-ID uniqueness and link/reachability additions above are
consumer decisions, not all properties enforced by `VerifyDirectory`. Encode
relation identities as unambiguous tuples in SQLite; do not copy delimiter-based
keys for unrestricted relation strings. Do not require every collection to be
used, or infer publication solely from record counts.

## Publication guarantees and their limits

The following distinctions are necessary for honest downstream behavior:

- **Policy defaults are not forced invariants.** Selection defaults exclude
  private/draft/confidential tags, read-only notebooks and Trash; omit provenance
  and source bundles; and use `plain_text`. Policy flags can override several
  defaults. Profile validation allows `retain`/`report` and provenance/bundle
  opt-ins; direct export has still more policy controls. Consumer refusals above
  therefore apply to some checksum-valid producer publications.
- **Only certain metadata is stripped.** Revision metadata becomes `{}` and
  link context is blank; collection settings are always `{}`. Revision messages,
  collection descriptions, resource metadata/unreferenced fields and relation
  anchor JSON survive the producer. Validate but do not automatically carry
  those into vault frontmatter, recovery bundles, sidecars or search sources.
  Reviewed titles, filenames, bodies and exact attachment bytes remain content,
  not proof that embedded personal information has been removed.
- **Rewriting can be skipped.** With `plain_text`/`redact`, stale, overlapping or
  mismatched link spans are left unchanged and increment `skipped_rewrites`.
  `writeLink` still drops those rewrite-candidate records. The manifest does not
  contain that counter, warnings or the selected link action. An archive-only
  consumer cannot certify zero skipped rewrites or reconstruct missing records.
  The importer must refuse recognized dangling internal links under the grammar
  frozen in 1c, and must not claim a general content/privacy audit.
- **No source-library lookup or query execution.** Preserve withheld prose and
  redaction; never resolve missing targets from private state. `note-query` fenced
  blocks are carried unevaluated (`TestPublicationHandoffCarriesQueryBlocksUnevaluated`).
- **Size policy is not a proven export filter at this pin.**
  `loadSelectionResourcesLocked` marks oversized resources, then returns them;
  `ResolveSelection` retains their IDs and `writeResources` writes that set.
  Do not claim that `--max-resource-bytes` ensures their absence. Verify fixture
  contents and enforce actual consumer hard/conversion limits independently.

These are static findings about the pinned implementation, not newly run
producer experiments. Slice 1b must save the actual run report outside the
archive and require `verified=true`, `skipped_rewrites=0`,
`cleared_link_targets=0`, the expected target/counts and both matching digests
for its normal fixture. The receipt/report is useful evidence but is not an
authenticated substitute for archive verification or content review.

## CLI contract for the next slice

Commands below are syntax templates, not executions performed in 1a. Supply
`--db`, `--asset-store` and `--profiles` explicitly for a disposable synthetic
library so the commands cannot use a real default library. Place all flags
before the output-directory positional argument.

```text
notriosctl publish profile save --db <db> --asset-store <assets> --profiles <profiles.json> --name fixture --target publication_handoff --notebooks <public-id> --link-action plain_text
notriosctl publish plan --db <db> --asset-store <assets> --profiles <profiles.json> --profile fixture
notriosctl publish run --db <db> --asset-store <assets> --profiles <profiles.json> --profile fixture --reviewed-plan <plan.manifest_sha256> <archive-dir>
notriosctl compatibility archive-v2 --reader previous-loose-v2 <archive-dir>
notriosctl verify archive-v2 <archive-dir>
```

The CLI prints `{profile,target,plan,next_step}` for planning, and
`{profile,destination,report}` for running. Run re-plans and compares the supplied
digest before export, then compares the exported selection digest afterwards.
A post-export mismatch exits nonzero but does not remove the already-written
archive in `runPublishRun`; retain and inspect the exit status, not just the
presence of `manifest.json`. Never use `--no-verify` for evidence. `publish run`
does not expose `--pack`, so its default loose layout fits this profile.

The planning CLI does not expose `max_documents`; it uses the planner's default
100000-candidate cap, whereas archive export internally selects a larger default.
Large-corpus slice 7c must account for that actual CLI limit (for example through
reviewed bounded selections); do not infer that full-library `publish plan`
works merely because `Export` has a higher cap. This is not an importer limit.

Published contract goldens remain format-verifier inputs and importer refusals;
see the [fixture matrix](../notrios/contracts/archive-v2/fixtures/fixture-matrix.json).
An optional-capability manifest probe is not a complete positive archive. Slice
1b generates the first real publication; 1c freezes conversion APIs/ID vectors,
Markdown/body limits and exact link syntax. None of those later slices is marked
complete by this contract review.

## Slice 1a acceptance evidence

- Reference HEAD and clean working tree checked; registry schema 27 matches
  `internal/store/store.go:CurrentSchemaVersion`.
- All twelve payload field sets and required members cross-checked against the
  pinned schema; all twenty hard-limit keys/values cross-checked against the
  registry; manifest/nested field order checked against Go structs.
- Each admission/refusal group above cites the source functions or explicitly
  identifies a stricter consumer decision. Loose-only capability rejection and
  the two digest meanings are fixed.
- Documentation links and `git diff --check` checked before commit. No importer,
  producer fixture, full runtime suite or real corpus/site build was run in 1a.

## Slice 1b observed publication

The subsequent [synthetic publication fixture](testdata/notrios/README.md) was
generated and verified with the clean pinned CLI. It is now the concrete input
for 1c. Its README records the exact commands, digests and semantic assertions.
This adds evidence without claiming that the planned Python verifier exists.

Observed details for the mapping design:

- A fragment is separate from `raw_target`. In this fixture, a self-anchor has
  an empty raw target **and the source document's target ID**, with heading
  metadata. The rule permitting ID-less self-anchors does not require them to
  be ID-less. See `internal/markdownlinks/parser.go:decorateCandidate`.
- Resource links are `resolved` with resource target IDs in the archive, even
  when the planner calls them `external` classifications. Planner classification
  counts must not be mistaken for archived resolution-status counts.
- The producer normalizes SQLite UTC timestamp spelling to RFC3339 without
  changing the instant. Included links retain correct UTF-8 byte offsets after
  earlier spans are rewritten; fragment and self-link expectations are in the
  fixture's `expected.json`.
- The fixture has a shared image and a relation-only binary attachment; all
  selected resource bytes survive exactly. The private resource and historical
  revision are absent. Nonempty revision metadata, source bundles, provenance
  and Trash were not seeded, so their stripping/exclusion is not proven by this
  particular producer run.
