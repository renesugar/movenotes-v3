# Plan: replace Relearn with Ledger, add Vercel deployment, and re-open the
# static-search question

Scope of this plan:

1. Replace `hugo-theme-relearn` with `hugo-theme-ledger` in the site generated
   by `obsidian2site.py`, keeping the movenotes Bluge server.
2. Make `movenotes-site-server` deployable on Vercel *and* usable locally.
3. Benchmark Orama and FlexSearch against Pagefind at 25k / 100k / 200k pages
   and, only if the numbers justify it, add one or both to `obsidian2site.py`.
4. Document Vercel (Bluge) and GitHub Pages (static) deployment.

Two repositories are involved and each step below names the one it touches:

| repo | path | role |
|---|---|---|
| `movenotes-v3` | `/home/renes/projects/movenotes-v3` | generator, Bluge server, docs |
| `hugo-theme-ledger` | `/home/renes/projects/hugo-theme-ledger` | theme, search adapters, bench harness |

## Working agreement

- One step per session. Every step ends with the repo building, its tests
  passing, and a commit whose subject carries the step number.
- Ask before starting the next step.
- `python3 -m unittest -v test_movenotes.py test_image_resources.py
  test_obsidian2sql.py test_obsidian2site.py` must pass at the end of every
  step that touches `movenotes-v3`.
- `hugo --source exampleSite --themesDir ../..` must succeed at the end of
  every step that touches the theme.
- Nothing is pushed to GitHub until the whole plan is complete, the user has
  tested against a real Twitter/X archive, and the user has agreed. Push target
  is `develop`; the pull request into `main` is created by the user.

---

## Part A — Evaluation: is Ledger the right replacement?

**Verdict: yes, and the fit is unusually close.** Ledger was written for the
problem `obsidian2site.py` already solves by hand, and its Bluge adapter was
modelled on this repo's server. Relearn is being used against its own design:
roughly a third of the generated-project scaffolding in `obsidian2site.py`
exists to *suppress* Relearn behaviour.

### What the swap deletes from `obsidian2site.py`

| Relearn workaround | why it exists | after |
|---|---|---|
| `_modernize_copied_relearn_theme` + `_RELEARN_HUGO_0158_REPLACEMENTS` | Relearn checkouts lag Hugo's template API | deleted — Ledger's `min_version` is 0.146 and it is developed on 0.164 |
| `layouts/partials/dependencies/search.html` and `search-lunr.html` kill switches | stop Relearn shipping Lunr | deleted — Ledger ships no built-in search runtime |
| `params.sidebarheadermenus` / `sidebarmenus` / `sidebarfootermenus` blocks | force a fixed three-item sidebar and stop note titles being enumerated | deleted — Ledger's sidebar never enumerates pages |
| `_SIDEBAR_SEARCH_PARTIAL` (`sidebar/element/movenotes-search.html`) | inject a search box into Relearn's sidebar | deleted — Ledger has a search bar and a search view |
| `_HEADING_PARTIAL` (`heading.html` override) | suppress the duplicated H1 on Twitter notes | replaced by a theme-level front-matter switch (decision M5) |
| `_CONTENT_PARTIAL_PAGEFIND` / `_CONTENT_PARTIAL_PLAIN` | scope Pagefind to note bodies | deleted — Ledger's `page.html` owns the `data-pagefind-body` contract |
| `hidden: true`, `disableBreadcrumb`, `disableToc`, `hideAuthorDate` on every note | Relearn front matter | deleted — smaller front matter on every note |
| `themeVariant`, `disableLandingPageButton`, … | Relearn params | replaced by Ledger's `[params]` schema |

The three shortcodes (`movenotes-start`, `movenotes-search`, `movenotes-tags`)
and `_SITE_CSS` shrink to whatever Ledger does not already provide — chiefly the
exact-tag browse page, which stays a movenotes feature (decision M2).

### What the swap gains

- Measured behaviour at 10k / 100k / 500k pages, written down in the theme's
  `PERFORMANCE.md`, including five refuted attempts at making Pagefind fast.
- Server-rendered first page for over-limit terms, so opening a tag issues no
  search query at all — the single largest win in that document.
- A designed home / term / tags-grid / post / about set of views, three themes,
  and a contrast-audited palette (nothing below 4.5:1).
- One backend-agnostic query parser with a documented adapter interface, which
  is where Orama and FlexSearch will plug in (Part C).

### What the swap costs — and how each cost is paid

1. **Search grammar regression.** Ledger's `query.js` accepts one
   `category:`/`tag:` clause or free text. The movenotes Bluge server already
   supports quoted phrases, several `tag:` clauses, `since:` and `until:`.
   → Decision M6: extend the theme's parser and contract rather than lose
   syntax.
2. **Ledger reads Hugo taxonomies; movenotes deliberately does not.**
   `_extract_tags` makes a tag of every unique non-filler word, which is why
   generated tags live in a hashed posting index under `static/movenotes/`
   instead of Hugo's taxonomy. Feeding those into `[taxonomies]` would create
   hundreds of thousands of term pages. → Decision M2 (two-tier tags).
3. **`disableKinds = ['taxonomy','term','RSS']` must go**, because Ledger's
   sidebar, `/tags/` grid and term archives are taxonomy pages. That re-admits
   exactly the build cost movenotes disabled, so the tag tier that reaches Hugo
   has to be bounded. → Decision M2 again, plus the M3 cap.
4. **Two API contracts for Bluge.** → Decision M7 (one superset contract).
5. **Twitter-note presentation.** Ledger's `page.html` always renders
   `<h1>{{ .Title }}</h1>` and a date/reading-time row. → Decision M5.

---

## Part B — Decisions

### M1 — Theme delivery

`--relearn-theme` becomes `--ledger-theme` (copy a local checkout into the
generated project, source untouched). Without it, the generated `hugo.toml`
imports `github.com/renesugar/hugo-theme-ledger` as a Hugo module. No
post-copy rewriting: if a Ledger checkout does not build on the installed Hugo,
that is a theme bug to fix in the theme repo.

`--relearn-theme` is kept as a deprecated alias for one release: it warns and
behaves as `--ledger-theme`, because it is in `STATIC_SITE.md` command lines
users have copied.

### M2 — Two-tier tags (the load-bearing decision)

| tier | source | storage | surfaces |
|---|---|---|---|
| **explicit** | frontmatter `tags`/`tag` + inline `#hashtags` | Hugo `tags` taxonomy (front matter `tags`) | sidebar, `/tags/` grid, term archives, post footer, Pagefind/Bluge `tag:` filter |
| **generated** | every unique non-filler word ≥ `--minimum-word-length` | existing hashed posting index under `static/movenotes/` + `tag` fields in `server/search-source.jsonl` | the movenotes **Browse Tags** page and `tag:` queries answered by Bluge |

Both tiers keep working exactly as today for search; the change is only that
the explicit tier is *also* a Hugo taxonomy so Ledger's designed surfaces have
something real to show. Generated word tags never become taxonomy terms.

The invariant in `AGENTS.md` ("static-site note titles must never be enumerated
in the Relearn sidebar") is preserved and restated for Ledger: nothing
page-specific may enter the sidebar, which is `partialCached` with no variant
key.

### M3 — Bounded taxonomy

Explicit tags are unbounded in principle (a vault can contain 50k distinct
hashtags), and every term is a Hugo page. New flag `--max-taxonomy-tags N`:

- the N most frequent explicit tags become Hugo taxonomy terms, ties broken by
  name so two runs of one vault promote the same set;
- the remainder stay searchable through the posting index and Bluge, and the
  Browse Tags page continues to list all of them;
- the generator logs how many tags were promoted and how many were not.

**The default is adaptive: `max(200, min(5000, notes // 10))`.** Measured at
5,000 synthetic notes with 5,000 Zipf-distributed tags, a taxonomy term costs
about as much to build as a note page — so a flat 5,000 would have tripled the
build of a small archive while being negligible on a large one:

| cap | terms | pages | Hugo build | peak RSS | `public/` |
|---|---|---|---|---|---|
| 200 | 200 | 5,213 | 11.2 s | 386 MB | 137 MB |
| 2,000 | 2,000 | 7,013 | 18.6 s | 477 MB | 181 MB |
| 5,000 / uncapped | 5,000 | 10,013 | 32.2 s | 539 MB | 245 MB |

Each additional 1,000 terms cost ~1,000 pages, ~4.4 s, ~32 MB of RSS and ~22 MB
of output at this corpus size. 5,000 remains the ceiling because it is the term
count the theme has been benchmarked at; 200 is the floor because a sidebar
holds `sidebar.maxTerms = 200` anyway.

Promotion needs global counts, which are only complete after every note has been
read, so it runs as a second pass that rewrites the front-matter line of just
the notes carrying a demoted tag. Bodies are not buffered — a vault's do not fit
in memory. Measured cost: ~3 s to rewrite 4,940 of 5,000 notes, and nothing at
all for a vault under its cap.

`taxonomyPageLimit` (default 25) then keeps every promoted term from
paginating: over-limit terms server-render page 1 and hand the rest to search.

### M4 — Categories

Ledger's views expect one category per note. Derive it from the note's
top-level vault folder, which is meaningful for these vaults (`Twitter`,
`Notes`, …). New flag `--category-mode {folder,fixed,none}` (default `folder`),
with `--category-name` for `fixed`. Notes at the vault root get
`--category-name` or, absent that, the site title. Ledger's synthetic
"All notes" sidebar row is left enabled.

### M5 — Twitter-note presentation (theme change)

Add to the theme two front-matter switches read by `page.html`:
`ledgerHideTitle` and `ledgerHideMeta`. `obsidian2site.py` sets them from the
existing `_is_twitter_note` detection — which must keep coming from
`movenotes-original-format` / Joplin source metadata, never from the folder
name.

Ledger also renders a hero-image block with a striped placeholder when a note
has no `image`. For a Twitter archive that placeholder on 166k notes is noise:
add `params.post.heroPlaceholder` (default `true`) so the generator can turn it
off, rather than fighting it with CSS.

### M6 — One query grammar, extended in the theme

Extend `assets/js/search/query.js` to the movenotes grammar, keeping it parsed
once and backend-agnostically:

```
category:<name>            (unchanged; "all notes" label means no filter)
tag:<name>                 repeatable, ANDed
"quoted phrase"            exact phrase
since:YYYY-MM-DD           inclusive
until:YYYY-MM-DD           exclusive
anything else              free text, ANDed
```

The parsed shape grows from `{field, value, text, matchAll}` to
`{categories[], tags[], phrases[], terms[], since, until, matchAll}`. Both
existing adapters are updated: `bluge.js` passes the clauses through;
`pagefind.js` maps what Pagefind can express (`category`/`tag` filters, text)
and reports the rest as unsupported rather than silently ignoring it — a
Pagefind-hosted site should say that `since:` needs the Bluge backend. The
theme's three number-windowing implementations and the "ordering must agree"
rule are untouched by this.

### M7 — One Bluge HTTP contract

Today:

| | movenotes `site_server` | Ledger `bluge.js` |
|---|---|---|
| request | `q`, `offset`, `limit`, `sort` | `q`, `category`, `tag`, `page`, `per` |
| result item | `url`, `title`, `date`, `excerpt` | `title`, `summary`, `url`, `category`, `tags`, `date`, `readingTime` |
| envelope | `backend`, `query`, `total`, `offset`, `limit` | `total`, `page`, `per` |

Converge on a superset served by `movenotes-site-server`:

- accept `page`+`per` **and** `offset`+`limit`; accept repeated `tag=` and
  `category=`, plus `since`/`until`/`sort`;
- return `total`, `page`, `per`, `offset`, `limit`, `backend`, `query`, and
  result items carrying `url`, `title`, `summary`, `date`, `category`, `tags`,
  `readingTime`, `excerpt`;
- keep `/api/health` (`{"backend":"bluge","notes":N}`) and the `Server-Timing`
  header and request logging, which are the documented way to tell a
  Bluge-backed site apart from a stale build.

`search-source.jsonl` gains `category` and `readingTime`; the theme's
reference server in `search-server/` is updated to the same contract so the two
do not drift.

### M8 — What stays exactly as it is

Canonical URLs from `obsidian2site.py` reused in front matter, posting index,
Pagefind results and Bluge rows. `uglyURLs = true`. Streaming/batched
generation. Standard-library-only Python. Bluge building from
`search-source.jsonl` and never from Pagefind's private index. Pagefind
running after Hugo. `_validate_built_search_backend` — retargeted from Relearn's
Lunr filenames to Ledger's bundle, so a `bluge`-only build still fails if a
browser index leaks in.

---

## Part C — Vercel

### Findings (verified against Vercel docs, July 2026)

- Two shapes exist. **(a)** `.go` files in `api/` exporting an
  `http.HandlerFunc` become individual functions, zero-config, alongside a
  static build output. **(b)** A root `main.go` (or `cmd/api/main.go`,
  `cmd/server/main.go`) with `framework: "go"` runs a whole `net/http` server
  that must listen on `$PORT`.
- `go.mod` must be at the **project root** in both shapes.
- Function bundles are capped at **250 MB uncompressed**. The 5 GB "large
  functions" path is Node.js and Python only, so it is not available here.
- Max duration 300 s (Hobby); memory 2 GB (Hobby); response body 4.5 MB;
  filesystem read-only apart from `/tmp`.
- Extra files reach a function only if matched by
  `functions[...].includeFiles` in `vercel.json`.

### V1 — Shape: `api/` functions, not a root server

Shape (b) is tempting because `movenotes-site-server` already serves static
files, but it would put `public/` inside the function bundle — a 25k-note site
is already over 250 MB of HTML. Vercel's CDN must serve `public/`, and the Go
code must serve only `/api/*`:

```
<generated site>/
  go.mod                    module movenotes/site      (root: Vercel requirement)
  api/search.go             package handler → Handler
  api/health.go             package handler → Handler
  server/                   package server: index build, query parse, handlers
  cmd/movenotes-site-server/main.go   local binary: flags, static files, listen
  public/                   Hugo output — Vercel's outputDirectory
  vercel.json
```

The local binary keeps its current behaviour and command line. Nothing about
the local workflow in `STATIC_SITE.md` §3 changes.

### V2 — Server refactor  ✅ (step 27)

- Move index building, query parsing and the two HTTP handlers into a `server`
  package with no `log.Fatal` and no `flag` use.
- Configuration resolution order: explicit argument → environment
  (`MOVENOTES_INDEX`, `MOVENOTES_SOURCE`, `MOVENOTES_SITE`, `PORT`) → default.
- Open the index lazily behind `sync.Once` so a cold function does not open it
  until the first search, and share the reader across warm invocations.
- **Never build an index inside a function.** 100k notes take 116 s to index
  and the filesystem is read-only; the index is built at deploy time and
  shipped. A function that finds no index returns 503 with a message saying so.
- ~~Verify `bluge.OpenReader` can open an index on a read-only filesystem.~~
  **It can.** Against an index directory with every write permission removed,
  Bluge opens it, counts it, searches it, and adds no files. No `/tmp` copy, no
  cold-start penalty. A regression test holds it: the whole `api/` half depends
  on it.

### V3 — Size ceiling  ✅ measured (step 28)

**The earlier arithmetic was wrong by about 4×.** Measured on a generated 20,000-
note site: the Bluge index is **97 MB — 4.85 KB/note**, not the 1.11 KB/note the
theme's positions-free index suggested. Where it goes, measured by rebuilding the
same corpus three ways:

| index | size at 20k | per note |
|---|---|---|
| as first shipped (every tag stored) | 127 MB | 6.35 KB |
| display tags only (**shipped now**) | 97 MB | 4.85 KB |
| also without body term positions | 72 MB | 3.60 KB |

So the 250 MB function bundle, shared with a ~30 MB binary, is full at roughly
**45,000 notes** — not 150k. Body positions are the remaining 25 MB and buy
phrase search, which is worth keeping.

The corpus is deliberately near worst case: 181 *unique* words per note, each
becoming a tag, so the inverted index carries 181 keyword terms per document.
Real prose repeats itself and should do better — but the honest number to
document is the measured one, with the caveat.

**Two harder limits arrive first, though**, both measured on that same 20k site:

| limit | value | 20k-note site |
|---|---|---|
| source files per CLI deployment | 15,000 | **49,277** |
| source upload, Hobby / Pro | 100 MB / 1 GB | **397 MB** |
| function bundle | 250 MB | 97 MB index + binary |
| build time | 45 min | n/a — the site is built locally |

A CLI deployment of a 20k-note archive is therefore already impossible, well
before the index ceiling matters. Past ~6k notes the options are a Git-connected
project (the build container clones rather than uploads), or hosting the static
site somewhere without a file-count limit and pointing the theme's search at a
Bluge server elsewhere. The documentation will give the arithmetic, the
`du -sh` command to check, and three options past the ceiling:

1. static search (Pagefind, or whatever Part C promotes) on Vercel, no Go;
2. Bluge on a long-running host (Fly.io, a VPS, a container) with Vercel
   serving the static site and rewriting `/api/*` across;
3. split the archive.

### V4 — `vercel.json` the generator writes

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "outputDirectory": "public",
  "functions": {
    "api/*.go": { "includeFiles": "server/bluge-index/**", "maxDuration": 60 }
  }
}
```

Hugo-module theme mode conflicts with the root `go.mod` the Go runtime needs, so
Vercel deployment requires `--ledger-theme` (a copied theme). The generator
will say so rather than emitting a project that fails at build time.

---

## Part D — Search benchmark: Orama and FlexSearch vs Pagefind

Run in the **theme** repo, which already has the harness
(`scripts/gen-corpus.js`, `scripts/bench.sh`, `scripts/query-latency.js`) and
the Pagefind baseline. Existing tiers are 10k / 100k / 500k; this plan adds
25k and 200k as asked.

### What is actually being asked

Pagefind's advantage is that it *never* loads a whole index: the browser fetches
only the chunks a query touches. Orama (in-memory, restored from a serialized
index via `@orama/plugin-data-persistence`) and FlexSearch v0.8 (export/import,
*or* a persistent IndexedDB adapter) have different shapes. So the comparison
must measure the thing that decides it — bytes and memory before the first
result — and not just warm query latency, where an in-memory index will win
trivially and misleadingly.

### Metrics per backend per tier

1. index build time and index size on disk;
2. **bytes the browser downloads before the first result** (and how much on
   each subsequent query);
3. cold time-to-first-result, including download, deserialize and any IndexedDB
   population;
4. warm latency for four query classes, matching the existing table: filter
   only, ~600 matches, ~4.5k matches, ~20k matches;
5. peak JS heap;
6. latency at page 1,000 of a large result set (Pagefind's flat case).

Backends measured: Pagefind 1.5.2 (baseline, already measured at 10k/100k/500k),
Orama with `plugin-data-persistence`, FlexSearch v0.8 `Document` index in both
fast-boot-import and IndexedDB-persistent configurations. Same corpus, same
machine, same Zipf-distributed vocabulary and tags — the corpus shape matters
and `PERFORMANCE.md` records why.

### Promotion rule, fixed before the numbers arrive

**Outcome (step 35): neither backend passed, and neither was added.** The rule as
written is below; the measurements are in the theme's `PERFORMANCE.md` and
summarised in step 35.

A backend becomes an `obsidian2site.py` option only if, at **25k and above**:

- cold time-to-first-result is no worse than Pagefind's, and
- warm filter-query latency is under 500 ms, and
- first-result download is within ~1.5× Pagefind's, and
- peak heap stays under ~500 MB.

Anything else is written up as refuted in `PERFORMANCE.md`, in the same form as
the five Pagefind hypotheses already recorded there, so it is not retried. The
honest prior: Orama probably fails the download and heap tests at 25k;
FlexSearch-over-IndexedDB is the only candidate with a shape that can compete
at 100k+.

Cost note: the 200k tier is ~15 min to build plus ~25 min to index per search
backend. These steps are long-running and are the natural place to be
interrupted by a usage limit, which is why they come after the migration is
already working.

---

## Steps

Numbering continues the movenotes `PLAN.md`, which ends at Step 19.

### Step 20 — This plan  ✅
Write `LEDGER_MIGRATION_PLAN.md`; add a pointer from `PLAN.md`. No code.

### Step 21 — Theme-side prerequisites *(theme repo)*  ✅
M5, M6 and the theme half of M7, committed as the theme's step 16 (`10f31cc`).

Done: `ledgerHideTitle` / `ledgerHideMeta` / `params.post.heroPlaceholder`; the
tokenising grammar in `query.js` with both adapters updated; `search-server/`
on the superset contract with `main_test.go`; docs in the theme's `AGENTS.md`,
`PLAN.md`, `README.md`, `PERFORMANCE.md` and `search-server/README.md`.
Verified in a browser on a Bluge build and a Pagefind build; the two agree on
every query both can express.

Four findings that change later steps:

1. **Tokenising made quoting load-bearing.** `category:Field notes` used to mean
   the category "Field notes"; it now means a category plus a stray term. The
   theme generates every clause through `_partials/search-clause.html`, so
   `obsidian2site.py` must not hand-build query strings either — steps 22 and 24
   use that partial, or a Python equivalent of the same rule for anything it
   writes into static JSON.
2. **Phrase queries need term positions**, or they match nothing while the
   server looks healthy. The movenotes server already indexes positions; the
   theme's did not, which is how this surfaced.
3. **V3's ceiling arithmetic is understated.** The 111 MB/100k Bluge index was
   measured without positions. The real phrase-capable figure is larger and
   must be re-measured before the Vercel ceiling in `DEPLOY_VERCEL.md` is
   written as a number. Step 27 or 32 measures it; until then, treat 250 MB ÷
   1.11 KB/note as an upper bound on the note count, not a promise.
4. **Pagefind cannot express `since:`/`until:`.** Backends report dropped
   clauses and the UI names them, so a `pagefind`-only movenotes build will tell
   the visitor that date bounds need the Bluge backend rather than silently
   ignoring them. `STATIC_SITE.md`'s search-syntax section has to say which
   backend supports what.

### Step 22 — Generator: project scaffolding *(movenotes)*  ✅
`_write_hugo_project` rewritten for Ledger and every Relearn workaround in
Part A's table deleted. A generated site builds against the real theme with no
warnings, renders the Ledger shell, and lists its notes.

Content is now home (the theme's primed-search view, no body), `about.md`
(`layout: about`, the Getting Started card), `search.md` (`layout: search`), and
`browse-tags.md` with a generated project-level `layouts/browse-tags.html`.
Browse Tags stays a movenotes view over the hashed posting index, which is a
different and much larger set than the Hugo tag taxonomy behind `/tags/`.

Decided while implementing:

- **`uglyURLs` dropped.** Notes carry an explicit `url` ending in `.html`, which
  Hugo honours regardless, so `uglyURLs` only pushed the theme's own pages to
  `/search.html` — which its templates never link to. Auxiliary pages are
  directory-style now and the canonical note URLs are unchanged.
- **`locale`, not `languageCode`.** Hugo deprecated `languageCode` in v0.158 and
  warns on every build; the original key was already right.
- **CSS and JS reach pages through `params.extraCSS` / `params.extraJS`**, two
  small hooks added to the theme, rather than by overriding a theme partial the
  way `custom-header.html` was overridden. Overriding `head.html` to add one
  stylesheet would have copied the theme's whole asset pipeline into the
  generated project, where it would drift.
- **RSS is capped at 20 items** (`[services.rss] limit`). Hugo's default is the
  entire site, which for a six-figure archive is neither useful nor cheap.
- **`googleFonts = false`** and **`heroPlaceholder = false`**: a local archive
  should not need a font CDN to render, and 166k striped placeholders are noise.
- **`--search-backend both` points the theme at Bluge.** Ledger picks one
  adapter at build time, so `both` builds both indexes but selects `bluge`. The
  automatic fall back to Pagefind when the server is not running needs an `auto`
  adapter in the theme — added in step 26, not silently dropped.
- Theme copying now skips `exampleSite`, `node_modules`, `public`, `resources`,
  `bench` and `.git`, which are bulk a generated site must not carry.

Two theme bugs were found by this step and fixed in the theme (`f8e7568`): the
primed home query was built with `printf` rather than the clause partial, so the
default "All notes" label tokenised wrongly; and `section.html` paginated its
whole page set uncapped, which for a 166k-note `notes/` section is ~28k pager
directories.

Note front matter is still Relearn-shaped, so the sidebar and `/tags/` are empty
— step 23 fills them. Tests updated to assert the Ledger structure, including
that none of the deleted partial overrides comes back; 19 pass in
`test_obsidian2site.py`, 87 across the suite.

### Step 23 — Generator: note front matter and taxonomy *(movenotes)*  ✅
`_frontmatter_json` now emits `categories`, `tags`, and
`ledgerHideTitle`/`ledgerHideMeta`; every Relearn field is gone (`hidden`,
`disableBreadcrumb`, `disableToc`, `hideAuthorDate`, `movenotes_hide_heading`,
`movenotes_explicit_tags`). M3's cap and M4's `--category-mode` /
`--category-name` are implemented, with the measurement above.

Deviations from this step as planned, both to keep front matter small — it is
repeated once per note, so 166k notes pay for every field:

- **No `summary`.** Every summary movenotes could write is the first N characters
  of the body, which is exactly what Hugo's `.Summary` already gives result
  cards, and exactly what step 21 stopped the post view from using as a
  standfirst because it duplicates the text directly below it. Search results
  still get a real summary: it is in `search-source.jsonl` for Bluge, and
  Pagefind falls back to its own excerpt.
- **No `readingTime`.** `.ReadingTime` computes it. The Bluge JSONL needs the
  number, and that is step 25's field to add.

The promotion pass is a second pass, not the `ORDER BY` this step assumed: the
counts it orders by are not complete until every note has been converted, and
buffering 166k bodies to defer writing them is not an option. See M3.

Verified against a generated 10-note vault and the 5,000-note synthetic corpus:
front matter carries the right categories and tags, the cap demotes the right
tags and leaves them searchable, promotion is byte-identical across two runs, the
sidebar fills with categories and tags, and a Twitter note renders with its title
in the document outline but off the screen, no meta row, and no hero. At 5,000
notes in one over-limit category the archive emits **zero pager directories** and
the sidebar is byte-identical between `/` and note 4,999 — decision D2 and the
`partialCached` invariant both holding through generated config. 23 tests in
`test_obsidian2site.py`, 91 across the suite.

### Step 24 — Generator: Browse Tags and exact-tag results on Ledger *(movenotes)*  ✅
**The generated project now has no shortcodes at all**, and 451 lines of
hand-written search UI are gone.

`/search/` is the theme's own view: its grammar, its two adapters, its results.
The two search shortcodes (`movenotes-search`, 451 lines across the Pagefind and
Bluge variants) are deleted outright — everything they did that still matters is
either in the theme now or on Browse Tags.

**Browse Tags is the one view that stays movenotes'**, because it answers for
every tag, not just the ones that reached the Hugo taxonomy. A generated word
tag like `housing` is not a taxonomy term and not a Pagefind filter; the hashed
posting index is the only thing that can resolve it. It grew the exact-tag
results the search page used to hold, so the browser and the results for a tag
are now one page: `/browse-tags/` and `/browse-tags/?tag=x`.

Structural decisions:

- **No shortcodes.** Getting Started is plain Markdown in `about.md` — a `{{< >}}`
  shortcode's output is never run through the Markdown renderer, and that page is
  prose with a table. Browse Tags needs `resources.Get`/`js.Build`, so its body
  belongs in a layout. Neither needed a shortcode indirection.
- **The tag page imports the theme's `paging.js`** through Hugo's asset pipeline
  (`assets/js/movenotes-tags.js`, bundled with `js.Build`). The theme's AGENTS.md
  records that the page-number windowing rule already exists three times there; a
  fourth copy in generated JS would have been the trap it warns about. Verified
  that a project asset can import a theme asset before relying on it.
- **The tag filter borrows the theme's search-bar classes but none of its data
  attributes**, so the theme's search controller does not try to drive it.
- **Document chunks carry a date** (`[url, title, date]`, manifest version 3) so
  an exact-tag result card looks like every other card on the site. Ten bytes a
  note, read 512 notes at a time.
- **`_SITE_CSS`: 205 lines → 65.** Result cards, the tag grid, headings, pagers,
  the search bar and the empty state are all the theme's. What is left is the two
  Getting Started cards, a lead paragraph, and one spacing fix — written against
  the theme's tokens so all three palettes keep working.

Verified in a browser: the filter's three states (frequent, too-short, matching);
a tag's badge count and the number of results it opens are the same number;
`?tag=housing` resolves a generated word tag Pagefind cannot filter on; paging
across three pages repeats and skips nothing, with correct `aria-current` and
disabled ends; an unknown tag gets the empty state; and the Getting Started
Markdown renders as a table rather than as literal pipes.

### Step 25 — Bluge server: M7 contract *(movenotes + theme)*  ✅
`site_server` now speaks the superset contract, and the theme's UI drives it end
to end. The theme's reference server was already moved in step 21, so this step
brought movenotes' to the same shape.

**The server-side grammar parser is deleted** — `splitQuery`, `parseQuery`, the
`since|until|tag` regex, ~110 lines. The grammar is parsed once, client-side, in
`query.js`; this server receives fields (`q`, repeatable `phrase`/`category`/
`tag`, `since`, `until`) and must never grow a second parser. A test asserts
those symbols stay gone.

The rest: `page`/`per` accepted alongside `offset`/`limit` with both resolved in
the response; `backend`, `query`, `total`, `page`, `per`, `offset`, `limit`;
result items carrying `title`, `summary`, `url`, `category`, `tags`, `date`,
`readingTime`; `Server-Timing` and one log line per request; 400 on a malformed
or inverted date range; `/api/health` returning `{"backend":"bluge","notes":N}`.

`search-source.jsonl` gained `category` and `readingTime`. Reading time is
computed in Python with Hugo's own rule (words ÷ 213, rounded up) because a
result rendered from the index has no Hugo page behind it to ask. `summary` was
already there. Every tag still reaches Bluge — generated word tags included, and
the ones the taxonomy cap left out — so `tag:` answers for all of them in
server-side search, which is the compensation for the cap.

Deviations from M7 as written:

- **No `excerpt` field.** M7 listed it for continuity with the old response, but
  the only consumer was the search shortcode deleted in step 24, and `summary`
  carries the same text. A duplicate field with no reader is worse than a
  removed one.
- **`/api/health` reports `notes`, not `documents`.** The M7 contract's key wins;
  nothing consumed the old one.

One defect the browser caught: cards showed `2026-07-28T18:08:00Z · 1 min`
because the server returned the note's full RFC 3339 timestamp where the contract
specifies `YYYY-MM-DD`. Trimmed at the result boundary — the stored value and the
indexed date field keep full precision, so date-range queries are unaffected.

Verified against the generated site with the real server: category filter, two
tags ANDed, phrase, free terms, date window, `offset`/`limit` paging, a generated
word tag, and a rejected bad date — first over HTTP, then through the theme's
search UI, where `tag:housing` returns the same 9 notes the Browse Tags badge
claims. 23 tests in `test_obsidian2site.py`, 91 across the Python suite, and the
Go server's own tests pin the parsing rules two clients depend on.

### Step 26 — Build pipeline, `auto` backend, and backend validation  ✅
**`--search-backend both` finally means what it says.** The theme gained an
`auto` adapter (its step 17, `62e4bf3`): one probe of `/api/health` per page
load, then delegation to Bluge or Pagefind. `both` maps to it, so one generated
build works as static files *and* behind the Go server, instead of being wrong in
one of them. If the server stops mid-session the first failing query falls back
to Pagefind for the rest of the session, one-way.

**`_validate_built_search_backend` was rewritten, not retargeted.** Grepping for
Lunr filenames no longer means anything — the theme ships no built-in search
runtime. What decides which index a visitor downloads is the JSON config the
theme embeds in every page carrying the search view, so that is what the check
reads. It now catches:

| mistake | why it matters |
|---|---|
| pages configure a backend other than the one asked for | a `bluge` build shipping `"backend":"pagefind"` looks fine and quietly loads a browser index |
| `auto`/`pagefind` build with no `public/pagefind/` | nothing to fall back to |
| a Bluge-only build whose HTML loads the Pagefind runtime | the old check, kept |
| no search view in the output at all | a missing or stale theme |

All five outcomes were exercised against the real built site by mutating copies
of it, and again as a unit test on synthetic HTML.

The validation moved to *after* the Pagefind step in `--build`, since it now
checks that the index a backend needs exists.

Two fake-Hugo build-ordering tests had to start emitting a search view: they were
failing the new check for the right reason and the wrong test.

Verified end to end:

- `--build` runs Hugo → Pagefind → `go mod tidy` → `go build` → Bluge prebuild,
  and validates, on a generated vault.
- **The real toolchain**, not a hand-made vault: `sample/source1` through
  `joplin2sql.py`, `sample/twitter-archive` through `twitterx2sql.py`, then
  `sql2obsidian.py`, then `obsidian2site.py --build`. A genuinely imported
  Twitter note renders with its title in the document outline but off screen, no
  meta row, no hero, the right category filter, and its attachment embedded.
- One generated build served two ways: static, it probes, gets a 404 and uses
  Pagefind (`tag:pizza` → 8); behind the generated server it gets `bluge` and
  answers `tag:pizza since:2026-07-25` → 4 with no unsupported-clause notice and
  no Pagefind download at all.

`--build` for the new layout; retarget `_validate_built_search_backend` from
Relearn's Lunr filenames to Ledger's bundle; confirm a `bluge`-only build emits
no browser search runtime. Run the full generated pipeline on the `sample/`
vault end to end.

### Step 27 — Server refactor for Vercel *(movenotes)*  ✅
One `search` package, two entry points:

```
search/                      config, index, query, handlers — no flags, no
                             log.Fatal, no listening
cmd/movenotes-site-server/   local process: flags, static files, one port
api/                         Search and Health, for a serverless runtime
```

**The open question is answered: Bluge opens a read-only index directory.** With
every write permission removed it opens, counts, searches, and adds no files — so
no `/tmp` copy and no cold-start penalty on a read-only serverless filesystem.
A regression test holds it, because the entire `api/` half rests on it.

- **Configuration resolves explicit → environment → default**, so a flag beats a
  deployment's `MOVENOTES_INDEX`/`MOVENOTES_SOURCE`/`MOVENOTES_SITE`, and a
  platform with no command line still configures the same binary. `-listen` falls
  back to `$PORT`, then to loopback — running it by hand should not put a personal
  archive on the network.
- **The index is opened lazily behind `sync.Once`** and shared for the life of the
  instance, so a cold start never asked to search pays nothing for it.
- **Handlers never build an index.** Indexing takes minutes and needs a writable
  filesystem; a missing index is an operational error, answered **503** with the
  command that fixes it. Tests assert both that the status is 503 and that the
  request created no index directory.
- **`/api/health` fails when the index is missing** rather than reporting a
  healthy backend — the theme's `auto` adapter reads it to decide whether a server
  is answering, and would otherwise pick Bluge and then fail every query.
- The two `api` functions export `Search` and `Health` rather than both exporting
  `Handler`: distinct names keep one Go package that `go vet ./...` can check,
  while Vercel accepts any exported `http.HandlerFunc` name.

The local command line is unchanged, and `--build` still produces the same
`server/movenotes-site-server` — only its build target moved to
`./cmd/movenotes-site-server`. Verified by generating a site and driving it both
with flags and with environment variables plus `$PORT`.

Tests: Go tests over both halves (contract, read-only index, 503 paths,
env-only configuration), and a Python test asserting the shared package contains
no process concerns — comment-stripped, since the package's own doc comment says
"no flags, no log.Fatal, no listening".

### Step 28 — Generator emits the Vercel project *(movenotes)*  ✅
`--vercel` — a flag, not always-on, because a root `go.mod` collides with Hugo's
module mode — emits `vercel.json`, `.vercelignore`, and for Bluge builds a root Go
module with `api/search.go` and `api/health.go`.

**Deployment shape: build locally, deploy the output.** No `buildCommand`. Hugo,
Pagefind and a Bluge index inside one 45-minute Vercel build is not a plan for a
six-figure archive, and it makes the index a build product whose path into the
function bundle is unverifiable. Built locally, the index is deployment *source*.

- **The root module is derived from `server/go.mod`**, every requirement rewritten
  as indirect, so the two cannot drift. Verified by building `./api/...` in a
  generated project with no `go mod tidy` — which caught a parser bug that
  dropped the one direct dependency, because `require x v1` and `require (` both
  start with `require`.
- **`--search-backend pagefind` + `--vercel` emits no Go at all** and needs no
  copied theme. It also adds Hugo's own `go.mod` to `.vercelignore`: a root
  `go.mod` is precisely what makes Vercel's Go runtime decide a project is Go.
- **`--vercel` with Bluge refuses without `--ledger-theme`**, exits 1, and creates
  nothing.
- **`--build --vercel` measures the site against Vercel's limits** and says which
  ones it fails. See V3: at 20,000 notes the file-count and upload limits are
  already exceeded, long before the index ceiling.

**Two defects found while measuring, both fixed:**

1. **The Bluge index was 31% larger than it needed to be.** Every tag was stored
   for display, including all ~181 generated content words per note. Now only the
   written tags are stored; every tag is still *indexed*, so `tag:housing` finds
   a generated word tag exactly as before. 127 MB → 97 MB at 20k notes.
2. **Result cards were showing generated content words as tags** — a Twitter note
   displayed `#canada #housing #jul`, where "jul" comes from the date in its
   footer. Cards now show the note's written tags, which for that note is
   `#pizza`. This was visible in step 25's own verification output and I read past
   it.

### Step 29 — `DEPLOY_VERCEL.md` *(movenotes)*  ✅
Written, and it leads with the verdict rather than burying it: which archive
sizes can be deployed which way. Up to ~5,000 notes anything works; to ~45,000
it has to be a Git-connected project; past that the index no longer fits a
function and Bluge belongs on a host that keeps a process.

Contents: prerequisites, the generating command, what each emitted file is for
and why (including why there is no `buildCommand` and no `trailingSlash`), both
deployment paths, environment configuration, a verification sequence, what runs
where (read-only filesystem, no request-time indexing, cold starts and archiving),
the measured limit table with the commands to check your own archive, three
options past the ceiling, and a troubleshooting table. Cites the Go runtime,
function-limits, runtimes, platform-limits and `vercel.json` pages.

**The most useful thing in it is a warning that only exists because of `auto`:**
if the index does not ship, the probe fails, the browser falls back to Pagefind,
and search keeps working — so a broken Bluge deployment looks fine. The only
symptom is `since:`/`until:` reporting themselves unsupported. Check
`/api/health` explicitly; it answers 503 naming the path it looked for.

Two fixes while writing it, both from reading my own emitted config as a user
would:

- **`trailingSlash: false` removed from `vercel.json`.** The theme links to
  `/search/` and `/tags/x/` while notes are `.html` files, so enforcing either
  form would have turned every internal navigation into a 308 redirect. I added
  that line last step without thinking it through.
- **`--vercel` no longer gitignores `public/` and `server/bluge-index/`.** A Git
  deployment ships exactly those two, and the alternative was a documented
  instruction to start by editing `.gitignore` — a step that exists only because
  the generator got it wrong.

### Step 30 — `DEPLOY_GITHUB_PAGES.md` *(movenotes + theme)*  ✅
Written, and it leads with the size question because that is what decides
whether GitHub Pages is possible at all: a published site may be no larger than
**1 GB**, and an archive builds to ~20 KB/note, so the host tops out around
**50,000 notes**.

Contents: generating with the right `--base-url` for a project versus a user
site, pushing, the Actions workflow (Hugo's own, plus a Pagefind step, minus the
Dart Sass and Go steps this theme does not need), a five-point verification list
on the published site, the limit table with measuring commands, and the subpath
section below.

**This step found the largest defect of the migration so far: every subpath
deployment was broken, in both repositories.** Hugo's `relURL` drops the
baseURL's path when its argument begins with a slash —

```
"/search/" | relURL  ->  /search/            wrong
"search/"  | relURL  ->  /archive/search/    right
```

— and *every* site-absolute URL in the theme (23 of them) and in the generated
templates was written the first way. On a GitHub Pages project site, which is the
normal case, that means no stylesheet, no script, no working link, and no
search result that resolves.

Fixed by routing them all through a new theme partial, `site-url.html`, rather
than deleting 23 slashes and hoping (theme step 18, `acdc67e`). Three runtime
consequences needed more:

- the search config's `bundlePath`, `endpoint` and `healthEndpoint` are fetched by
  the browser, so they carry the subpath, while absolute URLs still pass through;
- **Pagefind needed `baseUrl` in `options()`** — it records result URLs relative
  to the directory it indexed, so every result linked to the domain root;
- **the exact-tag index's stored note URLs** are site-root-relative, so Browse
  Tags resolves them against `siteRoot` instead of assigning them to `href`. I
  introduced that one in step 24 by dropping the `new URL(url, siteRoot)` the
  Relearn-era shortcode had.

Verified by building both the theme's `exampleSite` and a generated archive with
`--base-url https://example.github.io/archive/`, serving them under `/archive/`,
and driving search and Browse Tags in a browser: correct counts, every result
href under `/archive/`, a followed result link returning 200, and no request
outside the subpath but the favicon.

### Step 31 — Docs and invariants pass *(movenotes)*  ✅
`STATIC_SITE.md` rewritten around what the site now is rather than what was
suppressed: the three ways in, a backend comparison table with the crossover from
the theme's measurements, the real generated layout, the two-tier tag model with
the measurement behind its cap, and the subpath section that step 30 earned. It
states plainly that there are no shortcodes and no theme-partial overrides, which
is the whole difference from the Relearn build — verified against a real
generation, path by path.

`README.md`'s publishing section rewritten, `requirements.txt` corrected,
`PERFORMANCE_REVIEW.md`'s two Relearn sentences made theme-agnostic,
`PLAN.md` marked so its steps 1–19 read as history, and `AGENTS.md` given the
invariants this migration created — the sidebar rule, bounded pagers, the two tag
tiers, one clause generator, one URL resolver, `extraCSS`/`extraJS` instead of
partial overrides.

`CHANGELOG.md` gained a 3.36 entry covering steps 20–31, and
`obsidian2site.py` is 3.36.

`grep -ri relearn` now returns only deliberate mentions: the deprecated
`--relearn-theme` alias and its tests, historical changelog and plan entries, and
this document. Cross-checked for stale references to things that no longer exist
(`search.html?tag=`, `movenotes-start`, `sidebarmenus`, `themeVariant`, Lunr) —
all remaining hits are in history, none in instructions.

### Step 32 — Benchmark tiers 25k and 200k, Pagefind baseline *(theme)*  ✅
The harness already accepted arbitrary tiers, so the work was the metrics — and
the metric turned out to need a new tool.

**Bytes cannot be measured in the browser.** Pagefind fetches its index from a
SharedWorker, and a worker's requests never appear in the page's Resource Timing
entries, so an in-page count reports **zero bytes** for Pagefind while correctly
counting a backend that fetches from the page. That would have flattered Pagefind
in exactly the comparison this step exists to set up. `scripts/serve-counting.js`
is a dependency-free static server that tallies what it serves, with
`/__bytes?reset=1` to start a measurement — the same measurement for every
backend.

Also fixed in the probe: `transferSize` is 0 for a cache hit, so re-running a
query reported zero bytes; it uses `encodedBodySize` now, which answers "how many
bytes does this query need" rather than "did this browser already have them".

**The 25k baseline, and the sharpest result of the whole benchmark so far.** Each
row is one cold page load plus one query, nothing cached:

| cold load | matches | Pagefind bytes | requests |
|---|---|---|---|
| free text | 2,327 | **369 KB** | 17 |
| `tag:` filter | 39 | **13,637 KB** | 443 |
| no query at all | 25,000 | 13,497 KB | many |

A filtered query costs **37× the bytes** of a free-text one and does not care how
selective it is: 39 matches cost the same as 25,000, because the cost is loading
the filter index — 443 requests for 250 tag values — before filtering can start.
Warm, queries cost 5–139 KB and paging is 2 ms. Peak heap stayed 6–31 MB.

Two consequences worth acting on later: visiting `/search/` with no query pays
the full filter cost, because the empty query is a date-sorted matchAll — the
page's resting state is its most expensive request. And the numbers above are what
Orama and FlexSearch must be judged against; a backend that restores a whole
serialized index into memory has to beat 369 KB on free text, which nothing that
works that way can.

**At 200,000 notes it is worse than "slow".** A cold `tag:` query downloads
**103 MB over 2,200 requests** and takes 56 s, and warm — with the filter index
cached, so 6 KB on the wire — a query matching 54,854 notes takes **132 seconds**.
So Pagefind has two independent limits: cold bytes scale with the number of tag
values (~52 KB each, at both tiers), and warm latency scales with match count.
Free text stays cheap and sublinear: 369 KB at 25k, 1,759 KB at 200k.

Build and index, both tiers:

| notes | build | peak RSS | public | HTML files | Pagefind | index |
|---|---|---|---|---|---|---|
| 25,000 | 58.3 s | 1.3 GB | 838 MB | 26,285 | 141 s | 114 MB |
| 200,000 | 631.0 s | 6.2 GB | 6.5 GB | 203,224 | 1,086 s | 901 MB |

Both pager caps bind at both tiers, and 200k emits 203,224 files for 200,000
notes — 1.02 per note, against 1.18 for the uncapped 500k build.

Committed as the theme's step 19 (`d090073`). The 200k corpus and built site are
left in `bench/` so step 33 can index the same corpus rather than regenerate it.

Also: the older 10k/100k/500k rows predate `maxSectionPagerPages`, so they include
a pager directory per six notes — ~83,000 of them at 500k. `results.tsv` gained
`home_pagers`, `section_pagers` and `term_dirs` columns so the caps are visible
rather than inferred, and the historical rows are marked `-` rather than
backfilled with guesses.

### Step 33 — Orama adapter and measurement *(theme)*  ✅
Built, measured, **not promoted** — the theme's step 20 (`00194af`).

Orama holds its whole index in memory, so the measurement is short: at 25,000
notes a visitor downloads **223 MB** (bodies indexed) or **33 MB** (titles and
summaries only) and waits **11–19 s** for the first result, against Pagefind's
**369 KB** and about a second.

| criterion (fixed in Part D before measuring) | result |
|---|---|
| cold time to first result ≤ Pagefind's | ❌ 11.2–18.9 s vs ~1 s |
| first-result download within ~1.5× | ❌ 90× to 600× |
| warm filter query < 500 ms | ✅ 19–102 ms |
| peak heap < ~500 MB | ✅ 82 MB / 364 MB, on a desktop |

Warm, Orama is genuinely extraordinary: **35 ms** for a filter over 8,924 of
25,000 notes where Pagefind takes **6,006 ms**. It is the wrong half of the trade
at this scale, and the rule says so.

**100k and 200k were deliberately not measured.** The index is linear, so 200k
projects to ~1.8 GB and the Node builder would need ~14 GB of RSS. No measurement
could change a decision already failed by two orders of magnitude at the smallest
tier, and the plan's rule gates promotion on 25k "and above". The projection is
labelled arithmetic in `PERFORMANCE.md`, not measurement — the honest version of
skipping work.

The adapter stays in the theme, registered and documented as a **small-site**
option: at a few thousand notes its index is a few megabytes, and it answers the
`since:`/`until:` bounds Pagefind cannot express at all. It does not enter
`obsidian2site.py`, which targets archives 100× larger.

One finding that would have cost every site something: a static
`import '@orama/orama'` in the adapter makes esbuild inline the library into the
shared search bundle — **8.9 KB → 88.2 KB, for every site including Pagefind
ones**. It is built as its own asset and imported from a runtime URL now, and only
when a site selects the backend.

### Step 34 — FlexSearch adapter and measurement *(theme)*  ✅
Built in both configurations, measured, **not promoted** — the theme's step 21
(`da2745a`).

The IndexedDB configuration was the plan's one real hope: "the only candidate with
a shape that can compete at 100k+". It half-delivers.

| | index at 25k | first result | bytes | heap |
|---|---|---|---|---|
| memory, title+body | 342.7 MB | — | 342.7 MB | — |
| memory, title+summary | 74.4 MB | 13.1 s | 74.5 MB | 133 MB |
| indexeddb, first visit | 74.4 MB | 24.3 s | 74.5 MB | 4 MB |
| indexeddb, second visit | — | 14.8 s | **136 KB** | 16 MB |
| *Pagefind* | 114 MB | ~1 s | **0.37 MB** | 6–31 MB |

**What it wins:** repeat visits download nothing, and the heap drops to 4–16 MB —
lower than Pagefind's. The memory-pressure objection to a client-side index is
genuinely solved.

**What it does not:** the first visit still transfers the whole index, because a
browser cannot be shipped a prepopulated IndexedDB. Time-to-first-result stays at
~15 s even on a repeat visit, since reading 40 MB back out of IndexedDB is not
free. And queries get *slower* than in memory — 1,313 ms against 109 ms — because
each one now goes through storage.

FlexSearch also covers the least of the grammar: no count API (whole match sets are
materialised for a total and for paging, which is where that 1,313 ms goes), no
numeric range filter (dates applied after searching, reported approximate), tag
clauses ORed rather than ANDed (intersected in the adapter), no phrase operator.

I made one of the two recorded traps myself and measured it before noticing:
detecting an already-populated IndexedDB with an empty tag filter matches nothing
whether or not data is there, so every visit silently re-downloaded 74.5 MB while
the feature appeared to work. The fix is a tag search for a value the builder
records as present. `db.has()` is not usable — it throws on a mounted-but-unqueried
store.

### Step 35 — Promote what earned it *(movenotes + theme)*  ✅
**Nothing earned it, so nothing was promoted.** `--search-backend` still offers
`both`, `bluge` and `pagefind`; `obsidian2site.py` gained no option, `--build`
gained no step, and `_validate_built_search_backend` needed no new case.

That is the rule working, not the rule being ignored. Both engines were built as
real theme backends against the real adapter contract, measured on the same corpus
as Pagefind with the same instrumentation, and failed the same criterion:

| | index at 25k | bytes to first result | first result | heap |
|---|---|---|---|---|
| **Pagefind** | 114 MB | **0.37 MB** free text | **~1 s** | 6–31 MB |
| Orama, full text | 223 MB | 223 MB | 18.9 s | 364 MB |
| Orama, summaries | 33 MB | 33.4 MB | 11.2 s | 82 MB |
| FlexSearch, full text | 343 MB | 343 MB | — | — |
| FlexSearch, summaries | 74 MB | 74.5 MB | 13.1 s | 133 MB |
| FlexSearch + IndexedDB | 74 MB | 74.5 MB then **136 KB** | 24.3 s then 14.8 s | **4–16 MB** |

**One sentence explains every row: an in-browser index has to cross the wire at
least once, and Pagefind's does not.** Pagefind fetches the fragments a query
touches — 0.37 MB of a 114 MB index — while the others must transfer the whole
thing before answering anything. FlexSearch over IndexedDB is the only one that
escapes the *repeat* cost, and it still needs ~15 s to a first result and holds the
first visit at 74.5 MB.

What the losing side won, recorded because it is real: warm queries. Orama answers
a filter over 8,924 of 25,000 notes in **35 ms** where Pagefind takes **6,006 ms**,
and FlexSearch over IndexedDB holds the smallest heap of anything measured, 4–16 MB.
Neither is worth 33–343 MB up front on an archive this size.

Both adapters stay in the theme, registered and documented as small-site options —
at a few thousand notes their indexes are a few megabytes, and Orama answers the
`since:`/`until:` bounds Pagefind cannot express. Neither is offered by the
generator, which targets archives 100× larger.

The settled decision is written where someone would look before re-opening it:
`STATIC_SITE.md` ("there is no third static option, and that was tested rather
than assumed"), `DEPLOY_GITHUB_PAGES.md`, the theme's `README.md` and
`PERFORMANCE.md`, and movenotes' `CHANGELOG.md`.

### Step 35b — Result ordering and a resting search page *(movenotes + theme)*  ✅
Added after step 35, from the user's requirement: *"Every query should return
results ordered by date descending. Notes showing up in an unpredictable order or
having to go to the last page for most recent notes would not be useful. Going to
the Search page, showing the results can be deferred until the user initiates a
search; an empty search being the same as `category:"All notes"`."*

**Ordering.** The date sort had been conditional — requested only where there was
no text term to rank by. Made unconditional in all four theme adapters and both Go
servers (`site_server/search/query.go`, the theme's `search-server/main.go`), with
`sort=score` left as an escape hatch no theme code sends. This also completes the
Hugo/backend invariant from step 30: `term.html` renders page 1 in date order and
the backend serves page 2, which was only sound for the query shapes that already
sorted.

The cost was the reason it had been conditional, and it did not materialise. At
25k, cold, bytes counted at the server:

| query | matches | latency | bytes |
|---|---|---|---|
| free text | 2,327 | 1,192 ms | 369 KB |
| filter + text | 175 | 555 ms | 62 KB |
| `tag:` alone | 497 | 8,962 ms | 13,274 KB |
| empty = `category:"All notes"` | 25,000 | 7,006 ms | 5 KB (warm) |

369 KB is what the unsorted free-text query cost, so the sort is free on the path
visitors actually take; the expensive rows are the null-term shapes, unchanged.
Page 2 was verified to continue page 1's sequence with no overlap.

**A resting search page.** Arriving at `/search/` with no query ran a matchAll,
the most expensive request Pagefind can answer. It now shows a prompt and issues
nothing until a query is submitted: **13,503 KB / 442 requests → 86 KB / 12
requests, none of them Pagefind's**. The same lever as step 30 — the win is in not
searching.

Nothing is lost, because the two idle meanings coincide: the grammar already
discarded `category:"All notes"` (Joplin's phrasing for "no filter"), so it and an
empty box are one request. Verified identical on the theme's exampleSite — 17
notes, same order — and across four query shapes on the 25k corpus.

Documented in `STATIC_SITE.md`, the generated Getting Started page, the theme's
`README.md`, `AGENTS.md` (as an invariant, not a preference), `PERFORMANCE.md`
(hypotheses 6 and 7) and `search-server/README.md`.

### Step 36 — Real-archive test and release
User runs the pipeline against a real Twitter/X archive. Fix what it finds.
Then, with the user's agreement, push `develop`.

**Run 1: 166,654 notes, `--search-backend bluge --build`.** The pipeline
completed and the site served. Two defects found, both in Part E.

---

## Part E — What the real archive found

Findings from the step-36 run on a 166,654-note Twitter/X vault. Numbered
continuing from step 36 so the sequence stays readable.

### Step 37 — Diagnose: URLs are not searchable  ✅
**Symptom.** Searching a URL returns nothing on a Bluge site:
`https://globalnews.ca/news/10063968/more-canadians-housing-need-cmhc-estimates-report/`
→ 0, `https://x.com/i/web/status/294324228247937024` → 0,
`tag:vanre https://x.com/DrCameronMurray/status/1591306824804106240` → 0. A few
URL queries *do* return results, which made the failure look random.

**Cause.** `_searchable_text()` in `obsidian2site.py:590` deletes every URL from
the text that becomes the Bluge `body` and `summary`:

```python
text = _MARKDOWN_LINK_RE.sub(lambda match: match.group(2), text)  # keeps the label, drops the target
text = re.sub(r"<https?://[^>]+>", " ", text, flags=re.IGNORECASE)
text = re.sub(r"https?://\S+", " ", text)
```

The stripping is deliberate but was a *display* decision — the comment above it
is about `[label](` fragments appearing in summaries. Nothing about it was meant
to decide what is searchable, and the effect was never measured against a corpus
with URLs in it.

Verified against the user's own generated data, not inferred:

```
note body in the vault:  https://globalnews.ca/news/10063968/more-canadians-...
same note in search-source.jsonl:
  "@JohnPasalis \"legalize housing\" - making illegal suites… In reply to:
   @JohnPasalis … 3 million more Canadians in housing need than CMHC estimates
   suggest: report … 10:22 AM · Nov 02, 2023 🔁 0 💙 0"
```

Occurrence counts across all 166,654 indexed records:

| string | in `title` | in `body` |
|---|---|---|
| `10063968` | 0 | 0 |
| `globalnews.ca` | 1 | 0 |
| `ncbi.nlm.nih.gov` | 8,667 | 0 |
| `PMC4603207` | 11 | 0 |
| `x.com/i/web/status` | 0 | 0 |

**The `body` field contains no URLs at all.** Every URL query that appeared to
work was matching the *title*, which is stored raw and keeps whatever URL the
tweet text happened to contain — `PMC4603207` → 11 hits, `globalnews.ca` → 1 hit.
Two more were false positives of a different kind:
`more-canadians-housing-need-cmhc-estimates-report` → 2 hits is the analyser
splitting on `-` and matching the ordinary words *more/canadians/housing/need/
report* in unrelated notes; the string itself appears in no record.

**Not an analyser problem.** Bluge's default is `NewStandardAnalyzer()` —
unicode tokenizer plus lowercase, no stemming and no stop-word list — and it
tokenises URLs well, keeping hosts whole and splitting paths into words:

```
https://globalnews.ca/news/10063968/more-canadians-housing-need-cmhc-estimates-report/
  [https] [globalnews.ca] [news] [10063968] [more] [canadians] [housing] [need]
  [cmhc] [estimates] [report]
http://www.upworthy.com/a-12-year-old-egyptian-boy-…-genius-4?g=2
  [http] [www.upworthy.com] [a] [12] [year] [old] [egyptian] [boy] … [g] [2]
http://t.co/CT…                    [http] [t.co] [ct]
```

Every query the user reported would match on these tokens if the text were
indexed, including the component searches they asked for — `globalnews.ca news`
and `https://globalnews.ca/news/` both reduce to tokens that a note carrying that
URL would hold. So the fix is to stop deleting the text, not to change how it is
analysed.

**The site disagrees with its own index.** The built page shows the URL twice —
`<a href=https://globalnews.ca/news/10063968/…>https://globalnews.ca/news/10063968/…</a>`
— so a visitor reads a URL the search index does not have. This also splits the
two backends, because Pagefind indexes the rendered HTML:

| where the URL is | Bluge | Pagefind |
|---|---|---|
| bare URL (rendered as an autolink) | ✗ stripped from the source | ✓ indexed as visible text |
| markdown/HTML link target (`[label](url)`) | ✗ stripped | ✗ `href` is not visible text |

So `--search-backend bluge` is strictly worse than `pagefind` here, and the user
asked for both cases: *"whether it is a bare link or in an HTML link."*

### Step 38 — Index URLs for the Bluge backend *(movenotes)*  ✅
Keep the URLs instead of discarding them, without regressing what the stripping
was actually protecting.

- Split the one function in two: the prose text (URLs removed, unchanged) and
  the URLs it removed, returned alongside.
- `body` becomes prose + the URL text. Body is indexed and **not** stored, so
  nothing a result card shows changes.
- `summary`, `readingTime` and tag extraction keep using the clean prose text:
  summary is displayed, reading time would inflate, and feeding URL components
  to `_extract_tags` would add a word tag per path segment on top of 121,433
  existing tags.
- Both link forms are covered: markdown/HTML targets and bare URLs.
- Appending to `body` rather than adding a separate `urls` field is deliberate.
  `buildQuery` ANDs terms *within* a field and ORs across fields, so a mixed
  query like `Pizza vs any celebrity https://trends.google.com/…` only matches
  if the prose words and the URL tokens are in the same field.

**Done.** `_searchable_text()` became `_searchable_parts()`, returning the prose
and the URLs it removed; `_searchable_text()` remains as the wrapper for the
callers that only want prose (tag extraction). Markdown/HTML link targets, angle
autolinks and bare URLs are all collected, deduped in order, and appended to
`body` by `_search_body()`. Relative destinations are skipped — the note they
point at is already searchable as itself. Auto-linked `@mentions` come along for
free, so `https://x.com/JohnPasalis` is now findable too.

Verified end to end on the note from the report — generator → `search-source.jsonl`
→ `BuildIndex` → live `/api/search`, every query the user ran:

| query | before | after |
|---|---|---|
| `https://globalnews.ca/news/10063968/more-canadians-…-report/` | 0 | 1 |
| `10063968/more-canadians-housing-need-cmhc-estimates-report/` | 0 | 1 |
| `globalnews.ca news` | 1 (a title, not this note) | 1 |
| `https://globalnews.ca/news/` | 1 (a title) | 1 |
| `https://x.com/i/web/status/1720129280733217258` | 0 | 1 |
| `tag:affordable` + the globalnews URL | 0 | 1 |

Tests: `_searchable_parts` over all four link forms plus a fenced block, and an
end-to-end generator test asserting the URL reaches `body`, appears once rather
than twice, stays out of `summary` and out of the tag list, and leaves reading
time equal to the same note without links. On the Go side,
`TestURLsInBodyAreSearchable` runs the reported queries — including the ones with
`&` query strings, `%2F` escapes and the truncated `http://t.co/CT…` — against a
built index. 99 Python tests, Go suite clean.

### Step 39 — Pagefind parity: index link targets *(theme)*
Bare URLs already work on Pagefind; `href` targets do not. Pagefind can index an
attribute (`data-pagefind-index-attrs`), which a Hugo link render hook can apply
to links in note content. Investigate, then measure the index-size cost before
adopting — the Pagefind index is already the constraint on a static deployment.

### Step 40 — Measure what indexing URLs costs
On a bench tier: index size, build time, and the latency of the reported queries
before and after. The Bluge index was 4.85 KB/note, which sets the Vercel
ceiling (V3) — if URLs move it materially, `DEPLOY_VERCEL.md` needs the new
number.

### Step 41 — Report progress during the post-Hugo validation *(movenotes)*
**Symptom.** A long silent gap between Hugo's `Total in 500227 ms` and
`building Bluge site server...`, with no output, which reads as a hang.

**Cause.** `_validate_built_search_backend()` walks `public/` and reads every
built HTML file — 177,682 files and 5.6 GB on this archive — running two regexes
over each, printing nothing at any point. **Measured on the user's own built
site: 529.7 s, or 8 min 50 s, with no output whatsoever.**

Print what it is doing and roughly how far along it is, and reduce the work
itself where that is free: the check only needs the search config and a Pagefind
runtime reference, so scanning bytes rather than decoding UTF-8, and stopping
early per file, are both available. Keep the guarantee — it exists to catch a
build that silently configures the wrong backend.

### Step 42 — Docs, and re-test on the real archive
Update `STATIC_SITE.md`, `DEPLOY_*.md` and the generated Getting Started page to
say that URLs are searchable and how they tokenise. Then the user re-runs the
real archive and checks the reported queries.

---

## File inventory

**movenotes-v3**

| file | change |
|---|---|
| `obsidian2site.py` | scaffolding, front matter, taxonomy, categories, shortcodes, CSS, build, validation, flags |
| `site_server/` → `server/` + `cmd/` + `api/` | package split, superset contract, Vercel entry points |
| `test_obsidian2site.py` | Relearn assertions → Ledger; new taxonomy/category/contract regressions |
| `STATIC_SITE.md` | rewritten |
| `DEPLOY_VERCEL.md`, `DEPLOY_GITHUB_PAGES.md` | new |
| `AGENTS.md` | invariants restated for Ledger |
| `README.md`, `CHANGELOG.md`, `PLAN.md`, `requirements.txt` | updated |

**hugo-theme-ledger**

| file | change |
|---|---|
| `layouts/page.html` | `ledgerHideTitle`, `ledgerHideMeta`, hero placeholder switch |
| `assets/js/search/query.js` | extended grammar |
| `assets/js/search/backends/{pagefind,bluge}.js` | new parsed shape |
| `assets/js/search/backends/{orama,flexsearch}.js` | new, if promoted |
| `search-server/` | M7 contract |
| `scripts/*` | 25k/200k tiers, byte and heap metrics |
| `PLAN.md`, `PERFORMANCE.md`, `AGENTS.md`, `README.md` | updated |

## Open questions

1. ~~**`bluge.OpenReader` on a read-only filesystem.**~~ Resolved in step 27:
   it opens and searches a directory with no write permission at all, writing
   nothing. The `/tmp` fallback is not needed.
2. ~~**Hugo build cost of 5,000 taxonomy terms.**~~ Resolved in step 23: a term
   costs about as much as a note page, so the default cap became adaptive rather
   than a flat 5,000. Table in M3. Not yet measured at 166k notes — the shape is
   linear in terms at 5k, and the theme has run 5,000 terms at 500k notes, but
   neither is the same as measuring it.
3. **Whether `includeFiles` puts the Bluge index into the function bundle.**
   Step 28 made it moot for build-generated files by building locally instead —
   the index is part of the deployment source, not a build product. Whether
   Vercel then copies it into the bundle is still unverified, and cannot be
   verified without deploying. The failure is loud rather than silent:
   `/api/health` answers 503 naming the path it looked for. **Check it on the
   first deploy.**
4. ~~**Whether `--vercel` is a flag or always-on.**~~ A flag: emitting a root
   `go.mod` unconditionally would collide with Hugo's module mode, which claims
   that same file. Settled in step 28.
5. ~~**The phrase-capable Bluge index size**, which sets the Vercel ceiling.~~
   Measured in step 28: 4.85 KB/note on a near-worst-case corpus, so the 250 MB
   function bundle holds roughly 45,000 notes. See V3.
