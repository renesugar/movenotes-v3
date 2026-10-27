# Notrios publications

Import a Notrios publication into SQLite, and carry it through to a site.

## Import a Notrios publication into SQLite

[Notrios](https://github.com/renesugar/notrios) publishes a reviewed selection
of a library as a *publication handoff*: a loose archive-v2 directory holding
the selected notes, their notebooks, tags and attachments, and the links between
them. `notrios2sql.py` verifies one and imports it into a new database:

```
python3 -B notrios2sql.py \
  --input  ~/publication \
  --output ~/notes_sqlite \
  --expected-selection-sha256 <the reviewed plan's manifest_sha256>
```

[Publishing a Notrios library](#publishing-a-notrios-library) below shows how
to produce the publication and carry it through to a site. movenotes is tested
against Notrios `v1.0.0`.

The whole archive is verified before anything is written: every object's size
and SHA-256, the manifest's digests, and the records and how they refer to each
other. The database is then built in a hidden staging directory beside
`--output` and renamed into place in one step, so `--output` either does not
exist or holds a complete import.

Notebooks keep their nesting, and each note gets its current revision's title,
dates and body, its tags, and its attachments with their exact bytes. IDs are
derived from the publication's own identities, so the same publication always
produces the same IDs. A link to a note or attachment in the publication
becomes a Joplin `:/id` link, keeping its label and any title byte for byte,
and an HTML `<img>` whose `src` names an attachment maps the same way. Every
other destination is left exactly as written. The whole import is refused if a
link names an internal target the importer cannot account for, such as one not
in the publication or one the producer's link records do not cover. A link
like that would lead nowhere on the site, or name a note that was withheld.

`--expected-selection-sha256` is the digest of the plan that was reviewed, and
a publication with any other selection is refused. It is optional, but without
it nothing ties the import to the review.

- `--output` must not exist yet, and its parent must. There is no merge and no
  overwrite. Rerunning into a completed import of the same publication verifies
  it and reports `unchanged` without writing. A different publication there is
  refused.
- Only loose `publication_handoff` archives are read. A packed archive (one
  exported with `--pack`), another export target, and an archive carrying
  source bundles or provenance are refused.
- Linux only: the final rename needs `renameat2(RENAME_NOREPLACE)`, and the
  filesystem must support `fsync`.
- `sql2obsidian.py` and `sql2joplin.py` open the database read-only, so
  exporting it does not change it and a rerun still reports `unchanged`.

On success stdout is one JSON line: `status` (`created` or `unchanged`),
`commit_sha256`, `selection_manifest_sha256`, `row_count` and
`resource_count`. It holds no paths or note content. Progress phases and
errors go to stderr. `--version` prints the release. The exit status is 0 on success, 1 when the import is
refused or fails, and 2 for a usage error.

An error or Ctrl-C removes everything the run created. A run that is killed
outright, or a power loss, can leave `.movenotes-notrios-lock-…`,
`.movenotes-notrios-work-…` and `.movenotes-notrios-stage-…` directories beside
`--output`, each with an `owner.json`. The next run refuses while the lock is
there, and prints its path. Make sure no import is still running, then move
those exact directories aside and rerun. The importer never removes another
run's lock by itself.

## Publishing a Notrios library

Publish notes from a Notrios `v1.0.0` library, import them, export a vault
and generate the site. The `notriosctl` commands below use the default library.
Add `--db` and `--asset-store` to use another one.

```bash
# 1. Find the notebooks to publish. A notebook brings its subnotebooks with it.
notriosctl notebooks list

# 2. Save a publication profile, then plan it and review the plan.
notriosctl publish profile save \
  --profiles ~/profiles.json --name public \
  --target publication_handoff --notebooks nb_public \
  --link-action plain_text
notriosctl publish plan --profiles ~/profiles.json --profile public > ~/plan.json
selection=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["plan"]["manifest_sha256"])' < ~/plan.json)

# 3. Publish exactly the reviewed plan, and verify the result.
notriosctl publish run --profiles ~/profiles.json --profile public \
  --reviewed-plan "$selection" ~/publication
notriosctl verify archive-v2 ~/publication

# 4. Import it, export a vault and build the site.
python3 -B notrios2sql.py --input ~/publication --output ~/notes_sqlite \
  --expected-selection-sha256 "$selection"
mkdir -p ~/public_vault
python3 -B sql2obsidian.py --input ~/notes_sqlite --output ~/public_vault \
  --include-notrios-receipt --no-simplify-urls
python3 -B obsidian2site.py --input ~/public_vault --output ~/public_site \
  --title "Public notes" --ledger-theme ~/projects/hugo-theme-ledger \
  --search-backend bluge --include-notrios-receipt --build
```

`~/plan.json` lists every note the publication will hold, with counts that
include `selected_documents`, `private_links` and `broken_links`. Notrios
leaves out notes tagged `private`, `draft` or `confidential`, read-only
notebooks and the Trash by default. Read the plan before step 3:
`--reviewed-plan` publishes that plan or nothing, and step 4 refuses any other
selection. Serve the site as the
[static-site guide](static-site.md#3-recommended-build-and-run-the-bluge-server) describes.

The `plain_text` link action replaces a link to an unpublished note with its
label. At `v1.0.0` it does the same to every link Notrios could not resolve
(`file:`, `tel:`, `data:` and relative destinations), so those never reach
movenotes. `--no-simplify-urls` keeps the remaining links as they were
published. `--include-notrios-receipt` copies the import's receipt to
`.movenotes/notrios-receipt.json` in the vault. The receipt identifies the
publication: its commit and selection digests, its snapshot and library IDs,
and the reader and mapper versions, with no paths, times or note content. On the site it is published
at `movenotes/notrios-receipt.json`, where anyone can download it, so leave
the flag off `obsidian2site.py` if you don't want that.

An `<img>` written in HTML imports correctly, but the exported vault still
points its `src` at `:/id`, so Obsidian and the site do not show the image.

**Over 100,000 notes.** At `v1.0.0`, `publish plan` and `publish run` select at
most 100,000 notes, and a profile holds at most 100 notebook and tag
selectors. For a larger publication, export the handoff directly and take the
selection digest from its report:

```bash
notriosctl export archive-v2 --target publication_handoff \
  --notebooks nb_a,nb_b --max-documents 1000000 ~/publication > ~/export.json
selection=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["selection_manifest_sha256"])' < ~/export.json)
```

Step 3's `verify archive-v2` and step 4 are unchanged. The export has no profile and no
plan to review. Check the report's `selected_documents`, `excluded_documents`,
`rewritten_links` and `skipped_rewrites` before importing. Notes that belong
to no notebook cannot be selected this way. Selecting them by ID hits the
8,192-byte limit on a Notrios job's parameters long before 100,000 notes.

Measured end to end on three real libraries (one Linux workstation, internal
disk, Hugo `v0.164.0`, Go 1.27.0), with every note published. Each cell is
wall-clock time and peak memory for that step alone:

| Step | Joplin, 103,349 notes | Recipes from RAW, 382,206 | Recipes from a vault, 382,206 |
|---|---:|---:|---:|
| `notriosctl export archive-v2` | 12 min, 110 MiB | 1 h 45 min, 303 MiB | 1 h 48 min, 332 MiB |
| `notrios2sql.py` (verification included) | 20 min, 69 MiB | 1 h 53 min, 67 MiB | 1 h 1 min, 68 MiB |
| `sql2obsidian.py` | 10 min, 173 MiB | 1 h 5 min, 845 MiB | 35 min, 466 MiB |
| `obsidian2site.py` (generation) | 17 min, 473 MiB | 1 h 36 min, 1.4 GiB | 1 h 26 min, 1.3 GiB |
| Hugo `--gc --minify` | 5 min, 5.2 GiB | 31 min, 14.7 GiB | 17 min, 13.6 GiB |
| Bluge index | 3 min, 310 MiB | 15 min, 414 MiB | 11 min, 404 MiB |

The importer's peak memory stayed between 46 and 69 MiB from 1,000 notes to
382,206: bounded, not proportional to the library. Hugo needs the most
memory of any step, so it decides the machine a large library needs. The
Joplin library's 757 attachments arrived byte for byte, and both recipe
libraries were compared note by note against movenotes' own imports of the
same sources. Every step and its measurements are in
[`plans/v3.37/010-corpus-trials.md`](../plans/v3.37/010-corpus-trials.md).
