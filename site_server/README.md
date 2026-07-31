# Generated movenotes site server

This Go module is copied into each Hugo project produced by `obsidian2site.py`.
It answers the theme's search API from a Bluge index, and — locally — serves the
built `public/` tree as well.

```
search/                        the whole implementation: config, index, query,
                               handlers. No flags, no log.Fatal, no listening.
cmd/movenotes-site-server/     local process: flags, static files, one port
api/                           serverless functions: Search and Health
```

Two entry points, one package, so a local site and a deployed one cannot answer
differently.

## Local

From the generated site's `server/` directory:

```bash
go mod tidy
go build -o movenotes-site-server ./cmd/movenotes-site-server
./movenotes-site-server \
  -site ../public \
  -source search-source.jsonl \
  -index bluge-index \
  -listen 127.0.0.1:8080
```

The checked-in `go.sum` is a baseline; `go mod tidy` normalizes it for the
installed Go release. The index is built on first start and rebuilt when
`search-source.jsonl` changes — `-reindex` forces it, and `-index-only` builds
without serving, which is what `obsidian2site.py --build` uses so the first
interactive start does not pause for indexing.

## Configuration

Every setting resolves explicit value → environment → default, so the same
binary works from a command line and from a platform's project settings:

| flag | environment | default |
|---|---|---|
| `-index` | `MOVENOTES_INDEX` | `server/bluge-index` |
| `-source` | `MOVENOTES_SOURCE` | `server/search-source.jsonl` |
| `-site` | `MOVENOTES_SITE` | `public` |
| `-listen` | `PORT` (as `:$PORT`) | `127.0.0.1:8080` |

Loopback is the default listen address on purpose: running the binary by hand
should not put a personal archive on the network.

## Serverless

`api/search.go` and `api/health.go` export `Search` and `Health`. On a platform
whose Go runtime turns each exported `http.HandlerFunc` in `api/` into a
function, the CDN serves `public/` and only `/api/*` reaches Go code — which is
the only shape that works, since a generated archive's `public/` is far larger
than any function bundle limit.

Two constraints shape this half:

- **The index is opened, never built.** Indexing takes minutes on a large archive
  and needs a writable filesystem. A function that finds no index answers **503**
  with the command that fixes it, rather than trying.
- **Opening is read-only.** Verified against an index directory with every write
  permission removed: Bluge opens it, searches it, and adds no files. That is
  what makes a read-only serverless filesystem workable.

The index is opened on the first request that needs it and then shared for the
life of the instance, so a cold start that is never asked to search pays nothing
for the index.

## Notes

This index is independent of Pagefind, which remains an optional static-hosting
fallback generated from Hugo's built HTML and never consumed here.

The query grammar — quoted phrases, `category:`, repeatable `tag:`,
`since:`/`until:` — is parsed once in the browser, in the theme's
`assets/js/search/query.js`. This server receives already-split fields and has no
parser of its own. See the theme's `search-server/README.md` for the full
request and response contract.

Startup, `/api/health` and `/api/search` are logged; search responses carry
`"backend":"bluge"` and a `Server-Timing` duration.
