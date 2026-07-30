# Publishing a large Obsidian vault with Hugo, Ledger, Bluge, and Pagefind

`obsidian2site.py` converts an Obsidian vault into a Hugo project built for
archives with tens or hundreds of thousands of notes.

The theme is [Ledger](https://github.com/renesugar/hugo-theme-ledger), which was
written for this scale: it never enumerates pages in its navigation, bounds every
surface that could grow with the archive, and takes its search from a swappable
backend. Its own measurements — build times, index sizes and query latencies at
10k, 100k and 500k notes — are in the theme's `PERFORMANCE.md`, and they are the
reason for most of the decisions below.

The generated site has three ways in:

- **Search** (`/search/`) — the theme's own view, over one of the backends below.
- **Categories and tags** in the sidebar, from the Hugo taxonomy. A term smaller
  than `taxonomyPageLimit` gets a real archive page; a larger one becomes a search
  query, which is what keeps a 200k-note term from generating 33,000 pager pages.
- **Browse Tags** (`/browse-tags/`) — a movenotes view over every tag in the
  archive, including the generated content words that the taxonomy deliberately
  does not hold.

## Search backends

| `--search-backend` | what it builds | when |
|---|---|---|
| `both` (default) | Bluge index **and** Pagefind index; the theme's `auto` adapter picks at page load | one build that works served locally *and* as static files |
| `bluge` | Bluge only, no browser index at all | a large local archive |
| `pagefind` | Pagefind only, no Go server | static hosting: GitHub Pages, a CDN |

`auto` probes `/api/health` once per page load: Bluge when the generated Go
server answers, Pagefind when nothing does.

Bluge does **not** consume the Pagefind index. Pagefind's output is a
browser-oriented static bundle; movenotes instead writes
`server/search-source.jsonl`, a neutral document stream from which Bluge builds
its own disk index.

Choosing between them, from the theme's measurements: Pagefind is comfortable up
to about 25k notes. Past that its filter queries cost seconds — at 200k a
hand-typed `tag:` query downloads 103 MB over 2,200 requests — and a search-led
archive wants Bluge, which answers the same query in tens of milliseconds.

**There is no third static option, and that was tested rather than assumed.** Orama
and FlexSearch were both implemented as theme backends and measured against
Pagefind on the same corpus; both were rejected, because an in-browser index has to
be transferred at least once and theirs run 33–343 MB at 25,000 notes against the
0.37 MB Pagefind fetches for a free-text query. FlexSearch over IndexedDB removes
the repeat download and holds the smallest heap of any backend, but still needs
~15 s to a first result. The theme's `PERFORMANCE.md` records all of it, including
what not to retry.

## 1. Generate the Hugo project

```bash
python3 -B obsidian2site.py \
  --input ~/twitter_vault \
  --output ~/twitter_site \
  --title "Twitter Archive" \
  --ledger-theme ~/projects/hugo-theme-ledger \
  --search-backend both \
  --build
```

A large archive ends with something like:

```text
generated Hugo project: 166,654 note(s), 4,210 file(s), 1,284,904 unique tag(s)
5,000 of 61,203 explicit tag(s) published as Hugo taxonomy terms (automatic cap
  for 166,654 note(s)); the other 56,203 stay searchable through the tag index
  and Bluge (63,914 note(s) rewritten)
built Hugo site in '~/twitter_site/public'
serve with '~/twitter_site/server/movenotes-site-server -site ~/twitter_site/public …'
```

The output contains:

```
content/notes/            converted Markdown, canonical Hugo-safe names
content/_index.md         home: the theme's primed-search view
content/about.md          Getting Started
content/search.md         /search/
content/browse-tags.md    /browse-tags/
layouts/browse-tags.html  the tag browser and exact-tag results
assets/js/movenotes-tags.js  its behaviour, bundled by Hugo
static/vault-assets/      copied attachments and ordinary vault files
static/movenotes/tags/            tag names and exact unique-note counts
static/movenotes/tag-postings/    exact tag-to-note posting lists
static/movenotes/documents/       chunked URLs, titles and dates for results
static/css/movenotes-site.css     what the theme does not already provide
server/search-source.jsonl        plain-text records for the Bluge indexer
server/search/ cmd/ api/          the Go module: one package, two entry points
hugo.toml                 Hugo and theme configuration
pagefind.yml              only for `both` or `pagefind` builds
```

There are no shortcodes and no theme-partial overrides. Everything the theme
provides is used as the theme provides it, which is what keeps a regeneration
from breaking when the theme changes.

### Theme installation

`--ledger-theme` copies a local checkout into the generated project, skipping the
bulk a site does not need (`exampleSite`, `node_modules`, `public`, `bench`,
`.git`). The original checkout is not modified, and nothing is rewritten on the
way in.

Without it, the generated `hugo.toml` imports
`github.com/renesugar/hugo-theme-ledger` as a Hugo module, fetched on the first
build. `--vercel` requires the copy: Vercel's Go runtime wants `go.mod` at the
project root, which Hugo's module mode claims for itself.

`--relearn-theme` still works as a deprecated alias — it warns, and copies
whatever path it is given as the Ledger theme.

## 2. Build Hugo

```bash
hugo --source ~/twitter_site
```

Each note has an explicit frontmatter `url` derived from the canonical path every
search index also uses. Folder names are case-folded and unsafe filename
separators become hyphens, so:

```text
Twitter/@xxxxxxxxxxxx @xxxxxxxxxxxx 49.8% of xxxxxxxx….md
```

is published as:

```text
/notes/twitter/@xxxxxxxxxxxx-@xxxxxxxxxxxx-49.8-of-xxxxxxxx.html
```

The exact-tag metadata, Bluge source, Pagefind result and Hugo output all use
that same destination. This is what prevents 404s caused by source-vault case,
spaces, `%` or ellipsis characters leaking into result links.

## 3. Recommended: build and run the Bluge server

Install Go, then build the local binary from the module's command package:

```bash
cd ~/twitter_site/server
go mod tidy
go build -o movenotes-site-server ./cmd/movenotes-site-server
```

Run it from the `server` directory:

```bash
./movenotes-site-server \
  -site ../public \
  -source search-source.jsonl \
  -index bluge-index \
  -listen 127.0.0.1:8080
```

Open `http://127.0.0.1:8080/`.

On its first run the program streams `search-source.jsonl` into a disk-backed
Bluge index, stores a source fingerprint beside it, and rebuilds automatically
when the JSONL changes. `-reindex` forces a rebuild; `-index-only` builds without
serving, which is what `--build` uses so the first interactive start does not
pause for indexing.

Each setting also reads from the environment — `MOVENOTES_INDEX`,
`MOVENOTES_SOURCE`, `MOVENOTES_SITE`, and `PORT` for the listen address — so the
same binary runs in a container without a command line. Explicit flags win.

The server supplies `/` and every static page, `/api/health` for backend
detection, and `/api/search` for paginated JSON results. Every request is logged
with its query, total, window and duration, and responses carry
`"backend":"bluge"` and a `Server-Timing` header. If no such lines appear after a
search, the browser is not reaching this server — or an old build is being
served.

Static assets get cache headers; HTML stays revalidated so rebuilding does not
leave stale note pages in the browser.

### The same code, deployed

`server/` is one Go package with two entry points: the command above, and
`api/search.go` / `api/health.go` for a serverless platform, where a CDN serves
the static files and only `/api/*` reaches Go. Neither can answer differently
from the other. See `DEPLOY_VERCEL.md`.

### Confirm which backend is active

`--build` checks the built HTML and fails if the site does not configure the
backend that was asked for, if a `bluge`-only build references a browser search
runtime, if an `auto` or `pagefind` build has no Pagefind index to fall back on,
or if no search view was built at all — which is what a missing or stale theme
looks like.

In the browser's network tools, a `bluge` site shows `/api/health` and
`/api/search` and no `/pagefind/` requests; a `pagefind` site shows the reverse.
An `auto` site shows the health probe followed by whichever one answered.

> A broken Bluge deployment can look healthy under `auto`: the probe fails, the
> browser falls back to Pagefind, and search keeps working. The tell is that
> `since:`/`until:` report themselves unsupported. Check `/api/health` directly.

### Search syntax

The grammar is parsed once, in the browser, and handed to whichever backend is
configured:

| query | meaning |
|---|---|
| `canadian housing` | both words, anywhere in the note |
| `"Bank of Canada"` | that exact phrase |
| `category:Twitter` | one category; quote a name with a space |
| `tag:economics` | one tag; repeat the clause to require several |
| `since:2026-07-01 until:2026-08-01` | July, by note date — `until:` is exclusive |
| *(empty)*, or `category:"All notes"` | every note |

Clauses are ANDed, and anything that does not fit — `foo:bar`, a URL — is
searched as text.

**Results are ordered newest first, always.** Whatever the query, the most
recent note is on page 1 — an archive is read by date, and ranking would put it
somewhere unpredictable in a long result set.

**`category:"All notes"` is Joplin's phrasing for "no filter",** and the parser
discards it, so it is exactly an empty search. Both mean every note.

**Opening `/search/` runs nothing.** The page waits for a query rather than
searching for everything on arrival — that arrival used to be the most expensive
request on a Pagefind site (13.5 MB at 25,000 notes, now zero).

**Pagefind cannot express date bounds.** On a static build the results view says
which clauses were ignored rather than quietly returning the unbounded set.
Everything else in the table works on both backends.

`/api/search` also accepts `offset`, `limit` (max 100), `page`, `per` and
`sort=score` for a caller that wants relevance ranking instead of the date order.

## 4. Optional: build the Pagefind fallback

For static hosting, or to keep a fallback when the Go server is stopped, run
Pagefind after Hugo:

```bash
npx -y pagefind --site ~/twitter_site/public
```

Then any static server works:

```bash
python3 -m http.server 8080 --directory ~/twitter_site/public
```

Pagefind reads the built HTML and writes `public/pagefind/`. It is not an input
to Bluge; keeping the indexes independent avoids coupling the Go server to
Pagefind's private, version-specific browser bundle.

For a six-figure archive the Go server is normally far more responsive, because
the browser never downloads or constructs an index — only the visible result page
crosses the connection.

## 5. Automatic builds

`--build` runs Hugo, then the selected search steps, then the backend check:

```bash
python3 -B obsidian2site.py \
  --input ~/twitter_vault \
  --output ~/twitter_site \
  --title "Twitter Archive" \
  --ledger-theme ~/projects/hugo-theme-ledger \
  --search-backend both \
  --build
```

- `both` — Hugo, Pagefind, `go build`, prebuild the Bluge index.
- `bluge` — Hugo, `go build`, prebuild the index, and no browser index anywhere.
- `pagefind` — Hugo and Pagefind only.

Use `--hugo-bin`, `--go-bin` or `--pagefind-bin` to select non-default
executables. Adding `--vercel` also emits the deployment files and reports the
built site against Vercel's limits.

## Two kinds of tag

A note's tags are the union of:

- `tags` or `tag` values in Obsidian frontmatter,
- inline hashtags such as `#codec`,
- every unique non-filler word meeting `--minimum-word-length`.

Those are two populations with very different sizes, and they are stored
differently:

| | written tags | generated word tags |
|---|---|---|
| where | Hugo `tags` taxonomy, capped | hashed posting index under `static/movenotes/` |
| surfaces | sidebar, `/tags/`, term archives, note footers, result cards | Browse Tags |
| searchable by `tag:` | yes, on both backends | yes on Bluge; Pagefind filters only the taxonomy ones |

**The taxonomy is capped because every term is a page.** Measured at 5,000
synthetic notes, a taxonomy term costs about as much to build as a note page: 200
terms took 11.2 s and 5,213 pages, 5,000 terms took 32.2 s and 10,013. So
`--max-taxonomy-tags` defaults to `max(200, min(5000, notes ÷ 10))` — a tenth of
the note count, bounded — and promotes the most frequent written tags, breaking
ties by name so two runs of one vault promote the same set. The rest stay fully
searchable; they simply have no archive page of their own.

Selecting a Browse Tags entry opens `/browse-tags/?tag=…` and reads that tag's
posting list, so the count on a tag and the number of results it opens are the
same number by construction. A full-text `q=canadian` query may differ, because
the analyzer matches related forms while exact-tag mode keeps `canadian` and
`canadians` apart.

Add project-specific filler words with:

```bash
python3 -B obsidian2site.py … --stop-words ~/my-stop-words.txt
```

The UTF-8 file may be whitespace- or comma-separated.

## Categories

Ledger's views expect one category per note, and by default it is the note's
top-level vault folder — meaningful for the archives this targets (`Twitter/`,
`Notes/`). `--category-mode fixed --category-name "Archive"` puts everything in
one; `--category-mode none` omits categories entirely. Notes at the vault root
take `--category-name`, or the site title.

## Twitter/X note presentation

A current `twitterx2sql.py` import carries archive context in the Markdown body:
a reply link, then the post, then the locally formatted timestamp linked to the
original with retweet and favourite counts.

```markdown
In reply to: [@username](https://x.com/i/web/status/1111111111111111111)

tweet/post text

[11:08 AM · Jul 21, 2026](https://x.com/i/web/status/2222222222222222222) 🔁 10 💙 5
```

Because the note already contains its own heading and timestamp, the generator
sets `ledgerHideTitle` and `ledgerHideMeta`, which the theme honours by keeping
the `h1` in the document outline for assistive technology while taking it off the
screen, and dropping its own date row. The striped hero placeholder is off
site-wide: 166k placeholder rectangles are noise, not design.

Twitter-origin detection comes from `movenotes-original-format` or Joplin source
metadata, never from the folder name. Use
`twitterx2sql.py --timezone America/Vancouver` (or another IANA zone) for a fixed
display zone.

## Obsidian Markdown conversion

The converter:

- removes original frontmatter and writes compact Hugo fields — nothing the theme
  can derive, so no summary and no reading time;
- converts wiki links and local Markdown links to canonical `.html` paths;
- converts embeds to copied assets or scalable note links;
- preserves fenced and inline code while rewriting prose links;
- repairs malformed HTTP(S) destinations enough for Hugo to build, keeping the
  original URL visible for investigation;
- links plain valid-looking `@username` mentions to `https://x.com/username`;
- escapes literal Hugo shortcode openers in note examples;
- normalizes dates to RFC 3339;
- deterministically shortens long or colliding output names.

`--note-embeds transclude` expands note embeds; the default `link` mode is more
scalable. Cycles and excessive nesting stop automatically.

Dot directories are excluded unless `--include-hidden` is used. `.movenotes` is
always excluded from publishing.

## Deployment below a URL prefix

Pass the public base URL while generating:

```bash
python3 -B obsidian2site.py … --base-url https://example.github.io/archive/
```

This matters more than it looks. Hugo builds every link, stylesheet and fetch URL
against `baseURL`, and a project site on GitHub Pages is always published below
the root. The theme and the generated templates resolve site-absolute paths
through one partial for exactly this reason, and the exact-tag index's stored note
URLs are resolved against the site root at runtime.

If a subpath deployment 404s its assets or its search results, the base URL is
the first thing to check. See `DEPLOY_GITHUB_PAGES.md`.

The generated Go server is intended for a local root deployment such as
`http://127.0.0.1:8080/`; behind a subpath, put it behind a reverse proxy that
strips the prefix.

## Rebuilding

Re-run the same command after the vault changes. A recognized generated project
is cleaned first — old content, layouts, public output and server source — then
rebuild Hugo and restart the Go server. The Bluge index rebuilds itself when its
JSONL source changes.

The expensive paths stay bounded:

- the vault is scanned once;
- pending conversion jobs are bounded to about twice the worker count;
- tag counts and postings live in temporary SQLite;
- JSON structures are written bucket by bucket;
- Bluge source is streamed one JSON record per note, and indexed in batches of
  500;
- the taxonomy cap's second pass rewrites only the notes carrying a demoted tag —
  about 3 s for 4,940 of 5,000 notes, and nothing at all for a vault under its
  cap.

## Deploying

- `DEPLOY_VERCEL.md` — static site plus Bluge search as serverless functions,
  with the measured limits that decide which archives fit.
- `DEPLOY_GITHUB_PAGES.md` — static Pagefind site, the Actions workflow, and the
  1 GB ceiling.

## Quartz

Quartz remains an option for smaller vaults where its navigation and browser
search model fits the note count. For archives around or above 100,000 notes,
Ledger's bounded surfaces plus server-side Bluge search avoid generating or
loading a complete note tree in the browser.

## References

- Hugo: https://gohugo.io/
- Ledger: https://github.com/renesugar/hugo-theme-ledger
- Bluge: https://github.com/blugelabs/bluge
- Pagefind: https://pagefind.app/
- Obsidian Export: https://github.com/zoni/obsidian-export
