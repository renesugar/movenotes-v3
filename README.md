# About

**movenotes** is a small set of utilities for importing and exporting
[Joplin](https://joplinapp.org) notes using an intermediate SQLite database.

* **Import:** Joplin RAW Directory → SQLite
* **Import:** Twitter/X archive → SQLite
* **Import:** Obsidian vault → SQLite
* **Import:** Notrios publication → SQLite
* **Export:** SQLite → Joplin RAW Directory
* **Export:** SQLite → Obsidian vault

The Obsidian vault export can be published as a scalable Hugo site with
`obsidian2site.py`, using the
[Ledger](https://github.com/renesugar/hugo-theme-ledger) theme. For archives with over 100,000 notes, the generated Go
server keeps the Bluge search index on the server instead of downloading browser
index chunks. Pagefind remains available as a fully static fallback:

* Joplin RAW Directory → SQLite → Obsidian vault → Hugo + Bluge/Pagefind
* Twitter/X archive → SQLite → Obsidian vault → Hugo + Bluge/Pagefind
* Notrios library → publication → SQLite → Obsidian vault → Hugo + Bluge/Pagefind

Quartz remains documented as an option for smaller vaults.

Multiple Joplin RAW directories can be imported into the same SQLite database
and then exported as a single Joplin source with multiple notebooks. This
makes it possible to merge several note collections into one.

A *Joplin RAW Directory* is the format produced by Joplin's
`File → Export all → RAW - Joplin Export Directory` command and accepted by
`File → Import → RAW - Joplin Export Directory`. It contains one `.md` file
per item (note, notebook, resource, tag, …) named by the item's 32-character
id, plus a `resources/` directory holding attachment files.

# Scripts

| Script            | Purpose                                                  |
|-------------------|----------------------------------------------------------|
| `joplin2sql.py`   | Import a Joplin RAW directory into a SQLite database     |
| `twitterx2sql.py` | Import a Twitter/X archive into a SQLite database        |
| `obsidian2sql.py` | Import an Obsidian vault into a SQLite database          |
| `notrios2sql.py`  | Verify a Notrios publication and import it into a new SQLite database |
| `sql2joplin.py`   | Export a SQLite database to a Joplin RAW directory       |
| `sql2obsidian.py` | Export a SQLite database to an Obsidian vault            |
| `obsidian2site.py` | Convert an Obsidian vault to a Hugo/Ledger site with Bluge and Pagefind search |
| `removedups.py`   | Remove duplicate notes from a database (useful after merging several sources) |
| `cleanres.py`     | Remove unused files from a resources directory           |
| `images2resources.py` | Convert embedded/remote Markdown images to local Joplin resources |
| `quarantinelinks.py` | Replace checked problem links from the image report with one local placeholder resource |
| `image_resources.py` | Shared Markdown, MIME, network, report, and resource helpers |
| `notesdb.py`      | Shared database code                                     |
| `common.py`       | Shared helper functions                                  |
| `constants.py`    | Shared constants                                         |
| `notrios_archive.py` | Notrios publication verification                      |
| `notrios_links.py` | Notrios link checking and projection to `:/id` links    |
| `notrios_mapping.py` | Notrios identity and database row mapping            |
| `notrios_receipt.py` | Notrios import receipt validation and copying         |
| `notrios_c7c.py`  | Development tool: compares a Notrios import with a movenotes import of the same source |
| `test_movenotes.py` | End-to-end verification suite (see Testing)            |
| `test_image_resources.py` | Image localization and quarantine regressions   |
| `test_obsidian2sql.py` | Obsidian import regressions                         |
| `test_obsidian2site.py` | Hugo/Bluge/Pagefind site generation regressions    |
| `test_notrios2sql.py` | Notrios verification, import, vault and site regressions |
| `test_notrios_7c.py` | Tests for the corpus trial harness in `scripts/`      |

# Setup

The scripts require Python 3.9 or later and use only the standard library —
no packages to install.

# Usage

## Import a Joplin RAW directory into SQLite

Export your notes from Joplin using
`File → Export all → RAW - Joplin Export Directory`, then:

```
mkdir -p ~/notes_sqlite

python3 -B joplin2sql.py \
  --input  ~/joplin_raw_export \
  --output ~/notes_sqlite
```

This creates `~/notes_sqlite/notesdb.sqlite` and copies attachments into
`~/notes_sqlite/resources`. For every Joplin item, SQLite stores both parsed
columns and the exact original RAW bytes plus an ordered property list. Unknown
or newly introduced Joplin properties therefore survive without a schema
update. Resource and item-ID collisions with different data are rejected
instead of silently overwriting one source.

Large imports use batched inserts, persisted SHA-256 source fingerprints, and
periodic progress output. Full re-imports use one sequential fingerprint
preload, while small merges query only the IDs present in each input batch via
the `joplin_id` index. They do not issue one database query per input file,
preload a million-row database for a ten-note merge, or retain every RAW item
in memory. Parent notebook files are parsed at most once, and ordinary Joplin
RAW filenames avoid a database-wide folder-title update. Useful tuning options
are `--batch-size N`, `--progress-every N`, and `--verbose`; the defaults are
chosen for ordinary local SQLite imports and preserve transactional safety.

To merge several sources, run `joplin2sql.py` again with a different
`--input` and the same `--output`; notes accumulate in the same database.
After merging, `removedups.py` can remove duplicate notes:

```
python3 -B removedups.py --input ~/notes_sqlite
```

`removedups.py` and `cleanres.py` are intentionally destructive cleanup tools.
Do not run them when the goal is a complete, byte-for-byte preservation of the
source export.

## Import a Twitter/X archive into SQLite

Download your archive from X (`Settings → Your account → Download an archive
of your data`), extract the ZIP, then:

```
python3 -B twitterx2sql.py \
  --input  ~/twitter-archive \
  --output ~/notes_sqlite \
  --notebook Twitter \
  --timezone America/Vancouver
```

No Twitter/X API access is used — only the archive files are read
(`data/tweets*.js`, `data/account.js`, and the media folder; legacy
`tweet*.js` archives also work). Tweets become notes in the notebook named
by `--notebook` (default `Twitter`); the notebook is created if missing and
reused if it already exists, so archives can be merged into a database
alongside Joplin notebooks. Each note keeps the tweet's timestamps and a
`source_url` pointing at the original post; photos and other media become
attachments embedded in the note. Reply context, a linked date/time in the
selected local zone, retweet count, and favorite count are included in the
Markdown body. `--timezone` accepts an IANA name; when omitted, the machine's
local zone is used.

`t.co` short links are expanded in two layers: first offline, from the URL
entities stored in the archive itself (this covers almost all links); any
`t.co` link still left is resolved over the network with a HEAD request
that follows redirects. Relative redirect targets such as `/user/status/id`
and scheme-relative targets such as `//x.com/user/status/id` are resolved
against the current URL before the next request. Results are cached in
`tco_cache.json` in the output directory so re-runs don't re-fetch. Invalid
relative values written by an older cache are ignored and fetched again.
Pass `--no-expand-tco` to skip the network step.

Re-importing the same archive creates duplicate notes with identical
content (attachment ids are derived from file content, so embeds are
reproducible); run `removedups.py` afterwards to remove them.


## Import an Obsidian vault into SQLite

```
mkdir -p ~/notes_sqlite

python3 -B obsidian2sql.py \
  --input  ~/obsidian_vault \
  --output ~/notes_sqlite
```

The importer handles two vault kinds:

1. A vault produced by `sql2obsidian.py` contains
   `.movenotes/manifest.json` and `.movenotes/joplin-raw/`. The importer uses
   that bundle as the authoritative Joplin source, preserving auxiliary item
   types, unknown properties, original RAW bytes, and resources. The visible
   Obsidian paths and bytes are also recorded in SQLite.
2. A native Obsidian vault has no Joplin preservation bundle. Markdown notes,
   nested folders, tags, attachments, and other vault files are converted to
   deterministic Joplin-compatible rows. Exact note bytes, arbitrary YAML
   frontmatter, original paths, and non-Markdown file bytes are retained.

Native Obsidian snapshots are compressed into a namespaced value in Joplin's
`application_data` property. This lets the snapshot survive
SQLite → Joplin RAW → SQLite. No third-party YAML library is required: the
converter reads only mapped fields such as `title`, `tags`, `created`,
`updated`, and movenotes' structured `joplin-properties`; the exact original
frontmatter remains authoritative for restoration.

Large vaults use deterministic IDs, batched inserts, indexed collision checks,
one-pass directory discovery, and periodic progress. Options include
`--batch-size`, `--progress-every`, and `--verbose`.

### A damaged preservation bundle

If the vault has a `.movenotes` preservation bundle that cannot be imported,
`obsidian2sql.py` refuses it before it touches the output, rather than quietly
importing the vault as a native one and dropping what the bundle preserves. It
refuses a bundle in any of these cases:

- `manifest.json` is not valid JSON. The error gives the line, column and byte,
  and says so when the file ends mid-document, which is what an interrupted
  export leaves.
- `manifest.json` is not a preservation manifest.
- `manifest.json` is a version this release does not read.
- `joplin-raw/` or `export.json` is present with no manifest, which means an
  export that did not finish.

The error says that nothing was imported and lists the next steps as complete
commands, built from the command that failed. The steps are:

1. Restore `manifest.json` from a backup and rerun the same command. For a
   newer manifest version, update movenotes first.
2. Import the Joplin RAW copy with `joplin2sql.py`. This is lossless for the
   export but leaves out Obsidian edits made since.
3. Rerun with `--ignore-preservation` to import the vault as plain Obsidian
   notes. This keeps the edits but drops the Joplin-only items and properties.
4. Export the source library again into a new directory and import that.

For step 4 the directory is a suggestion, labelled as one. The source library
and the export's options come from the bundle's `export.json`. Vaults
exported before it existed get a named placeholder instead, with a line saying
what to put there.

`--ignore-preservation` also imports a vault with a valid bundle as a native
vault.

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
errors go to stderr. The exit status is 0 on success, 1 when the import is
refused or fails, and 2 for a usage error.

An error or Ctrl-C removes everything the run created. A run that is killed
outright, or a power loss, can leave `.movenotes-notrios-lock-…`,
`.movenotes-notrios-work-…` and `.movenotes-notrios-stage-…` directories beside
`--output`, each with an `owner.json`. The next run refuses while the lock is
there, and prints its path. Make sure no import is still running, then move
those exact directories aside and rerun. The importer never removes another
run's lock by itself.

## Export SQLite to a Joplin RAW directory

```
mkdir -p ~/joplin_raw_import

python3 -B sql2joplin.py \
  --input  ~/notes_sqlite \
  --output ~/joplin_raw_import
```

Then in Joplin use `File → Import → RAW - Joplin Export Directory` and select
`~/joplin_raw_import`.

Imported Joplin items are written byte-for-byte by default, including
unknown properties, property order, whitespace, line endings, body text and
URL syntax. Attachment files are also copied byte-for-byte.

URL-only links can still be simplified as an explicit, lossy transformation:

```
python3 -B sql2joplin.py \
  --simplify-urls \
  --input  ~/notes_sqlite \
  --output ~/joplin_raw_import
```

This changes `[https://x](https://x)` and `<https://x>` to bare URLs while
leaving titled links, images, resource links and code unchanged.

## Clean unused resources

Removes files from a `resources/` directory that are not referenced by any
note:

```
python3 -B cleanres.py --input ~/notes_sqlite
```

## Localize embedded and remote images

`images2resources.py` edits Markdown note bodies in the SQLite database before
export. It converts inline base64 `data:image/...;base64,...` images and
HTTP(S) Markdown image links into Joplin resource links (`![alt](:/id)`), saves
the validated image bytes in the SQLite directory's `resources/` folder, and
adds resource rows to the database. The existing exporters then produce local
Joplin resources or Obsidian attachments automatically.

```
python3 -B images2resources.py \
  --input  ~/notes_sqlite \
  --config ~/notes_sqlite/movenotes-images.ini
```

The script remains dependency-free. It periodically reports
`processed X of Y note(s)` (the interval is controlled by
`--progress-every`). Remote images are fetched concurrently
with the standard library. Each URL receives a HEAD request first; redirects
are inspected hop-by-hop, then a bounded GET is made. The declared MIME type is
checked against the URL/original response on redirects and against the actual
file signature after download. Non-image responses, MIME changes, malformed
base64, oversize images, network errors, private-network destinations, and
stop-listed domains are left unchanged.

The default configuration path is
`<input>/movenotes-images.ini`; it is created automatically. See
`movenotes-images.example.ini` for all settings. `stop_domains` accepts comma-
or whitespace-separated domains and also blocks subdomains. SVG conversion is
disabled by default because SVG may contain active content. Private, loopback,
link-local, reserved, and other non-public addresses are also blocked by
default; only enable `allow_private_networks` for a trusted local service.

A Markdown report is written to
`<input>/images2resources-report.md` by default. It has separate sections for
links that could not be converted, links intentionally not converted, and
malformed embedded images. Every issue includes the note title, source Markdown
filename/item ID, line number, a preview, and a machine-readable metadata
comment.

To quarantine selected failures, edit the report and change their checkboxes to
`[x]`, then run:

```
python3 -B quarantinelinks.py \
  --input  ~/notes_sqlite \
  --report ~/notes_sqlite/images2resources-report.md \
  --config ~/notes_sqlite/movenotes-images.ini
```

Only checked, exact occurrences are replaced. The replacement is stored as a
normal local resource so both exporters handle it. Pass `--replacement-image`
to use a custom image; otherwise a built-in “Image removed” SVG is created.
The resource ID, local file path, and MIME type are written back to the
configuration and reused on later runs rather than adding duplicate placeholders. The managed
comment and all three values are rewritten together when any value is missing.
Set `quarantine_domains` in the `[quarantine]` section to replace every remote
Markdown image from those domains (and their subdomains); in that mode
`--report` is optional.

Existing local links, Joplin `:/resource` links, Obsidian embeds, and image-like
text inside fenced or inline code are not changed or reported.

## Export SQLite to an Obsidian vault

```
mkdir -p ~/obsidian_vault

python3 -B sql2obsidian.py \
  --input  ~/notes_sqlite \
  --output ~/obsidian_vault
```

Open `~/obsidian_vault` in Obsidian with `Open folder as vault`.

To export only a subset of notebooks — for example, to publish public notes
as a website with Quartz while keeping private notebooks out of the vault
entirely — pass `--notebooks` with comma-separated notebook titles (the
flag may also be repeated):

```
python3 -B sql2obsidian.py \
  --notebooks "Blog,Recipes" \
  --input  ~/notes_sqlite \
  --output ~/public_vault
```

Each named notebook and all its subnotebooks are exported; each selected
notebook becomes a top-level vault directory, so a nested notebook's parent
names are not exposed. Only attachments and preservation records belonging to
the selected subset are copied. A name that doesn't match any notebook is an
error, so a typo can't silently publish the wrong notes.

Notebooks become vault subdirectories (nesting preserved) and notes become
`Title.md` files. Obsidian identifies notes by file name rather than by the
unique ids Joplin uses, so titles are sanitized for the filesystem and
duplicate titles within a folder are deduplicated (`Title.md`,
`Title 2.md`, ...). File-name limits are enforced in UTF-8 bytes, and an
`ENAMETOOLONG` write is retried with a deterministic shortened name instead of
aborting a large export. Attachments are copied to an `attachments` folder under
their human-readable names; Joplin resource links are rewritten to
wiki-style embeds (`![[photo.png]]`) for images and relative markdown links
for other files. Each note gets YAML front matter with Obsidian-friendly
`title`, `created`, `updated`, `source-url`, and `tags` properties. Every source
property is also retained in legacy flat `joplin-*` fields and in a structured
`joplin` object. The exact ordered property list, including duplicate keys, is
stored as the directly parseable `joplin-properties` array; the older
`joplin-properties-json` string remains for compatibility. These structured
values are convenient to read through the Obsidian Local REST API (disable
front matter with `--no-frontmatter`).

The vault also contains `.movenotes/joplin-raw/`, a lossless Joplin RAW copy of
all exported items and raw resource files, plus `.movenotes/manifest.json`
with Joplin-to-Obsidian path mappings and SHA-256 checksums. This preservation
bundle keeps non-note items, ignored properties and the original Markdown body
available even though the visible Obsidian note is renamed, has front matter,
and has rewritten links. Pass `--no-preserve-joplin` only when this recovery
copy is not wanted.

An export removes any previous bundle before it writes a note, so a re-export
that stops part way never leaves an old bundle describing notes it no longer
matches. It then writes `.movenotes/export.json`, recording the source library
and the options that shape the vault, so that `obsidian2sql.py` can print the
command to export it again. The path is recorded without the user's name:

- Under the home directory it is written as `~/...`.
- Elsewhere, each path segment equal to the user name is written as `$USER`, as
  in `/run/media/$USER/HD2/library`.

Both are expanded for whoever reads the record. The manifest is written last,
to a temporary file that is renamed into place, so an interrupted export leaves
no manifest rather than a truncated one. URL-only links in visible Obsidian notes are still
simplified by default; use `--no-simplify-urls` to retain their original syntax.


# Lossless round-trip workflows

## Joplin → Obsidian → Joplin

```
python3 -B joplin2sql.py   --input ~/joplin_raw --output ~/notes_sqlite
python3 -B sql2obsidian.py --input ~/notes_sqlite --output ~/vault
python3 -B obsidian2sql.py --input ~/vault --output ~/notes_sqlite_2
python3 -B sql2joplin.py   --input ~/notes_sqlite_2 --output ~/joplin_raw_2
```

`sql2obsidian.py` writes a `.movenotes/joplin-raw/` recovery copy and a
manifest containing note paths, visible-note SHA-256 values, and attachment
mappings. `obsidian2sql.py` prefers that recovery copy, so an unmodified vault
returns to byte-identical Joplin RAW items and resources. If a visible note was
edited in a current-format vault, its exact Obsidian snapshot is carried in
`application_data` while the Joplin body receives the edited Markdown.

## Obsidian → Joplin → Obsidian

```
python3 -B obsidian2sql.py --input ~/vault --output ~/notes_sqlite
python3 -B sql2joplin.py   --input ~/notes_sqlite --output ~/joplin_raw
python3 -B joplin2sql.py   --input ~/joplin_raw --output ~/notes_sqlite_2
python3 -B sql2obsidian.py --input ~/notes_sqlite_2 --output ~/vault_2
```

For native vaults, exact Markdown bytes and original paths are stored both in
SQLite and in compressed movenotes metadata inside Joplin `application_data`.
Non-Markdown vault files, including attachment and `.obsidian` files, are
represented as resources with their original paths. When the generated Joplin
body is unchanged, `sql2obsidian.py` restores the original note and file bytes
exactly. Empty vault directories are represented by path-carrying folder rows and are
recreated on export.

If notes are intentionally edited in Joplin, the exporter falls back to a
normal generated Obsidian note rather than overwriting the edit with an older
snapshot.

# Publishing a large vault with Hugo, Ledger, and Bluge

`obsidian2site.py` creates a Hugo project using the
[Ledger](https://github.com/renesugar/hugo-theme-ledger) theme, which is built
for archives of 100,000+ notes: no note is ever listed in the navigation, every
surface that could grow with the archive is bounded, and search comes from a
swappable backend.

```bash
python3 -B obsidian2site.py \
  --input ~/twitter_vault \
  --output ~/twitter_site \
  --title "Twitter Archive" \
  --ledger-theme ~/projects/hugo-theme-ledger \
  --search-backend bluge \
  --build

cd ~/twitter_site/server
./movenotes-site-server \
  -site ../public \
  -source search-source.jsonl \
  -index bluge-index \
  -listen 127.0.0.1:8080
```

Open `http://127.0.0.1:8080/`. A `bluge` build ships no browser search index at
all; the search page calls the server's `/api/health` and `/api/search`, and the
terminal logs every request with its query, total and duration. The server builds
its Bluge index on first run and rebuilds when `search-source.jsonl` changes.

Search accepts ordinary keywords, quoted phrases, `category:`, repeatable
`tag:name`, and `since:`/`until:` date bounds (`since:` inclusive, `until:`
exclusive). The grammar is parsed once in the browser, so every backend answers
the same syntax — except that Pagefind has no date filter and says so rather than
ignoring the clause. Results come back newest first for every query; an empty
box means every note.

**A note's links are searchable by their destination**, whether the URL is
written out or hidden behind a label. A URL is split like a sentence — the host
stays whole, the path becomes words — so the whole URL, a prefix of it, or its
components in any order all find the notes that link it, and the subdomain is
optional: `kqed.org` finds `www.kqed.org` and `blogs.kqed.org` alike.

Three ways in: search, the sidebar's categories and tags, and **Browse Tags**.
The two tag populations are stored differently, because they differ in size by
orders of magnitude: the written tags become a bounded Hugo taxonomy with real
archive pages, while every unique content word lives in a disk-backed posting
index that Browse Tags reads. `tag:` searches the written ones, so it returns the
same count as that tag's archive page; a generated word is found by searching for
the word.

Every generated note gets one deterministic lowercase URL, reused in Hugo
frontmatter, exact-tag metadata, Pagefind output and Bluge records. This prevents
results from requesting source-vault paths such as
`/notes/Twitter/File%20Name.html` when Hugo emitted
`/notes/twitter/file-name.html`.

Bluge does not ingest Pagefind's private browser index: `obsidian2site.py` writes
a neutral JSONL document stream for it instead. Pagefind remains available for
static hosting, or as an automatic fallback:

```bash
npx -y pagefind --site ~/twitter_site/public
python3 -m http.server 8080 --directory ~/twitter_site/public
```

`--search-backend both` (the default) builds both indexes and lets the theme's
`auto` adapter choose per page load — Bluge when the server answers, Pagefind
when it does not — so one build works served locally and as static files. With
`--build`, the generator then checks the built HTML and fails if the site does
not configure the backend that was asked for.

The converter also normalizes Hugo dates, copies attachments, repairs malformed
external URL destinations while retaining their visible source text, links valid
plain `@username` mentions to X, and writes a disk-backed exact tag index whose
counts match its result lists.

Hugo passes a note's raw HTML through to the page, but a few tags written in
prose are shown as text instead: `<script>`, `<style>`, `<title>`,
`<textarea>`, `<noscript>`, `<noembed>`, `<noframes>`, `<xmp>` and
`<plaintext>`. Left alone, the browser would run or swallow whatever follows
them, and `hugo --minify` fails on a `<script>` that is not JavaScript. An
SVG's own `<title>` and `<style>` elements are kept. Code spans, code blocks
and indented code are not touched, and the search text is unchanged. The run
prints how many tags it showed as text.

Deploying the result: [`DEPLOY_VERCEL.md`](DEPLOY_VERCEL.md) for server-side
Bluge search, [`DEPLOY_GITHUB_PAGES.md`](DEPLOY_GITHUB_PAGES.md) for a static
Pagefind site.

See [`STATIC_SITE.md`](STATIC_SITE.md) for complete build, query, local serving,
deployment-prefix, stop-word, embed, Pagefind fallback, and Quartz instructions.

# Publishing a Notrios library

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
selection. Serve the site as in the
[previous section](#publishing-a-large-vault-with-hugo-ledger-and-bluge).

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
[`NOTRIOS_CORPUS_TRIALS.md`](NOTRIOS_CORPUS_TRIALS.md).

# Publishing with Quartz

[Quartz](https://quartz.jzhao.xyz/) is a fast, batteries-included
static-site generator that transforms Markdown content into fully
functional websites — thousands of people use it to publish personal
notes and digital gardens. The vaults produced by `sql2obsidian.py` work
as Quartz content: Quartz understands Obsidian-flavored markdown,
including the wiki-style image embeds (`![[photo.png]]`) this project
writes, and reads the `title` and `tags` fields from the exported front
matter (its created-modified-date plugin can also be configured to take
dates from front matter, where this project writes `created` and
`updated`).

Both pipelines end in the same place:

* **Joplin:** Joplin RAW Directory → SQLite → Obsidian vault → Quartz
* **Twitter/X:** Twitter/X archive → SQLite → Obsidian vault → Quartz

## 1. Export a publishable vault

Use `--notebooks` to export only the notebooks you want on the web —
private notebooks are never written into the vault, so they cannot end up
on the site by accident:

```
python3 -B joplin2sql.py --input ~/joplin_raw_export --output ~/notes_sqlite
python3 -B twitterx2sql.py --input ~/twitter-archive --output ~/notes_sqlite --notebook Twitter

python3 -B sql2obsidian.py \
  --notebooks "Blog,Twitter" \
  --input  ~/notes_sqlite \
  --output ~/public_vault
```

## 2. Set up Quartz

Quartz 5 requires Node v22+ and npm v10.9.2+:

```
git clone https://github.com/jackyzha0/quartz.git
cd quartz
npm install --allow-git=all
npx quartz create
npx quartz plugin add github:saberzero1/quartz-themes --subdir plugin
npx quartz plugin install --from-config
NODE_OPTIONS="--max-old-space-size=12288" npx quartz build --serve --concurrency=2
```

`npx quartz create` asks how to initialize the `content/` folder; choose
to import an existing folder and point it at `~/public_vault` (or copy
the vault's contents into `content/` yourself afterwards — re-run
`sql2obsidian.py` with `--output <quartz>/content` on later updates).

Quartz uses `content/index.md` as the site's home page. The export does
not create one, so add it by hand, for example:

```
---
title: Home
---
Welcome! Start with [[Blog]] or browse the tags.
```

## 3. Preview and deploy

```
npx quartz build --serve
```

serves the site at `http://localhost:8080`. When it looks right, publish
with `npx quartz sync` after setting up a GitHub repository; Quartz's
[hosting guide](https://quartz.jzhao.xyz/hosting) covers GitHub Pages,
Cloudflare Pages, Netlify, and Vercel.

Tips:

* To exclude an individual note without moving it out of a published
  notebook, add `draft: true` to its front matter in the vault before
  building — Quartz filters drafts out of the site.
* Re-exporting after notes change is cheap: unchanged attachments are
  skipped and note files are rewritten in place. Exports never delete
  files, though, so after removing or renaming notes it is safest to
  export into an empty directory and replace `content/`.

# Testing

`sample/` contains a small two-source Joplin RAW dataset covering nested
notebooks, duplicate titles, titles needing sanitization, image and PDF
attachments, tags, a duplicate note, an orphan resource, and every link
variety. The verification suite imports it, exercises every script, and
checks byte-for-byte Joplin round trips, unknown/future and duplicate
properties, CRLF input, property whitespace, collision rejection, schema
migration, structured Obsidian property mapping, the embedded lossless
preservation bundle, and performance regressions for indexed/batched
source-fingerprint lookups, dependency traversal, filename deduplication,
attachment-directory indexing, Twitter media fallback lookup, and bulk
image-link replacement:

```
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_movenotes.py test_image_resources.py \
  test_obsidian2sql.py test_obsidian2site.py test_notrios2sql.py test_notrios_7c.py
```

The tests run the scripts as subprocesses, so both the variable and `-B` are
needed: `-B` covers only the test process, and a `__pycache__` left by an
earlier run can shadow the script under test.

`test_notrios2sql.py` checks the Notrios importer against committed synthetic
publications under `testdata/notrios/`, made with real Notrios commands:
verification and its refusals, the import and its reruns, links, attachments,
and the vault and site built from the result. It needs no Notrios binary.
`test_notrios_7c.py` tests the corpus trial harness in `scripts/`.

The image-resource suite uses a local HTTP server to verify successful
retrieval, HEAD fallback, redirect MIME changes, byte-signature mismatches,
stop lists, malformed data URIs, deterministic deduplication, quarantine
selection, replacement reuse, and both export paths. The six modules contain
318 tests and use only the standard library.
On environments where the combined
notebook-filtering class stalls during subprocess cleanup, each test method can
be run independently; the conversion commands themselves complete normally.

`PERFORMANCE_REVIEW.md` records the reviewed complexity changes and a local
synthetic benchmark. Results depend on hardware, storage, item size, and the
state of the destination database; they are regression evidence rather than a
runtime guarantee.

# Schema references

The known queryable columns track the Joplin Data API property lists and item
type IDs. In particular, Joplin defines the note `order` property as numeric,
so `JOPLIN_COLUMNS["joplin_order"]` is declared as SQLite `REAL` and accepts
scientific notation and subnormal values such as `6e-323`. `joplin2sql._convert_known_value()` has an
explicit `REAL` conversion branch, so these values are parsed with `float()`
during import. The exact RAW bytes and ordered property JSON remain authoritative,
so fields absent from those lists are still preserved. Schema version 4 added
binary SHA-256 source fingerprints and query indexes. Schema version 5 adds
exact native-Obsidian path, body, frontmatter, and byte snapshots; supported
version 2 through 4 databases are migrated and fingerprinted in bounded batches
when opened. Obsidian output uses
ordinary Markdown files and YAML front matter compatible with the Local REST
API's note representation and frontmatter operations.

* Joplin Data API: https://joplinapp.org/help/api/references/rest_api/
* Obsidian Local REST API OpenAPI: https://github.com/coddingtonbear/obsidian-local-rest-api/blob/main/docs/openapi.yaml
* Obsidian Local REST API: https://github.com/coddingtonbear/obsidian-local-rest-api

# Development plan

`PLAN.md` records the step-by-step plan used to refocus and modernize this
project. All steps are complete.

# History

This project began as a larger toolkit for migrating notes from Apple Notes,
GMail, and Twitter into Joplin. It was later refocused around the Joplin RAW ↔
SQLite core, while retaining the archive-based Twitter/X importer and adding
Obsidian export, lossless source preservation, image localization, and
performance-oriented large-library processing. The current scripts require
only dependency-free Python 3.9+.

# License

MIT License — see `LICENSE.md`.

### PDF OCR metadata

Joplin PDF resource items can contain OCR text with embedded ASCII control
characters. Version 3.05 and later split RAW metadata only on CR/LF physical
line endings, so these characters remain part of `ocr_text` and do not cause a
false “cannot find Joplin property block” error.
