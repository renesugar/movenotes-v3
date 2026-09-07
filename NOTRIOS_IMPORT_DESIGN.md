# Notrios importer implementation design — slice 1c

Frozen on 2026-09-06. This specifies future implementation; it does not add a
supported command. The [admission contract](NOTRIOS_IMPORT_CONTRACT.md) remains
authoritative for archive verification. This document adds stricter conversion
rules and freezes the interfaces needed by the
[remaining slices](NOTRIOS_IMPORT_PLAN.md). The real
[publication fixture](testdata/notrios/README.md) is the positive input.

## Modules and handoffs

Use Python's standard library only. Public helpers raise `NotriosError`, never
print or exit; only the CLI formats diagnostics. Dataclasses below are frozen;
paths and open handles are owned by their context manager. All sizes are bytes.
No API returns an archive-wide list of bodies, records or paths.

| Owner / file | Interface and responsibility |
|---|---|
| Main, Steps 2a/2b/2d/2e; `notrios_archive.py` | `NotriosError(code: str, message: str, *, object_sha256: str | None = None, record_type: str | None = None, record_id: str | None = None)`. Stable code families: `format`, `capability`, `limit`, `json`, `path`, `integrity`, `graph`, `publication`, `conversion`, `collision`, `destination`, `platform`, `io`. No body, arbitrary metadata or raw link target in diagnostics. |
| Same | `ArchiveLimits`: frozen named fields exactly matching the twenty registry keys in the contract; defaults equal those ceilings. Positive lower overrides are allowed for library tests; larger values refuse. `read_manifest(root: Path, *, limits: ArchiveLimits) -> Manifest`; `compute_commit_sha256(manifest: Manifest) -> str`. Reading the manifest performs declaration/target/shape gates without opening objects; semantic digest encoding follows the pinned Go structs, not input key order. |
| Same | `verify_archive(root: Path, *, work_dir: Path, limits: ArchiveLimits = DEFAULT_LIMITS) -> ContextManager[VerifiedArchive]`. Owns an exclusively created child of `work_dir`. Yields only after complete filesystem, hash, graph and publication verification. Copies verified index, record and blob bytes into that private work tree while hashing; every later body/resource consumption rechecks the copied object's size and SHA-256. No reopened source path is trusted. Cleanup occurs on exception and context exit. |
| Same | `VerifiedArchive.manifest`, `.counts`; `iter_records(kind: str) -> Iterator[Record]` in binary source-key order; `get_record(kind: str, key: tuple[str, ...]) -> Record`; `iter_relations(kind: str, document_id: str) -> Iterator[Record]`; `open_blob(ref: BlobRef) -> ContextManager[BinaryIO]`. A blob context verifies on complete read, including EOF; abandoning it cannot count as successfully consumed. `Record` exposes `.kind`, `.key`, `.payload`; `BlobRef` exposes `.sha256`, `.size_bytes`, `.media_type`. Handles cannot outlive `VerifiedArchive`. |
| Luna 3a, Main 3b; `notrios_mapping.py` | `source_key(database_id: str, kind: str, parts: tuple[str, ...]) -> bytes`; `mapped_id(...) -> str`; `joplin_timestamp(value: str) -> str`; `build_notebook_row(record, *, item_id, parent_id) -> dict`; `build_note_row(document, revision, *, item_id, parent_id, body) -> dict`; `build_tag_row(record, *, item_id) -> dict`; `build_note_tag_row(*, item_id, note_id, tag_id, timestamp) -> dict`; `build_resource_row(record, *, item_id, mime, extension) -> dict`; `generated_properties(row: Mapping) -> list[tuple[str, str]]`. Pure builders take validated input and use the exact rules below. They do not read files or independently allocate IDs. |
| Main design / Terra 3d and 5b; `notrios_links.py` | Owns `ConversionLimits` with constants below (Main adds the dataclass when first needed for 3a/3b). `scan_markdown(body: bytes) -> Iterator[Token]`; `validate_links(body: bytes, records: Iterable[Record], *, resolve, limits: ConversionLimits) -> LinkPlan`; `project_body(body: bytes, plan: LinkPlan, *, related_resources: Iterable[Attachment]) -> str`; `rewrite_projected_links(body: str, *, note_id: str, note_path: PurePosixPath, lookup_item_type, lookup_note_path, attachments) -> str`. Token/plan details below; may import archive dataclasses/errors, but performs no archive I/O and never imports a CLI. |
| Main 3b/6a/6b; `notrios2sql.py` | Imports `ConversionLimits` from `notrios_links`; `import_publication(source: Path, destination: Path, *, expected_selection_sha256: str | None = None, archive_limits: ArchiveLimits = DEFAULT_LIMITS, conversion_limits: ConversionLimits = DEFAULT_CONVERSION_LIMITS) -> ImportResult`. Result: `status` (`created` or `unchanged`), `destination`, `commit_sha256`, `selection_manifest_sha256`, and numeric row/resource counts. Owns staging, collision checks, database writes, receipt and completion. Future CLI: `notrios2sql.py SOURCE DESTINATION [--expected-selection-sha256 HEX]`; no limit-widening, overwrite, merge or unsafe flags. Exit 0 for created/unchanged, 2 for usage, 1 for refused/failed import. Do not expose it until Step 6. |
| Terra 3d; `sql2obsidian.py`, narrowly `notesdb.py` | A narrow branch for the Notrios-generated note marker and a second finalization pass, plus generated RAW title serialization described below. Reuse folder naming, deduplication, attachment copying, frontmatter and bundle writers. No changes to `obsidian2site.py` path maps, templates or schema are authorized by this design. |
| Luna 1d; `test_notrios2sql.py` | Fixture-copy/inventory helpers and baseline data assertions only. ID builders are implemented/tested in 3a; importer admission tests start in 2a. Tests must not import future modules before they exist. Own no runtime module in 1d. |

`resolve(kind, source_id)` returns the already validated mapped ID, using an
indexed lookup; a missing target raises, never falls back to a title. A `Token`
contains byte `start`, `end` (half-open, covering the entire link), `bang`, exact
label bytes, destination bytes, base and fragment. A `LinkPlan` contains only the
bounded current note's validated tokens and mapped targets, including external
tokens that will be copied unchanged. `Attachment` carries mapped resource ID,
safe display filename, relation type and ordinal; it contains no anchor JSON.
`lookup_item_type(id)` returns the Joplin type integer or `None`, independently
of notebook filtering. `lookup_note_path(id)` returns an actual exported
vault-relative path or `None`. The
`attachments` argument is the existing `AttachmentTable` protocol (`vault_name`,
`is_image`). Shared constants live in their owning module, not in the CLI.

## Stable identity and collision rules

Mapper name is `movenotes-notrios-v1`. Encode the ordered string sequence
`(mapper_name, database_id, kind, *parts)` as:

```text
b"MNID\x00" + uint32_be(number_of_strings)
             + concat(uint32_be(len(utf8(string))) + utf8(string))
mapped ID = lowercase hex SHA256(encoded_key)[0:32]
```

Do not normalize Unicode, case, whitespace or ID punctuation. Lengths count
UTF-8 bytes, not code points; no separators or JSON serializers participate.
`uint32_be` is unsigned, four bytes, network byte order. Reject invalid Unicode,
oversized components and wrong kind/arity before hashing. The general encoder's
Unicode examples exercise framing; archive IDs must additionally pass the
contract's narrower ASCII grammar.

| Kind | Ordered identity parts | Persisted projection |
|---|---|---|
| `collection`, `notebook`, `document`, `revision`, `tag`, `resource`, `link` | Source `id` only | Collections/revisions/links are bookkeeping; notebooks/documents/tags/resources become notesdb items. |
| `document_tag` | `document_id`, `tag_id` | NOTE_TAG item. |
| `document_resource` | `document_id`, `resource_id`, `relation_type`, decimal `ordinal` | Association bookkeeping, not a synthetic Joplin NOTE_RESOURCE item. Ordinal has no sign or leading zero except `0`. |

Where an API specifies source-key order, compare the complete framed key bytes
lexicographically (SQLite BLOB order), including component lengths.
Snapshot ID, replica ID, collection membership, title, revision pointer and
output paths never enter an item's identity. Identical resource bytes under two
source IDs remain two resources; shared resource IDs get one row/file. Persist
`notrios_ids(mapped_id TEXT PRIMARY KEY, source_key BLOB UNIQUE NOT NULL)` in
notesdb; every identity, including bookkeeping-only records, is registered.
Inserting an existing mapped ID with a different full key is `collision`. A
duplicate source record still refuses in verification, even if its bytes match.
Tests inject a fake hash result to prove collision refusal; no reliance on the
statistical rarity of truncation. The committed
[vectors](testdata/notrios/design-v1.json) freeze keys, full digests, IDs and
fixture body projections. Updates to a future mapper require a new version.

## Complete notesdb row and property contract

Use `notesdb.create_database` and batch helpers, with final indexes installed
before completion. No schema-version bump: auxiliary tables are namespaced and
existing exporters ignore them. Start every builder with all `NOTE_COLUMNS` and
`JOPLIN_COLUMNS` set to `None`; then set exactly the fields below. Let SQLite
allocate `note_id`. Do not accidentally apply `note_internal_date`'s current-time
default. Insert notebooks, documents, tags, document-tags and resources in that
order, binary source-key order within each group; identical creation dates then
have reproducible insertion order.

For every projected row set `note_uuid=joplin_id`,
`note_parent_uuid=joplin_parent_id`, `note_note_uuid=joplin_note_id`, and
`note_tag_uuid=joplin_tag_id`. Absent relation aliases remain NULL; the root
folder's parent is the empty string on both sides. `note_type` is exactly
`common.note_type_from_joplin_type(type_)`: NOTE_TAG is currently the empty
string, not an invented enum. `note_original_format='notrios'` on every row.
`note_folder` and `note_url` are NULL. `note_data_format='text/markdown'` for
all five item types, as required by `sql2joplin.write_joplin_item`.
`note_hash` is SHA-512 hex of UTF-8 `note_data`
for every generated row; it is not an attachment or source-archive checksum.

| Row | `type_` | Title/body | Parent and times |
|---|---:|---|---|
| Notebook | 2 | Original name; body equals name | Mapped parent or `''`; its created/updated times. Position, builtin and icon are validated but not projected. |
| Document | 1 | Current revision title exactly, including empty string; transformed Markdown body | Mapped notebook; document created/updated times, not revision times. Filename fallback to `Untitled` is the exporter's decision. |
| Tag | 5 | Original name; body equals name | No parent; both times from tag `created_at`. |
| Document-tag | 6 | Empty title/body | No parent; mapped `note_id` and `tag_id`; both times from owning document `created_at`. |
| Resource | 4 | Safe display filename below; body equals display filename | No parent; both times from resource `created_at`; size/MIME/extension below. Never put resource bytes in `note_data`. |

Convert UTC RFC3339 timestamps to `YYYY-MM-DDTHH:MM:SS.mmmZ`, flooring
sub-millisecond fractions, using integer calendar operations (no floating-point
epoch rounding). Joplin-facing properties use this spelling. Set
`note_internal_date` to the same instant as `YYYY-MM-DD HH:MM:SS.mmm` so
`sqlite3.PARSE_DECLTYPES` can read it. Timestamp truncation is a documented
projection loss; no source time or private message is copied to another field.

Ordered generated property pairs are as follows. Every listed value also sets
the corresponding typed `joplin_*` column; INTEGER/REAL values use numeric types
there. Serialize the pairs into `note_source_properties` as a JSON array of
two-string arrays (`ensure_ascii=False`, compact separators). This is generated
property bookkeeping, not an assertion of Joplin source bytes.

1. `id`; `parent_id` for notes/folders only.
2. `created_time`, `updated_time`, `user_created_time`, `user_updated_time`,
   `encryption_cipher_text=''`, `encryption_applied='0'`.
3. Type-specific pairs, in this order:
   - NOTE: `is_conflict=0`, `latitude=0.00000000`, `longitude=0.00000000`,
     `altitude=0.0000`, `author=''`, `source_url=''`, `is_todo=0`, `todo_due=0`,
     `todo_completed=0`, `source=movenotes-notrios`,
     `source_application=movenotes-notrios2sql`, `application_data=''`, `order=0`,
     `markup_language=1`, `is_shared=0`.
   - FOLDER: `is_shared=0`, `application_data=''`.
   - RESOURCE: `mime`, `filename`, `file_extension`, `size`, `is_shared=0`,
     `application_data=''`.
   - NOTE_TAG: `note_id`, `tag_id`. TAG has no type-specific pairs.
4. `user_data=''`, then `type_`.

All other Joplin fields remain NULL. All `note_obsidian_*`, `note_source_raw`,
`note_source_sha256`, `note_source_filename` and `note_source_body` remain NULL.
No application-data envelope stores original Notrios payloads. In particular,
resource metadata, collection descriptions, revision messages, relation anchors,
raw link records and arbitrary settings cannot enter frontmatter or preservation
bundles. This follows the existing generated-property convention in
`obsidian2sql._generated_properties` without importing that CLI helper.

Persist `notrios_document_resources(relation_id TEXT PRIMARY KEY,
note_id TEXT NOT NULL, resource_id TEXT NOT NULL, relation_type TEXT NOT NULL,
ordinal INTEGER NOT NULL, UNIQUE(note_id, resource_id, relation_type, ordinal))`
with indexes starting with `note_id` and `resource_id`. References are mapped IDs.
Do not retain `anchor_json`. Collections and revisions need no payload tables:
the ID table plus receipt provides the required minimal bookkeeping.

## Conversion limits, MIME and attachments

These consumer limits are intentionally smaller than archive-v2 ceilings.
Verify a valid larger archive independently, then refuse conversion before
creating notesdb rows. All admitted current bodies and relation counts must
pass the preflight. Limits cannot be widened in this mapper version.

| `ConversionLimits` field | Maximum / behavior |
|---|---:|
| `max_body_bytes` | 16777216 per current revision, checked before allocation |
| `max_projected_body_bytes` | 33554432, including synthesized attachment list |
| `max_links_per_note` | 10000 archived link records and independently 10000 scanned active tokens |
| `max_resource_relations_per_note` | 10000 records, before deduplication |
| `max_fragment_bytes` | 1024 |
| `batch_rows` | 1000 |
| `batch_bytes` | 33554432 estimated UTF-8/BLOB bytes in queued row values, including generated properties |
| `copy_chunk_bytes` | 1048576 |

One row larger than the batching byte target is inserted alone after the prior
batch flush; it is still bounded by body/record conversion limits. Do not build
an additional archive-wide body cache. Temporary SQLite holds indexed objects,
record identities/payloads, references and ID maps. Use bounded cursor iteration,
`fetchmany`, composite indexes and joins for reconciliation; cap SQLite's page
cache and temporary memory (8 MiB cache, `temp_store=FILE`). A single note's
bounded parser working set may exceed its UTF-8 byte size due to Python objects;
the limits do not promise an unmeasured exact RSS. Resources retain the registry
16 GiB per-blob ceiling and are streamed, never decoded or accumulated.

Only semantic `text/markdown` bodies are convertible, with no parameters or
sole `charset=utf-8` parameter (charset token case-insensitive). Canonical MIME
comparison with the reference is still required before this narrower check.
Strict UTF-8 decode; refuse BOM, NUL and C0 controls other than TAB/CR/LF. Preserve
line endings and trailing whitespace in the database. Do not convert HTML,
plain text, binary or another charset implicitly. No query evaluation, network
fetch, sanitizing HTML renderer or source-library lookup is part of conversion.

Normalize MIME using the pinned Go `mime.ParseMediaType`/`FormatMediaType`
semantics, including parameter parsing, duplicate rejection, quoting, sorted
parameter serialization and extended values; freeze differential vectors in
2d rather than substituting permissive `email` parsing. Blob descriptor MIME
remains only a hint; reference MIME must be canonical and match semantic MIME.
All valid resource MIME types are copied as opaque bytes. Extension is selected
from the canonical base media type by this fixed map:

```text
image/png png             image/jpeg jpg          image/gif gif
image/webp webp           image/svg+xml svg        image/avif avif
image/bmp bmp             image/tiff tif           image/x-icon ico
text/plain txt           text/markdown md         text/csv csv
application/pdf pdf      application/json json    application/zip zip
audio/mpeg mp3           audio/ogg ogg            audio/wav wav
video/mp4 mp4            video/webm webm
everything else bin
```

Never use OS-dependent `mimetypes` tables or a source suffix to choose storage
paths. Store exactly `resources/<mapped-resource-id>.<extension>`, once per
resource, using exclusive file creation and streamed size/hash validation.
Content collisions refuse. For the display filename only: take the last
component after either slash kind; remove C0/DEL, strip surrounding whitespace;
if empty, `.` or `..`, use `attachment.<extension>`. Retain the resulting Unicode
filename and its original suffix otherwise. Joplin `filename` and `note_title`
are that same value. `sql2obsidian` applies its normal filename sanitization and
deduplication at export. This basename is approved content, not an input path.

For each note, subtract resources with a validated inline resource link from
its document-resource set. Append each remaining resource once, sorted by
minimum `(ordinal, relation_type UTF-8 bytes, mapped-resource-id)` across its
relations. All nonblank relation types are admitted as a generic association;
no special behavior is inferred from an unknown type or anchor JSON. Append
exactly `\n\n## Attachments\n\n` followed by one LF-terminated
`- [LABEL](:/ID)` per missing resource. This suffix is added even to an empty
body; do not trim existing bytes. Labels use the display filename with `&`,
`[`, `]`, `<`, `>` and backslash encoded respectively as `&amp;`, `&#91;`,
`&#93;`, `&lt;`, `&gt;`, `&#92;`. Use ordinary links even for images, so a
relation alone does not unexpectedly embed media. Multiple relations remain
in the auxiliary table but generate one link. The fixture adds only
`- [related.bin](:/<mapped res_sidecar>)` to the main note; shared PNG bytes
are exported once and both inline embeds refer to them.

## Admitted links and refusal boundary

This is a deliberately narrow Markdown projection, not a complete CommonMark
parser. Inspect each note independently. Recognize protected fenced blocks at
line start after 0–3 spaces, backtick/tilde runs of length at least three, closed
by the same character with at least that length and whitespace only afterwards;
an unclosed fence protects through EOF. Backtick fence info strings cannot
contain backticks. Also protect lines beginning with a tab or at least four
spaces, and inline code bounded by equal-length backtick runs outside fences;
an unmatched inline run is ordinary text. Mark escaped punctuation before token
recognition. These are lexical protection rules, not inferred rendered block
structure. Ambiguous nested container/fence syntax containing internal targets
refuses rather than guessing its context.

Active accepted syntax is `[label](destination)` or `![label](destination)` on
one line, with no optional title, nested brackets, backslash escapes in label or
destination, angle destination or whitespace in destination. Empty labels are
allowed. Destination may not contain parentheses; percent-encoded bytes remain
encoded. Every archived link must match one complete active token at exactly
its half-open byte span; `start < end <= body_size`, both endpoints must be
UTF-8 boundaries. Sort by `(start,end,id)` and reject any overlap, duplicate
span, stale span or token inside protected code. The producer currently scans
code too: such publications conservatively refuse if they contain those link
records. `source_line` and `source_column` are validated as nonnegative integers
but are not compared with the rewritten body; the fixture demonstrates that
byte offsets are the authority after publication rewrites.

Require `source_format='markdown'`, relation `link` for ordinary syntax or
`embed` for bang syntax, exact label equality if `display_text` is present, and
exact `raw_target` equality to the destination before its first `#`. Do not
decode percent escapes for this comparison. Accepted target rules:

| Target | Additional agreement / output |
|---|---|
| `document://default/documents/ID` | `resolved`, existing matching `target_document_id`, no resource target; `target_uri` if present equals that base exactly. Produce `:/<mapped-id>` plus unchanged validated fragment. Document embeds refuse. |
| `resource://default/resources/ID` | `resolved`, matching resource target, no document target; matching `target_uri` if present; require a document-resource relation for this source and target. No fragment. Produce `:/<mapped-id>`. |
| `#fragment` | `resolved`; target ID absent or equal to source document; no resource ID. `target_uri` absent/empty or the source's canonical document URI. Keep `#fragment` unchanged. |
| HTTP(S) absolute URL | `external`, no internal IDs; hostname required, no userinfo, controls or backslashes. `target_uri` if present equals destination base. Preserve the entire original token byte-for-byte, including query/fragment. |

Only lowercase exact internal scheme/authority/path spellings above are admitted;
no userinfo, ports, queries, encoded IDs, traversal or alternate authorities.
For any destination fragment, require one nonempty fragment of at most 1024
bytes with valid `%HH` sequences and no controls/whitespace or additional `#`.
`anchor_type` must be `heading` and `anchor_value` must equal the raw fragment;
empty/absent anchor fields are required when there is no fragment. Refuse block
anchors (`#^...`) in this first mapper: translating their semantics through
both Obsidian and Hugo is not implemented. Heading fragments are preserved,
not recalculated or resolved by title; target heading existence/rendered slug
compatibility is tested downstream, not certified for every renderer at import.

Every active internal token and self-anchor must have one matching retained
record. Ordinary unrecorded HTTP(S) links remain untouched. Refuse missing
internal records even when their target happens to be included. After accounting
for accepted tokens, scan unprotected bytes case-insensitively for
`document://`, `resource://`, `notrios://` and `:/` followed by 32 hex digits;
any unconsumed occurrence refuses. Refuse unprotected wiki links/embeds and
Markdown reference definitions/uses that could be local links, and active
inline links with relative, file, unsupported-scheme or malformed destinations.
There is no filename/title resolution fallback. Bare relative prose is not a
link. These conservative checks include HTML attribute/autolink occurrences
of recognized internal schemes; they do not constitute an arbitrary HTML or
privacy audit. Protected code bytes, withheld prose and redaction remain inert
and unchanged. Do not claim that archive integrity detects every skipped
producer rewrite or hidden private reference.

Apply replacements in a single left-to-right byte pass using validated spans;
never reuse original offsets after editing. Only destination bytes change;
external/self tokens and bytes between tokens stay exact. Then append the
relation-only attachment suffix. Strictly decode the final bytes once and check
the projected-byte ceiling. `design-v1.json` contains full expected database
bodies, so Unicode offset regressions cannot pass a substring-only assertion.

## Final vault paths and exporter boundary

Generated Joplin RAW uses a title line in its body, whereas the Notrios NOTE
row deliberately stores only the projected body. In 3d, add a narrow branch to
`notesdb.serialize_joplin_item`: only for `note_original_format='notrios'` and
NOTE type, prefix the supplied/default body with
`(single_line_title or 'Untitled') + '\n\n'`. Use the same line-break removal
convention as the existing Joplin exporter for `single_line_title`. This applies
to preservation bundles and direct Joplin export without duplicating logic.
Never prefix already imported RAW or native Obsidian items. Folder/tag/resource
bodies already contain their title, per the row table. Reimport of this generated
RAW follows normal Joplin title parsing (including its empty-title fallback and
heading normalization); it is not an exact Notrios round trip. The initial vault
frontmatter retains the original title. Test generated RAW through `joplin2sql`
to catch empty folder/tag bodies and an accidental duplicate note prelude.

Treat a note as this generated projection when both
`joplin_source='movenotes-notrios'` and
`joplin_source_application='movenotes-notrios2sql'`. This marker survives a
generated Joplin preservation bundle; `note_original_format` alone need not
survive reimport. Do not change behavior of existing Joplin/Obsidian notes.

The Notrios branch uses the shared protected-token scanner for mapped links.
Do not run the global resource regex over its full body: that would rewrite
link examples inside code. Classify `:/ID` by the database's item type, not a
guess that every 32-hex ID denotes a resource. Resource tokens alone invoke the
existing attachment behavior (image bang → wiki embed; other links → encoded
relative attachment path). Missing mapped resources refuse; a selected-note
filter must not make a missing resource silently look like a note link.

1. Keep the existing loop's note order, folder paths and filename reservations.
   Write notes normally to determine the **returned** path from
   `write_note_bytes`, including its `ENAMETOOLONG` fallback. For marked notes,
   defer note-link replacement, skip leading-title removal for original Notrios
   rows (it could remove a fragment target), and apply only token-aware resource
   rewriting. For marked notes reimported from generated RAW, remove exactly
   its one synthetic title line and separator, not matching headings below it.
   Record actual
   paths for all exported notes in `obsidian_paths`. Code and note-query blocks
   remain untouched. Existing `--no-simplify-urls` is required for byte-fidelity
   checks; optional URL simplification retains its existing documented effect.
2. After all filenames exist, iterate marked rows again. Rebuild each body from
   notesdb, with the same attachment names, and resolve mapped note links using
   the complete final path map. Relative path = POSIX `relpath(target,
   start=source.parent)`; quote UTF-8 with only `/` and RFC3986 unreserved
   characters safe. Append the unchanged fragment. Self `#fragment` stays local.
   No absolute filesystem path appears in the Markdown.
3. If notebook filtering omitted a linked target, render only its label as text
   (HTML-unescape character references, then backslash-escape every ASCII
   punctuation character using `string.punctuation`), with a numeric omitted-link
   summary. Do not leak the skipped title/path from the unfiltered database.
   In an unfiltered export a missing target is an error. Retain referenced
   resource IDs using active tokens only; bundle selection must include the
   relation-only resources already present in the projected body.
4. Rewrite content at the recorded path; do not reserve another name or invoke
   a second length fallback. If this write fails, fail the export. Recompute
   `obsidian_hashes` from finalized bytes **before** writing the preservation
   bundle and any receipt sidecar. Use the normal frontmatter and final-newline
   behavior. Nothing in this branch changes canonical site URL generation.

This keeps bodies bounded per note; existing exporter metadata maps still scale
with the vault. It does not make vault export transactional: an interrupted vault
export must be rerun into a fresh directory. The atomic guarantee below covers
the importer output only. Test the final-path resolver with explicit path maps
and injected first-write `ENAMETOOLONG`, not merely with guessed sanitized
titles. Duplicate-title suffix assignment remains the existing exporter's rule.

## Staging, completion and identical-output no-op

Initial atomic publication is supported on Linux filesystems providing
`renameat2(RENAME_NOREPLACE)` and file/directory `fsync`. Implement the primitive
with the standard-library `ctypes` libc interface, explicit signatures and
`use_errno=True`; fail `platform` on a missing symbol or unsupported filesystem.
Do not silently fall back to POSIX `rename`, which may replace an empty directory.
This platform restriction applies to importer publication, not archive-only
verification. Future portability is a separately tested change.

Require an existing writable real destination parent; source and destination
trees must be disjoint (neither may contain the other). Reject symlink path
components and hold a parent directory descriptor for final operations.
Resolve/check source and destination before creating work files. No source
files are modified. Random work names do not enter IDs, SQLite fields or receipts.

The lifecycle is:

1. Exclusively `mkdir` a sibling lock named
   `.movenotes-notrios-lock-<SHA256(destination basename UTF-8)>` with mode 0700.
   Write an owner record containing a random token, PID and creation time; hold
   its directory identity. An existing lock refuses, even if its PID is dead.
   A lock coordinates importers; the final no-replace primitive also protects
   against an unrelated process creating the destination.
2. Make private sibling work and stage directories with unpredictable names,
   mode 0700, and the owner token. Verify the entire source into work copies.
   Compare `expected_selection_sha256`, if provided, to the manifest selection
   digest; malformed or mismatched expectations refuse even on a no-op.
   Run conversion preflight over every current body/link/relation count.
3. If destination exists, perform the identical-output check below and either
   return `unchanged` or refuse. No writes to the existing tree are permitted,
   including SQLite WAL/SHM side effects. For an absent destination, build in
   stage using `journal_mode=DELETE`, `synchronous=FULL` after database creation;
   no WAL sidecars may be part of a completed tree. Store the receipt and
   auxiliary IDs/associations before flushing batches, creating indexes,
   checking row/reference counts and `PRAGMA integrity_check`, committing and
   closing. Finish all streamed resource writes before completion.
4. Close every handle and remove the stage's ownership record (the lock retains
   the stage name/token). Write a streamed inventory of final payload files and then a completion
   marker as specified below; fsync files and directories bottom-up. Work/lock
   ownership files and verifier spools must never enter the final stage.
5. Call `renameat2` with parent-relative basenames and `RENAME_NOREPLACE`.
   `EEXIST` refuses without touching the winner. Fsync the parent. Remove only
   this process's work and lock, checking the owner token/directory identity.
   Return created. If parent fsync fails after rename, report a durability error
   and leave the complete destination intact; do not delete a published result.

On pre-rename exceptions, clean up only owned stage/work/lock entries; report
cleanup errors without hiding the original error. SIGKILL/power loss can leave
hidden entries; never auto-steal a lock, delete stale stages, resume partial
SQLite, or guess ownership from a PID alone. The operator must confirm no writer
is active, inspect the owner record and move the exact stale lock/work/stage
aside before retrying. Expose their paths in local error diagnostics only, never
the receipt. A completed destination with a stale lock also requires that
explicit recovery. Noncooperating same-user modification of owned work files is
not a security boundary; source mutation between verification/use is covered by
verified copies and per-consumption hashing.

Receipt setting key is `movenotes.notrios.import.v1`, compact JSON object with
exact fields `version=1`, `contract="notrios-archive-v2"`,
`contract_schema_version=1`, `reader_profile="movenotes-publication-loose-v1"`,
`mapper="movenotes-notrios-v1"`, `commit_sha256`,
`selection_manifest_sha256`, `snapshot_id`, `database_id`,
`target="publication_handoff"`. No wall-clock import time, replica/path, arbitrary
metadata or body is recorded. It establishes traceability, not authenticated
approval. Slice 6c may propagate only this content-free allowlist in excluded
sidecars, after testing site/search/bundle exclusion.

Final payload is `notesdb.sqlite` and `resources/` (present even when empty).
`notrios-inventory.jsonl` has sorted relative POSIX paths, one compact object
`{"path":...,"size_bytes":...,"sha256":...}` per payload file, final LF.
Each line is bounded to 4096 bytes. `notrios-complete.json` is a compact object
with `version=1`, `receipt` (the exact receipt object), `inventory_sha256`,
`inventory_size_bytes`, `file_count`; cap marker size at 16384 bytes. Neither
inventory nor marker inventories itself. These two local control files are not
public sidecars and must not be copied wholesale to a vault/site.

An identical no-op requires a fully verified input, matching receipt/mapper,
strictly valid completion and inventory, exact real-file inventory (no extras,
symlinks or WAL/SHM), all current payload hashes/sizes, and a matching SQLite
receipt read with `mode=ro&immutable=1`. Use disk-backed inventory joins and
streamed hashing; do not trust marker presence alone or compare nondeterministic
SQLite bytes against a fresh rebuild. Different/edited/unrelated/incomplete
outputs refuse. It is acceptable that later database maintenance invalidates
this exact-complete no-op. No merge/update semantics are implied.

## Acceptance cases assigned to later slices

| Slice | Required concrete checks |
|---|---|
| 1d | Offline fixture file inventory/hashes/counts; expected selected bodies, metadata and excluded sentinels; design JSON shape and fixture digest linkage. No Notrios installation needed. |
| 2a | Independent Go-compatible semantic digest vectors, including HTML-sensitive/Unicode strings, omission/default distinctions and alternative JSON whitespace/key ordering; declaration refusals before object access. |
| 2b–2e | Contract mutation matrix, integer/depth/line boundaries, legacy zero blob counts, all references/cycles, immutable-copy and rehash-at-use failures, MIME parameter vectors; larger valid blob accepted by verifier but refused as a body by conversion. |
| 3a | All ID vectors, unchanged identity on replica/snapshot/title changes; injected ID collision; all column defaults, exact property order and generic aliases; empty/Unicode titles; nanosecond flooring and UTC zero-offset spellings. |
| 3b | Insertion/copy/inventory/rename/fsync fault injection; no completed partial destination; two writers and unrelated empty-directory race; old output untouched; no-op detects modified resource/database/receipt/extra file; stale lock never stolen. |
| 3c/3d | Exact projected fixture bodies; duplicate titles, nested directories, actual path fallback; selected notebooks; heading-title retention; final bundle hashes; UTF-8 mid-codepoint/stale/overlap/missing-record refusals; protected code unchanged and code-overlapping records refused; malformed URI, query, authority, title syntax, wikilink, block anchor and unsupported body MIME refusals. |
| 4/5 | Six fixture memberships and four distinct tag names preserved; three resource files with exact hashes; shared PNG copied once; only sidecar receives synthetic download link; duplicate/unknown-type relations deterministic; all three resources reachable in vault/bundle. |
| 6/7 | Real CLI fixture→DB→vault→Hugo/search runs, receipt allowlist/exclusion and explicit-tag agreement; required existing-format regression suite; measure importer and downstream memory separately. |

Slice 1c acceptance checks the design vectors against the actual fixture's byte
spans and independent length-framing/hash implementations, and checks document
links/diffs. Runtime importer, parser, crash recovery and exporter acceptance
remain unimplemented until their assigned slices. Next item is **1d**, after
the user's per-item approval.
