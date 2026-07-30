# Performance review

## Comparison with the alternate 3.10 implementation

The alternate implementation correctly identified the dominant historical
problem: one `joplin_id` lookup per input file against an unindexed column. It
also added useful structural tests for the query plan, automatic index repair,
and SQL statement counts. Those tests have been adapted into this project.

This implementation retains several stronger changes from the previous 3.10
release:

* exact RAW SHA-256 fingerprints are persisted in schema v4 instead of hashing
  every stored RAW BLOB again on each run;
* secondary indexes are built after a new bulk import rather than maintained
  row by row;
* filtered Obsidian preservation is a pre-indexed graph traversal rather than a
  shrinking fixed-point scan;
* full preservation streams exact RAW BLOBs instead of loading the complete
  database into memory;
* filename deduplication, image replacement, remote-image scheduling, and
  Twitter resource staging already use bounded or linear algorithms.

## Improvements added after the comparison

### Adaptive existing-ID checks

A single complete fingerprint preload is ideal for a full re-import, but it is
wasteful when ten notes are merged into a database containing a million rows.
`joplin2sql.py` now selects between two paths:

* **full or large re-import:** one sequential preload of compact persisted
  fingerprints;
* **small merge:** bounded `IN (...)` queries containing only IDs from the
  current input batch, using the `joplin_id` index.

The second path is proportional to the input size and does not allocate a
mapping for unrelated database rows. Rows inserted during the current run are
excluded from database lookups and are checked through the in-run digest map.

### Notebook-title resolution

Canonical parent notebook files are parsed at most once and their parsed
columns are reused when the main import loop reaches the file. Titles from
folders already present in SQLite are loaded once. A targeted SQL fallback is
used only for newly inserted notes whose parent could not be resolved from a
canonical source filename.

### Attachment and media directory indexes

Several fallback paths performed a directory glob for every attachment:

* generated image resource reuse in `image_resources.py`;
* Joplin resource lookup during Obsidian export;
* Twitter/X video fallback lookup.

Each directory is now indexed once. Subsequent lookups are expected O(1),
turning O(resources × directory entries) behaviour into O(directory entries +
lookups).

### Case-insensitive extensions

File-extension checks are now case-insensitive, so `.MD` RAW items are not
silently omitted.

## Local measurements

Measurements below were taken in one shared container and are regression
signals, not runtime guarantees.

### 4,000-item fresh import, approximately 5 KB per note

| Implementation | Elapsed |
|---|---:|
| Previous project 3.10 | 3.91 s |
| Alternate 3.10 | 3.05 s |
| Reviewed 3.11 | 3.17 s |

The reviewed build retains more indexes and persisted fingerprint metadata than
the alternate build, while avoiding the previous database-wide folder update.

### Ten-item merge into a 100,000-row database

| Implementation | Elapsed | Maximum RSS |
|---|---:|---:|
| Previous project 3.10 | 1.97 s | 339,232 KB |
| Reviewed 3.11 | 1.08 s | 309,420 KB |

The improvement comes from input-scoped fingerprint queries rather than a
complete existing-ID preload.

## Complexity summary

| Path | Previous behaviour | Reviewed behaviour |
|---|---|---|
| Full existing-ID comparison | O(input + database) | O(input + database) |
| Small merge into large DB | O(database + input) memory/time preload | O(input log database) indexed batches |
| In-run duplicate memory | O(total RAW bytes) historically | O(number of IDs) fixed-size digests |
| Parent folder resolution | database-wide update or repeated parses | one parse per referenced source folder + targeted fallback |
| Filtered preservation closure | repeated scans historically | O(rows + references) graph traversal |
| Repeated attachment fallback | O(lookups × files) directory scans | O(files + lookups) directory index |
| Repeated identical filenames | O(k²) historically | amortized O(k) |
| k image replacements in n chars | O(k × n) copies historically | O(n + k log k) |
| Obsidian full preservation memory | O(total RAW BLOB bytes) historically | one RAW row at a time |
| Remote image futures | one Future per URL historically | bounded to roughly 2 × workers |

## Deliberately rejected settings

`PRAGMA synchronous=OFF` is not used because interruption or power loss can
leave the interchange database corrupt. Connections retain WAL journalling and
`synchronous=NORMAL`. A large forced SQLite cache was also not adopted; the
principal import scans are sequential and measurements did not justify a
project-wide memory reservation.

## Obsidian importer scaling (3.20)

`obsidian2sql.py` builds compact path-to-ID and basename indexes once, then
streams folder, resource, note, tag, and relation rows through the same bounded
SQLite batch mechanism used by the Joplin importer. It does not accumulate all
note bodies or resource bytes before insertion. Resource files are hashed and
compared in chunks, copied to `resources/`, and are not duplicated as SQLite
BLOBs. Native note raw bytes are retained because they are required for exact
frontmatter and Markdown restoration; only one configured batch is resident.

The resulting complexity is O(vault files + links) for inventory and link
resolution, plus indexed/batched SQLite insertion. Memory is O(path index +
batch note bytes + tags), rather than O(total vault bytes).

## Static-site generation scaling (3.30)

`obsidian2site.py` scans the vault once, retains compact source-to-output path
maps, bounds pending conversion jobs to approximately twice the worker count,
and stores global tag counts plus exact tag-to-note associations in temporary
SQLite. Tag JSON is emitted one prefix, posting, or document bucket at a time.
Individual note titles are never rendered into the sidebar.

Generated non-filler-word tags are not copied into every note's Hugo
frontmatter or into Pagefind filters. Only explicit Obsidian frontmatter or
hashtag tags are emitted as Pagefind filter metadata. Tag counts and posting
rows are accumulated in bounded note batches, sorted for locality, and inserted
with `executemany`, avoiding one SQL statement per ordinary word occurrence.

A local 5,000-note benchmark (approximately 1 KB per note, eight workers)
generated the Hugo project and tag data in 5.82 seconds. Maximum reported RSS
was 318,896 KB in a container whose empty Python process reported 289,376 KB,
for an approximate workload increment of 30 MB. Hugo and Pagefind build time is
separate and depends on their installed versions, theme cache, and note text.

## Browser-side search and navigation scaling (3.32)

The generated site overrides no theme shell. Keeping the theme’s supported
structure avoids malformed layout state and lets the theme’s
responsive navigation code operate on the DOM it expects. The custom sidebar
contains only three fixed links and one search field, independent of vault size.

Pagefind result metadata is fetched in concurrent visible batches of 20 rather
than one result at a time. Only the current batch is inserted into the DOM; a
“Load more” control advances to the next batch. Stale asynchronous searches are
discarded with a generation token. The tag browser loads one prefix bucket and
renders at most 300 matching entries. Browser work is therefore bounded by the
visible batch or one tag bucket, rather than the total result or vault count.

## Exact tag navigation and Pagefind isolation (3.33)

Browse Tags counts unique notes containing the exact normalized token. Tag
links use a separate static inverted index with 4,096 hashed posting buckets.
Result metadata is split into 512-note chunks and only chunks needed for the
visible 20-result page are fetched. The displayed count and exact tag result set
therefore remain identical without adding more than 100,000 generated word
values to Pagefind's filter index.

Full-text queries continue to use Pagefind, including its language stemming.
The Pagefind module is initialized once per search-page visit, typed terms are
preloaded, excerpts are shortened, metadata uses a stable per-build cache tag,
and the worker is destroyed on page exit. Internal HTML links are conservatively
prefetched after hover intent or keyboard focus.
Exact tag navigation does not import Pagefind at all, reducing CPU and memory
pressure for the common Browse Tags workflow.
## Canonical URLs and server-side search (3.34)

`--build` also runs the generated server in `-index-only` mode after compiling it, moving the one-time disk-index cost out of the interactive serving path.

Earlier tag metadata retained source-vault capitalization and filename spelling
while Hugo generated lowercase, hyphenated output paths. The 3.34 path map is
the sole source of truth: content filenames, explicit Hugo `url` frontmatter,
exact-tag document records, Pagefind links, and Bluge records all derive from the
same canonical path. URL lookup is therefore O(1) and does not require probing
multiple source-name variants at request time.

For local archives, the generated Go server keeps the Bluge index in a disk
directory and returns only one JSON result page. The browser no longer downloads
or initializes Pagefind chunks for ordinary search, phrase, tag-clause, or date
range queries. Static HTML and assets are served with cache headers. This does
not make raw filesystem lookup fundamentally faster than every other static
server, but it removes the dominant browser-side search CPU, memory, and network
work observed on six-figure-note archives.

The Bluge index is built from a streaming JSONL source in batches of 500. Index
creation memory is bounded by the scanner buffer, one decoded note, the current
batch, and Bluge's writer buffers. The source fingerprint stamp triggers an
automatic rebuild only when size or nanosecond modification time changes.
Pagefind remains optional for deployments that require a serverless static site.

