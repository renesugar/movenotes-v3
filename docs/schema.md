# Schema references

The known queryable columns track the Joplin Data API property lists and item
type IDs. In particular, Joplin defines the note `order` property as numeric,
so `JOPLIN_COLUMNS["joplin_order"]` is declared as SQLite `REAL` and accepts
scientific notation and subnormal values such as `6e-323`. `joplin2sql._convert_known_value()` has an
explicit `REAL` conversion branch, so these values are parsed with `float()`
during import. The exact RAW bytes and ordered property JSON remain authoritative,
so fields absent from those lists are still preserved. Schema version 4 added
binary SHA-256 source fingerprints and query indexes. Schema version 5 adds
exact native-Obsidian path, body, frontmatter, and byte snapshots; supported
version 2 through 4 databases are migrated and fingerprinted in bounded batches
when opened. Obsidian output uses
ordinary Markdown files and YAML front matter compatible with the Local REST
API's note representation and frontmatter operations.

* Joplin Data API: https://joplinapp.org/help/api/references/rest_api/
* Obsidian Local REST API OpenAPI: https://github.com/coddingtonbear/obsidian-local-rest-api/blob/main/docs/openapi.yaml
* Obsidian Local REST API: https://github.com/coddingtonbear/obsidian-local-rest-api
