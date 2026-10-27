# Joplin RAW directories

Import a Joplin RAW export into SQLite, export it again, and clean up resources.

## Import a Joplin RAW directory into SQLite

Export your notes from Joplin using
`File → Export all → RAW - Joplin Export Directory`, then:

```
mkdir -p ~/notes_sqlite

python3 -B joplin2sql.py \
  --input  ~/joplin_raw_export \
  --output ~/notes_sqlite
```

This creates `~/notes_sqlite/notesdb.sqlite` and copies attachments into
`~/notes_sqlite/resources`. For every Joplin item, SQLite stores both parsed
columns and the exact original RAW bytes plus an ordered property list. Unknown
or newly introduced Joplin properties therefore survive without a schema
update. Resource and item-ID collisions with different data are rejected
instead of silently overwriting one source.

Large imports use batched inserts, persisted SHA-256 source fingerprints, and
periodic progress output. Full re-imports use one sequential fingerprint
preload, while small merges query only the IDs present in each input batch via
the `joplin_id` index. They do not issue one database query per input file,
preload a million-row database for a ten-note merge, or retain every RAW item
in memory. Parent notebook files are parsed at most once, and ordinary Joplin
RAW filenames avoid a database-wide folder-title update. Useful tuning options
are `--batch-size N`, `--progress-every N`, and `--verbose`; the defaults are
chosen for ordinary local SQLite imports and preserve transactional safety.

To merge several sources, run `joplin2sql.py` again with a different
`--input` and the same `--output`; notes accumulate in the same database.
After merging, `removedups.py` can remove duplicate notes:

```
python3 -B removedups.py --input ~/notes_sqlite
```

`removedups.py` and `cleanres.py` are intentionally destructive cleanup tools.
Do not run them when the goal is a complete, byte-for-byte preservation of the
source export.

## Export SQLite to a Joplin RAW directory

```
mkdir -p ~/joplin_raw_import

python3 -B sql2joplin.py \
  --input  ~/notes_sqlite \
  --output ~/joplin_raw_import
```

Then in Joplin use `File → Import → RAW - Joplin Export Directory` and select
`~/joplin_raw_import`.

Imported Joplin items are written byte-for-byte by default, including
unknown properties, property order, whitespace, line endings, body text and
URL syntax. Attachment files are also copied byte-for-byte.

URL-only links can still be simplified as an explicit, lossy transformation:

```
python3 -B sql2joplin.py \
  --simplify-urls \
  --input  ~/notes_sqlite \
  --output ~/joplin_raw_import
```

This changes `[https://x](https://x)` and `<https://x>` to bare URLs while
leaving titled links, images, resource links and code unchanged.

## Clean unused resources

Removes files from a `resources/` directory that are not referenced by any
note:

```
python3 -B cleanres.py --input ~/notes_sqlite
```

## PDF OCR metadata

Joplin PDF resource items can contain OCR text with embedded ASCII control
characters. Version 3.05 and later split RAW metadata only on CR/LF physical
line endings, so these characters remain part of `ocr_text` and do not cause a
false “cannot find Joplin property block” error.
