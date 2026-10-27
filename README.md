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
| `tests/`          | The unittest suite; each module is described in [docs/testing.md](docs/testing.md) |
| `scripts/`        | Development tools: corpus trial and comparison harnesses (`notrios_7c_trials.py`, `notrios_c7c.py`), the plan ledger renderer, the link and example checkers |

# Setup

The scripts require Python 3.9 or later and use only the standard library —
no packages to install.

# Usage

Each workflow has its own page in [`docs/`](docs/index.md), with every option and
guarantee. The commands below are the shortest path through each one.

**Joplin RAW → SQLite → Joplin RAW** ([docs/joplin.md](docs/joplin.md)):

```
mkdir -p ~/notes_sqlite

python3 -B joplin2sql.py \
  --input  ~/joplin_raw_export \
  --output ~/notes_sqlite
```

```
mkdir -p ~/joplin_raw_import

python3 -B sql2joplin.py \
  --input  ~/notes_sqlite \
  --output ~/joplin_raw_import
```

**Twitter/X archive → SQLite** ([docs/twitter.md](docs/twitter.md)):

```
mkdir -p ~/notes_sqlite

python3 -B twitterx2sql.py \
  --input  ~/twitter-archive \
  --output ~/notes_sqlite \
  --notebook Twitter \
  --timezone America/Vancouver
```

**Obsidian vault ↔ SQLite**, including the lossless round trips
([docs/obsidian.md](docs/obsidian.md)):

```
mkdir -p ~/notes_sqlite

python3 -B obsidian2sql.py \
  --input  ~/obsidian_vault \
  --output ~/notes_sqlite
```

```
mkdir -p ~/obsidian_vault

python3 -B sql2obsidian.py \
  --input  ~/notes_sqlite \
  --output ~/obsidian_vault
```

**Notrios publication → SQLite**, and on to a site
([docs/notrios.md](docs/notrios.md)):

```
python3 -B notrios2sql.py \
  --input  ~/publication \
  --output ~/notes_sqlite \
  --expected-selection-sha256 <the reviewed plan's manifest_sha256>
```

**Embedded and remote images → local resources**
([docs/images.md](docs/images.md)):

```
python3 -B images2resources.py \
  --input  ~/notes_sqlite \
  --config ~/notes_sqlite/movenotes-images.ini
```

**Obsidian vault → Hugo site with Bluge search**
([docs/static-site.md](docs/static-site.md); deployment in
[docs/deploy-vercel.md](docs/deploy-vercel.md) and
[docs/deploy-github-pages.md](docs/deploy-github-pages.md); smaller vaults with
Quartz in [docs/quartz.md](docs/quartz.md)):

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

# Testing

The suite uses only the standard library. How to run it, and what each module
covers, is in [docs/testing.md](docs/testing.md).

# Development plan

[`PLAN.md`](PLAN.md) is the plan being implemented now, and
[`ROADMAP.md`](ROADMAP.md) says what coming releases are meant to do, including
the features deferred so far. Finished plans are
archived under [`plans/`](plans/) by the version they shipped in; the first,
which refocused and modernized this project, is
[`plans/v3.34/000-refocus-plan.md`](plans/v3.34/000-refocus-plan.md).

# History

This project began as a larger toolkit for migrating notes from Apple Notes,
GMail, and Twitter into Joplin. It was later refocused around the Joplin RAW ↔
SQLite core, while retaining the archive-based Twitter/X importer and adding
Obsidian export, lossless source preservation, image localization, and
performance-oriented large-library processing. The current scripts require
only dependency-free Python 3.9+.

# License

MIT License — see `LICENSE.md`.
