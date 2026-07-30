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

### V2 — Server refactor

- Move index building, query parsing and the two HTTP handlers into a `server`
  package with no `log.Fatal` and no `flag` use.
- Configuration resolution order: explicit argument → environment
  (`MOVENOTES_INDEX`, `MOVENOTES_SOURCE`, `MOVENOTES_SITE`, `PORT`) → default.
- Open the index lazily behind `sync.Once` so a cold function does not open it
  until the first search, and share the reader across warm invocations.
- **Never build an index inside a function.** 100k notes take 116 s to index
  and the filesystem is read-only; the index is built at deploy time and
  shipped. A function that finds no index returns 503 with a message saying so.
- Verify `bluge.OpenReader` can open an index on a read-only filesystem. If it
  needs a writable directory, copy or symlink into `/tmp` on first use and
  record the cost; this is the one genuinely unknown item in Part C.

### V3 — Size ceiling, stated plainly in the docs

The ~1.11 KB/note figure (111 MB at 100k) comes from an index without term
positions, so it is a **floor**, not the size of a phrase-capable index — see
step 21's finding 3. Re-measure before publishing a note count. On that floor,
with a ~30 MB binary, the 250 MB cap lands at roughly **150k–190k notes**; the
real ceiling is lower. The documentation will give the arithmetic, the
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

### Step 27 — Server refactor for Vercel *(movenotes)*
V1/V2: `server` package, `cmd/movenotes-site-server`, `api/search.go`,
`api/health.go`, env-var configuration, lazy `sync.Once` reader, 503 when no
index. Resolve the read-only-filesystem question for `bluge.OpenReader`. Local
command line and behaviour unchanged; Go tests cover both entry points.

### Step 28 — Generator emits the Vercel project *(movenotes)*
`vercel.json` per V4, root `go.mod`, `.vercelignore`, the
`--ledger-theme`-required check, and a `--vercel` flag (or unconditional
emission — decide when the layout is real) plus the index-size warning from V3.

### Step 29 — `DEPLOY_VERCEL.md` *(movenotes)*
Build and deploy the Hugo site with the Bluge backend on Vercel: prerequisites,
`obsidian2site.py` invocation, `vercel.json`, the 250 MB arithmetic and how to
measure it, `includeFiles`, prebuilt-index requirement, the read-only
filesystem, cold starts, and the three over-ceiling options. Cites the Go
runtime and function-limits pages.

### Step 30 — `DEPLOY_GITHUB_PAGES.md` *(movenotes)*
Build and deploy with the static backend on GitHub Pages: the Actions workflow
from Hugo's own host-on-GitHub-Pages page, `baseURL` handling for a project
site, `--base-url` on the generator, where the Pagefind (and any promoted
backend) index build goes in the workflow, and GitHub Pages' 1 GB / 100 MB
limits against measured output sizes.

### Step 31 — Docs and invariants pass *(movenotes)*
Rewrite `STATIC_SITE.md` for Ledger; update `AGENTS.md` invariants, `README.md`,
`CHANGELOG.md`, `PLAN.md`, `requirements.txt`; make sure no stale Relearn
instruction survives (`grep -ri relearn` should return only deliberate
historical notes).

### Step 32 — Benchmark tiers 25k and 200k, Pagefind baseline *(theme)*
Add both tiers to `scripts/bench.sh` / `gen-corpus.js`; add the
first-result-bytes and peak-heap measurements to `query-latency.js`; record the
Pagefind baseline for the two new tiers.

### Step 33 — Orama adapter and measurement *(theme)*
`assets/js/search/backends/orama.js` behind the same interface, an index-build
script, and the full metric set at 25k / 100k / 200k. Result written up in
`PERFORMANCE.md` whichever way it goes.

### Step 34 — FlexSearch adapter and measurement *(theme)*
`flexsearch.js` in both configurations (fast-boot import, IndexedDB
persistent), same metrics, same write-up.

### Step 35 — Promote what earned it *(movenotes + theme)*
Apply the Part D rule. For each backend that passed: register it in the theme's
`BACKENDS` map, extend `--search-backend` to accept it, emit its index build in
`--build`, extend `_validate_built_search_backend`, and add it to
`DEPLOY_GITHUB_PAGES.md`. For each that failed: the `PERFORMANCE.md` entry is
the deliverable, and `obsidian2site.py` does not grow an option.

### Step 36 — Real-archive test and release
User runs the pipeline against a real Twitter/X archive. Fix what it finds.
Then, with the user's agreement, push `develop`.

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

1. **`bluge.OpenReader` on a read-only filesystem** — resolved in Step 27; the
   fallback is a `/tmp` copy, which costs cold-start time.
2. ~~**Hugo build cost of 5,000 taxonomy terms.**~~ Resolved in step 23: a term
   costs about as much as a note page, so the default cap became adaptive rather
   than a flat 5,000. Table in M3. Not yet measured at 166k notes — the shape is
   linear in terms at 5k, and the theme has run 5,000 terms at 500k notes, but
   neither is the same as measuring it.
3. **Whether `vercel.json`'s `includeFiles` picks up an index generated during
   the build** rather than committed. If not, the index must be committed or
   built in CI and uploaded. Settled in Step 28.
4. **Whether `--vercel` is a flag or always-on.** Deciding once the emitted
   layout exists (Step 28).
5. **The phrase-capable Bluge index size**, which sets the Vercel ceiling. Open
   since step 21; measured in step 27 or 32.
