# Independent implementation review

This revision was compared with the independently supplied `movenotes-v3`
implementation of the same lossless-conversion requirements.

## Changes adopted

* Added a structured `joplin` frontmatter object so Obsidian and the Local REST
  API can consume the effective Joplin metadata directly.
* Added `joplin-properties` as an actual ordered array of `[key, value]` pairs.
  This retains duplicate properties and avoids the extra JSON-decoding step
  required by the compatibility `joplin-properties-json` string.
* Preserved additional leading and trailing property-value whitespace in the
  ordered SQLite source representation. Only the canonical first delimiter
  space after `:` is consumed.
* Made sanitized legacy `joplin-*` frontmatter key collisions deterministic by
  assigning numeric suffixes rather than emitting duplicate YAML keys.

## Substantial design differences retained

* This project stores the exact original RAW bytes, filename, body snapshot and
  ordered property pairs. The independent implementation reconstructs RAW from
  typed columns plus an extras object and property-order array. Exact bytes are
  more robust for BOMs, CRLF, delimiter spacing, duplicate unknown keys and
  future syntax.
* This project writes `.movenotes/joplin-raw/` and a checksum manifest into the
  Obsidian vault. That preserves folders, tags, relation items, revisions,
  auxiliary item types, original note Markdown and raw resource files, not just
  visible notes and their frontmatter.
* URL simplification is opt-in for Joplin RAW export here. The independent
  implementation simplifies by default, so its default path is intentionally
  lossy.
* Resource and item-ID collisions are checked by bytes and rejected. The
  independent implementation can overwrite a same-name resource based on
  size/mtime heuristics and permits duplicate item IDs in SQLite.
* This project's queryable schema includes revision diff/item fields and the
  resource OCR driver field in addition to the catch-all ordered source data.
* Filtered Obsidian exports preserve a dependency-closed Joplin subset without
  retaining stale or private backlinks from earlier/full exports.

## Performance implementation comparison (3.10)

The later independent 3.10 archive correctly added a `joplin_id` index,
replaced per-file database queries with compact SHA-256 comparisons, cached
folder parsing, cached filtered-preservation property maps, and added valuable
query-plan/query-count regression tests.

This reviewed release adopted the structural tests and folder-cache idea, then
combined them with the stronger existing design:

* schema v4 persists binary source fingerprints, avoiding a complete RAW-BLOB
  rehash on every run;
* full imports defer secondary-index construction until after bulk insertion;
* filtered preservation uses a direct dependency graph and full preservation
  streams BLOBs;
* full re-imports use one fingerprint preload, while small merges query only
  input-batch IDs;
* image, Obsidian attachment, and Twitter media directories are indexed once
  rather than globbed for each fallback lookup.

The alternate implementation's fixed-point preservation optimization is a
clear improvement over its earlier repeated reparsing, but the queue-based
adjacency traversal retained here is asymptotically tighter. Its full existing
RAW scan is also appropriate for a full re-import but unnecessarily expensive
for small incremental merges, which is why release 3.11 selects the lookup
strategy adaptively.
