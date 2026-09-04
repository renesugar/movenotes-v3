# Plan: Import a Notrios publication handoff

## Goal

Add `notrios2sql.py`: read a Notrios archive-v2 **publication handoff** into
`notesdb.sqlite`, so the projections that already exist take it the rest of the
way.

    notrios2sql.py  →  notesdb.sqlite  →  sql2obsidian.py  →  obsidian2site.py

Nothing downstream changes. `sql2obsidian.py` and `obsidian2site.py` are
written and tested; this is the one adapter that never got built.

## Why this rather than an Obsidian emitter inside Notrios

Notrios' `PUBLISHING_POLICY.md` divides the work deliberately. Notrios owns
selection of public notes, private/draft exclusion, resource reachability, link
rewriting for withheld targets, metadata stripping, privacy warnings, and
writing a checksum-verified handoff. movenotes owns the projections: Obsidian
vault output for interoperability and Quartz, Hugo/Ledger, Pagefind and Bluge.

That boundary named `notrios2sql.py` as the consumer, and it was never written,
so the handoff currently has none: Notrios can produce a publication that
nothing in either toolkit can turn into a site. Adding a vault emitter to
Notrios instead would duplicate `sql2obsidian.py`, oblige Notrios to own
wikilink rewriting and frontmatter mapping, and weaken a guarantee — see
"reviewed-plan integrity" below.

## What a publication handoff is

Archive-v2, described in `NATIVE_ARCHIVE_V2.md` in the Notrios repository. For
this importer the relevant parts are:

* a **manifest** with a `manifest_sha256` covering the whole selection;
* **`records`** objects: LF-terminated JSONL, each line `{ "type", "payload" }`;
* **`blob`** objects: exact bytes, hash-addressed, with canonical MIME types;
* an **`index`** listing every blob and records object.

A publication handoff is a projection, not a backup: current revisions only, no
trashed notes, no provenance, no source bundles, stripped revision metadata, and
links to withheld notes already rewritten to plain text or a placeholder.

## Mapping

`sql2obsidian.py` reads `note_type`, `note_title`, `note_data`, `note_uuid`,
`note_parent_uuid` and `note_original_format`, with `note_type` one of `folder`,
`note` or `resource`. So:

| archive-v2 record | notesdb row |
|---|---|
| `notebook` | `note_type='folder'`, `note_uuid`, `note_parent_uuid`, `note_title` |
| `document` + its current `revision` + body blob | `note_type='note'`, `note_title` from the revision, `note_data` from the blob, `note_parent_uuid` = notebook |
| `resource` + blob | `note_type='resource'` plus the exact bytes |
| `tag`, `document_tag` | the tag rows `sql2obsidian` already expects from the Joplin importer |
| `link` | **nothing** — see below |
| `search_notebook`, `provenance`, `source_bundle` | not present in a publication handoff |

`note_original_format` is `notrios`, so a later export can tell where a note
came from without guessing.

## Decisions

**Verify before importing, not after.** The handoff is checksum-verified by
construction and the point of that is lost if the first consumer trusts file
paths instead of hashes. `notrios2sql.py` checks each object against the index
and the index against the manifest before writing a row. A handoff that fails
verification is refused whole rather than partially imported.

**Refuse a full archive.** The same container carries `full_archive`,
`subset_transfer` and `publication_handoff`, and a full archive contains
private state this pipeline would publish. The importer reads the manifest's
target and refuses anything but `publication_handoff` unless explicitly
overridden, because feeding a backup to a site generator by accident is the
failure worth designing against.

**Do not re-rewrite links.** Notrios has already rewritten links to withheld or
unresolved targets, dropped the corresponding link records, and adjusted byte
offsets onto the published body. `link` records are informational here. Any
second pass would be rewriting text that has already been made safe, against a
graph this database does not have.

**Reviewed-plan integrity stops at the manifest.** Notrios binds a publication
to the digest somebody reviewed: `publish run` re-plans, refuses on a mismatch,
and checks the written manifest against it. This importer should record
`manifest_sha256` in `settings`, so a generated site can be traced to the
reviewed plan that authorised it. That is the property a vault emitter inside
Notrios would have had to invent from scratch.

## Open questions

* **Attachment layout.** `sql2obsidian.py` has its own attachment conventions.
  Do resources import as `note_type='resource'` rows carrying bytes, or are they
  written to a resources directory with rows pointing at them? Settled by
  reading `sql2obsidian.py` and `cleanres.py` rather than by choosing.
* **Tags.** The Joplin importer produces tag rows in a particular shape
  (`note_tag_uuid`, `note_note_uuid`). Reuse it exactly, or the vault emitter
  will silently produce no tags.
* **Multiple handoffs into one database.** Merging is an existing movenotes
  feature. Do note UUIDs from two Notrios libraries collide, and does the
  existing duplicate removal handle them?

## Steps

1. Read `NATIVE_ARCHIVE_V2.md`, then a real handoff produced by
   `notriosctl publish run`, and write down what a minimal publication contains.
2. Manifest and index verification, with a hostile fixture: a handoff whose
   blob bytes do not match their hash must be refused.
3. Notebooks and notes, with bodies. `sql2obsidian.py` produces a vault at this
   point, without tags or attachments.
4. Tags, in the shape the vault emitter already reads.
5. Resources and attachments.
6. `manifest_sha256` recorded in `settings`; refuse non-publication targets.
7. End to end: a Notrios publication becomes a vault, and the vault becomes a
   site, in one documented run.

## Verification

Fixtures generated by Notrios rather than written by hand, because a fixture
somebody typed is a fixture that agrees with its author's understanding of the
format. `notriosctl publish run` produces the input; the test asserts the
resulting database, and then that `sql2obsidian.py` renders it.
