# Plan: Refocus movenotes on Joplin import/export

## Goal

Convert the general-purpose migration toolkit (Apple Notes / GMail / Twitter →
Joplin) into a small, modern set of scripts focused on Joplin RAW directories:

* **Import:** Joplin RAW Directory → SQLite
* **Export:** SQLite → Joplin RAW Directory; SQLite → Obsidian vault
* Multiple Joplin RAW sources can be imported into one SQLite database and
  merged into a single Joplin export with multiple notebooks.

Final scripts:

| Script          | Purpose                                             |
|-----------------|-----------------------------------------------------|
| `joplin2sql.py` | Import a Joplin RAW directory into SQLite           |
| `sql2joplin.py` | Export SQLite to a Joplin RAW directory             |
| `sql2obsidian.py` | Export SQLite to an Obsidian vault (new)          |
| `removedups.py` | Remove duplicate notes after merging sources        |
| `cleanres.py`   | Remove unused files from a resources directory      |
| `notesdb.py`, `common.py`, `constants.py` | Shared library code       |

## Steps

Each step leaves the project in a working state so work can stop and resume
at any step boundary.

### Step 1 — Prune to a Joplin-only project  ✅ (this step)

* Delete scripts not needed for the Joplin workflow: `eml2mbox.py`,
  `eml2sql.py`, `gyb2eml.py`, `mbox2eml.py`, `sql2eml.py`, `icloud2sql.py`,
  `macapt2sql.py`, `twitterlikes2sql.py`, `twitterarchivelikes2sql.py`,
  `url2sql.py`, `expandurls.py`.
* Keep `cleanres.py` and `removedups.py` (useful for merged Joplin data).
* Rewrite `README.md` for the Joplin-only workflow.
* Trim `requirements.txt` to what the remaining scripts use.
* Shared modules (`common.py`, `notesdb.py`, `constants.py`) are left
  untouched in this step so everything keeps working; they are cleaned up in
  Steps 2–3.

### Step 2 — Modernize the Python  ✅

* Replaced `optparse` with `argparse`; `os.path` with `pathlib.Path`.
* f-strings; removed `== True` / `== False` comparisons; removed unused
  imports and dead code (`NotesColumns`, macapt/email/apple database
  functions, Twitter URL helpers).
* Replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)`.
* 4-space indentation, type hints, docstrings, `main() -> int` /
  `sys.exit(main())` entry points; snake_case helper names.
* **Removed all third-party dependencies** (mistune, html2txt,
  beautifulsoup4, requests). The text/html→markdown conversion and link
  rewriting in `sql2joplin.py` only ran for rows created by the removed
  Apple/email/Twitter importers; since `joplin2sql.py` is now the only
  importer, every row is markdown already. `sql2joplin.py` reports a clear
  error if it meets a legacy-format row (movenotes 1.0 handles those).
* Bug fixes found during the rewrite:
  * Both resource-copy loops joined filenames against the parent directory
    instead of the `resources` directory, so attachments were never
    actually copied. Fixed.
  * `sql2joplin.py` previously always emitted a default "Notes" notebook
    even when the database already had notebooks, producing a spurious
    empty notebook on import; it is now only created when the database
    contains no folders.
  * `cleanres.py` built SQL by string concatenation; now parameterized.
  * `removedups.py` now reports how many duplicates were removed.

### Step 3 — Remove Apple Notes / email leftovers from the Joplin path  ✅

* Dropped all `apple_*` and `email_*` columns; folders are first-class
  (`note_folder` holds the Joplin parent folder title).
* New SQLite schema v2 containing only `note_*` and `joplin_*` columns.
  Schema versioning now lives in `notesdb.py` (`DB_SCHEMA_VERSION = "2"`)
  with a new `open_database()` helper used by every script. Opening a v1
  database produces a clear error telling the user to re-import from the
  Joplin RAW source (databases are disposable interchange files, so there
  is no migration).
* Removed the `--email` option from all scripts and the `email_address`
  setting from the database; removed `check_email_address` and the
  attachment-picking helpers (`get_file_mime_type`,
  `get_resource_file_names`, `format_universally_unique_identifier`) from
  `common.py`, along with the orphaned `string_to_datetime`.
* `cleanres.py` now checks only markdown resource links, not the removed
  `apple_attachment_path` column.
* `common.get_resource_links()` now scans whole note text instead of
  whitespace-split words (the old approach missed resource links whose
  display filename contained spaces); it is kept for the Obsidian export
  in Step 6.
* Script versions bumped to 2.00.

### Step 4 — Simplify URL-only links in exported markdown  ✅

* `sql2joplin.py` now writes links whose display text is just the URL
  itself (`[https://x](https://x)` or `<https://x>`) as the bare URL;
  Joplin auto-links plain URLs and the markdown stays readable. On by
  default; `--no-simplify-urls` keeps the original link syntax.
* Left untouched: links with meaningful titles, image links
  (`![...](...)`), resource links (`[name](:/32-hex-id)`), and anything
  inside fenced code blocks or inline code spans. Only note bodies are
  transformed (never folders, resources, or tags).
* Implemented as `common.simplify_url_links()` so the Obsidian export
  (Step 6) can reuse it; covered by unit-style edge-case tests during
  development.

### Step 5 — Performance improvements  ✅

The original batching and single transaction were retained, then the remaining
large-library scaling paths were reviewed again in release 3.10.

* `joplin2sql.py` no longer performs one unindexed `joplin_id` query per input
  file. Schema v4 stores a compact SHA-256 of the exact RAW bytes and adds
  indexes for IDs, item types, parents, UUIDs, dates, and hashes. Existing
  fingerprints are loaded once; duplicate checks are expected O(1).
* In-run duplicate detection stores one 32-byte digest per item ID instead of
  retaining every complete RAW file. Exact RAW bytes remain in SQLite for
  lossless export.
* New databases defer secondary-index construction until after the bulk insert;
  existing v2/v3 databases are migrated and fingerprinted in bounded batches.
* Folder titles are populated with one indexed, set-based update after import,
  eliminating repeated parent-file parsing. Title extraction also avoids a
  second full-body split.
* Per-item output is replaced by periodic progress (`--progress-every`), with
  `--verbose` available when detailed logging is needed. Batch size is
  configurable with `--batch-size`.
* `cleanres.py` already collects referenced resource IDs in one pass, and
  `sql2joplin.py` streams rows. Resource copies continue to reject collisions
  and skip byte-identical destinations.
* Similar superlinear paths were removed elsewhere: filtered Obsidian
  preservation uses a pre-indexed dependency graph; duplicate filenames use
  forward counters; image replacements are applied in one pass; remote image
  futures and Twitter resource batches are bounded.

A local generated 5,000-item import improved from 11.07 seconds with the 3.05
importer to about 1.8–2.0 seconds with 3.10. A 10,000-item old-version run did
not finish within 180 seconds in that environment; 3.10 completed in 2.66
seconds. See `PERFORMANCE_REVIEW.md`; these figures are not runtime promises.

### Step 6 — New Obsidian vault export (`sql2obsidian.py`)  ✅

* Notebooks → vault subdirectories with nesting preserved (parent cycles
  and missing parents fall back to the vault root); notes → `Title.md`.
* Titles sanitized for the filesystem (Windows-illegal characters plus
  `# ^ [ ] |` which break wiki links; reserved device names; 100-char
  limit) and deduplicated case-insensitively per folder (`Title.md`,
  `Title 2.md`, ...). The `attachments` name is reserved at the vault root
  so a notebook cannot collide with it.
* Referenced resources copied to `attachments/` under their human-readable
  titles (deduplicated, change-aware copy); `(:/resourceid)` links
  rewritten to `![[file.png]]` wiki embeds for images and relative
  markdown links (correct `../` depth, percent-encoded) for other files.
  Links to unknown resource ids are left unchanged.
* YAML front matter (default on, `--no-frontmatter` to disable) preserves
  the Joplin id, created/updated timestamps, source URL, and tags —
  resolved from the tag and note_tag items in the database.
* The leading body line duplicating the note title is stripped, since in
  Obsidian the file name is the title. URL-only links are simplified as in
  `sql2joplin.py` (`--no-simplify-urls` to disable).
* Bug found during testing: `RESOURCE_LINK_RE` used a greedy `(.*)` with
  DOTALL, merging two resource links on one line into a single match. The
  display text is now `[^\]]*`, and the Joplin round trip was re-verified
  after the change.

### Step 7 — Round-trip verification and final docs  ✅

* Added `sample/` — a two-source Joplin RAW dataset (11 items, 3 resource
  files) covering nested notebooks, duplicate titles, titles needing
  sanitization, image and PDF attachments, tags/note_tags, a duplicate
  note body, an orphan resource, and every link variety.
* Added `test_movenotes.py`, an end-to-end unittest suite (15 tests,
  stdlib only) that drives the actual command-line scripts: merge import,
  removedups, cleanres, Joplin round trip (property-order-insensitive file
  comparison plus byte comparison of resources), URL simplification on and
  off, Obsidian vault structure/links/front matter/attachments, and
  schema v1 rejection.
* Final README pass: Testing section, script table, History updated.

## Status

All steps (1–13) complete. Run `python3 -m unittest -v test_movenotes.py test_image_resources.py` to verify the project.

### Step 8 — Twitter/X archive import (`twitterx2sql.py`)  ✅

* Parse the archive users download from X (Settings → "Download an archive
  of your data"), **without using the Twitter/X API**: `data/tweets*.js`
  (and legacy `tweet*.js`) files with the `window.YTD.<name>.partN = [...]`
  wrapper, the username from `data/account.js`, and media files from
  `data/tweets_media/` (legacy `data/tweet_media/`), named
  `{tweet_id}-{filename}`. Format verified against
  timhutton/twitter-archive-parser and doggy8088/x-archive-parser.
* Tweets are imported as Joplin-style note rows into a notebook named with
  `--notebook` (default "Twitter"); the notebook is created if missing and
  reused when it already exists, so several archives can be merged.
* t.co links are expanded, in two layers:
  1. offline, from each tweet's `entities.urls[].expanded_url` mapping —
     this covers almost all links and needs no network;
  2. any t.co link still left is resolved over the network by issuing a
     HEAD request and following redirect Location headers (stdlib
     `urllib`, no API), with results cached in `tco_cache.json` in the
     output directory so re-runs don't re-fetch. `--no-expand-tco`
     disables the network step.
* Tweet media become Joplin resource items copied into `resources/` and
  embedded with `![name](:/resource_id)` links; the corresponding t.co
  media URL is removed from the text. HTML entities (`&amp;` …) are
  unescaped.
* Each note gets a title derived from the tweet text (truncated preview;
  media-only tweets fall back to `Tweet <date>`), Joplin timestamps from
  `created_at`, and `source_url` pointing at the original post.
* The exporters' provenance check changes from
  `note_original_format == "joplin"` to "row has a `joplin_id`", since
  every importer now writes complete `joplin_*` columns; provenance stays
  accurate (`note_original_format` is `"twitter"` for tweets).
* Resource ids are derived from the media file's content (first 32 hex
  digits of its SHA-256), so re-importing the same archive produces
  byte-identical note bodies and `removedups.py` can remove the
  duplicates; resource rows are not duplicated across runs.
* Sample archive in `sample/twitter-archive/` and end-to-end tests
  (9 new tests): import counts, notebook reuse across imports, entity and
  network t.co expansion, HTML entity unescaping, media embedding with
  byte-identical attachment files, Joplin RAW re-parse of every exported
  item, Obsidian front matter carrying the tweet's source URL, and the
  redirect-following expander exercised against a local HTTP server
  (chain following, caching, graceful failure, disabled mode).

### Step 9 — Obsidian export notebook filtering for publishing  ✅

* `sql2obsidian.py --notebooks "A,B"` (comma-separated titles, flag
  repeatable, exact match) exports only the named notebooks and all their
  subnotebooks, so a vault can be built from public notebooks only and
  published with Quartz without exporting private notes.
* Selected notebooks are re-rooted to the vault root, so publishing a
  nested notebook does not expose its parent notebooks' names; relative
  attachment links adapt to the new depth.
* Only attachments referenced by exported notes are copied (verified:
  exporting one notebook copies only its own attachments).
* Unknown notebook names are an error listing the available notebooks, so
  a typo cannot silently publish (or omit) the wrong notes; the summary
  line reports how many notes were skipped.
* 5 new tests: re-rooting with link depth, subnotebook inclusion,
  referenced-only attachments, both flag forms, and the unknown-name
  error path.

### Step 10 — Quartz documentation and final pass  ✅

* README "Publishing with Quartz" section covering both pipelines
  (Joplin RAW → SQLite → Obsidian vault → Quartz; Twitter/X archive →
  SQLite → Obsidian vault → Quartz): exporting a publishable vault with
  `--notebooks`, Quartz 5 setup (verified against the current docs: Node
  v22+, `npx quartz create`, `npx quartz plugin install --from-config`),
  the `content/index.md` home page, local preview, `npx quartz sync`
  deployment, `draft: true` for excluding single notes, and the caveat
  that exports never delete stale files.
* `sql2obsidian.py` front matter now includes a `title` field with the
  original (unsanitized) note title, which Quartz and Obsidian use in
  place of the sanitized file name.
* Final documentation and test pass (29 tests).

### Step 11 — Lossless Joplin preservation across SQLite and Obsidian  ✅

* Bumped the interchange schema to v3. SQLite now stores each imported RAW
  item's exact bytes, original filename, and ordered property list in addition
  to queryable known Joplin columns. Compatible v2 databases migrate in place.
* Expanded known columns to the current Joplin Data API note, folder, resource,
  tag, revision, sharing, deletion, locking, OCR, and user-data fields; future
  unknown fields remain preserved by the ordered property list and raw bytes.
* `sql2joplin.py` now emits imported items byte-for-byte by default. URL
  simplification is explicitly opt-in with `--simplify-urls`.
* Joplin item-ID and resource filename collisions with different data are
  rejected instead of silently overwriting one source.
* `sql2obsidian.py` maps common metadata to Obsidian properties, exposes every
  source property under a `joplin-` namespace, stores the complete property
  list as JSON, and writes `.movenotes/joplin-raw/` plus a checksum/path
  manifest so non-note items, original bodies, ignored properties, and raw
  resources remain recoverable. Filtered exports preserve only the selected
  dependency closure.
* Added byte-exact CRLF, future-property, auxiliary-item, raw-resource,
  collision, frontmatter, preservation-manifest, and v2-to-v3 migration tests.
  The suite now contains 33 tests.

### Step 12 — Comparative implementation review  ✅

* Reviewed an independent implementation of the same lossless-conversion
  requirements and retained this project's exact-byte snapshot design,
  collision checks, complete Joplin item schema, and vault-side RAW recovery
  bundle.
* Adopted the independent implementation's strongest usability idea by adding
  a structured `joplin` frontmatter object. Also added a directly parseable
  `joplin-properties` array while retaining legacy flat fields and
  `joplin-properties-json` compatibility.
* Source property parsing now consumes only the canonical delimiter space and
  preserves all additional leading/trailing value whitespace. Ordered source
  pairs remain authoritative, including duplicate and future properties.
* Sanitized legacy `joplin-*` frontmatter key collisions now receive stable
  numeric suffixes rather than producing duplicate YAML keys.
* Expanded the lossless test fixture to cover duplicate unknown fields,
  significant property whitespace, structured frontmatter, and sanitized-key
  collisions. The suite remains 33 tests.


### Step 13 — Embedded and remote images to local resources  ✅

* Added `images2resources.py`, which scans Markdown note bodies in SQLite,
  decodes base64 image data URIs, performs HEAD-first inspection of HTTP(S)
  redirects, downloads within configured limits, validates MIME headers against
  image signatures, creates deterministic Joplin resources, and rewrites only
  successful image links to `:/resource_id`.
* Kept the dependency-free Python 3.9+ design: bounded concurrent downloads use
  `urllib` plus a thread pool rather than requiring `httpx`/`aiofiles`.
* Added an INI domain stop list, private-address blocking, redirect count,
  timeout, size, worker, user-agent, report path, and opt-in SVG controls.
* Added a Markdown problem report with checkboxes, note/file/line context,
  redirect and MIME details, compact previews, and machine-readable occurrence
  metadata.
* Added `quarantinelinks.py`; checked report occurrences are replaced with one
  local configurable “Image removed” resource. Its ID/path are written back to
  the INI file and reused on later runs.
* Added local-server integration tests for successful and failed conversion,
  deduplication, report categories, exact quarantine selection, placeholder
  reuse, and SQLite → Joplin/Obsidian attachment exports.

### Step 14 — Comparative performance review and adaptive scaling  ✅

* Compared the two 3.10 performance implementations and adopted structural
  query-plan/index/query-count tests from the alternate implementation.
* Retained schema-v4 persisted SHA-256 fingerprints, deferred index creation,
  queue-based preservation traversal, streamed RAW export, bounded image
  futures, linear replacements, and forward filename counters.
* Added adaptive existing-ID checks: full re-imports preload fingerprints once;
  small merges issue bounded indexed queries only for IDs in each input batch.
* Cached canonical parent folder parsing, reused parsed folder rows in the main
  loop, loaded existing folder titles once, and limited SQL fallback to newly
  inserted unresolved notes.
* Indexed attachment/resource/media directories once in image localization,
  Obsidian export, and Twitter media fallback paths.
* Made extension matching case-insensitive and added `.MD` regression coverage.
* Expanded the suite to 56 tests and documented benchmark/complexity results in
  `PERFORMANCE_REVIEW.md` and `CHANGELOG.md`.

### Step 15 — Bidirectional Obsidian import and operational hardening  ✅

* Added `obsidian2sql.py` and `obsidianmeta.py` for native vaults and vaults
  carrying a movenotes Joplin preservation bundle.
* Added schema v5 exact Obsidian path/raw/body/frontmatter snapshots plus a
  compressed restoration envelope that survives Joplin `application_data`.
* Native vault discovery is one pass; compact path/ID indexes are retained,
  while note rows stream into bounded SQLite batches and attachment bytes are
  stored only in `resources/`.
* Added visible-note hashes and attachment paths to the preservation manifest,
  exact native-file restoration, edited-visible-note handling, and four-stage
  round-trip documentation.
* Added UTF-8 byte-aware filenames and graceful `ENAMETOOLONG` fallback.
* Added image note-count progress, automatic quarantine domains, canonical
  managed configuration repair, `CHANGELOG.md`, and `AGENTS.md`.
* Expanded the suite to 64 tests.

### Step 16 — Scalable Obsidian static-site publishing  ✅

* Added `obsidian2site.py` to generate Hugo projects using the Relearn theme,
  Pagefind search, and a fixed sidebar that never enumerates individual notes.
* Added direct Obsidian wiki-link, local-link, attachment, frontmatter/date,
  optional transclusion, and deterministic filename conversion.
* Generated all unique non-filler-word tags with temporary SQLite counts and
  prefix-bucketed JSON; explicit Obsidian tags also receive Pagefind filter metadata.
* Bounded pending note conversions, kept tag counting disk-backed, generated a
  valid Hugo module, and documented Hugo/Pagefind build and local serving.
* Added `STATIC_SITE.md`, updated repository orientation, and expanded the suite
  to 73 tests.


### Step 17 — Relearn visual integration and browser responsiveness  ✅

* Replaced the incomplete custom `menu.html` with supported Relearn menu
  configuration and a custom sidebar search element.
* Added responsive, theme-aware Getting Started, Search, and Browse Tags
  surfaces while preserving Relearn’s complete shell and variant controls.
* Removed exact duplicate opening headings, generated the Getting Started date
  at conversion time, and bounded/concurrent Pagefind result rendering.
* Expanded the suite to 76 tests.

### Step 18 — Exact tag results and X mention links  ✅

* Added disk-backed exact tag posting lists and chunked note metadata so Browse
  Tags counts always match the selected result set without depending on
  Pagefind stemming.
* Kept ordinary text search on Pagefind while avoiding Pagefind initialization
  for exact tag navigation and preloading submitted full-text terms.
* Linked plain valid-looking `@username` mentions to X while preserving emails,
  URLs, code, and existing Markdown links.
* Added tag-count/posting-list and mention-boundary regressions, expanding the
  suite to 78 tests.
### Step 19 — Canonical site URLs and optional server-side search

- Made the generated content path the authoritative note URL and reused it in
  Hugo frontmatter, exact-tag metadata, Pagefind output, and Bluge records.
- Added the generated `site_server` Go module, JSONL search source, automatic
  Bluge index construction, paginated search API, phrase/tag/date operators,
  and static-file serving with cache headers.
- Kept Pagefind as an independent static-hosting fallback rather than coupling
  Bluge to Pagefind's private browser index.
- Added build-backend selection, a configurable Go executable, prebuilt-index
  mode, documentation, checksum data, and structural/integration regressions.
- Expanded the suite to 81 tests.

