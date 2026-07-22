# Changelog

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
- Added `STATIC_SITE.md` and six static-site generation regression tests; documented Quartz as an alternative for smaller vaults.

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
