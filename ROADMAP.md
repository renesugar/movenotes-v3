# Roadmap

What future releases of movenotes are meant to do. [`PLAN.md`](PLAN.md) says how
far the active plan has got. This file carries no slice status, and the rules
for keeping the two apart are in [`AGENTS.md`](AGENTS.md#plans-the-roadmap-and-the-archive).
Finished plans are in [`plans/`](plans/).

## 3.38 — the active plan

[`PLAN.md`](PLAN.md) holds the work for this release:

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
  resolved wiki links, which refuses today (W1).

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
its text before writing anything. R2's probe also found that `plain_text` at
`v1.0.0` replaces a wiki link with no alias to a withheld note with that
note's URI, `document://default/documents/<id>`, which for a library imported
from Obsidian spells the note's folder and title. movenotes refuses such a
publication, so it reaches no vault or site, but the handoff holds it.

**What it needs.** The change in Notrios' `publicationLinkNeedsRewrite` and
`replacementFor`, a release, a new producer pin here, and fixtures regenerated
from it. movenotes then reads both actions' handoffs the same way.

**Depends on** R2 (option (a)), decided by the user on 2026-10-27.

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
