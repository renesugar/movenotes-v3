# Changelog

Unreleased changes:
- Made HTML images show after export. `sql2obsidian.py` used to leave `<img src=":/id">` pointing at the Joplin ID, which neither Obsidian nor the site can open. Now, on both the Joplin and the Notrios paths, only the `src` value changes, to the copied attachment's path relative to the note, and every other byte of the tag is kept. `obsidian2site.py` resolves that path to the attachment's URL, including in a tag that spans lines, and `obsidian2sql.py` maps it back to `:/id` on a native reimport.
- Documented how to keep notes out of a Notrios publication. Measured on Notrios `v1.0.0`: the `private`, `draft` and `confidential` tags are withheld by default; `--exclude-tags` adds to that list, while `--private-tags` replaces it, so `--private-tags secret` publishes a note tagged `private`. A notebook named `Private` is not private. Also documented what tags cannot catch (personal data in prose, code, titles, URLs and attachments), with Presidio and hawk-eye recommended for scanning a publication first.
- Documented publishing more than 100,000 notes from Notrios: export the handoff over the root notebooks with `--max-documents`. The export applies the same default policy (its selection digest equals the reviewed plan's), but has no profile and no plan review.
- Moved the documentation into `docs/`, one page per workflow, with `docs/index.md`; the README keeps an overview and a short example per workflow. The tests moved to `tests/`, development tools to `scripts/`, and finished plans to `plans/` by release, with `ROADMAP.md` for deferred features.
- Added `scripts/check_doc_links.py`, run by `tests/test_docs.py`, which refuses a relative link or `#anchor` that does not resolve, and a link that leaves the repository.
- Removed the account name from every committed path, and from the Git history: `develop` and `main` were rewritten and force-pushed on 2026-10-27, so every commit after the first has a new hash. A clone made before then must be cloned again. `docs/plan/l8-commit-map.txt` maps the old hashes to the new ones.
- Added `scripts/check_doc_examples.py`, run by `tests/test_doc_examples.py`. Every fenced example in the README and `docs/` is registered in `docs/examples.json`, and an edited or unregistered one fails the gate. The 22 that need only Python run in the gate against the sample data; the 16 that need Hugo, Go, `npx` or `notriosctl` run with `--with-tools`; the other 28 record why they are not run.
- Fixed examples that failed as written: every converter needs its `--output` directory to exist, and the Twitter/X import, the notebook-subset export, both round trips and the Quartz export did not create it.

---

Changes in 3.37:
- Added `notrios2sql.py`, which verifies a Notrios publication handoff (a loose archive-v2 directory) and imports it into a new database: notebooks with their nesting, each note's current revision, tags and memberships, and attachments with their exact bytes. IDs are derived from the publication's own identities, so one publication always produces the same IDs. Tested against Notrios `v1.0.0`.
- Verified the whole archive before writing anything: every object's size and SHA-256, the manifest's digests, the records and how they refer to each other, and the publication's own rules. Reads go through no-follow directory handles with bounded JSON and fixed size limits, and a packed archive, another export target, source bundles or provenance are refused.
- Made each import all-or-nothing. It is built in owned staging directories beside the output and published with one no-replace rename (`renameat2`, so Linux only), and the output must not exist yet: there is no merge and no overwrite. Rerunning into a completed import of the same publication verifies it and reports `unchanged`. A run that is killed leaves a lock that the next run refuses, naming its path; the importer never removes it by itself.
- Added `--version` to `notrios2sql.py`, and synced every changed script's version at 3.37, `cleanres.py` included, which had its own 2.x numbering.
- Added `--expected-selection-sha256`, which ties an import to the plan that was reviewed and refuses any other selection, including on reruns. Success prints one JSON line with the status, both digests and the row and resource counts, and no paths or note content. Progress phases go to stderr; exit status 0, 1 for a refusal, 2 for a usage error.
- Mapped links to notes and attachments in a publication (`document://`, `resource://`) to Joplin `:/id` links. Labels are kept, and so is a delimited title, byte for byte: Notrios `v1.0.0` keeps a link's title when it rewrites the destination. An HTML `<img>` whose `src` names one of the note's attachments maps the same way. Every other destination passes through as written, whatever its scheme. A link to an internal target the importer cannot account for refuses the import, rather than publishing a link that leads nowhere or names a withheld note.
- Admitted every link form in three real libraries, 867,761 notes in all, with no note filtered out. Brackets in prose are read the way the Notrios parser reads them, wiki links stay text, and a Notrios link record inside code is accepted when it is a single external link.
- Added `--include-notrios-receipt` to `sql2obsidian.py` and `obsidian2site.py`. It copies the import's receipt, which identifies the publication by its digests and IDs and holds no paths, times or note content, to `.movenotes/notrios-receipt.json` in the vault and to `movenotes/notrios-receipt.json` on the site, where it is public. Each stage needs its own flag, an invalid receipt refuses the export, and a rerun without the flag removes an old one.
- Measured publication → import → vault → site on those three libraries (103,349, 382,206 and 382,206 notes). The importer's peak memory stayed between 46 and 69 MiB from 1,000 notes to 382,206, and Hugo used up to 14.7 GiB, the most of any step. README has the recipe and the table, `plans/v3.37/010-corpus-trials.md` every step.
- Fixed `cleanres.py` deleting attachments referenced only by a titled link (`[a](:/id "title")`), because its pattern did not allow a title. Reimporting a vault no longer leaves a stray `)` or an unresolved titled link, `sql2obsidian.py` keeps an attachment link's title (a titled image becomes a Markdown image), and `obsidian2site.py` keeps the title on note and attachment links.
- Stopped `sql2obsidian.py` and `sql2joplin.py` rewriting the database they read. Opening it switched it to WAL mode, so exporting a completed Notrios import changed `notesdb.sqlite` and the next identical rerun refused it. Both now open the input read-only, unless it needs a migration or recovery.
- Fixed a note titled `index` (in any case) emptying its folder on the site. Hugo treats `index.md` as a leaf bundle, so every other note in that folder stopped being a page; one note removed 95,148 recipes from a generated site. A note file with a bundle name now gets a `-note` suffix.
- Made a fresh Obsidian import of a large vault finish. Each batch looked its IDs up in a table with no index yet, which is quadratic: a 382,206-file vault was stopped after 17,943 s. The new database now gets `joplinididx` when it is created, and the import takes 1,628 s. At 40,000 files it fell from 330 s to 130 s, with identical output.
- Kept each file's relative path from the vault inventory, instead of recomputing it at every later step. On 10,000-file vaults a fresh import takes 0.834 of the time and an unchanged rerun 0.823.
- Skipped unchanged notes before converting them. An unchanged rerun used to convert every note before finding it already stored; it now checks each batch's IDs and byte digests first. It takes 0.472 of the time on 10,000 files, and 983 s fell to 515 s over the full vault, at about 6 MB more peak memory.
- Imported into an existing empty library, which is what an interrupted fresh import leaves, as fast as into a new one, by deferring its indexes the same way: 0.799 of the time at 10,000 files and 0.667 at 40,000.
- Streamed the preservation manifest in both directions, 530 MB for a 1.2 million-item library. The export's peak memory fell from 3.5 GiB to 0.8 GiB and the preserved import's from 1.8 GiB to 0.5 GiB, with byte-identical manifests.
- Refused a damaged preservation bundle instead of importing the vault as plain Obsidian and dropping what the bundle keeps: invalid JSON, another format or version, or `joplin-raw/` with no manifest. Nothing is written, and the error lists the next steps as complete commands built from the one that failed.
- Added `--ignore-preservation` to `obsidian2sql.py`, which imports a vault as plain Obsidian notes even when it has a bundle. `sql2obsidian.py` now writes `.movenotes/export.json`, recording the source library (as `~/…`, or with `$USER` for the user's name) and the export's options, so that the refusal can print the export command. It writes the manifest last, by renaming a finished temporary file.
- Fixed a re-export that stopped part way, or ran with `--no-preserve-joplin`, leaving the previous bundle beside notes it no longer described.
- Fixed two collision gaps in `obsidian2sql.py`. Two files with one ID but different bytes in the same batch now fail before the batch is inserted, and a preserved resource that collides is caught before any resource is copied.
- Showed `<script>`, `<style>`, `<title>`, `<textarea>`, `<noscript>`, `<noembed>`, `<noframes>`, `<xmp>` and `<plaintext>` tags written in a note's prose as text on the site. Before, they ran in the browser or swallowed the page after them, and a `<script>` that was not JavaScript failed `hugo --minify`, as it did on a 103,349-note Joplin library. An SVG's own `<title>` and `<style>` are kept, code and search text are unchanged, and the run prints how many tags it escaped.
- Stopped the test suite writing `__pycache__`, which could shadow the script under test.

---

Changes in 3.36:
- Replaced the Relearn theme with `hugo-theme-ledger`, which is built for archives of 100,000+ notes; deleted every Relearn workaround, including the Hugo 0.158 template rewriter, both Lunr kill switches, the sidebar-element, heading, content, and custom-header partial overrides, and the fixed three-item menu.
- Added `--ledger-theme`, keeping `--relearn-theme` as a warning alias; the copied checkout is used verbatim, skipping `exampleSite`, `node_modules`, `public`, `bench`, and `.git`.
- Rewrote note frontmatter for the new theme: `categories`, `tags`, and `ledgerHideTitle`/`ledgerHideMeta` for notes carrying their own heading and timestamp; dropped every Relearn field, and writes nothing the theme can derive.
- Added a two-tier tag model: written tags become a bounded Hugo taxonomy with real archive pages, while every generated content word stays in the disk-backed posting index.
- Made `tag:` mean the same thing everywhere. It matched every generated content word on Bluge only, so `tag:ifnβ` returned 23 where the tag archive and Pagefind showed 16 — one query, three answers. It now matches the tags written in a note, which is what the archive and Pagefind's filter are built from. Nothing became unreachable: a generated tag is a word of the note, so free text returns exactly what `tag:` used to add, and Browse Tags reads the posting index. Search remains a superset of the archive, because a written tag that missed the taxonomy cap is still searchable.
- Added `--max-taxonomy-tags`, defaulting to `max(200, min(5000, notes ÷ 10))`, because a taxonomy term costs about as much to build as a note page — measured at 5,000 notes: 200 terms took 11.2 s, 5,000 took 32.2 s. Promotion is by frequency, ties broken by name, so two runs of one vault promote the same set.
- Added `--category-mode` and `--category-name`; a note's category is its top-level vault folder by default.
- Deleted 451 lines of hand-written search UI: `/search/` is now the theme's own view, over its grammar and its adapters. The generated project has no shortcodes at all.
- Rebuilt Browse Tags on the theme's markup as one page with two modes, `/browse-tags/` and `/browse-tags/?tag=…`, importing the theme's pagination rule rather than reimplementing it; trimmed the generated stylesheet from 205 lines to 65.
- Extended the search grammar to repeatable `tag:`, `category:`, quoted phrases, and `since:`/`until:`, parsed once in the browser; a backend that cannot honour a clause now says so instead of returning the unbounded set.
- Converged the Bluge server on one superset HTTP contract and deleted its server-side grammar parser; `search-source.jsonl` gained `category`, `readingTime`, and `displayTags`.
- Split the server into one `search` package with two entry points — a local process and serverless functions — with configuration resolving explicit value, then environment, then default; the index is opened lazily, read-only, and never built by a request, which answers 503 instead.
- Stopped storing every tag in the Bluge index for display, cutting it 31% (127 MB to 97 MB at 20,000 notes) and fixing result cards that listed generated content words as if they were the note's tags.
- Added `--vercel`, emitting `vercel.json`, `.vercelignore`, and a root Go module with `api/` functions; `--build --vercel` measures the built site against Vercel's file-count, upload, and bundle limits and reports which it exceeds.
- Fixed subpath deployments, which were broken throughout: Hugo's `relURL` drops the baseURL's path when its argument starts with a slash, so every asset, link, and search result on a GitHub Pages project site pointed at the domain root.
- Added `docs/deploy-vercel.md` and `docs/deploy-github-pages.md`, each leading with the measured platform limits that decide which archives can be deployed where.
- Retargeted the post-build backend check from Relearn's Lunr filenames to the backend the built pages actually configure, and to whether the index that backend needs exists.
- Evaluated Orama and FlexSearch as additional static-hosting search options and rejected both: an in-browser index must be transferred at least once, and theirs are 33–343 MB at 25,000 notes against the 0.37 MB Pagefind fetches for a free-text query. `--search-backend` therefore still offers `both`, `bluge`, and `pagefind`; the measurements and the reasons not to retry them are in the theme's `PERFORMANCE.md`.
- Ordered every search result newest first, not just the queries with no text to rank: an archive is read by date, and relevance ranking left the most recent note at an unpredictable position, sometimes on the last page. Measured free on a text query at 25,000 notes (369 KB, unchanged); `sort=score` remains for callers that want ranking.
- Made the search page wait for a query instead of searching for everything on arrival, which on a Pagefind site was its single most expensive request: 13,503 KB across 442 requests at 25,000 notes, now 86 KB and nothing from Pagefind. An empty search still means every note, identically to `category:"All notes"`.
- Made URLs searchable. The text handed to Bluge had every URL removed from it — Markdown link targets and bare links alike — so a note's links were visible on the page and absent from the index, and searching for one returned nothing. Link targets now ride on the indexed `body` field, which is not stored, so cards, reading time and tags are unchanged; searching a whole URL, a prefix, or its components all work.
- Indexed every parent domain of a link's host for Bluge, whose analyser keeps a host whole: `kqed.org` now finds `www.kqed.org`, `blogs.kqed.org` and `u.kqed.org` alike, and `nih.gov` finds `www.ncbi.nlm.nih.gov`. Searching `sciencedirect.com` previously found 2 notes where `www.sciencedirect.com` found 455. Costs 0.5% of the index; Pagefind needs none of it, because it splits a host on its dots already.
- Measured the cost of indexing links on a real 20,000-note Twitter/X archive: the Bluge index grows 12.1% (37.48 MB to 42.03 MB) and ordinary queries are no slower. At 2.20 KB per note it is less than half the 4.85 KB the synthetic worst-case corpus produces, so `docs/deploy-vercel.md` now carries both figures.
- Made the post-Hugo backend check say what it is doing. On a 166,654-note archive it read 177,682 built pages and 5.6 GB in silence, taking 8m50s that looked like a hang; it now names the page count, reports every 20,000 pages, and prints its elapsed time, all silenced by `--progress-every 0`.
- Sped that check up 1.81× on the same archive (529.7 s to 292.2 s) by scanning bytes behind a substring test instead of decoding every page to run two regexes over it. Only 95 of 177,682 pages carry the search config, so both regexes are now skipped for nearly every page. Threads were measured and are slower — the work is a scan, not I/O wait.
- Added a `compiling the site server...` line, the other unannounced wait during `--build`.
- Documented link search: a "Searching for a link" section in `docs/static-site.md` and on the generated Getting Started page showing how a URL splits and which queries find it, plus its two limits — it is not a URL parser, and a host every note links is as common a word as it sounds.
- Announced every phase of generation. `scanning the vault...`, `mapping N note path(s) to site URLs...`, `copying the theme...`, `copying N attachment(s)...` and `converting N note(s)...` used to run in silence; on a 166,654-note vault that was 78 s before the first line and minutes more before the first `converted` line. `--progress-every 0` silences them with the note counter.
- Made note-path mapping 5.44× faster (86.0 s to 15.8 s at 166,654 notes) by replacing `Path.relative_to` with a string slice, slugging each directory once instead of once per note, and building one path object per note instead of five. The output is byte-identical over the whole vault, which matters because these paths are the canonical note URLs.
- Announced the preservation bundle in `sql2obsidian.py`. Its four phases ran after the last `exported N` line with no output, which on a full library is 173,290 raw files, 6,634 resource copies and an 83 MB manifest — long enough to look like a hang. Each phase now names itself, the item loop counts like the export loop, and `--progress-every 0` silences them.
- Added `expr` to `/api/search`: the query as a JSON expression tree, which is how `OR`, negation and grouping reach the server. The existing parameters are a flat set of ANDed clauses and cannot carry them; they still work for callers without a tree. Malformed trees are a 400 naming the problem, and both size and nesting depth are bounded.
- Added `OR`, negation and grouping to the search grammar, following Twitter/X: `cat OR dog`, `housing -rental`, `(rent OR lease) tag:vanre`. A space is AND, and AND binds tighter than OR. `OR` is uppercase only, so a note that says "or" stays findable. Every one of these previously returned nothing, because the operator became one more word to require.
- Answered them in full on Bluge, which receives the parsed expression as a tree. Pagefind cannot express them — its text search takes one term string with punctuation stripped — so those queries run there as though every clause were ANDed and the results view names the operators it dropped, the same contract `since:`/`until:` already used.
- Made emoji searchable on the Bluge backend, which produced no term for one at all: `😃` matched nothing and an emoji in a note was not indexed, on an archive whose notes end `🔁 0 💙 0`. They are indexed as keywords now, from title and body, and an emoji-only term is matched against that field. Pagefind already found them. Costs 0.6% of the index.
- Expanded the suite to 102 Python tests, plus Go tests over both server entry points.

---

Changes in 3.35:
- Disabled Relearn's native search at both the configuration and template-extension layers, preventing its default Lunr adapter, generated search index, native search box, and keyboard search handler from being emitted in Bluge-only sites.
- Added a post-Hugo validation gate for `--search-backend bluge` that rejects any built HTML still referencing Lunr, Relearn `searchindex.js`, or Pagefind runtime assets.
- Made Bluge-only Search, Browse Tags, Getting Started, and note layouts contain no Pagefind runtime or indexing attributes; the sidebar and full Search page now submit to the same `/api/health` and `/api/search` backend.
- Added Bluge API health/search telemetry, backend identity in JSON responses, and `Server-Timing` search duration headers so server use is visible in the terminal and browser network tools.
- Added Twitter/X reply context, locally formatted linked timestamps, retweet counts, favorite counts, and compact source metadata during archive import; added `--timezone` for an explicit IANA display time zone.
- Hid the redundant Relearn page H1 and theme date on notes originating from `twitterx2sql` while retaining the title for the topbar, search results, and document metadata.
- Made `obsidian2site.py --build` run `go mod tidy` before compiling the generated server, retaining a baseline `go.sum` while normalizing it for the user's Go toolchain.
- Added regressions for Bluge-only runtime isolation, unwanted-browser-index build rejection, Twitter page presentation, server telemetry, and tweet metadata formatting.

---

Changes in 3.34:
- Added deterministic, lowercase Hugo output URLs derived from the generated content path and wrote them explicitly to note frontmatter, fixing search/tag links that previously used source-folder case, spaces, percent signs, or ellipses instead of Hugo's emitted slug.
- Added a generated Go static-site server backed by Bluge for server-side full-text, quoted-phrase, exact `tag:`, and date-range search.
- Added `since:YYYY-MM-DD` inclusive and `until:YYYY-MM-DD` exclusive query operators, result pagination, cached static assets, and automatic index rebuilding when the generated JSONL source changes.
- Kept Pagefind as an optional static-hosting fallback; Bluge builds its own disk index from `server/search-source.jsonl` and does not consume Pagefind's browser-specific index.
- Updated the search page to prefer `/api/search` when the generated server is running and fall back to Pagefind otherwise.
- Added `--search-backend` and `--go-bin`, copied reproducible Go module files into each generated project, prebuilt the Bluge index during `--build`, and documented the large-archive server workflow.
- Added regressions proving generated note paths, Hugo URLs, exact-tag metadata, and server-search records all use the same canonical URL.

---

Changes in 3.33:
- Added an exact, disk-backed tag postings index so every Browse Tags count is the number of unique notes returned after selecting that tag.
- Changed tag links to use `search.html?tag=...`; exact tag browsing no longer relies on Pagefind stemming, so tags such as `canadian` and `canadians` remain distinct.
- Added chunked note metadata for exact tag result pages, allowing them to render in bounded batches without loading Pagefind or a global note catalog.
- Reduced Pagefind work by initializing it once per search-page visit, preloading typed terms, shortening excerpts, using a stable per-build metadata cache tag, and releasing its worker when leaving the page.
- Added conservative hover/focus prefetching for internal HTML links to reduce perceived navigation latency without scanning or preloading the complete archive.
- Converted plain `@username` mentions containing 1–15 ASCII letters, digits, or underscores into links to `https://x.com/username`, while leaving emails, URLs, code, and existing links unchanged.
- Added regressions proving tag counts match posting-list lengths and X mention conversion respects syntax boundaries.

---

Changes in 3.32:
- Restored Relearn’s complete sidebar shell by using the theme’s supported `sidebarheadermenus`, `sidebarmenus`, and custom sidebar-element interfaces instead of replacing `menu.html`.
- Added an integrated sidebar search control, theme-native fixed navigation, and responsive polished Search, Browse Tags, and Getting Started surfaces.
- Removed an initial Markdown heading when it exactly duplicates the Hugo/Relearn page title, eliminating repeated page headers without altering different headings.
- Generated the Getting Started page with the current UTC date rather than inheriting a source-vault date.
- Reduced browser work by loading only 20 Pagefind result details at a time, fetching each visible batch concurrently, guarding against stale searches, and limiting rendered tag matches.
- Kept source-path metadata out of Pagefind excerpts while retaining title and explicit-tag indexing.
- Added structural and behavioral regressions for the Relearn menu contract, current date, heading deduplication, bounded concurrent search rendering, and generated layout cleanup.

---

Changes in 3.31:
- Validated bare, angle-bracket, and ordinary Markdown HTTP(S) links during Obsidian-to-site conversion.
- Repaired incomplete percent escapes and safely encodable URL components while preserving the original URL as visible link text.
- Converted structurally unusable URLs to marked visible text so Relearn's URL parser cannot abort a Hugo build.
- Replaced deprecated Hugo `languageCode` configuration with `locale` and Relearn `disableSearch` with `params.search.disable`.
- Added Hugo 0.158+ compatibility handling for Relearn language and `Sites` APIs across copied themes and the module-mode templates exercised by generated sites.
- Clarified the documented one-command generation example and made build instructions match the exact next-step commands printed by `obsidian2site.py`.
- Added regressions for the reported `%E` URL failure, unrecoverable URLs, code-block preservation, current Hugo configuration, and Relearn template modernization.

---

Changes in 3.30:
- Added `obsidian2site.py` to convert native or generated Obsidian vaults into scalable Hugo projects using the Relearn theme and Pagefind.
- Replaced the automatic Relearn page tree with a fixed Getting Started, Search, and Browse Tags sidebar so note titles are never enumerated for very large vaults.
- Added direct Obsidian wiki-link, local Markdown-link, attachment, optional note-transclusion, Hugo date, and deterministic long-filename conversion; code examples are protected from link rewriting and literal Hugo shortcode execution.
- Added Pagefind body metadata, exact filters for explicit Obsidian tags, and a custom search page; generated word tags reuse Pagefind full-text search to avoid duplicating the complete vocabulary as filter data.
- Added explicit hashtag plus all-unique-non-filler-word tags without Hugo taxonomy pages or per-note generated-word frontmatter; global counts use batched temporary SQLite updates and bucketed JSON for bounded memory and browser bandwidth.
- Added optional Hugo/Pagefind build execution, local Relearn checkout copying, stop-word customization, safe output regeneration, and progress reporting.
- Added `docs/static-site.md` and six static-site generation regression tests; documented Quartz as an alternative for smaller vaults.

---

Changes in 3.21:
- Fixed Twitter/X `t.co` expansion when an HTTP redirect returns a relative `Location` such as `/user/status/id`; each hop is now resolved against the current absolute URL.
- Added support for scheme-relative redirect targets such as `//x.com/user/status/id`.
- Invalid relative targets left by older `tco_cache.json` files are ignored and re-resolved instead of being returned as broken URLs.
- Added local-server regressions for relative redirect chains and malformed cache entries.

---

Changes in 3.20:
- Added `obsidian2sql.py` for native Obsidian vaults and vaults carrying a `.movenotes/joplin-raw` preservation bundle.
- Added schema v5 exact Obsidian path, raw-byte, body, frontmatter, and generated-Joplin-body fingerprint columns.
- Native Obsidian notes and resources carry a compressed, namespaced restoration envelope through Joplin `application_data`.
- Manifest-backed vault imports also merge notes, attachments, settings files, and empty directories added later in Obsidian.
- Added exact Joplin → Obsidian → Joplin and Obsidian → Joplin → Obsidian round-trip tests.
- `sql2obsidian.py` records visible-note hashes and attachment mappings in the preservation manifest and restores native Obsidian files to original paths.
- UTF-8 byte limits and deterministic `ENAMETOOLONG` recovery prevent overlong note titles from aborting exports.
- `images2resources.py` reports notes processed out of the total with configurable progress intervals.
- `quarantinelinks.py` supports `quarantine_domains`, optional report-only operation, partial managed-value repair, and a canonical managed configuration block.
- Consolidated release notes into this reverse-chronological changelog and added `AGENTS.md`.

---

Changes in 3.11:
- Added adaptive full-reimport versus input-scoped indexed collision checking.
- Cached parent-folder parsing and restricted fallback folder updates to new rows.
- Added one-time resource, attachment, and Twitter media directory indexes.
- Added query-plan, SQL-count, missing-index repair, and uppercase-extension regressions.

---

Changes in 3.10:
- Added schema v4 persisted binary SHA-256 source fingerprints and bounded migration backfill.
- Removed per-file unindexed database lookups and full-RAW in-memory duplicate maps.
- Deferred secondary-index creation until after new bulk imports.
- Added queue-based filtered-preservation traversal, streaming RAW export, linear filename deduplication, bounded image downloads, linear image replacements, and batched Twitter resources.
- Replaced per-item console output with periodic progress options.

---

Changes in 3.05:
- Fixed PDF resource imports whose `ocr_text` contains control characters by splitting RAW metadata only on CR and LF physical line endings.
- Preserved embedded OCR controls and exact source bytes for byte-identical Joplin RAW round trips.

---

Changes in 3.04:
- Added an explicit normalized `REAL` conversion branch in `joplin2sql._convert_known_value()`.
- Added direct and end-to-end regressions for `order: 6e-323`.

---

Changes in 3.03:
- Corrected `notesdb.JOPLIN_COLUMNS["joplin_order"]` to SQLite `REAL`.
- Treated `REAL` as numeric during change detection, preserving original forms such as `order: 0` and scientific notation.

---
