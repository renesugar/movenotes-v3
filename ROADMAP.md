# Roadmap

What future releases of movenotes are meant to do. `PLAN.md`, when a plan is
active, says how far it has got; none is now, and the next will be written from
this file at a later date. This file carries no slice status, and the rules
for keeping the two apart are in [`AGENTS.md`](AGENTS.md#plans-the-roadmap-and-the-archive).
Finished plans are in [`plans/`](plans/).

## 3.38 — released

[The plan that built it](plans/v3.38/000-reorganization-plan.md) is archived:

- **A tidier repository.** The account name is removed from committed paths
  and, with the user's permission, from the Git history. The finished plans
  are archived by version. Tests live in `tests/`, development tools in
  `scripts/` and documentation in `docs/`. Every relative link is checked.
- **Documentation that can be trusted.** Every documented example is
  registered, and runs in the gate unless the reason it can't is recorded.
  Notrios publishing gets documentation on keeping private data out of a
  publication, what tagging cannot catch, and publishing more than 100,000
  notes.
- **The Notrios import follow-ups:**
  - HTML images that show after export (H1);
  - clearer refusals for an unusable `notrios2sql.py --output` (D1);
  - a report of the links a web reader cannot reach (R1);
  - keeping the links Notrios cannot resolve on the Notrios route (R2).
- **Found by the link report:** a same-folder link the site cannot resolve
  when another note shares its name (R3).
- **Found by R2's probe:** importing a Notrios publication that holds
  resolved wiki links (W1).
- **Found by W1:** links to a block, `#^id`, on the Notrios route and on the
  site (B1).

## Deferred

These are not in any plan yet. Each says what it is, why it waits, what it
needs, and what it depends on. When one is planned, it goes into `PLAN.md` and
stays listed here, under the release it is planned for.

### A `plain_text` that keeps every non-internal link

**What.** A Notrios change, so that the `plain_text` link action replaces only
a link to a note or attachment the publication leaves out, keeps every other
link as written (`file:`, `tel:`, `data:`, relative and the rest), and never
uses a target URI as a link's text. The one handoff then serves a site on the
author's machine, on an intranet and on the Internet alike.

**Why it waits.** It is a producer change, in Notrios rather than movenotes.
R2 meets the need for now with `--link-action retain`, which keeps every link
but puts each withheld note's ID into the handoff, so a handoff made that way
must stay as private as the library; movenotes replaces each such link with
its text before writing anything.

**A privacy defect in released handoffs.** R2's probe also found that
`plain_text` at `v1.0.0` replaces a wiki link with no alias to a withheld note
with that note's URI, `document://default/documents/<id>`, which for a library
imported from Obsidian spells the note's folder and title. So a reviewed
publication handoff names a note it withholds. movenotes refuses such a
publication, so it reaches no vault or site, but the handoff holds it, and any
other reader of it sees the name. Notrios should treat this as a bug in its
released handoffs, not only as a feature to add. Whether `publish plan` shows
the reviewer this text is not known here.

**What it needs.**

- The change, in Notrios at `v1.0.0` (commit `2aab9a8`):
  [`publicationLinkNeedsRewrite`](https://github.com/renesugar/notrios/blob/2aab9a8fe7c1ba8e411cd6003a6115b09abd6b9a/internal/archivev2/publish.go#L129)
  decides which links are rewritten, today every link that is not `external`
  or resolved to an included note or attachment, and
  [`replacementFor`](https://github.com/renesugar/notrios/blob/2aab9a8fe7c1ba8e411cd6003a6115b09abd6b9a/internal/archivev2/publish.go#L108) chooses the text,
  the link's display text or the placeholder `[redacted]` when it has none.
- The replacement text for a link whose display text is its target's URI. Notrios
  drops an unaliased wiki link's original text when it imports it, so that
  link has nothing else to show. The withheld note's title would name it, so
  the only safe text is the placeholder, `[redacted]`, as for a link with no
  text. movenotes already replaces such a link with the placeholder in a
  `retain` handoff (R2).
- A way for movenotes to tell the two behaviours apart. A new producer pin
  here is the least: movenotes reads `v1.0.0` handoffs as it does today, and
  the new release's with the narrower rewrite. A field in the manifest naming
  the rewrite rule would let one importer read both without trusting the
  producer version.
- A release, a new producer pin here, and fixtures regenerated from it.
  movenotes then reads both actions' handoffs the same way.

**Reproduce it** with the `retain` fixture and its generator,
[the `retain` publication (R2)](testdata/notrios/v1.0.0/README.md#the-retain-publication-r2),
and R2's probe of both actions in
[the archived plan](plans/v3.38/000-reorganization-plan.md#r2--non-internal-destinations-on-the-notrios-route).

**Depends on** R2 (option (a)), decided by the user on 2026-10-27.

### A Notrios body's frontmatter on the Notrios route

**What.** Notrios's Obsidian importer writes `source_system: obsidian`,
`obsidian_path` and `obsidian_folder` into each note's frontmatter, adding a
frontmatter block when the note has none
([`obsidian.go`](https://github.com/renesugar/notrios/blob/2aab9a8fe7c1ba8e411cd6003a6115b09abd6b9a/internal/importers/obsidian/obsidian.go#L1319), and again
at [L2108](https://github.com/renesugar/notrios/blob/2aab9a8fe7c1ba8e411cd6003a6115b09abd6b9a/internal/importers/obsidian/obsidian.go#L2108)). A publication
keeps that block at the start of the body, and `notrios2sql.py` imports the body
as it is, so the vault export puts it under its own frontmatter as a second
block. On the site it renders as a horizontal rule and a heading listing those
fields, at the top of every note from an Obsidian library (seen on B1's probe
site, 2026-10-27; not yet checked in Obsidian). By the source, a note's own
frontmatter, its tags and aliases included, is in the same block.

**Why it waits.** Found after B1, with no plan open. It changes the body of
every note on the Notrios route from an Obsidian library, so it needs its own
fixture and a decision.

**What it needs.** A decision on where it is handled. In movenotes, the import
or the export would move a leading frontmatter block into the note's
metadata, keeping its bytes, so the vault has one frontmatter and the site
shows none, with the native `obsidian2sql.py` route's handling of frontmatter
as the model. In Notrios, a publication could leave its own provenance fields
out of a published body, as it leaves out provenance records. The movenotes
side is needed either way, for a note's own frontmatter. Then a fixture from
the pinned producer with notes with and without frontmatter.

**Depends on** nothing.

### An unaliased wiki link's text

**What.** A Notrios change, so that a resolved wiki link with no alias keeps
the text it was written with. Notrios stores `[[Other Note]]` as
`[[document://default/documents/<id>]]`, and its link record's display text is
that URI, so the original text is gone from the handoff.

**Why it waits.** It is a producer change, and movenotes works around it: W1
labels such a link with the target note's current title, or the attachment's
file name, which is what Obsidian shows for it unless the note was renamed.

**What it needs.** The original target text kept in the stored body or in the
link record, a release, and a new pin and fixture here. W1's import would then
use it as the label.

**Depends on** nothing.

### Percent-encoded block anchors

**What.** A Notrios change, so that a link to a block written with its `^`
percent-encoded, `[x](Note.md#%5Eid)`, is recorded as the block anchor it is.
Obsidian decodes the fragment and opens the block, but Notrios's
[`splitAnchor`](https://github.com/renesugar/notrios/blob/2aab9a8fe7c1ba8e411cd6003a6115b09abd6b9a/internal/markdownlinks/parser.go#L373) tests for `^` without
decoding, and records a heading, `%5Eid`.

**Why it waits.** Nothing breaks: movenotes copies the fragment as written,
the vault export keeps it, and Obsidian and the site both decode it (B1). Only
the record disagrees with what the link means.

**What it needs.** `splitAnchor` decoding the fragment before testing it, and
a regenerated `publication-block` fixture
([the block-link publication (B1)](testdata/notrios/v1.0.0/README.md#the-block-link-publication-b1)),
whose generator expects the heading today.

**Depends on** nothing.

### Packed publications

**What.** Import a Notrios archive-v2 that stores its objects in pack files,
the `objects.pack.v1` capability that `notriosctl export archive-v2 --pack`
writes, instead of one file per object.

**Why it waits.** The importer reads one reader profile,
`movenotes-publication-loose-v1`, and refuses a packed archive, or a pack
location in a loose one, before reading anything else. A loose publication
holds the same records, and the producer writes one whenever `--pack` is left
off, so nothing published today needs packs.

**What it needs.** A pack reader with the same guarantees as the loose one:
bounded reads, no-follow opens, the size and SHA-256 checks on every object
before it is used, pack-file digests checked against the index, and limits on
pack count, pack size and objects per pack. It also needs fixtures from the
pinned producer, and a differential audit against the producer's own reader,
like the loose profile's.

**Depends on** nothing in movenotes. The pinned producer already writes packs.

### Multiple handoffs and merges

**What.** Import more than one publication into one library: several
publications from different Notrios libraries, a newer publication of the
same selection over an older import, or publications combined with notes
imported by `joplin2sql.py` or `obsidian2sql.py`.

**Why it waits.** `notrios2sql.py` writes only into a new output directory, or
reruns an identical completed import, and publishes the whole database with
one no-replace rename. That makes every import all or nothing, and it is why
an import can refuse a damaged archive without touching anything. Merging
gives up the single rename, and needs decisions this release has not made.

**What it needs.**

- Rules for a note in both publications: its IDs come from the publication's
  own identities, so a newer publication of the same library yields the same
  IDs. Is the newer revision an update?
- Rules for a note in the older import that is missing from the newer one: is
  it deleted, withheld or kept?
- Rules for collisions with other sources, keeping the invariant that the same
  ID with different bytes is an error.
- A receipt for each publication. Today there is one setting,
  `movenotes.notrios.import.v1`.
- A transactional merge that still writes nothing when it refuses.

It would also let a library over the `publish` path's 100,000-note cap be
published in parts and joined into one site. Until then, the parts are
separate sites, or the export route in the Notrios publishing documentation is
used instead.

**Depends on** a decision on update and deletion semantics. Packed
publications are independent of it.

### Full and subset archives

**What.** Import the other two archive-v2 targets, `full_archive` and
`subset_transfer`, which a library is backed up or moved with.

**Why it waits.** Both carry what a publication withholds: revision history,
trashed notes, saved searches, source provenance with local paths, exact
source bundles and private metadata. The importer reads only
`publication_handoff`, and refuses search notebooks, provenance and source
bundles in it. A full archive is not a publication, so importing one must
never become a shortcut to a public site that skips Notrios's review.

**What it needs.**

- A mapping for each record kind into notesdb without losing anything:
  revisions, provenance (application data, as the Obsidian importer keeps its
  snapshots), source bundles (the exact source bytes, perhaps into
  `note_source_raw`, which holds a note's exact Joplin RAW bytes today), saved
  searches and trash.
- A separate import path whose output is marked as private library data.
- A guard that keeps that output from reaching `obsidian2site.py` without an
  explicit selection step.

**Depends on** multiple handoffs and merges, if a transfer is meant to add to
an existing library, and on packed publications, since backups at library
scale are where packs matter.
