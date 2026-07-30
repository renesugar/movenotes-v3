# About

**movenotes** is a small set of utilities for importing and exporting
[Joplin](https://joplinapp.org) notes using an intermediate SQLite database.

* **Import:** Joplin RAW Directory → SQLite
* **Import:** Twitter/X archive → SQLite
* **Import:** Obsidian vault → SQLite
* **Export:** SQLite → Joplin RAW Directory
* **Export:** SQLite → Obsidian vault

The Obsidian vault export can be published as a scalable Hugo site with
`obsidian2site.py`, using the
[Ledger](https://github.com/renesugar/hugo-theme-ledger) theme. For archives with over 100,000 notes, the generated Go
server keeps the Bluge search index on the server instead of downloading browser
index chunks. Pagefind remains available as a fully static fallback:

* Joplin RAW Directory → SQLite → Obsidian vault → Hugo + Bluge/Pagefind
* Twitter/X archive → SQLite → Obsidian vault → Hugo + Bluge/Pagefind

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
| `test_movenotes.py` | End-to-end verification suite (see Testing)            |
| `test_obsidian2site.py` | Hugo/Bluge/Pagefind site generation regressions    |

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
copy is not wanted. URL-only links in visible Obsidian notes are still
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
index that Browse Tags reads. Both are searchable with `tag:`.

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

Deploying the result: [`DEPLOY_VERCEL.md`](DEPLOY_VERCEL.md) for server-side
Bluge search, [`DEPLOY_GITHUB_PAGES.md`](DEPLOY_GITHUB_PAGES.md) for a static
Pagefind site.

See [`STATIC_SITE.md`](STATIC_SITE.md) for complete build, query, local serving,
deployment-prefix, stop-word, embed, Pagefind fallback, and Quartz instructions.

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
python3 -m unittest -v test_movenotes.py test_image_resources.py test_obsidian2sql.py test_obsidian2site.py
```

The image-resource suite uses a local HTTP server to verify successful
retrieval, HEAD fallback, redirect MIME changes, byte-signature mismatches,
stop lists, malformed data URIs, deterministic deduplication, quarantine
selection, replacement reuse, and both export paths. The suites contain 81
tests, include the static-site regressions, and use only the standard library.
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
