# Generated movenotes site server

This Go module is copied into each Hugo project produced by
`obsidian2site.py`. It serves the generated `public/` tree and exposes a Bluge
search API.

From the generated site's `server/` directory:

```bash
go mod tidy
go build -o movenotes-site-server .
./movenotes-site-server \
  -site ../public \
  -source search-source.jsonl \
  -index bluge-index \
  -listen 127.0.0.1:8080
```

The checked-in `go.sum` is a baseline. Run `go mod tidy` to normalize it for
the installed Go release before compiling. The index is built on first start
and rebuilt when `search-source.jsonl` changes. Use `-reindex` to force it. To build the index without starting the
HTTP server, add `-index-only`; `obsidian2site.py --build` uses this mode so
normal server startup is immediate. Query syntax includes quoted phrases,
`tag:name`, `since:YYYY-MM-DD` (inclusive), and `until:YYYY-MM-DD` (exclusive).

This index is independent of Pagefind. Pagefind remains an optional static-site
fallback and is generated from Hugo's built HTML, not consumed by this server.

The server logs startup, `/api/health`, and `/api/search` activity. Search JSON
contains `"backend":"bluge"`, and responses expose a `Server-Timing` duration.
