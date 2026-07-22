# Publishing a large Obsidian vault with Hugo, Relearn, Bluge, and Pagefind

`obsidian2site.py` converts an Obsidian vault into a Hugo project designed for
archives with tens or hundreds of thousands of notes. It replaces automatic
page-tree navigation with a fixed Relearn sidebar containing **Getting
Started**, **Search**, and **Browse Tags**. Individual note titles are never
listed in the sidebar.

The generated project supports two search modes:

- **Bluge server search** — recommended for a large local archive. Search runs
  in Go on the server, and the browser receives only the current result page.
- **Pagefind static search** — useful when the finished site must be hosted as
  ordinary static files with no application server.

The default `--search-backend both` keeps both choices. For the largest local
archives, prefer `--search-backend bluge`: it emits no Relearn/Lunr or Pagefind
browser search runtime. The custom sidebar form and the full Search page both
use the generated Go server. `both` checks the server first and keeps Pagefind
only as a static-hosting fallback.
Bluge does **not** consume the Pagefind index. Pagefind's output is a
browser-oriented static bundle; movenotes instead writes
`server/search-source.jsonl`, a neutral document stream from which Bluge builds
its own disk index.

The site uses:

- Hugo for Markdown-to-HTML generation.
- `hugo-theme-relearn` for the documentation UI.
- `github.com/blugelabs/bluge` for server-side search.
- Pagefind as the optional serverless fallback.
- A movenotes exact-tag index backed by bucketed static JSON rather than one
  Hugo taxonomy page per word.

Python conversion uses only the standard library. The optional local search
server is a separate Go module generated under `server/`.

## 1. Generate the Hugo project

```bash
python3 -B obsidian2site.py \
  --input ~/twitter_vault \
  --output ~/twitter_site \
  --title "Twitter Archive" \
  --relearn-theme ~/src/hugo-theme-relearn \
  --search-backend bluge
  --build
```

A large archive ends with instructions similar to:

```text
2026/07/21 14:55:58 indexed 166654 notes
2026/07/21 14:55:58 Bluge index ready: ~/twitter_site/server/bluge-index
built Hugo site in '~/twitter_site/public'
serve with '~/twitter_site/server/movenotes-site-server -site ~/twitter_site/public -source ~/twitter_site/server/search-source.jsonl -index ~/twitter_site/server/bluge-index -listen 127.0.0.1:8080'
```

The output contains:

- `content/notes/` — converted Markdown notes using canonical Hugo-safe names.
- `static/vault-assets/` — copied attachments and ordinary vault files.
- `static/movenotes/tags/` — tag names and exact unique-note counts.
- `static/movenotes/tag-postings/` — exact tag-to-note posting lists.
- `static/movenotes/documents/` — chunked URLs and titles for exact-tag results.
- `server/search-source.jsonl` — plain-text records for the Bluge indexer.
- `server/main.go`, `go.mod`, and `go.sum` — the generated static/search server; `go mod tidy` normalizes checksums for the installed Go toolchain.
- `layouts/` and `static/css/` — Relearn extensions for the fixed sidebar,
  Getting Started, Search, and Browse Tags. A project-level search dependency
  partial prevents Relearn from loading its default Lunr adapter.
- `hugo.toml` — Hugo and Relearn configuration.
- `pagefind.yml` — present only for `both` or `pagefind` builds.

### Theme installation

Passing `--relearn-theme` copies a local Relearn checkout into the generated
project and updates the copy for current Hugo language/site APIs. The original
checkout is not modified.

Without `--relearn-theme`, the generated Hugo project uses Hugo modules and
fetches `github.com/McShelby/hugo-theme-relearn` during the first build.

## 2. Build Hugo

```bash
hugo --source ~/twitter_site
```

Hugo writes the finished pages to `~/twitter_site/public`.

Each generated note has an explicit frontmatter `url` derived from the same
canonical path used by every search index. Folder names are case-folded and
unsafe filename separators become hyphens. For example, a source file named:

```text
Twitter/@xxxxxxxxxxxx @xxxxxxxxxxxx @xxxxxxxxxxxx 49.8% of xxxxxxxx….md
```

is published as:

```text
/notes/twitter/@xxxxxxxxxxxx-@xxxxxxxxxxxx-@xxxxxxxxxxxx-49.8-of-xxxxxxxx.html
```

The exact-tag metadata, Bluge source, Pagefind result, and Hugo output all use
that same destination. This prevents 404s caused by source-vault case, spaces,
`%`, or ellipsis characters leaking into result links.

## 3. Recommended: build and run the Bluge server

Install Go, then build the generated module:

```bash
cd ~/twitter_site/server
go mod tidy
go build -o movenotes-site-server .
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

On its first run, the program streams `search-source.jsonl` into a disk-backed
Bluge index. It stores a source fingerprint next to the index and automatically
rebuilds when the JSONL file changes. Force a rebuild with `-reindex`. Build the
index without starting HTTP by adding `-index-only`; when `obsidian2site.py` is
run with `--build`, it compiles the Go server and prebuilds this index so the
first interactive server launch does not pause for indexing.

The server supplies:

- `/` and all Hugo static pages/assets.
- `/api/health` for search-backend detection.
- `/api/search` for paginated JSON search results.

The terminal logs every health probe and search request, including the query,
total matches, returned page size, and duration. Search responses also contain
`"backend":"bluge"` and a `Server-Timing` header. If no health/search lines
appear after submitting the custom search form, the browser is not reaching the
generated server or an old site build is still being served.

Static assets receive cache headers. HTML remains revalidated so rebuilding the
site does not leave stale note pages in the browser.

### Confirm that Bluge-only mode is active

A Bluge-only build has exactly one sidebar search form. Relearn's built-in
search partial is overridden, so Hugo does not emit `lunr.min.js`,
`search-lunr.min.js`, `searchindex.js`, or Pagefind scripts. The build command
scans the produced HTML and fails if one of those browser indexes is referenced.

Regenerate the whole recognized output directory before testing an upgrade; the
converter removes the previous `public/`, layouts, theme copy, Pagefind output,
and server artifacts. In Firefox Network or Debugger tools, a Bluge-only site
should show `/api/health` and `/api/search`, but no Lunr or Pagefind runtime.

### Search syntax

Ordinary terms are ANDed. Each term may match the title or body:

```text
canadian housing
```

Use double quotes for an exact phrase:

```text
"Bank of Canada"
```

Use one or more exact tag clauses:

```text
tag:canadian
"interest rate" tag:economics
```

Use date bounds in ISO format:

```text
since:2026-07-01 until:2026-07-02
"pizza" since:2026-06-01 until:2026-07-01
```

`since:` is inclusive. `until:` is exclusive, so the first example covers only
2026-07-01. Date clauses use the normalized note date written by
`obsidian2site.py`.

The API also accepts `offset`, `limit` (maximum 100), and `sort=date`.

## 4. Optional: build the Pagefind fallback

For a static-only deployment, or to keep an automatic fallback when the Go
server is stopped, run Pagefind after Hugo:

```bash
npx -y pagefind --site ~/twitter_site/public
```

Then any ordinary static server works:

```bash
python3 -m http.server 8080 --directory ~/twitter_site/public
```

Open `http://127.0.0.1:8080/`.

Pagefind reads the built HTML and creates `public/pagefind/`. It is not used as
an input to Bluge. Maintaining independent indexes avoids coupling the Go
server to Pagefind's private, version-specific browser bundle.

For a six-figure-note local archive, the Go server is normally more responsive
because the browser does not download or construct Lunr/Pagefind indexes. Only
the visible result page crosses the HTTP connection.
Replacing Python's static file server alone is not the important improvement;
moving full-text search from the browser to Bluge is.

## Twitter/X note presentation

A current `twitterx2sql.py` import includes archive context directly in the
Markdown body. Replying posts receive an `In reply to:` link; the footer links
the locally formatted archive timestamp to the post and shows retweet and
favorite counts:

```markdown
In reply to: [@username](https://x.com/i/web/status/1111111111111111111)

tweet/post text

[11:08 AM · Jul 21, 2026](https://x.com/i/web/status/2222222222222222222) 🔁 10 💙 5
```

Use `twitterx2sql.py --timezone America/Vancouver` (or another IANA zone) for a
fixed display zone. Without `--timezone`, the importer uses the machine's local
time zone. Twitter-origin notes keep their title for the Relearn topbar and
search result metadata, but suppress the repeated article H1 and the theme's
second date line.

## 5. Automatic builds

`--build` runs Hugo and the selected search build steps:

```bash
python3 -B obsidian2site.py \
  --input ~/twitter_vault \
  --output ~/twitter_site \
  --title "Twitter Archive" \
  --relearn-theme ~/projects/hugo-theme-relearn \
  --search-backend both \
  --build
```

Choices are:

- `--search-backend both` — build the Go server, prebuild Bluge, and build Pagefind.
- `--search-backend bluge` — build only the Go server/Bluge index and explicitly exclude Relearn/Lunr and Pagefind browser runtimes.
- `--search-backend pagefind` — build Pagefind only.

Use `--hugo-bin`, `--go-bin`, or `--pagefind-bin` to select non-default
executables.

## Search and exact tags

A note's site tags are the union of:

- `tags` or `tag` values in Obsidian frontmatter.
- Inline hashtags such as `#codec`.
- Every unique non-filler word meeting `--minimum-word-length`.

Generated word tags are not placed in Hugo's built-in taxonomy or duplicated
into Pagefind filters. Instead, temporary SQLite tables produce prefix buckets,
hashed exact posting lists, and chunked note metadata.

Selecting a Browse Tags entry opens `search.html?tag=...` and reads its exact
posting list. The displayed tag count and result count therefore use the same
set of unique note IDs. A full-text `q=canadian` query may have a different
count because the full-text analyzer can match related forms; exact-tag mode
keeps `canadian` and `canadians` separate.

The Bluge search bar also accepts `tag:name` clauses for combining an exact tag
with phrases, terms, and date ranges.

Add project-specific filler words with:

```bash
python3 -B obsidian2site.py \
  --input ~/obsidian_vault \
  --output ~/obsidian_site \
  --stop-words ~/my-stop-words.txt
```

The UTF-8 file may contain whitespace- or comma-separated words.

## Obsidian Markdown conversion

The converter:

- Removes original frontmatter and writes compact Hugo fields.
- Converts wiki links and local Markdown links to canonical `.html` paths.
- Converts embeds to copied assets or scalable note links.
- Preserves fenced/inline code while rewriting prose links.
- Repairs malformed HTTP(S) destinations sufficiently for Hugo to build while
  keeping the original URL visible for investigation.
- Links plain valid-looking `@username` mentions to `https://x.com/username`.
- Escapes literal Hugo shortcode openers in note examples.
- Normalizes dates to RFC 3339.
- Deterministically shortens long or colliding output names.

Use `--note-embeds transclude` to expand note embeds. The default `link` mode is
more scalable. Cycles and excessive nesting are stopped automatically.

Dot directories are excluded unless `--include-hidden` is used. `.movenotes`
is always excluded from publishing.

## Deployment below a URL prefix

Pass the public base URL while generating:

```bash
python3 -B obsidian2site.py \
  --input ~/obsidian_vault \
  --output ~/obsidian_site \
  --base-url https://example.com/archive/
```

Pagefind/static deployment honors the Hugo prefix. The generated Go server is
primarily intended for a local root deployment such as
`http://127.0.0.1:8080/`; place it behind a reverse proxy that strips the public
prefix when deploying it below a subpath.

## Rebuilding

Re-run the same `obsidian2site.py` command after the vault changes. A recognized
generated project is cleaned before regeneration, including old content,
layouts, public output, and server source. Then rebuild Hugo and restart the Go
server. The Bluge index is rebuilt automatically when its JSONL source changes.

The expensive generation paths remain bounded:

- The vault is scanned once.
- Pending note conversion jobs are bounded to about twice the worker count.
- Tag counts and postings are stored in temporary SQLite.
- JSON structures are written bucket by bucket.
- Bluge source is streamed one JSON record per note.
- Bluge index insertion uses batches of 500 records.

## Quartz

Quartz remains an option for smaller vaults where its navigation and browser
search model fits the note count. For archives around or above 100,000 notes,
the fixed Relearn sidebar plus server-side Bluge search avoids generating or
loading a complete note tree in the browser.

## References

- Hugo: https://gohugo.io/
- Relearn: https://github.com/McShelby/hugo-theme-relearn
- Bluge: https://github.com/blugelabs/bluge
- Pagefind: https://pagefind.app/
- Obsidian Export: https://github.com/zoni/obsidian-export
